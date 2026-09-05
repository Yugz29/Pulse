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
from collections.abc import Callable
from dataclasses import dataclass, field
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
# Transport d'un changement observé ; True = pris en charge durablement.
Enqueue: TypeAlias = Callable[[str, Path], bool]


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


@dataclass(frozen=True)
class DetectedChange:
    """Un écart entre le disque et le snapshot, pas encore appliqué."""

    event: str  # created | modified | deleted
    path: Path
    signature: FileSignature | None  # None = le fichier a disparu


def detect_changes(
    snapshot: Snapshot,
    dirty_files: set[Path],
    dirty_directories: set[Path],
    workspace: Path,
) -> list[DetectedChange]:
    """Compare dirty paths against the snapshot without touching it.

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

    created: list[DetectedChange] = []
    modified: list[DetectedChange] = []
    deleted: list[DetectedChange] = []
    for path in sorted(candidates):
        if should_ignore(path, workspace):
            continue
        signature = _current_signature(path)
        known = snapshot.get(path)
        if signature is None:
            if known is not None:
                deleted.append(DetectedChange("deleted", path, None))
        elif known is None:
            created.append(DetectedChange("created", path, signature))
        elif known != signature:
            modified.append(DetectedChange("modified", path, signature))
    return created + modified + deleted


def apply_change(snapshot: Snapshot, change: DetectedChange) -> None:
    if change.signature is None:
        snapshot.pop(change.path, None)
    else:
        snapshot[change.path] = change.signature


@dataclass(frozen=True)
class ResolvedPaths:
    events: list[tuple[str, Path]]  # transmis, snapshot avancé
    deferred: list[Path]  # refusés par le transport, snapshot intact


def resolve_dirty_paths(
    snapshot: Snapshot,
    dirty_files: set[Path],
    dirty_directories: set[Path],
    workspace: Path,
    enqueue: Enqueue,
) -> ResolvedPaths:
    """Detect, hand each change to the transport, advance the snapshot on
    success only.

    Le snapshot est la mémoire de ce qui a été *transmis*, pas de ce qui a
    été *vu* : l'avancer avant la confirmation de l'enqueue perdait le
    changement pour de bon dès que l'outbox refusait (verrou, disque). Un
    chemin refusé ressort dans ``deferred`` pour être re-signalé au passage
    suivant, et sera redétecté tel quel puisque le snapshot n'a pas bougé.
    """
    events: list[tuple[str, Path]] = []
    deferred: list[Path] = []
    for change in detect_changes(snapshot, dirty_files, dirty_directories, workspace):
        if enqueue(change.event, change.path):
            apply_change(snapshot, change)
            events.append((change.event, change.path))
        else:
            deferred.append(change.path)
    return ResolvedPaths(events=events, deferred=deferred)


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


def canonical_case_path(path: Path) -> Path:
    """Rend le chemin tel que le disque l'écrit, segment par segment.

    ``resolve()`` suit les liens symboliques mais ne corrige pas la casse : sur
    APFS, insensible à la casse, ``/Users/yugz`` « existe » et se résout en
    ``/Users/yugz`` alors que le disque écrit ``/Users/Yugz``. Les comparaisons
    de ``PurePath``, elles, sont sensibles à la casse — d'où un workspace qui
    passe tous les contrôles mais dont plus aucun chemin ne correspond.

    Un segment introuvable, ambigu (deux graphies présentes sur un volume
    sensible à la casse) ou illisible arrête la canonisation : on rend ce qui
    est déjà résolu plutôt que de deviner.
    """
    if not path.is_absolute():
        return path
    parts = path.parts
    cursor = Path(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        # `parts.index(part)` mentirait dès qu'un nom se répète
        # (`Projets/DevNote/DevNote`) : l'indice vient de l'énumération.
        remainder = parts[index:]
        try:
            names = {entry.name for entry in cursor.iterdir()}
        except OSError:
            return cursor.joinpath(*remainder)
        if part in names:
            cursor = cursor / part
            continue
        matches = [name for name in names if name.casefold() == part.casefold()]
        if len(matches) != 1:
            return cursor.joinpath(*remainder)
        cursor = cursor / matches[0]
    return cursor


def read_watched_workspaces(config_path: Path) -> tuple[list[Path], list[str]]:
    """Liste des workspaces à observer en mode résident (launchd).

    Un chemin absolu par ligne (``~`` accepté), ``#`` commentaires. Une
    entrée inexistante est signalée mais n'empêche pas les autres d'être
    observées (un workspace supprimé ne doit pas aveugler le service).
    Fichier absent = erreur : le service résident ne doit jamais tourner
    sans savoir quoi observer.

    Chaque entrée est ramenée à la casse du disque : FSEvents remonte les
    chemins tels qu'ils y sont écrits, et ``should_ignore`` filtre tout ce qui
    n'est pas sous le workspace. Une casse déclarée différente rendait donc le
    watcher silencieusement aveugle — il démarrait, journalisait « Watching
    files in … » et n'émettait plus rien.
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
        canonical = canonical_case_path(workspace)
        if canonical != workspace:
            warnings.append(
                f"workspace case corrected: {workspace} -> {canonical}"
            )
            workspace = canonical
        # La déduplication porte sur la forme canonique : deux graphies du même
        # dossier donnaient deux workspaces, donc deux collecteurs et deux
        # snapshots sur la même arborescence.
        if workspace in seen:
            continue
        seen.add(workspace)
        if not workspace.is_dir():
            warnings.append(f"missing workspace ignored: {workspace}")
            continue
        workspaces.append(workspace)
    return workspaces, warnings


@dataclass
class WatchedWorkspace:
    workspace: Path
    collector: DirtyPathCollector
    snapshot: Snapshot
    # Chemins dont l'enqueue a échoué : re-signalés au passage suivant, sans
    # attendre que watchdog les revoie (il ne le fera pas sans nouvel accès).
    deferred: set[Path] = field(default_factory=set)


def flush_workspace(watched: WatchedWorkspace, enqueue: Enqueue) -> ResolvedPaths:
    """One pass: fresh dirty paths plus the ones deferred last time."""
    dirty_files, dirty_directories = watched.collector.drain()
    dirty_files |= watched.deferred
    result = resolve_dirty_paths(
        watched.snapshot, dirty_files, dirty_directories, watched.workspace, enqueue
    )
    had_deferred = bool(watched.deferred)
    watched.deferred = set(result.deferred)
    if watched.deferred and not had_deferred:
        print(
            f"[file-watcher] {len(watched.deferred)} change(s) deferred in "
            f"{watched.workspace}: outbox refused, will retry",
            flush=True,
        )
    elif had_deferred and not watched.deferred:
        print(
            f"[file-watcher] deferred changes delivered for {watched.workspace}",
            flush=True,
        )
    return result


def watch(
    workspaces: list[Path],
    interval: float = 1.0,
    *,
    outbox: ProducerOutbox | None = None,
) -> None:
    outbox = outbox or ProducerOutbox()
    watched: list[WatchedWorkspace] = []
    observer = Observer()
    for workspace in workspaces:
        collector = DirtyPathCollector(workspace)
        watched.append(
            WatchedWorkspace(workspace, collector, take_snapshot(workspace))
        )
        observer.schedule(collector, str(workspace), recursive=True)
    observer.start()
    for entry in watched:
        print(f"Watching files in {entry.workspace}", flush=True)
    try:
        while True:
            time.sleep(interval)
            observer_alive = observer.is_alive()
            for entry in watched:
                flush_workspace(
                    entry,
                    lambda event, path, workspace=entry.workspace: record_file_event(
                        outbox, event, path, workspace
                    ),
                )
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
