"""Pure dry-run linker between journal commits and work episode candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping

_STRONG_DELIVERY_PROXIMITY_MIN = 30
_ACCEPTABLE_DELIVERY_PROXIMITY_MIN = 90
_WINDOW_PROXIMITY_MIN = 20
_MAX_WINDOW_DISTANCE_MIN = 60
_AMBIGUOUS_SCORE_DELTA = 0.10


@dataclass(frozen=True)
class CommitEpisodeLink:
    id: str
    entry_id: str
    commit_subject: str
    commit_message: str | None
    delivered_at: str | None
    journal_started_at: str | None
    journal_ended_at: str | None
    episode_id: str | None
    candidate_id: str | None
    episode_started_at: str | None
    episode_ended_at: str | None
    project: str | None
    confidence: float
    status: str
    link_reason: str | None
    flags: tuple[str, ...]
    delivery_delta_min: int | None = None
    window_distance_min: int | None = None
    overlap_min: int | None = None
    score_breakdown: dict[str, Any] | None = None


def link_commits_to_episodes(
    journal_entries: list[Any],
    candidates: list[Any],
) -> dict[str, Any]:
    """Link persisted journal commit units to closed dry-run candidates."""
    commits = _extract_commits(journal_entries)
    candidate_items = [
        _entry_dict(candidate)
        for candidate in candidates
        if not _truthy(_entry_dict(candidate).get("ignored"))
    ]

    links: list[CommitEpisodeLink] = []
    unlinked: list[CommitEpisodeLink] = []
    for commit in commits:
        link = _link_one_commit(commit, candidate_items)
        if link.status == "linked":
            links.append(link)
        else:
            unlinked.append(link)

    return {
        "commit_count": len(commits),
        "linked_count": len(links),
        "unlinked_count": len(unlinked),
        "links": [asdict(link) for link in links],
        "unlinked_commits": [asdict(link) for link in unlinked],
    }


def _link_one_commit(commit: Mapping[str, Any], candidates: list[Mapping[str, Any]]) -> CommitEpisodeLink:
    scored = [
        item
        for item in (_score_candidate(commit, candidate) for candidate in candidates)
        if item is not None
    ]
    if not scored:
        flags = [*_commit_base_flags(commit), "no_plausible_episode"]
        if _optional_text(commit.get("delivered_at")):
            flags.append("no_delivery_near_episode")
            flags.append("delivery_far_from_episode")
        return _build_link(
            commit,
            None,
            confidence=0.0,
            status="unlinked",
            link_reason=None,
            flags=tuple(flags),
        )

    scored.sort(key=lambda item: (item["score"], -item["rank_delta"]), reverse=True)
    best = scored[0]
    flags = list(best["flags"])
    if len(scored) > 1 and (best["score"] - scored[1]["score"]) <= _AMBIGUOUS_SCORE_DELTA:
        flags.append("ambiguous_candidates")
    if _has_stale_journal_overlap_ignored(commit, candidates, best["candidate"]):
        flags.append("stale_journal_window_ignored")
    confidence, flags = _calibrated_confidence(best["score"], flags)
    return _build_link(
        commit,
        best["candidate"],
        confidence=confidence,
        status="linked",
        link_reason=best["reason"],
        flags=tuple(flags),
        score_breakdown=best["score_breakdown"],
    )


def _score_candidate(commit: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    if not _projects_compatible(commit, candidate):
        return None

    window_distance = _window_distance_min(commit, candidate)
    overlap = _overlap_min(commit, candidate)
    delivery_delta = _delivery_delta_min(commit.get("delivered_at"), candidate.get("ended_at"))
    delivery_score = _delivery_score(commit.get("delivered_at"), candidate)

    flags = list(_commit_base_flags(commit))
    score = 0.0
    reason = None

    if _optional_text(commit.get("delivered_at")):
        if delivery_score is None:
            return None
        score = delivery_score
        reason = "delivery_near_candidate_end"
        flags.append("linked_by_delivery_proximity")
        if delivery_delta is not None and delivery_delta <= 0:
            flags.append("delivery_inside_episode")
        elif delivery_delta is not None:
            flags.append("delivery_after_episode")
    elif overlap > 0:
        score = 0.58
        reason = "journal_candidate_overlap"
        flags.append("linked_by_overlap")
    elif window_distance is not None and window_distance <= _WINDOW_PROXIMITY_MIN:
        score = 0.45
        reason = "journal_window_near_candidate_window"
        flags.append("linked_by_window_proximity")
    else:
        return None

    if (
        not _optional_text(commit.get("delivered_at"))
        and window_distance is not None
        and window_distance > _MAX_WINDOW_DISTANCE_MIN
        and overlap <= 0
    ):
        return None

    flags.extend(_window_length_flags(commit, candidate))
    flags.append("candidate_no_commit_context")
    flags.append("no_file_scope_match")
    return {
        "candidate": candidate,
        "score": score,
        "reason": reason,
        "flags": tuple(dict.fromkeys(flags)),
        "rank_delta": _delivery_rank_delta(commit.get("delivered_at"), candidate),
        "score_breakdown": {
            "base_score": score,
            "delivery_delta_min": delivery_delta,
            "window_distance_min": window_distance,
            "overlap_min": overlap if overlap > 0 else 0,
        },
    }


def _build_link(
    commit: Mapping[str, Any],
    candidate: Mapping[str, Any] | None,
    *,
    confidence: float,
    status: str,
    link_reason: str | None,
    flags: tuple[str, ...],
    score_breakdown: dict[str, Any] | None = None,
) -> CommitEpisodeLink:
    delivery_delta = _delivery_delta_min(commit.get("delivered_at"), candidate.get("ended_at")) if candidate is not None else None
    window_distance = _window_distance_min(commit, candidate) if candidate is not None else None
    overlap = _overlap_min(commit, candidate) if candidate is not None else 0
    return CommitEpisodeLink(
        id=str(commit.get("id") or ""),
        entry_id=str(commit.get("entry_id") or ""),
        commit_subject=str(commit.get("commit_subject") or ""),
        commit_message=_optional_text(commit.get("commit_message")),
        delivered_at=_optional_text(commit.get("delivered_at")),
        journal_started_at=_optional_text(commit.get("started_at")),
        journal_ended_at=_optional_text(commit.get("ended_at")),
        episode_id=_optional_text(candidate.get("episode_id")) if candidate is not None else None,
        candidate_id=_optional_text(candidate.get("id")) if candidate is not None else None,
        episode_started_at=_optional_text(candidate.get("started_at")) if candidate is not None else None,
        episode_ended_at=_optional_text(candidate.get("ended_at")) if candidate is not None else None,
        project=_project(candidate) if candidate is not None else _project(commit),
        confidence=confidence,
        status=status,
        link_reason=link_reason,
        flags=flags,
        delivery_delta_min=delivery_delta,
        window_distance_min=window_distance,
        overlap_min=overlap if overlap > 0 else 0,
        score_breakdown=score_breakdown,
    )


def _extract_commits(journal_entries: list[Any]) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    for entry in journal_entries:
        item = _entry_dict(entry)
        messages = _commit_messages(item)
        for index, message in enumerate(messages):
            entry_id = str(item.get("entry_id") or "")
            commits.append({
                "id": f"commit-link-{entry_id}-{index + 1}",
                "entry_id": entry_id,
                "commit_subject": _commit_subject(message),
                "commit_message": message,
                "delivered_at": _optional_text(item.get("delivered_at")),
                "started_at": _optional_text(item.get("started_at")),
                "ended_at": _optional_text(item.get("ended_at")),
                "project": _project(item),
                "top_files": item.get("top_files") or [],
            })
    return commits


def _commit_messages(entry: Mapping[str, Any]) -> list[str]:
    messages: list[str] = []
    raw_messages = entry.get("commit_messages")
    if isinstance(raw_messages, list):
        messages.extend(_optional_text(message) for message in raw_messages)
    else:
        messages.append(_optional_text(entry.get("commit_message")))
    compacted = list(dict.fromkeys(message for message in messages if message))
    if not compacted and _optional_text(entry.get("commit_message")):
        compacted.append(str(entry.get("commit_message")))
    return compacted


def _commit_subject(message: str) -> str:
    for line in str(message).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return str(message).strip()


def _commit_base_flags(commit: Mapping[str, Any]) -> tuple[str, ...]:
    flags: list[str] = []
    if not _optional_text(commit.get("delivered_at")):
        flags.append("no_delivered_at")
    if _duration_min(commit) == 0:
        flags.append("commit_only_journal_entry")
    return tuple(flags)


def _window_length_flags(commit: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[str, ...]:
    commit_duration = _duration_min(commit)
    candidate_duration = _duration_min(candidate)
    if commit_duration is None or candidate_duration is None or commit_duration == candidate_duration:
        return ()
    if commit_duration > candidate_duration:
        return ("journal_window_longer",)
    return ("candidate_window_longer",)


def _calibrated_confidence(score: float, flags: list[str]) -> tuple[float, list[str]]:
    caps: list[float] = []
    if "ambiguous_candidates" in flags:
        caps.append(0.72)
    if "candidate_no_commit_context" in flags or "no_file_scope_match" in flags:
        caps.append(0.78)
    if "commit_only_journal_entry" in flags:
        caps.append(0.72)

    confidence = min([score, *caps]) if caps else score
    if confidence < score and ("candidate_no_commit_context" in flags or "no_file_scope_match" in flags):
        flags.append("confidence_capped_no_commit_context")
    return round(float(confidence), 2), list(dict.fromkeys(flags))


def _has_stale_journal_overlap_ignored(
    commit: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
    selected: Mapping[str, Any],
) -> bool:
    if not _optional_text(commit.get("delivered_at")):
        return False
    selected_id = _optional_text(selected.get("id"))
    for candidate in candidates:
        if _optional_text(candidate.get("id")) == selected_id:
            continue
        if not _projects_compatible(commit, candidate):
            continue
        if _overlap_min(commit, candidate) > 0:
            return True
    return False


def _projects_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_project = _project(left)
    right_project = _project(right)
    return left_project is None or right_project is None or left_project == right_project


def _project(entry: Mapping[str, Any]) -> str | None:
    return _optional_text(entry.get("project") or entry.get("active_project"))


def _window_distance_min(left: Mapping[str, Any], right: Mapping[str, Any]) -> int | None:
    left_start = _parse_dt(left.get("started_at"))
    left_end = _parse_dt(left.get("ended_at"))
    right_start = _parse_dt(right.get("started_at"))
    right_end = _parse_dt(right.get("ended_at"))
    if None in {left_start, left_end, right_start, right_end}:
        return None
    if left_end < right_start:
        return int((right_start - left_end).total_seconds() / 60)
    if right_end < left_start:
        return int((left_start - right_end).total_seconds() / 60)
    return 0


def _overlap_min(left: Mapping[str, Any], right: Mapping[str, Any]) -> int:
    left_start = _parse_dt(left.get("started_at"))
    left_end = _parse_dt(left.get("ended_at"))
    right_start = _parse_dt(right.get("started_at"))
    right_end = _parse_dt(right.get("ended_at"))
    if None in {left_start, left_end, right_start, right_end}:
        return 0
    overlap = (min(left_end, right_end) - max(left_start, right_start)).total_seconds() / 60
    return max(int(overlap), 0)


def _delivery_score(delivered_at: Any, candidate: Mapping[str, Any]) -> float | None:
    delivered = _parse_dt(delivered_at)
    started = _parse_dt(candidate.get("started_at"))
    ended = _parse_dt(candidate.get("ended_at"))
    if delivered is None or started is None or ended is None:
        return None
    if delivered < started:
        return None
    minutes_after_end = int((delivered - ended).total_seconds() / 60)
    if minutes_after_end <= 0:
        return 0.82
    if minutes_after_end <= _STRONG_DELIVERY_PROXIMITY_MIN:
        return 0.76 - (minutes_after_end / 1000)
    if minutes_after_end <= _ACCEPTABLE_DELIVERY_PROXIMITY_MIN:
        return 0.62 - (minutes_after_end / 1000)
    return None


def _delivery_delta_min(delivered_at: Any, candidate_ended_at: Any) -> int | None:
    delivered = _parse_dt(delivered_at)
    ended = _parse_dt(candidate_ended_at)
    if delivered is None or ended is None:
        return None
    return int((delivered - ended).total_seconds() / 60)


def _delivery_rank_delta(delivered_at: Any, candidate: Mapping[str, Any]) -> int:
    delivered = _parse_dt(delivered_at)
    started = _parse_dt(candidate.get("started_at"))
    ended = _parse_dt(candidate.get("ended_at"))
    if delivered is None or started is None or ended is None:
        return 999999
    if started <= delivered <= ended:
        return 0
    if delivered > ended:
        return int((delivered - ended).total_seconds() / 60)
    return int((started - delivered).total_seconds() / 60)


def _duration_min(entry: Mapping[str, Any]) -> int | None:
    value = entry.get("duration_min")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    started_at = _parse_dt(entry.get("started_at"))
    ended_at = _parse_dt(entry.get("ended_at"))
    if started_at is None or ended_at is None:
        return None
    return max(int((ended_at - started_at).total_seconds() / 60), 0)


def _entry_dict(entry: Any) -> Mapping[str, Any]:
    if isinstance(entry, Mapping):
        return entry
    return asdict(entry)


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)
