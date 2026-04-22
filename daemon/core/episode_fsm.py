from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from daemon.core.contracts import Episode
from daemon.core.uid import new_uid


EPISODE_TIMEOUT_MIN = 20


@dataclass(frozen=True)
class EpisodeTransition:
    boundary_detected: bool = False
    boundary_reason: Optional[str] = None
    closed_episode: Optional[Episode] = None
    opened_episode: Optional[Episode] = None
    current_episode: Optional[Episode] = None


class EpisodeFSM:
    """
    Source de vérité des frontières d'épisode.

    La FSM ne relit pas le bus seule : elle reçoit des signaux normalisés
    depuis l'orchestrateur et reste purement responsable du cycle de vie
    de l'épisode courant.
    """

    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"

    def __init__(self) -> None:
        self._state = self.CLOSED
        self._current_episode: Episode | None = None
        self._suspended_at: datetime | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def current_episode(self) -> Episode | None:
        return self._current_episode

    def ensure_active(self, *, session_id: str | None, started_at: datetime | None) -> EpisodeTransition:
        if not session_id or started_at is None:
            return EpisodeTransition(current_episode=self._current_episode)
        if self._current_episode is not None:
            if self._current_episode.session_id != session_id:
                self._current_episode = None
                self._state = self.CLOSED
                self._suspended_at = None
            else:
                return EpisodeTransition(current_episode=self._current_episode)
        opened = self._open_episode(session_id=session_id, started_at=started_at)
        return EpisodeTransition(opened_episode=opened, current_episode=opened)

    def on_screen_locked(self, *, when: datetime | None = None) -> EpisodeTransition:
        if self._current_episode is None:
            return EpisodeTransition(current_episode=None)
        self._state = self.SUSPENDED
        self._suspended_at = when or datetime.now()
        return EpisodeTransition(current_episode=self._current_episode)

    def on_screen_unlocked(
        self,
        *,
        session_id: str | None,
        when: datetime | None,
        boundary_detected: bool,
    ) -> EpisodeTransition:
        unlocked_at = when or datetime.now()
        if not boundary_detected:
            self._state = self.ACTIVE if self._current_episode is not None else self.CLOSED
            self._suspended_at = None
            return EpisodeTransition(current_episode=self._current_episode)

        closed = self._close_current(
            ended_at=self._suspended_at or unlocked_at,
            boundary_reason="screen_lock",
        )
        opened = self._open_episode(session_id=session_id, started_at=unlocked_at) if session_id else None
        return EpisodeTransition(
            boundary_detected=True,
            boundary_reason="screen_lock",
            closed_episode=closed,
            opened_episode=opened,
            current_episode=self._current_episode,
        )

    def on_idle_timeout(
        self,
        *,
        session_id: str | None,
        last_meaningful_activity_at: datetime | None,
        resumed_at: datetime | None,
    ) -> EpisodeTransition:
        if last_meaningful_activity_at is None:
            return self.ensure_active(session_id=session_id, started_at=resumed_at)

        ended_at = last_meaningful_activity_at + timedelta(minutes=EPISODE_TIMEOUT_MIN)
        closed = self._close_current(
            ended_at=ended_at,
            boundary_reason="idle_timeout",
        )
        opened = self._open_episode(session_id=session_id, started_at=resumed_at) if session_id and resumed_at else None
        return EpisodeTransition(
            boundary_detected=True,
            boundary_reason="idle_timeout",
            closed_episode=closed,
            opened_episode=opened,
            current_episode=self._current_episode,
        )

    def on_commit(
        self,
        *,
        session_id: str | None,
        when: datetime | None,
    ) -> EpisodeTransition:
        commit_at = when or datetime.now()
        closed = self._close_current(
            ended_at=commit_at,
            boundary_reason="commit",
        )
        opened = self._open_episode(session_id=session_id, started_at=commit_at) if session_id else None
        return EpisodeTransition(
            boundary_detected=closed is not None,
            boundary_reason="commit" if closed is not None else None,
            closed_episode=closed,
            opened_episode=opened,
            current_episode=self._current_episode,
        )

    def close_current(
        self,
        *,
        ended_at: datetime | None,
        boundary_reason: str,
    ) -> EpisodeTransition:
        closed = self._close_current(ended_at=ended_at or datetime.now(), boundary_reason=boundary_reason)
        return EpisodeTransition(
            boundary_detected=closed is not None,
            boundary_reason=boundary_reason if closed is not None else None,
            closed_episode=closed,
            current_episode=self._current_episode,
        )

    def reset_for_tests(self) -> None:
        self._state = self.CLOSED
        self._current_episode = None
        self._suspended_at = None

    def _open_episode(self, *, session_id: str, started_at: datetime) -> Episode:
        opened = Episode(
            id=new_uid(),
            session_id=session_id,
            started_at=started_at.isoformat(),
        )
        self._current_episode = opened
        self._state = self.ACTIVE
        self._suspended_at = None
        return opened

    def _close_current(self, *, ended_at: datetime, boundary_reason: str) -> Episode | None:
        if self._current_episode is None:
            self._state = self.CLOSED
            self._suspended_at = None
            return None

        started_at = datetime.fromisoformat(self._current_episode.started_at)
        duration_sec = max(int((ended_at - started_at).total_seconds()), 0)
        closed = Episode(
            id=self._current_episode.id,
            session_id=self._current_episode.session_id,
            started_at=self._current_episode.started_at,
            ended_at=ended_at.isoformat(),
            boundary_reason=boundary_reason,
            duration_sec=duration_sec,
        )
        self._current_episode = None
        self._state = self.CLOSED
        self._suspended_at = None
        return closed
