"""FSEvents-backed file watcher for explicitly selected workspaces.

Deux modes : un workspace positionnel (dev.sh, historique) ou ``--config``
(mode résident launchd : liste de workspaces déclarée dans un fichier —
le cwd implicite de make dev ne décide plus de ce qui est observé).

Detection change only (backlog FSEvents, après 2A-révisée) : watchdog
remplace le re-scan os.walk par seconde, le transport outbox est inchangé.
FSEvents coalesce et devine mal les types d'événements (renames, saves
atomiques), donc watchdog ne sert que de notificateur de chemins sales :
la vérité created/modified/deleted vient toujours du snapshot, comparé au
disque uniquement pour les chemins signalés.
"""

import argparse
import os
import sqlite3
import stat as stat_module
import threading
import time
from pathlib import Path
from typing import TypeAlias

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .private_files import apply_private_umask
from .producer_outbox import ProducerOutbox, enqueue_file_event


IGNORED_DIRECTORY_NAMES = {
    ".build",
    ".git",
    # Index GitNexus (base lbug + CSV régénérés à chaque analyse) : du churn
    # d'outillage, pas du travail — il remplissait /context jusqu'à la
    # troncature des fichiers.
    ".gitnexus",
    ".pytest_cache",
    ".swiftpm",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
IGNORED_FILE_NAMES = {".DS_Store"}
IGNORED_FILE_SUFFIXES = {".pyc", ".db"}

FileSignature: TypeAlias = tuple[int, int]
Snapshot: TypeAlias = dict[Path, FileSignature]


def should_ignore(path: Path, workspace: Path) -> bool:
    try:
        relative_path = path.relative_to(workspace)
    except ValueError:
        return True
    return (
        any(part in IGNORED_DIRECTORY_NAMES for part in relative_path.parts[:-1])
        or path.name in IGNORED_FILE_NAMES
        or path.suffix in IGNORED_FILE_SUFFIXES
    )


def should_ignore_directory(path: Path, workspace: Path) -> bool:
    try:
        relative_path = path.relative_to(workspace)
    except ValueError:
        return True
    return any(part in IGNORED_DIRECTORY_NAMES for part in relative_path.parts)


def take_snapshot(workspace: Path, root: Path | None = None) -> Snapshot:
    snapshot: Snapshot = {}
    for walk_root, directory_names, file_names in os.walk(root or workspace):
        directory_names[:] = [
            name for name in directory_names if name not in IGNORED_DIRECTORY_NAMES
        ]
        root_path = Path(walk_root)
        for file_name in file_names:
            path = root_path / file_name
            if should_ignore(path, workspace):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[path] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


class DirtyPathCollector(FileSystemEventHandler):
    """Collect paths watchdog reports as touched, without trusting the kind.

    Runs on the observer thread; watch() drains it from the flush loop.
    """

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace
        self._lock = threading.Lock()
        self._files: set[Path] = set()
        self._directories: set[Path] = set()

    def dispatch(self, event: FileSystemEvent) -> None:
        paths = [event.src_path]
        dest_path = getattr(event, "dest_path", "")
        if dest_path:
            paths.append(dest_path)
        for raw_path in paths:
            self._mark(Path(os.fsdecode(raw_path)), directory=event.is_directory)

    def _mark(self, path: Path, *, directory: bool) -> None:
        if directory:
            if should_ignore_directory(path, self._workspace):
                return
            with self._lock:
                self._directories.add(path)
            return
        if should_ignore(path, self._workspace):
            return
        with self._lock:
            self._files.add(path)

    def drain(self) -> tuple[set[Path], set[Path]]:
        with self._lock:
            files, self._files = self._files, set()
            directories, self._directories = self._directories, set()
        return files, directories


def _current_signature(path: Path) -> FileSignature | None:
    """Signature of a regular file, None when absent or not a plain file."""
    try:
        stat = path.stat()
    except OSError:
        return None
    if not stat_module.S_ISREG(stat.st_mode):
        return None
    return (stat.st_mtime_ns, stat.st_size)


def resolve_dirty_paths(
    snapshot: Snapshot,
    dirty_files: set[Path],
    dirty_directories: set[Path],
    workspace: Path,
) -> list[tuple[str, Path]]:
    """Compare dirty paths against the snapshot and update it in place.

    A dirty directory (coalesced FSEvents on deletes, moves of whole trees)
    expands to its known snapshot children plus a scoped re-scan when it
    still exists — never a full-workspace walk unless the root itself moved.
    """
    candidates = set(dirty_files)
    for directory in dirty_directories:
        if should_ignore_directory(directory, workspace):
            continue
        candidates.update(
            path for path in snapshot if directory in path.parents
        )
        if directory.is_dir():
            candidates.update(take_snapshot(workspace, root=directory))

    created: list[tuple[str, Path]] = []
    modified: list[tuple[str, Path]] = []
    deleted: list[tuple[str, Path]] = []
    for path in sorted(candidates):
        if should_ignore(path, workspace):
            continue
        signature = _current_signature(path)
        known = snapshot.get(path)
        if signature is None:
            if known is not None:
                del snapshot[path]
                deleted.append(("deleted", path))
        elif known is None:
            snapshot[path] = signature
            created.append(("created", path))
        elif known != signature:
            snapshot[path] = signature
            modified.append(("modified", path))
    return created + modified + deleted


def record_file_event(
    outbox: ProducerOutbox,
    event: str,
    path: Path,
    workspace: Path,
) -> bool:
    """Enqueue one observed change into the durable producer outbox.

    Transport only (decision 2A-révisée): a stopped daemon no longer loses
    events — the outbox worker delivers them when it comes back, like every
    other producer.
    """
    try:
        enqueue_file_event(
            outbox,
            path=str(path),
            event=event,
            workspace=str(workspace),
        )
        return True
    except (sqlite3.Error, ValueError, OSError):
        return False


def read_watched_workspaces(config_path: Path) -> tuple[list[Path], list[str]]:
    """Liste des workspaces à observer en mode résident (launchd).

    Un chemin absolu par ligne (``~`` accepté), ``#`` commentaires. Une
    entrée inexistante est signalée mais n'empêche pas les autres d'être
    observées (un workspace supprimé ne doit pas aveugler le service).
    Fichier absent = erreur : le service résident ne doit jamais tourner
    sans savoir quoi observer.
    """
    try:
        raw_lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"unreadable workspace list: {config_path} ({exc})")
    workspaces: list[Path] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    for line in raw_lines:
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        workspace = Path(entry).expanduser()
        try:
            workspace = workspace.resolve()
        except OSError:
            warnings.append(f"unresolvable workspace ignored: {entry}")
            continue
        if workspace in seen:
            continue
        seen.add(workspace)
        if not workspace.is_dir():
            warnings.append(f"missing workspace ignored: {workspace}")
            continue
        workspaces.append(workspace)
    return workspaces, warnings


def watch(
    workspaces: list[Path],
    interval: float = 1.0,
    *,
    outbox: ProducerOutbox | None = None,
) -> None:
    outbox = outbox or ProducerOutbox()
    watched: list[tuple[Path, DirtyPathCollector, Snapshot]] = []
    observer = Observer()
    for workspace in workspaces:
        collector = DirtyPathCollector(workspace)
        watched.append((workspace, collector, take_snapshot(workspace)))
        observer.schedule(collector, str(workspace), recursive=True)
    observer.start()
    for workspace, _collector, _snapshot in watched:
        print(f"Watching files in {workspace}", flush=True)
    try:
        while True:
            time.sleep(interval)
            observer_alive = observer.is_alive()
            for workspace, collector, snapshot in watched:
                dirty_files, dirty_directories = collector.drain()
                events = resolve_dirty_paths(
                    snapshot, dirty_files, dirty_directories, workspace
                )
                for event, path in events:
                    record_file_event(outbox, event, path, workspace)
            if not observer_alive:
                # Un observer mort = plus aucune détection : mourir
                # bruyamment pour que le superviseur (dev.sh ou launchd
                # KeepAlive) le relance, après avoir livré les derniers
                # événements collectés.
                raise RuntimeError("file watcher observer stopped unexpectedly")
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join(timeout=5.0)


def main() -> None:
    apply_private_umask()
    parser = argparse.ArgumentParser(
        description="Watch one workspace (or a configured list) for file changes"
    )
    parser.add_argument("workspace", type=Path, nargs="?")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="resident mode: file listing one workspace path per line",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="coalescing window in seconds between event flushes",
    )
    args = parser.parse_args()

    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    if (args.workspace is None) == (args.config is None):
        parser.error("exactly one of <workspace> or --config is required")

    if args.config is not None:
        try:
            workspaces, warnings = read_watched_workspaces(
                args.config.expanduser()
            )
        except ValueError as exc:
            parser.error(str(exc))
        for warning in warnings:
            print(f"[file-watcher] {warning}", flush=True)
        if not workspaces:
            parser.error(f"no watchable workspace in {args.config}")
    else:
        workspace = args.workspace.expanduser().resolve()
        if not workspace.is_dir():
            parser.error(f"workspace is not a directory: {workspace}")
        workspaces = [workspace]
    watch(workspaces, args.interval)


if __name__ == "__main__":
    main()
