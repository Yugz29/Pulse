from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Optional

from daemon.core.contracts import Episode
from daemon.core.uid import new_uid


EPISODE_TIMEOUT_MIN = 20
SEMANTIC_TASK_CONFIDENCE_MIN = 0.65
_SEMANTIC_PENDING_TIMEOUT_SEC = 600


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
        self._pending_semantic_key: tuple[str, str] | None = None
        self._pending_semantic_since: datetime | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def current_episode(self) -> Episode | None:
        return self._current_episode

    @property
    def semantic_boundary_pending(self) -> bool:
        return self._pending_semantic_key is not None

    def ensure_active(self, *, session_id: str | None, started_at: datetime | None) -> EpisodeTransition:
        if not session_id or started_at is None:
            return EpisodeTransition(current_episode=self._current_episode)
        if self._current_episode is not None:
            if self._current_episode.session_id != session_id:
                self._current_episode = None
                self._state = self.CLOSED
                self._suspended_at = None
                self._clear_pending_semantic_boundary()
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

    def sync_current_semantics(
        self,
        *,
        active_project: str | None,
        probable_task: str | None,
        activity_level: str | None,
        task_confidence: float | None,
    ) -> Episode | None:
        if self._current_episode is None:
            return None

        updated = replace(
            self._current_episode,
            active_project=active_project,
            probable_task=probable_task,
            activity_level=activity_level,
            task_confidence=task_confidence,
        )
        if updated == self._current_episode:
            return None
        self._current_episode = updated
        return updated

    def on_semantic_signal(
        self,
        *,
        session_id: str | None,
        when: datetime | None,
        active_project: str | None,
        probable_task: str | None,
        task_confidence: float | None,
    ) -> EpisodeTransition:
        if self._current_episode is None or session_id is None or when is None:
            self._clear_pending_semantic_boundary()
            return EpisodeTransition(current_episode=self._current_episode)

        boundary_reason, pending_key = self._semantic_boundary_candidate(
            active_project=active_project,
            probable_task=probable_task,
            task_confidence=task_confidence,
        )
        if boundary_reason is None or pending_key is None:
            self._clear_pending_semantic_boundary()
            return EpisodeTransition(current_episode=self._current_episode)

        if self._pending_semantic_key != pending_key:
            self._pending_semantic_key = pending_key
            self._pending_semantic_since = when
            return EpisodeTransition(current_episode=self._current_episode)

        if (
            self._pending_semantic_since is not None
            and (when - self._pending_semantic_since).total_seconds() > _SEMANTIC_PENDING_TIMEOUT_SEC
        ):
            self._pending_semantic_key = pending_key
            self._pending_semantic_since = when
            return EpisodeTransition(current_episode=self._current_episode)

        return self._split_current(
            session_id=session_id,
            when=when,
            boundary_reason=boundary_reason,
        )

    def reset_for_tests(self) -> None:
        self._state = self.CLOSED
        self._current_episode = None
        self._suspended_at = None
        self._clear_pending_semantic_boundary()

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
            active_project=self._current_episode.active_project,
            probable_task=self._current_episode.probable_task,
            activity_level=self._current_episode.activity_level,
            task_confidence=self._current_episode.task_confidence,
        )
        self._current_episode = None
        self._state = self.CLOSED
        self._suspended_at = None
        self._clear_pending_semantic_boundary()
        return closed

    def _split_current(
        self,
        *,
        session_id: str,
        when: datetime,
        boundary_reason: str,
    ) -> EpisodeTransition:
        closed = self._close_current(
            ended_at=when,
            boundary_reason=boundary_reason,
        )
        opened = self._open_episode(session_id=session_id, started_at=when)
        return EpisodeTransition(
            boundary_detected=True,
            boundary_reason=boundary_reason,
            closed_episode=closed,
            opened_episode=opened,
            current_episode=self._current_episode,
        )

    def _semantic_boundary_candidate(
        self,
        *,
        active_project: str | None,
        probable_task: str | None,
        task_confidence: float | None,
    ) -> tuple[str | None, tuple[str, str] | None]:
        current = self._current_episode
        if current is None:
            return None, None

        current_project = current.active_project
        if (
            current_project is not None
            and active_project is not None
            and active_project != current_project
        ):
            return "project_change", ("project_change", active_project)

        current_task = current.probable_task
        current_confidence = current.task_confidence or 0.0
        next_confidence = task_confidence or 0.0
        if (
            current_task is not None
            and probable_task is not None
            and probable_task != current_task
            and current_confidence >= SEMANTIC_TASK_CONFIDENCE_MIN
            and next_confidence >= SEMANTIC_TASK_CONFIDENCE_MIN
        ):
            return "task_change", ("task_change", probable_task)

        return None, None

    def _clear_pending_semantic_boundary(self) -> None:
        self._pending_semantic_key = None
        self._pending_semantic_since = None
