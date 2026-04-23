from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .file_classifier import file_signal_significance

SESSION_TIMEOUT_MIN = 30

_MEANINGFUL_FILE_EVENT_TYPES = {"file_created", "file_modified", "file_renamed"}
_MEANINGFUL_TERMINAL_EVENT_TYPES = {"terminal_command_started", "terminal_command_finished"}
_DEV_APPS = {
    "Xcode", "VSCode", "Visual Studio Code", "Cursor", "WebStorm",
    "PyCharm", "Terminal", "iTerm2", "Warp",
}


@dataclass(frozen=True)
class SessionTransition:
    state: str
    boundary_detected: bool = False
    boundary_reason: Optional[str] = None
    should_reset_clock: bool = False
    should_start_new_session: bool = False
    should_clear_sleep_markers: bool = False
    sleep_minutes: Optional[float] = None


class SessionFSM:
    """
    Source unique de vérité du cycle de session.

    La FSM décide des transitions; les side effects externes
    (sync mémoire, SessionMemory.new_session, logs) restent à l'orchestrateur.
    """

    ACTIVE = "active"
    IDLE = "idle"
    LOCKED = "locked"

    def __init__(self) -> None:
        self._state = self.IDLE
        self._session_started_at = datetime.now()
        self._last_meaningful_activity_at: datetime | None = None
        self._last_screen_locked_at: datetime | None = None
        self._ignored_short_lock_at: datetime | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def session_started_at(self) -> datetime:
        return self._session_started_at

    @property
    def last_meaningful_activity_at(self) -> datetime | None:
        return self._last_meaningful_activity_at

    @property
    def last_screen_locked_at(self) -> datetime | None:
        return self._last_screen_locked_at

    def is_locked(self) -> bool:
        return self._state == self.LOCKED

    def on_screen_locked(self, when: datetime | None = None) -> SessionTransition:
        locked_at = when or datetime.now()
        if self._state != self.LOCKED and self._last_screen_locked_at is None:
            self._last_screen_locked_at = locked_at
        self._state = self.LOCKED
        return SessionTransition(state=self._state)

    def on_screen_unlocked(
        self,
        *,
        when: datetime | None = None,
        sleep_session_threshold_min: int,
    ) -> SessionTransition:
        unlocked_at = when or datetime.now()
        sleep_minutes: float | None = None
        boundary = False
        locked_at = self._last_screen_locked_at

        if locked_at is not None:
            sleep_minutes = (
                unlocked_at - locked_at
            ).total_seconds() / 60
            boundary = sleep_minutes >= sleep_session_threshold_min
            if boundary:
                self._session_started_at = unlocked_at
                self._last_meaningful_activity_at = None
                self._ignored_short_lock_at = None
            else:
                self._ignored_short_lock_at = locked_at

        self._state = self.ACTIVE
        self._last_screen_locked_at = None
        return SessionTransition(
            state=self._state,
            boundary_detected=boundary,
            boundary_reason="screen_lock" if boundary else None,
            should_reset_clock=sleep_minutes is not None,
            should_start_new_session=boundary,
            should_clear_sleep_markers=sleep_minutes is not None,
            sleep_minutes=sleep_minutes,
        )

    def on_user_idle(self) -> SessionTransition:
        if self._state != self.LOCKED:
            self._state = self.IDLE
        return SessionTransition(state=self._state)

    def observe_recent_events(
        self,
        *,
        recent_events: list,
        now: datetime | None = None,
    ) -> SessionTransition:
        current_time = now or datetime.now()
        latest_meaningful = self._find_latest_meaningful_activity(recent_events)
        if latest_meaningful is None:
            if (
                self._state != self.LOCKED
                and self._last_meaningful_activity_at is None
            ):
                self._state = self.IDLE
            elif (
                self._state != self.LOCKED
                and self._last_meaningful_activity_at is not None
                and (current_time - self._last_meaningful_activity_at).total_seconds() / 60
                > SESSION_TIMEOUT_MIN
            ):
                self._state = self.IDLE
            return SessionTransition(state=self._state)

        if latest_meaningful >= self._session_started_at:
            previous_activity = self._last_meaningful_activity_at
            if previous_activity is not None:
                has_new_activity = latest_meaningful > previous_activity
                if has_new_activity:
                    screen_lock_at = self._latest_screen_lock_after(
                        recent_events,
                        previous_activity,
                    )
                    had_screen_lock = self._is_session_boundary_screen_lock(screen_lock_at)
                    if (
                        screen_lock_at is not None
                        and self._ignored_short_lock_at is not None
                        and screen_lock_at == self._ignored_short_lock_at
                    ):
                        self._ignored_short_lock_at = None
                    gap_minutes = (
                        latest_meaningful - previous_activity
                    ).total_seconds() / 60
                    if had_screen_lock or gap_minutes > SESSION_TIMEOUT_MIN:
                        self._session_started_at = latest_meaningful
                        self._last_meaningful_activity_at = latest_meaningful
                        self._state = self.ACTIVE
                        return SessionTransition(
                            state=self._state,
                            boundary_detected=True,
                            boundary_reason="screen_lock" if had_screen_lock else "idle",
                            should_reset_clock=True,
                            should_start_new_session=True,
                        )
            else:
                self._session_started_at = latest_meaningful

            self._last_meaningful_activity_at = latest_meaningful

        self._state = self.ACTIVE
        return SessionTransition(state=self._state)

    def reset_for_tests(self) -> None:
        self._state = self.IDLE
        self._session_started_at = datetime.now()
        self._last_meaningful_activity_at = None
        self._last_screen_locked_at = None
        self._ignored_short_lock_at = None

    def _find_latest_meaningful_activity(self, events: list) -> Optional[datetime]:
        for event in reversed(events):
            if event.type in _MEANINGFUL_TERMINAL_EVENT_TYPES:
                return event.timestamp
            if event.type in _MEANINGFUL_FILE_EVENT_TYPES:
                if self._is_trackable_file_path(event.payload.get("path")):
                    return event.timestamp
            if event.type in {"app_activated", "app_switch"}:
                if event.payload.get("app_name") in _DEV_APPS:
                    return event.timestamp
        return None

    def _latest_screen_lock_after(self, events: list, since: datetime) -> Optional[datetime]:
        for event in reversed(events):
            if event.type == "screen_locked" and event.timestamp > since:
                return event.timestamp
        return None

    def _is_session_boundary_screen_lock(self, lock_at: Optional[datetime]) -> bool:
        if lock_at is None:
            return False
        return lock_at != self._ignored_short_lock_at

    def _is_trackable_file_path(self, path: Optional[str]) -> bool:
        return file_signal_significance(path) != "technical_noise"
