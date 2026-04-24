from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class PresentState:
    session_status: str = "idle"
    awake: bool = True
    locked: bool = False
    active_file: str | None = None
    active_project: str | None = None
    probable_task: str = "general"
    activity_level: str = "idle"
    focus_level: str = "normal"
    friction_score: float = 0.0
    clipboard_context: str | None = None
    session_duration_min: int = 0
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_status": self.session_status,
            "awake": self.awake,
            "locked": self.locked,
            "active_file": self.active_file,
            "active_project": self.active_project,
            "probable_task": self.probable_task,
            "activity_level": self.activity_level,
            "focus_level": self.focus_level,
            "friction_score": self.friction_score,
            "clipboard_context": self.clipboard_context,
            "session_duration_min": self.session_duration_min,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass(frozen=True)
class RuntimeSnapshot:
    present: PresentState
    signals: Any = None
    decision: Any = None
    paused: bool = False
    memory_synced_at: datetime | None = None
    latest_active_app: str | None = None
    lock_marker_active: bool = False
    last_screen_locked_at: datetime | None = None


class RuntimeState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paused = False
        self._last_ping_at: datetime | None = None
        self._last_signals = None
        self._last_decision = None
        self._last_memory_sync_at: datetime | None = None
        self._last_screen_locked_at: datetime | None = None
        self._recent_file_events: dict[str, datetime] = {}
        self._screen_is_locked: bool = False
        self._latest_active_app: str | None = None
        self._present = PresentState()

    def touch_ping(self, when: datetime | None = None) -> bool:
        now = when or datetime.now()
        with self._lock:
            self._last_ping_at = now
            return self._paused

    def get_last_ping_at(self) -> datetime | None:
        with self._lock:
            return self._last_ping_at

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused

    def get_signal_snapshot(self) -> tuple[Any, Any, bool]:
        snapshot = self.get_runtime_snapshot()
        return snapshot.signals, snapshot.decision, snapshot.paused

    def get_context_snapshot(self) -> tuple[Any, Any]:
        snapshot = self.get_runtime_snapshot()
        return snapshot.signals, snapshot.decision

    def update_present(
        self,
        *,
        signals: Any,
        session_status: str,
        awake: bool,
        locked: bool,
        updated_at: datetime | None = None,
    ) -> PresentState:
        present = PresentState(
            session_status=session_status,
            awake=awake,
            locked=locked,
            active_file=getattr(signals, "active_file", None),
            active_project=getattr(signals, "active_project", None),
            probable_task=getattr(signals, "probable_task", "general"),
            activity_level=getattr(signals, "activity_level", "idle"),
            focus_level=getattr(signals, "focus_level", "normal"),
            friction_score=getattr(signals, "friction_score", 0.0),
            clipboard_context=getattr(signals, "clipboard_context", None),
            session_duration_min=getattr(signals, "session_duration_min", 0),
            updated_at=updated_at or datetime.now(),
        )
        with self._lock:
            self._present = present
            self._screen_is_locked = locked
            return self._present

    def get_present(self) -> PresentState:
        with self._lock:
            return self._present

    def get_present_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._present.to_dict()

    def get_runtime_snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return RuntimeSnapshot(
                present=self._present,
                signals=self._last_signals,
                decision=self._last_decision,
                paused=self._paused,
                memory_synced_at=self._last_memory_sync_at,
                latest_active_app=self._latest_active_app,
                lock_marker_active=self._screen_is_locked,
                last_screen_locked_at=self._last_screen_locked_at,
            )

    def set_analysis(
        self,
        *,
        signals: Any,
        decision: Any,
        memory_synced_at: datetime | None = None,
    ) -> None:
        with self._lock:
            self._last_signals = signals
            self._last_decision = decision
            if memory_synced_at is not None:
                self._last_memory_sync_at = memory_synced_at

    def get_last_memory_sync_at(self) -> datetime | None:
        with self._lock:
            return self._last_memory_sync_at

    def mark_screen_locked(self, when: datetime | None = None) -> None:
        with self._lock:
            # On enregistre l'heure du PREMIER signal de verrouillage uniquement.
            # Un second signal (ex. sommeil d'écran arrivant quelques minutes après
            # le vrai verrou utilisateur) ne doit pas écraser l'heure réelle du lock —
            # ce serait faux pour le calcul de sleep_min dans handle_event().
            if not self._screen_is_locked:
                self._last_screen_locked_at = when or datetime.now()
            self._screen_is_locked = True

    def mark_screen_unlocked(self) -> None:
        with self._lock:
            self._screen_is_locked = False

    def is_screen_locked(self) -> bool:
        with self._lock:
            return self._screen_is_locked

    def get_last_screen_locked_at(self) -> datetime | None:
        with self._lock:
            return self._last_screen_locked_at

    def clear_sleep_markers(self) -> None:
        with self._lock:
            self._last_screen_locked_at = None
            self._last_memory_sync_at = None

    def should_ignore_file_event(
        self,
        *,
        dedupe_key: str,
        now: datetime | None = None,
        cleanup_ttl: timedelta = timedelta(seconds=5),
        dedupe_window: timedelta = timedelta(seconds=1),
    ) -> bool:
        # Dédoublonnage purement technique, calé sur le temps local de réception.
        # Il ne porte aucune sémantique métier : le timestamp source reste
        # persistant dans l'event lui-même pour le scoring et la mémoire.
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

    def set_latest_active_app(self, app_name: str) -> None:
        with self._lock:
            self._latest_active_app = app_name

    def get_latest_active_app(self) -> str | None:
        with self._lock:
            return self._latest_active_app

    def reset_for_tests(self) -> None:
        with self._lock:
            self._paused = False
            self._last_ping_at = None
            self._last_signals = None
            self._last_decision = None
            self._last_memory_sync_at = None
            self._last_screen_locked_at = None
            self._screen_is_locked = False
            self._recent_file_events = {}
            self._latest_active_app = None
            self._present = PresentState()
