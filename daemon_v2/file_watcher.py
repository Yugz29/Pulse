"""FSEvents-backed file watcher for one explicitly selected workspace.

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

from .producer_outbox import ProducerOutbox, enqueue_file_event


IGNORED_DIRECTORY_NAMES = {
    ".build",
    ".git",
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


def watch(
    workspace: Path,
    interval: float = 1.0,
    *,
    outbox: ProducerOutbox | None = None,
) -> None:
    outbox = outbox or ProducerOutbox()
    snapshot = take_snapshot(workspace)
    collector = DirtyPathCollector(workspace)
    observer = Observer()
    observer.schedule(collector, str(workspace), recursive=True)
    observer.start()
    print(f"Watching files in {workspace}", flush=True)
    try:
        while True:
            time.sleep(interval)
            observer_alive = observer.is_alive()
            dirty_files, dirty_directories = collector.drain()
            events = resolve_dirty_paths(
                snapshot, dirty_files, dirty_directories, workspace
            )
            for event, path in events:
                record_file_event(outbox, event, path, workspace)
            if not observer_alive:
                # Un observer mort = plus aucune détection : mourir
                # bruyamment pour que le superviseur (dev.sh) le voie,
                # après avoir livré les derniers événements collectés.
                raise RuntimeError("file watcher observer stopped unexpectedly")
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join(timeout=5.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch one workspace for file changes")
    parser.add_argument("workspace", type=Path)
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="coalescing window in seconds between event flushes",
    )
    args = parser.parse_args()

    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error(f"workspace is not a directory: {workspace}")
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    watch(workspace, args.interval)


if __name__ == "__main__":
    main()
