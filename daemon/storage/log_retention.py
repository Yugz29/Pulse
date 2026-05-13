from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_ARCHIVE_LOG_RETENTION_DAYS = 3
DEFAULT_DEBUG_LOG_RETENTION_DAYS = 2
HARD_TECHNICAL_LOG_RETENTION_DAYS = 7

ACTIVE_LOG_NAMES = {
    "daemon.app.log",
    "daemon.error.log",
    "daemon.stdout.log",
    "launchd.error.log",
    "launchd.stdout.log",
}

PROTECTED_RELATIVE_PATHS = {
    "session.db",
    "vectors.db",
    "facts.db",
    "memory.db",
    "settings.json",
    "restart_state.json",
    "cooldown.json",
}

PROTECTED_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
}


class LogRetentionSafetyError(ValueError):
    pass


@dataclass(frozen=True)
class LogCleanupCandidate:
    path: str
    bytes: int
    reason: str
    kind: str


@dataclass(frozen=True)
class LogCleanupResult:
    dry_run: bool
    pulse_home: str
    candidates: list[LogCleanupCandidate]
    deleted: list[LogCleanupCandidate]
    total_bytes_reclaimable: int
    total_bytes_deleted: int


def cleanup_pulse_logs(
    *,
    pulse_home: Path | None = None,
    dry_run: bool = True,
    now: float | None = None,
    archive_retention_days: int = DEFAULT_ARCHIVE_LOG_RETENTION_DAYS,
    debug_retention_days: int = DEFAULT_DEBUG_LOG_RETENTION_DAYS,
    hard_retention_days: int = HARD_TECHNICAL_LOG_RETENTION_DAYS,
) -> LogCleanupResult:
    """Apply the Pulse technical-log retention policy.

    Only files/directories under ~/.pulse/logs and ~/.pulse/archive/logs-* are
    eligible. User memory, databases, settings, and runtime state are never
    candidates.
    """
    resolved_home = _resolve_pulse_home(pulse_home)
    current_time = time.time() if now is None else now
    candidates = _collect_candidates(
        pulse_home=resolved_home,
        now=current_time,
        archive_retention_days=archive_retention_days,
        debug_retention_days=debug_retention_days,
        hard_retention_days=hard_retention_days,
    )

    deleted: list[LogCleanupCandidate] = []
    if not dry_run:
        for candidate in candidates:
            path = Path(candidate.path)
            _assert_inside_pulse_home(path, resolved_home)
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            deleted.append(candidate)

    return LogCleanupResult(
        dry_run=dry_run,
        pulse_home=str(resolved_home),
        candidates=candidates,
        deleted=deleted,
        total_bytes_reclaimable=sum(candidate.bytes for candidate in candidates),
        total_bytes_deleted=sum(candidate.bytes for candidate in deleted),
    )


def _collect_candidates(
    *,
    pulse_home: Path,
    now: float,
    archive_retention_days: int,
    debug_retention_days: int,
    hard_retention_days: int,
) -> list[LogCleanupCandidate]:
    candidates: list[LogCleanupCandidate] = []
    seen: set[Path] = set()

    logs_dir = pulse_home / "logs"
    if logs_dir.exists():
        _assert_inside_pulse_home(logs_dir, pulse_home)
        candidates.extend(
            _collect_log_file_candidates(
                logs_dir=logs_dir,
                pulse_home=pulse_home,
                now=now,
                debug_retention_days=debug_retention_days,
                hard_retention_days=hard_retention_days,
                seen=seen,
            )
        )

    archive_dir = pulse_home / "archive"
    if archive_dir.exists():
        _assert_inside_pulse_home(archive_dir, pulse_home)
        for child in sorted(archive_dir.glob("logs-*")):
            _assert_inside_pulse_home(child, pulse_home)
            if not child.is_dir():
                continue
            if _is_protected_path(child, pulse_home):
                continue
            age_days = _age_days(child, now)
            if age_days >= min(archive_retention_days, hard_retention_days):
                candidates.append(
                    _candidate(
                        child,
                        reason=f"archived logs older than {archive_retention_days} days",
                        kind="archive_log_dir",
                        seen=seen,
                    )
                )

    return candidates


def _collect_log_file_candidates(
    *,
    logs_dir: Path,
    pulse_home: Path,
    now: float,
    debug_retention_days: int,
    hard_retention_days: int,
    seen: set[Path],
) -> list[LogCleanupCandidate]:
    candidates: list[LogCleanupCandidate] = []
    for path in sorted(logs_dir.rglob("*")):
        _assert_inside_pulse_home(path, pulse_home)
        if not path.is_file():
            continue
        if _is_protected_path(path, pulse_home):
            continue
        if path.name in ACTIVE_LOG_NAMES:
            continue
        if not _looks_like_log_file(path):
            continue

        age_days = _age_days(path, now)
        if _is_debug_or_temp_log(path) and age_days >= debug_retention_days:
            candidates.append(
                _candidate(
                    path,
                    reason=f"debug/temp log older than {debug_retention_days} days",
                    kind="log_file",
                    seen=seen,
                )
            )
        elif age_days >= hard_retention_days:
            candidates.append(
                _candidate(
                    path,
                    reason=f"technical log older than hard maximum {hard_retention_days} days",
                    kind="log_file",
                    seen=seen,
                )
            )
    return candidates


def _resolve_pulse_home(pulse_home: Path | None) -> Path:
    path = Path.home() / ".pulse" if pulse_home is None else Path(pulse_home)
    resolved = path.expanduser().resolve()
    if resolved.name != ".pulse":
        raise LogRetentionSafetyError(f"refusing non-.pulse root: {resolved}")
    return resolved


def _assert_inside_pulse_home(path: Path, pulse_home: Path) -> None:
    resolved_path = path.expanduser().resolve()
    try:
        resolved_path.relative_to(pulse_home)
    except ValueError as exc:
        raise LogRetentionSafetyError(f"refusing path outside Pulse home: {resolved_path}") from exc


def _is_protected_path(path: Path, pulse_home: Path) -> bool:
    try:
        relative = path.resolve().relative_to(pulse_home)
    except ValueError:
        return True
    relative_text = relative.as_posix()
    if relative_text in PROTECTED_RELATIVE_PATHS:
        return True
    if relative.parts and relative.parts[0] == "memory":
        return True
    if any(path.name.endswith(suffix) for suffix in PROTECTED_SUFFIXES):
        return True
    return False


def _looks_like_log_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        ".log" in name
        or name.endswith(".out")
        or name.endswith(".err")
        or name.endswith(".trace")
        or name.endswith(".tmp")
        or "debug" in name
        or "temp" in name
    )


def _is_debug_or_temp_log(path: Path) -> bool:
    name = path.name.lower()
    return "debug" in name or "temp" in name or name.endswith(".tmp")


def _age_days(path: Path, now: float) -> float:
    return (now - path.stat().st_mtime) / 86400


def _candidate(path: Path, *, reason: str, kind: str, seen: set[Path]) -> LogCleanupCandidate:
    resolved = path.resolve()
    if resolved in seen:
        return LogCleanupCandidate(path=str(resolved), bytes=0, reason=reason, kind=kind)
    seen.add(resolved)
    return LogCleanupCandidate(
        path=str(resolved),
        bytes=_path_size(resolved),
        reason=reason,
        kind=kind,
    )


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    return 0


def _result_to_dict(result: LogCleanupResult) -> dict:
    return {
        **asdict(result),
        "candidates": [asdict(candidate) for candidate in result.candidates],
        "deleted": [asdict(candidate) for candidate in result.deleted],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pulse technical log retention helper")
    parser.add_argument("--pulse-home", type=Path, default=None)
    parser.add_argument("--apply", action="store_true", help="delete eligible log files/directories")
    parser.add_argument("--dry-run", action="store_true", help="report eligible deletions without deleting")
    args = parser.parse_args(argv)

    dry_run = not args.apply
    if args.dry_run:
        dry_run = True

    result = cleanup_pulse_logs(pulse_home=args.pulse_home, dry_run=dry_run)
    print(json.dumps(_result_to_dict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
