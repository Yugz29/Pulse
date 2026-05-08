"""Pure debug comparator between persisted journal entries and dry-run candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping

_MATCH_DISTANCE_MIN = 20
_LARGE_DELTA_MIN = 20


@dataclass(frozen=True)
class JournalCandidateMatch:
    journal_entry_id: str | None
    candidate_id: str | None
    project: str | None
    journal_started_at: str | None
    journal_ended_at: str | None
    candidate_started_at: str | None
    candidate_ended_at: str | None
    start_delta_min: int | None
    end_delta_min: int | None
    duration_delta_min: int | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class JournalCandidateComparison:
    journal_entry_count: int
    candidate_count: int
    matches: tuple[JournalCandidateMatch, ...]
    unmatched_journal_entries: tuple[dict[str, Any], ...]
    unmatched_candidates: tuple[dict[str, Any], ...]


def compare_journal_candidates(
    journal_entries: list[Any],
    candidates: list[Any],
) -> dict[str, Any]:
    """Compare journal entries and dry-run candidates without deciding which is better."""
    journal_items = [_entry_dict(entry) for entry in journal_entries]
    candidate_items = [
        _entry_dict(candidate)
        for candidate in candidates
        if not _truthy(_entry_dict(candidate).get("ignored"))
    ]

    matched_candidate_indexes: set[int] = set()
    matches: list[JournalCandidateMatch] = []
    unmatched_journal_entries: list[dict[str, Any]] = []

    for journal in journal_items:
        best_index = _best_candidate_index(journal, candidate_items, matched_candidate_indexes)
        if best_index is None:
            unmatched_journal_entries.append(_unmatched_journal_entry(journal))
            continue

        matched_candidate_indexes.add(best_index)
        matches.append(_build_match(journal, candidate_items[best_index]))

    unmatched_candidates = [
        _unmatched_candidate(candidate)
        for index, candidate in enumerate(candidate_items)
        if index not in matched_candidate_indexes
    ]

    comparison = JournalCandidateComparison(
        journal_entry_count=len(journal_items),
        candidate_count=len(candidate_items),
        matches=tuple(matches),
        unmatched_journal_entries=tuple(unmatched_journal_entries),
        unmatched_candidates=tuple(unmatched_candidates),
    )
    return _comparison_to_dict(comparison)


def _best_candidate_index(
    journal: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
    used_indexes: set[int],
) -> int | None:
    scored: list[tuple[int, int, int]] = []
    for index, candidate in enumerate(candidates):
        if index in used_indexes:
            continue
        distance = _window_distance_min(journal, candidate)
        if distance is None:
            continue
        if not _projects_compatible(journal, candidate):
            continue
        if distance > _MATCH_DISTANCE_MIN:
            continue
        project_penalty = 0 if _project(journal) == _project(candidate) else 1
        start_delta = _abs_delta_min(journal.get("started_at"), candidate.get("started_at"))
        scored.append((project_penalty, distance, start_delta if start_delta is not None else 999999, index))
    if not scored:
        return None
    return min(scored)[3]


def _build_match(journal: Mapping[str, Any], candidate: Mapping[str, Any]) -> JournalCandidateMatch:
    journal_duration = _duration_min(journal)
    candidate_duration = _duration_min(candidate)
    start_delta = _signed_delta_min(journal.get("started_at"), candidate.get("started_at"))
    end_delta = _signed_delta_min(journal.get("ended_at"), candidate.get("ended_at"))
    duration_delta = None
    if journal_duration is not None and candidate_duration is not None:
        duration_delta = candidate_duration - journal_duration

    flags = _flags_for_match(
        journal,
        candidate,
        start_delta=start_delta,
        duration_delta=duration_delta,
    )
    return JournalCandidateMatch(
        journal_entry_id=_optional_text(journal.get("entry_id")),
        candidate_id=_optional_text(candidate.get("id")),
        project=_project(candidate) or _project(journal),
        journal_started_at=_optional_text(journal.get("started_at")),
        journal_ended_at=_optional_text(journal.get("ended_at")),
        candidate_started_at=_optional_text(candidate.get("started_at")),
        candidate_ended_at=_optional_text(candidate.get("ended_at")),
        start_delta_min=start_delta,
        end_delta_min=end_delta,
        duration_delta_min=duration_delta,
        flags=flags,
    )


def _flags_for_match(
    journal: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    start_delta: int | None,
    duration_delta: int | None,
) -> tuple[str, ...]:
    flags: list[str] = []
    if _project(journal) != _project(candidate):
        flags.append("project_mismatch")
    if _overlap_min(journal, candidate) <= 0:
        flags.append("no_overlap")
    elif abs(start_delta or 0) <= 5 and abs(_signed_delta_min(journal.get("ended_at"), candidate.get("ended_at")) or 0) <= 5:
        flags.append("time_aligned")

    if duration_delta is not None:
        if duration_delta < 0:
            flags.append("journal_longer")
        elif duration_delta > 0:
            flags.append("candidate_longer")
        if abs(duration_delta) > _LARGE_DELTA_MIN:
            flags.append("large_duration_delta")
    if start_delta is not None and abs(start_delta) > _LARGE_DELTA_MIN:
        flags.append("large_start_delta")
    if _journal_has_commit(journal):
        flags.append("journal_has_commit")
        flags.append("candidate_no_commit_context")
    if _truthy(candidate.get("ignored")):
        flags.append("candidate_open_ignored")
    return tuple(flags)


def _unmatched_journal_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": _optional_text(entry.get("entry_id")),
        "project": _project(entry),
        "started_at": _optional_text(entry.get("started_at")),
        "ended_at": _optional_text(entry.get("ended_at")),
        "duration_min": _duration_min(entry),
        "flags": tuple(["journal_has_commit"] if _journal_has_commit(entry) else []),
    }


def _unmatched_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    flags = ["candidate_open_ignored"] if _truthy(candidate.get("ignored")) else []
    return {
        "id": _optional_text(candidate.get("id")),
        "episode_id": _optional_text(candidate.get("episode_id")),
        "project": _project(candidate),
        "started_at": _optional_text(candidate.get("started_at")),
        "ended_at": _optional_text(candidate.get("ended_at")),
        "duration_min": _duration_min(candidate),
        "flags": tuple(flags),
    }


def _comparison_to_dict(comparison: JournalCandidateComparison) -> dict[str, Any]:
    return {
        "journal_entry_count": comparison.journal_entry_count,
        "candidate_count": comparison.candidate_count,
        "matches": [asdict(match) for match in comparison.matches],
        "unmatched_journal_entries": list(comparison.unmatched_journal_entries),
        "unmatched_candidates": list(comparison.unmatched_candidates),
    }


def _entry_dict(entry: Any) -> Mapping[str, Any]:
    if isinstance(entry, Mapping):
        return entry
    return asdict(entry)


def _project(entry: Mapping[str, Any]) -> str | None:
    return _optional_text(entry.get("project") or entry.get("active_project"))


def _projects_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_project = _project(left)
    right_project = _project(right)
    return left_project is None or right_project is None or left_project == right_project


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


def _signed_delta_min(base: Any, candidate: Any) -> int | None:
    base_dt = _parse_dt(base)
    candidate_dt = _parse_dt(candidate)
    if base_dt is None or candidate_dt is None:
        return None
    return int((candidate_dt - base_dt).total_seconds() / 60)


def _abs_delta_min(base: Any, candidate: Any) -> int | None:
    delta = _signed_delta_min(base, candidate)
    return abs(delta) if delta is not None else None


def _journal_has_commit(entry: Mapping[str, Any]) -> bool:
    if _optional_text(entry.get("commit_message")):
        return True
    commit_messages = entry.get("commit_messages")
    if isinstance(commit_messages, list) and any(_optional_text(item) for item in commit_messages):
        return True
    commit_items = entry.get("commit_items")
    return isinstance(commit_items, list) and len(commit_items) > 0


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
