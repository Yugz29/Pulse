from __future__ import annotations

import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from daemon.core.file_classifier import classify_file_type


_BUS_FILE_EVENT_TYPES: frozenset[str] = frozenset({
    "file_created", "file_modified", "file_renamed",
    "file_deleted", "file_change",
})
_COALESCIBLE_FILE_EVENT_TYPES: frozenset[str] = frozenset({
    "file_created",
    "file_modified",
    "file_renamed",
})
_FILE_EVENT_PRIORITY: dict[str, int] = {
    "file_modified": 0,
    "file_created": 1,
    "file_renamed": 2,
}
_SCREENSHOT_FILE_EVENT_PRIORITY: dict[str, int] = {
    "file_modified": 0,
    "file_renamed": 1,
    "file_created": 2,
}
_TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({
    "terminal_command_started",
    "terminal_command_finished",
})
_LOCK_PASSTHROUGH: frozenset[str] = frozenset({
    "screen_locked",
    "screen_unlocked",
})
_DEPENDENCY_ARTIFACTS: frozenset[str] = frozenset({
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pipfile.lock",
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "podfile.lock",
    "go.sum",
})

_SCREENSHOT_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".heic", ".tiff"})
_SCREENSHOT_NAME_PREFIXES: tuple[str, ...] = (
    "capture d’écran",
    "capture d'ecran",
    "capture d’écran",
    "screenshot",
    "screen shot",
)
_SCREENSHOT_CAPTURE_MARKERS: tuple[str, ...] = (
    "capture d'ecran",
    "capture decran",
    "screenshot",
)
_SCREENSHOT_CAPTURE_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".heic", ".tiff", ".webp",
})
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EventMeaningDecision:
    publish_to_bus: bool
    runtime_relevant: bool
    scoring_relevant: bool
    file_significance: str
    coalescible: bool
    coalescing_priority: int
    noise_policy: str
    dedupe_key: str | None
    sanitized_payload: dict | None


class EventMeaningPolicy:
    def __init__(self) -> None:
        self._recent_file_events: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def classify(
        self,
        event_type: str,
        payload: dict | None,
        *,
        now: datetime | None = None,
        cleanup_ttl: timedelta = timedelta(seconds=5),
        dedupe_window: timedelta = timedelta(seconds=1),
    ) -> EventMeaningDecision:
        sanitized_payload = dict(payload or {})
        if event_type == "clipboard_updated":
            sanitized_payload.pop("content", None)
        if event_type in _TERMINAL_EVENT_TYPES:
            sanitized_payload.pop("command", None)
            sanitized_payload.pop("raw", None)

        path = str(sanitized_payload.get("path") or "")
        file_significance = self._file_signal_significance(path)
        coalescible = bool(path) and event_type in _COALESCIBLE_FILE_EVENT_TYPES
        coalescing_priority = self._coalescing_priority(event_type, path)
        publish_to_bus = self._should_publish_to_bus(event_type, path)
        runtime_relevant = self._runtime_relevant(event_type, path, file_significance)
        scoring_relevant = self._scoring_relevant(event_type, path, file_significance)
        noise_policy = self._noise_policy(path, file_significance)
        dedupe_key = self._dedupe_key(event_type, path, runtime_relevant)

        return EventMeaningDecision(
            publish_to_bus=publish_to_bus,
            runtime_relevant=runtime_relevant,
            scoring_relevant=scoring_relevant,
            file_significance=file_significance,
            coalescible=coalescible,
            coalescing_priority=coalescing_priority,
            noise_policy=noise_policy,
            dedupe_key=dedupe_key,
            sanitized_payload=sanitized_payload,
        )

    def should_dedupe(
        self,
        dedupe_key: str,
        *,
        now: datetime | None = None,
        cleanup_ttl: timedelta = timedelta(seconds=5),
        dedupe_window: timedelta = timedelta(seconds=1),
    ) -> bool:
        current = now or datetime.now()
        with self._lock:
            last_seen = self._recent_file_events.get(dedupe_key)
            self._recent_file_events = {
                key: seen_at
                for key, seen_at in self._recent_file_events.items()
                if current - seen_at < cleanup_ttl
            }
            if last_seen and current - last_seen < dedupe_window:
                return True
            self._recent_file_events[dedupe_key] = current
            return False

    def classify_path(self, path: str) -> EventMeaningDecision:
        significance = self._file_signal_significance(path)
        return EventMeaningDecision(
            publish_to_bus=significance in {"meaningful", "observe_only"},
            runtime_relevant=significance == "meaningful",
            scoring_relevant=significance != "technical_noise",
            file_significance=significance,
            coalescible=False,
            coalescing_priority=-1,
            noise_policy=self._noise_policy(path, significance),
            dedupe_key=None,
            sanitized_payload=None,
        )

    def _should_publish_to_bus(self, event_type: str, path: str) -> bool:
        if event_type in _LOCK_PASSTHROUGH:
            return True
        if event_type not in _BUS_FILE_EVENT_TYPES:
            return True
        if "COMMIT_EDITMSG" in path:
            return True
        return self._file_signal_significance(path) in {"meaningful", "observe_only"}

    def _runtime_relevant(self, event_type: str, path: str, file_significance: str) -> bool:
        if event_type in _LOCK_PASSTHROUGH:
            return False
        if not event_type.startswith("file_"):
            return True
        if not path:
            return False
        if path.endswith(".git/COMMIT_EDITMSG") or "/COMMIT_EDITMSG" in path:
            return True
        return file_significance == "meaningful"

    def _scoring_relevant(self, event_type: str, path: str, file_significance: str) -> bool:
        if event_type not in _BUS_FILE_EVENT_TYPES:
            return False
        if not path:
            return True
        return file_significance != "technical_noise"

    def _dedupe_key(self, event_type: str, path: str, runtime_relevant: bool) -> str | None:
        if not runtime_relevant or not event_type.startswith("file_") or not path:
            return None
        if path.endswith(".git/COMMIT_EDITMSG") or "/COMMIT_EDITMSG" in path:
            return None
        return f"{event_type}:{path}"

    def _coalescing_priority(self, event_type: str, path: str) -> int:
        if not path or event_type not in _COALESCIBLE_FILE_EVENT_TYPES:
            return -1
        if _is_screenshot_path(path):
            return _SCREENSHOT_FILE_EVENT_PRIORITY.get(event_type, -1)
        return _FILE_EVENT_PRIORITY.get(event_type, -1)

    def _noise_policy(self, path: str, significance: str) -> str:
        if significance == "observe_only":
            return "observe_only"
        if significance == "technical_noise":
            return "ignore"
        if os.path.basename(path).lower() in _DEPENDENCY_ARTIFACTS:
            return "downrank"
        return "normal"

    def _file_signal_significance(self, path: str | None) -> str:
        if not path:
            return "technical_noise"
        if is_pulse_internal_path(path):
            return "technical_noise"

        path = str(path)
        name = path.split("/")[-1]
        lower_name = name.lower()
        lower_path = path.lower()

        if _is_git_hash_filename(name):
            return "technical_noise"

        if _contains_uuid(name):
            return "technical_noise"

        if name.startswith("."):
            return "technical_noise"
        if "/.trash/" in lower_path:
            return "technical_noise"
        if name.endswith((".DS_Store", "~", ".xcuserstate")):
            return "technical_noise"
        if name == "COMMIT_EDITMSG":
            return "technical_noise"
        if name.endswith((
            ".sqlite", ".sqlite3", ".db", ".db-journal", ".db-wal", ".db-shm",
            ".log", ".jsonl", ".tmp", ".temp", ".swp", ".swo",
        )):
            return "technical_noise"
        if lower_name == "models_cache.json":
            return "technical_noise"
        if lower_name.endswith(("_cache.json", "-cache.json", ".cache.json")):
            return "technical_noise"
        if _is_screenshot_capture(name):
            return "observe_only"
        if name.endswith(("-journal", "-wal", "-shm")):
            return "technical_noise"
        if ".sb-" in name:
            return "technical_noise"
        if lower_name.endswith(".d.ts"):
            return "technical_noise"
        if any(
            segment in path
            for segment in (
                "/.git/", "/node_modules/", "/__pycache__/",
                "/xcuserdata/", "/DerivedData/",
                "/site-packages/", "/dist-packages/", "/.venv/", "/venv/",
                "/.cache/", "/.codex/",
                "/opt/homebrew/Cellar/", "/opt/homebrew/lib/",
                "/usr/local/lib/", "/usr/lib/", "/usr/share/",
                "/System/Library/", "/private/var/",
            )
        ):
            return "technical_noise"

        if "/Downloads/" in path:
            return "neutral"

        lockfile_names = {
            "poetry.lock", "pipfile.lock", "cargo.lock",
            "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
            "podfile.lock", "gemfile.lock", "composer.lock",
        }
        if name.lower() in lockfile_names:
            return "neutral"

        file_type = classify_file_type(path)
        if file_type in {"source", "test", "config", "docs", "assets"}:
            return "meaningful"

        if lower_path.endswith((".lock", ".csv")):
            return "neutral"
        return "neutral"


def is_pulse_internal_path(path: str) -> bool:
    if not path:
        return False
    try:
        p = Path(path).expanduser().resolve()
        pulse_home = (Path.home() / ".pulse").resolve()
        return p == pulse_home or pulse_home in p.parents
    except Exception:
        return "/.pulse/" in str(path) or str(path).endswith("/.pulse")


def _is_screenshot_path(path: str) -> bool:
    name = os.path.basename(path).strip().lower()
    if not name:
        return False
    _, ext = os.path.splitext(name)
    if ext not in _SCREENSHOT_EXTENSIONS:
        return False
    return any(name.startswith(prefix) for prefix in _SCREENSHOT_NAME_PREFIXES)


def _is_screenshot_capture(path: str) -> bool:
    lower_name = _normalize_for_match(path)
    return (
        lower_name.endswith(tuple(_SCREENSHOT_CAPTURE_EXTENSIONS))
        and any(marker in lower_name for marker in _SCREENSHOT_CAPTURE_MARKERS)
    )


def _normalize_for_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only.lower()


def _is_git_hash_filename(name: str) -> bool:
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return len(stem) == 40 and all(c in "0123456789abcdef" for c in stem.lower())


def _contains_uuid(name: str) -> bool:
    return bool(_UUID_RE.search(name))


_default_policy = EventMeaningPolicy()
