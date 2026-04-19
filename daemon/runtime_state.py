from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any


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
        with self._lock:
            return self._last_signals, self._last_decision, self._paused

    def get_context_snapshot(self) -> tuple[Any, Any]:
        with self._lock:
            return self._last_signals, self._last_decision

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
