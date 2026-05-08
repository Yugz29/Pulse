"""File event coalescer — absorbs heterogeneous create/modify/rename bursts before EventBus injection."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

FILE_EVENT_COHERENCE_WINDOW_SEC: float = 1.0

_SCREENSHOT_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".heic", ".tiff"})
_SCREENSHOT_NAME_PREFIXES: tuple[str, ...] = (
    "capture d'écran",
    "capture d'ecran",
    "capture d'écran",
    "screenshot",
    "screen shot",
)


def is_screenshot_path(path: str) -> bool:
    """Return True if *path* looks like a screenshot file."""
    name = os.path.basename(path).strip().lower()
    if not name:
        return False
    _, ext = os.path.splitext(name)
    if ext not in _SCREENSHOT_EXTENSIONS:
        return False
    return any(name.startswith(prefix) for prefix in _SCREENSHOT_NAME_PREFIXES)


@dataclass
class PendingFileEvent:
    path: str
    event_type: str
    payload: dict[str, Any]
    timestamp: datetime | None
    started_at: float
    due_at: float


class FileEventCoalescer:
    """
    Regroupe un burst hétérogène create/modify/rename sur un même path
    avant injection dans l'EventBus.

    Le premier event éligible est retenu pendant une courte fenêtre.
    - même type (modify + modify) : pas de fusion, les events restent distincts
    - types hétérogènes : l'event de priorité la plus forte gagne
      (renamed > created > modified)

    Important : cette fenêtre est volontairement basée sur le temps local
    d'ingestion daemon (monotonic), pas sur le timestamp source. Le but est
    purement technique : absorber un burst HTTP/FSEvents local sans laisser
    l'ordre ou l'âge source reconfigurer la logique de transport.
    """

    def __init__(
        self,
        *,
        publisher: Callable[[str, dict[str, Any], datetime | None], None],
        window_sec: float = FILE_EVENT_COHERENCE_WINDOW_SEC,
        time_fn: Callable[[], float] | None = None,
        start_worker: bool = True,
    ) -> None:
        self._publisher = publisher
        self._window_sec = window_sec
        self._time_fn = time_fn or time.monotonic
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._pending_by_path: dict[str, PendingFileEvent] = {}
        self._stopped = False
        self._worker: threading.Thread | None = None
        if start_worker:
            self._worker = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="pulse-file-coalescer",
            )
            self._worker.start()

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> None:
        path = payload.get("path")
        if not self._is_coalescible(event_type, payload):
            self._publisher(event_type, payload, timestamp)
            return

        screenshot_event = is_screenshot_path(str(path))
        emit_now: tuple[str, dict[str, Any], datetime | None] | None = None
        now = self._time_fn()

        with self._condition:
            pending = self._pending_by_path.get(path)
            if pending is None:
                self._pending_by_path[path] = self._new_pending(
                    path=path,
                    event_type=event_type,
                    payload=dict(payload),
                    timestamp=timestamp,
                    started_at=now,
                )
                self._condition.notify_all()
                return

            expired = (now - pending.started_at) > self._window_sec
            same_type = pending.event_type == event_type

            if expired:
                emit_now = (pending.event_type, pending.payload, pending.timestamp)
                self._pending_by_path[path] = self._new_pending(
                    path=path,
                    event_type=event_type,
                    payload=dict(payload),
                    timestamp=timestamp,
                    started_at=now,
                )
            elif screenshot_event:
                if self._priority(event_type, payload) > self._priority(pending.event_type, pending.payload):
                    pending.event_type = event_type
                    pending.payload = dict(payload)
                    pending.timestamp = timestamp
            elif same_type:
                emit_now = (pending.event_type, pending.payload, pending.timestamp)
                self._pending_by_path[path] = self._new_pending(
                    path=path,
                    event_type=event_type,
                    payload=dict(payload),
                    timestamp=timestamp,
                    started_at=now,
                )
            else:
                if self._priority(event_type, payload) > self._priority(pending.event_type, pending.payload):
                    pending.event_type = event_type
                    pending.payload = dict(payload)
                    pending.timestamp = timestamp
            self._condition.notify_all()

        if emit_now is not None:
            self._publisher(*emit_now)

    def _new_pending(
        self,
        *,
        path: str,
        event_type: str,
        payload: dict[str, Any],
        timestamp: datetime | None,
        started_at: float,
    ) -> PendingFileEvent:
        return PendingFileEvent(
            path=path,
            event_type=event_type,
            payload=payload,
            timestamp=timestamp,
            started_at=started_at,
            due_at=started_at + self._window_sec,
        )

    def _flush_due(self) -> list[tuple[str, dict[str, Any], datetime | None]]:
        now = self._time_fn()
        due_paths = [
            path
            for path, pending in self._pending_by_path.items()
            if pending.due_at <= now
        ]
        emits: list[tuple[str, dict[str, Any], datetime | None]] = []
        for path in due_paths:
            pending = self._pending_by_path.pop(path, None)
            if pending is None:
                continue
            emits.append((pending.event_type, pending.payload, pending.timestamp))
        return emits

    def _run_loop(self) -> None:
        while True:
            with self._condition:
                while not self._stopped and not self._pending_by_path:
                    self._condition.wait()
                if self._stopped:
                    return
                next_due = min(pending.due_at for pending in self._pending_by_path.values())
                wait_sec = max(next_due - self._time_fn(), 0.0)
                if wait_sec > 0:
                    self._condition.wait(timeout=wait_sec)
                    continue
                emits = self._flush_due()

            for emit in emits:
                self._publisher(*emit)

    def close(self) -> None:
        emits: list[tuple[str, dict[str, Any], datetime | None]] = []
        with self._condition:
            for pending in self._pending_by_path.values():
                emits.append((pending.event_type, pending.payload, pending.timestamp))
            self._pending_by_path = {}
            self._stopped = True
            self._condition.notify_all()

        for emit in emits:
            self._publisher(*emit)

    def _is_coalescible(self, event_type: str, payload: dict[str, Any]) -> bool:
        from daemon.core.event_meaning import _default_policy
        return _default_policy.classify(event_type, payload).coalescible

    def _priority(self, event_type: str, payload: dict[str, Any]) -> int:
        from daemon.core.event_meaning import _default_policy
        return _default_policy.classify(event_type, payload).coalescing_priority
