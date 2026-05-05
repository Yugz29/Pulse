"""Pure dry-run journal candidate builder for work episodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class JournalCandidate:
    id: str
    episode_id: str
    project: str | None
    probable_task: str
    dominant_scope: str | None
    started_at: str
    ended_at: str
    duration_min: int
    boundary_reason: str
    strong_event_count: int
    weak_event_count: int
    confidence: float
    status: str
    ignored: bool
    ignore_reason: str | None
    debug_reason: str | None
    uncertainty_flags: tuple[str, ...] = ()


def build_journal_candidates(episodes: list[Any]) -> list[JournalCandidate]:
    """Project work episodes into dry-run journal candidates without merging."""
    return [_candidate_from_episode(_episode_dict(episode)) for episode in episodes]


def journal_candidates_to_payload(candidates: list[JournalCandidate]) -> dict[str, Any]:
    candidate_items = [asdict(candidate) for candidate in candidates if not candidate.ignored]
    ignored_items = [asdict(candidate) for candidate in candidates if candidate.ignored]
    return {
        "candidate_count": len(candidate_items),
        "ignored_count": len(ignored_items),
        "candidates": candidate_items,
        "ignored": ignored_items,
    }


def _candidate_from_episode(episode: Mapping[str, Any]) -> JournalCandidate:
    episode_id = str(episode.get("id") or "")
    boundary_reason = str(episode.get("boundary_reason") or "unknown")
    ignored = boundary_reason == "end_of_events"
    return JournalCandidate(
        id=f"journal-candidate-{episode_id}" if episode_id else "journal-candidate-unknown",
        episode_id=episode_id,
        project=_optional_text(episode.get("project")),
        probable_task=str(episode.get("probable_task") or "general"),
        dominant_scope=_optional_text(episode.get("dominant_scope")),
        started_at=str(episode.get("started_at") or ""),
        ended_at=str(episode.get("ended_at") or ""),
        duration_min=_int_value(episode.get("duration_min")),
        boundary_reason=boundary_reason,
        strong_event_count=_int_value(episode.get("strong_event_count")),
        weak_event_count=_int_value(episode.get("weak_event_count")),
        confidence=_float_value(episode.get("confidence")),
        status="ignored" if ignored else "candidate",
        ignored=ignored,
        ignore_reason="open_episode_end_of_events" if ignored else None,
        debug_reason=_optional_text(episode.get("debug_reason")),
        uncertainty_flags=tuple(str(flag) for flag in episode.get("uncertainty_flags") or ()),
    )


def _episode_dict(episode: Any) -> Mapping[str, Any]:
    if isinstance(episode, Mapping):
        return episode
    return asdict(episode)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
