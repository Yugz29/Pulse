"""Pure dry-run linker between journal commits and work episode candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

_STRONG_DELIVERY_PROXIMITY_MIN = 30
_ACCEPTABLE_DELIVERY_PROXIMITY_MIN = 90
_WINDOW_PROXIMITY_MIN = 20
_MAX_WINDOW_DISTANCE_MIN = 60
_AMBIGUOUS_SCORE_DELTA = 0.10
_MAX_OPEN_EPISODE_DURATION_MIN = 8 * 60
_FUTURE_COMMIT_GRACE_MIN = 5
_DELAYED_FILE_OVERLAP_MIN = 90
_JOURNAL_FILE_WINDOW_DELAY_MIN = 6 * 60
_MIN_JOURNAL_WINDOW_VISIBLE_COVERAGE = 0.60


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
    relation_status: str
    commit_status: str
    link_reason: str | None
    flags: tuple[str, ...]
    delivery_delta_min: int | None = None
    window_distance_min: int | None = None
    overlap_min: int | None = None
    score_breakdown: dict[str, Any] | None = None
    evidence_level: str | None = None
    evidence_candidate_id: str | None = None
    evidence_episode_id: str | None = None
    evidence_started_at: str | None = None
    evidence_ended_at: str | None = None
    evidence_source: str | None = None


def link_commits_to_episodes(
    journal_entries: list[Any],
    candidates: list[Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Link persisted journal commit units to closed or currently open dry-run candidates."""
    commits = _extract_commits(journal_entries)
    candidate_items = [
        _entry_dict(candidate)
        for candidate in candidates
        if not _truthy(_entry_dict(candidate).get("ignored")) or _is_open_candidate(_entry_dict(candidate))
    ]

    links: list[CommitEpisodeLink] = []
    unlinked: list[CommitEpisodeLink] = []
    for commit in commits:
        link = _link_one_commit(commit, candidate_items, now=now)
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


def _link_one_commit(
    commit: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> CommitEpisodeLink:
    candidate_items = [*candidates]
    journal_candidate = _journal_file_window_candidate(commit, candidate_items)
    if journal_candidate is not None:
        candidate_items.append(journal_candidate)

    scored = [
        item
        for item in (_score_candidate(commit, candidate, now=now) for candidate in candidate_items)
        if item is not None
    ]
    if not scored:
        flags = [*_commit_base_flags(commit), "no_plausible_episode"]
        if _optional_text(commit.get("delivered_at")):
            if _has_stale_short_episode_candidate(commit, candidate_items):
                flags.append("stale_short_episode_candidate")
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
    if not _truthy(best["candidate"].get("journal_file_window")) and _has_stale_journal_overlap_ignored(
        commit,
        candidate_items,
        best["candidate"],
    ):
        flags.append("stale_journal_window_ignored")
    confidence, flags = _calibrated_confidence(best["score"], flags, best["score_breakdown"])
    return _build_link(
        commit,
        best["candidate"],
        confidence=confidence,
        status="linked",
        link_reason=best["reason"],
        flags=tuple(flags),
        score_breakdown=best["score_breakdown"],
    )


def _score_candidate(
    commit: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if not _projects_compatible(commit, candidate):
        return None

    if _is_open_candidate(candidate):
        return _score_open_candidate(commit, candidate, now=now)

    window_distance = _window_distance_min(commit, candidate)
    overlap = _overlap_min(commit, candidate)
    delivery_delta = _delivery_delta_min(commit.get("delivered_at"), candidate.get("ended_at"))
    delivery_score = _delivery_score(commit.get("delivered_at"), candidate)
    file_overlap = _file_overlap_count(commit, candidate)

    flags = list(_commit_base_flags(commit))
    candidate_flags = candidate.get("link_flags")
    if isinstance(candidate_flags, (list, tuple)):
        flags.extend(str(flag) for flag in candidate_flags if str(flag or "").strip())
    score = 0.0
    reason = None

    if _is_delayed_file_scope_match(commit, candidate, delivery_delta, file_overlap):
        reason = "linked_by_journal_file_window" if _truthy(candidate.get("journal_file_window")) else "linked_by_file_overlap"
        score = 0.93 if reason == "linked_by_journal_file_window" else (
            0.88 if delivery_delta is not None and delivery_delta > 0 else 0.90
        )
        flags.extend([
            reason,
            "linked_by_file_overlap",
            "work_episode_link",
        ])
        if delivery_delta is not None and delivery_delta > 0:
            flags.append("delayed_delivery")
            flags.append("delivery_after_episode")
    elif _optional_text(commit.get("delivered_at")):
        if delivery_score is None:
            return None
        if _is_stale_short_episode_delivery(delivery_delta, overlap, candidate):
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
    if file_overlap > 0:
        flags.append("candidate_file_scope_match")
    else:
        flags.append("candidate_no_commit_context")
        flags.append("no_file_scope_match")
        flags.append("temporal_only_link")
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
            "file_overlap_count": file_overlap,
        },
    }


def _score_open_candidate(
    commit: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    current_time = now or datetime.now()
    started = _parse_dt(candidate.get("started_at"))
    commit_time = _commit_time(commit)
    if started is None or commit_time is None:
        return None
    if commit_time < started:
        return None
    if commit_time > current_time + timedelta(minutes=_FUTURE_COMMIT_GRACE_MIN):
        return None

    open_duration = int((current_time - started).total_seconds() / 60)
    if open_duration < 0 or open_duration > _MAX_OPEN_EPISODE_DURATION_MIN:
        return None

    minutes_after_start = int((commit_time - started).total_seconds() / 60)
    flags = [flag for flag in _commit_base_flags(commit) if flag != "commit_only_journal_entry"]
    flags.extend([
        "linked_to_open_episode",
        "linked_by_open_episode_window",
        "candidate_no_commit_context",
        "no_file_scope_match",
        "temporal_only_link",
    ])
    score = 0.64
    return {
        "candidate": candidate,
        "score": score,
        "reason": "linked_to_open_episode",
        "flags": tuple(dict.fromkeys(flags)),
        "rank_delta": 0,
        "score_breakdown": {
            "base_score": score,
            "delivery_delta_min": None,
            "window_distance_min": 0,
            "overlap_min": 0,
            "open_episode_age_min": open_duration,
            "commit_after_open_start_min": minutes_after_start,
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
    episode_started_at = None
    episode_ended_at = None
    if candidate is not None:
        episode_started_at = _optional_text(candidate.get("display_started_at")) or _optional_text(candidate.get("started_at"))
        episode_ended_at = _optional_text(candidate.get("display_ended_at")) or _optional_text(candidate.get("ended_at"))
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
        episode_started_at=episode_started_at,
        episode_ended_at=episode_ended_at,
        evidence_candidate_id=_optional_text(candidate.get("id")) if candidate is not None else None,
        evidence_episode_id=_evidence_episode_id(candidate) if candidate is not None else None,
        evidence_started_at=_optional_text(candidate.get("started_at")) if candidate is not None else None,
        evidence_ended_at=_optional_text(candidate.get("ended_at")) if candidate is not None else None,
        evidence_source=_evidence_source(candidate, flags) if candidate is not None else None,
        project=_project(candidate) if candidate is not None else _project(commit),
        confidence=confidence,
        status=status,
        relation_status=_relation_status(status, flags),
        commit_status="observed_commit",
        link_reason=link_reason,
        flags=flags,
        delivery_delta_min=delivery_delta,
        window_distance_min=window_distance,
        overlap_min=overlap if overlap > 0 else 0,
        score_breakdown=score_breakdown,
        evidence_level="file_scope" if "linked_by_file_overlap" in flags else (
            "temporal_only" if "temporal_only_link" in flags else None
        ),
    )


def _relation_status(status: str, flags: tuple[str, ...]) -> str:
    if status != "linked":
        return "unrelated_or_unknown"
    if "temporal_only_link" in flags:
        return "weak_temporal_candidate"
    return "likely_related"


def _evidence_episode_id(candidate: Mapping[str, Any]) -> str | None:
    if _truthy(candidate.get("journal_file_window")):
        return _optional_text(candidate.get("id"))
    return _optional_text(candidate.get("episode_id")) or _optional_text(candidate.get("id"))


def _evidence_source(candidate: Mapping[str, Any], flags: tuple[str, ...]) -> str:
    if _truthy(candidate.get("journal_file_window")):
        return "journal_file_window"
    if "temporal_only_link" in flags:
        return "temporal_candidate"
    if _is_open_candidate(candidate):
        return "open_episode"
    return "work_episode"


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
                "top_files": _entry_files(item),
            })
    return commits


def _journal_file_window_candidate(
    commit: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
) -> dict[str, Any] | None:
    project = _project(commit)
    files = _entry_files(commit)
    started_at = _optional_text(commit.get("started_at"))
    ended_at = _optional_text(commit.get("ended_at"))
    if not project or not files or not started_at or not ended_at:
        return None
    if _parse_dt(started_at) is None or _parse_dt(ended_at) is None:
        return None
    if _parse_dt(ended_at) <= _parse_dt(started_at):
        return None
    entry_id = str(commit.get("entry_id") or commit.get("id") or "unknown")
    evidence_id = f"journal-file-window-{entry_id}"
    visible_episode, display_flags = _matching_visible_episode(
        {
            "project": project,
            "started_at": started_at,
            "ended_at": ended_at,
            "top_files": files,
        },
        candidates,
    )
    return {
        "id": evidence_id,
        "episode_id": (visible_episode or {}).get("episode_id") or evidence_id,
        "project": project,
        "started_at": started_at,
        "ended_at": ended_at,
        "display_started_at": (visible_episode or {}).get("started_at"),
        "display_ended_at": (visible_episode or {}).get("ended_at"),
        "top_files": files,
        "link_flags": display_flags,
        "dominant_scope": "journal_file_window",
        "probable_task": "coding",
        "ignored": False,
        "journal_file_window": True,
    }


def _matching_visible_episode(
    journal_window: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
) -> tuple[dict[str, str] | None, tuple[str, ...]]:
    matches: list[tuple[int, int, dict[str, str]]] = []
    coverage_low = False
    for candidate in candidates:
        if _truthy(candidate.get("journal_file_window")) or _is_git_only_candidate(candidate):
            continue
        if not _projects_match_explicitly(journal_window, candidate):
            continue
        file_overlap = _file_overlap_count(journal_window, candidate)
        if file_overlap <= 0:
            continue
        overlap = _overlap_min(journal_window, candidate)
        window_distance = _window_distance_min(journal_window, candidate)
        if overlap <= 0 and (window_distance is None or window_distance > _WINDOW_PROXIMITY_MIN):
            continue
        coverage = _window_coverage_ratio(journal_window, candidate)
        if coverage < _MIN_JOURNAL_WINDOW_VISIBLE_COVERAGE:
            coverage_low = True
            continue
        episode_id = _optional_text(candidate.get("episode_id"))
        if not episode_id:
            continue
        distance = window_distance if window_distance is not None else 999999
        matches.append((
            file_overlap,
            -distance,
            {
                "episode_id": episode_id,
                "started_at": _optional_text(candidate.get("started_at")) or "",
                "ended_at": _optional_text(candidate.get("ended_at")) or "",
            },
        ))
    if not matches:
        flags = ["display_uses_journal_window"]
        if coverage_low:
            flags.append("visible_episode_coverage_low")
        return None, tuple(flags)
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return matches[0][2], ()


def _window_coverage_ratio(evidence_window: Mapping[str, Any], candidate: Mapping[str, Any]) -> float:
    started = _parse_dt(evidence_window.get("started_at"))
    ended = _parse_dt(evidence_window.get("ended_at"))
    if started is None or ended is None or ended <= started:
        return 0.0
    duration_seconds = (ended - started).total_seconds()
    overlap_minutes = _overlap_min(evidence_window, candidate)
    return max(float(overlap_minutes * 60) / duration_seconds, 0.0)


def _is_delayed_file_scope_match(
    commit: Mapping[str, Any],
    candidate: Mapping[str, Any],
    delivery_delta: int | None,
    file_overlap: int,
) -> bool:
    if file_overlap <= 0:
        return False
    if not _projects_match_explicitly(commit, candidate):
        return False
    if _is_git_only_candidate(candidate):
        return False
    if _optional_text(commit.get("delivered_at")) and delivery_delta is None:
        return False
    delay_limit = (
        _JOURNAL_FILE_WINDOW_DELAY_MIN
        if _truthy(candidate.get("journal_file_window"))
        else _DELAYED_FILE_OVERLAP_MIN
    )
    if _truthy(candidate.get("journal_file_window")) and not _same_calendar_day(
        commit.get("delivered_at"),
        candidate.get("ended_at"),
    ):
        return False
    if delivery_delta is not None and delivery_delta > delay_limit:
        return False
    return True


def _same_calendar_day(left: Any, right: Any) -> bool:
    left_dt = _parse_dt(left)
    right_dt = _parse_dt(right)
    if left_dt is None or right_dt is None:
        return False
    return left_dt.date() == right_dt.date()


def _projects_match_explicitly(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_project = _project(left)
    right_project = _project(right)
    return bool(left_project and right_project and left_project == right_project)


def _is_git_only_candidate(candidate: Mapping[str, Any]) -> bool:
    scope = str(candidate.get("dominant_scope") or "").strip().lower()
    task = str(candidate.get("probable_task") or "").strip().lower()
    return scope == "git" or task in {"version_control", "terminal_execution"}


def _file_overlap_count(left: Mapping[str, Any], right: Mapping[str, Any]) -> int:
    left_files = set(_entry_files(left))
    right_files = set(_entry_files(right))
    if not left_files or not right_files:
        return 0
    return len(left_files & right_files)


def _entry_files(entry: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("top_files", "commit_scope_files", "files", "changed_files"):
        raw = entry.get(key)
        if isinstance(raw, (list, tuple)):
            values.extend(raw)
    files: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = _file_name(value)
        if not name or name in seen:
            continue
        seen.add(name)
        files.append(name)
    return files


def _file_name(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _commit_messages(entry: Mapping[str, Any]) -> list[str]:
    messages: list[str] = []
    messages.append(_optional_text(entry.get("commit_message")))
    raw_messages = entry.get("commit_messages")
    if isinstance(raw_messages, list):
        messages.extend(_optional_text(message) for message in raw_messages)

    order: list[str] = []
    by_subject: dict[str, str] = {}
    for message in (message for message in messages if message):
        subject_key = _normalized_commit_subject(message)
        if not subject_key:
            continue
        if subject_key not in by_subject:
            order.append(subject_key)
            by_subject[subject_key] = message
            continue
        if len(message) > len(by_subject[subject_key]):
            by_subject[subject_key] = message
    return [by_subject[subject_key] for subject_key in order]


def _commit_subject(message: str) -> str:
    for line in str(message).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return str(message).strip()


def _normalized_commit_subject(message: str) -> str:
    return _commit_subject(message).strip().lower()


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


def _calibrated_confidence(
    score: float,
    flags: list[str],
    score_breakdown: Mapping[str, Any] | None = None,
) -> tuple[float, list[str]]:
    caps: list[float] = []
    has_no_file_scope = "no_file_scope_match" in flags
    has_no_commit_context = "candidate_no_commit_context" in flags
    overlap_min = 0
    if score_breakdown is not None:
        try:
            overlap_min = int(score_breakdown.get("overlap_min") or 0)
        except (TypeError, ValueError):
            overlap_min = 0

    if "ambiguous_candidates" in flags:
        caps.append(0.60)
    if has_no_commit_context or has_no_file_scope:
        caps.append(0.65)
    if "commit_only_journal_entry" in flags and has_no_file_scope:
        caps.append(0.55)
    if "delivery_after_episode" in flags and has_no_file_scope:
        caps.append(0.55)
    if overlap_min == 0 and has_no_file_scope:
        caps.append(0.55)

    confidence = min([score, *caps]) if caps else score
    if confidence < score and (has_no_commit_context or has_no_file_scope):
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


def _has_stale_short_episode_candidate(
    commit: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
) -> bool:
    if not _optional_text(commit.get("delivered_at")):
        return False
    for candidate in candidates:
        if not _projects_compatible(commit, candidate):
            continue
        delivery_delta = _delivery_delta_min(commit.get("delivered_at"), candidate.get("ended_at"))
        if _delivery_score(commit.get("delivered_at"), candidate) is not None and _is_stale_short_episode_delivery(
            delivery_delta,
            _overlap_min(commit, candidate),
            candidate,
        ):
            return True
    return False


def _is_stale_short_episode_delivery(
    delivery_delta: int | None,
    overlap: int,
    candidate: Mapping[str, Any],
) -> bool:
    candidate_duration = _duration_min(candidate)
    return (
        delivery_delta is not None
        and delivery_delta > _STRONG_DELIVERY_PROXIMITY_MIN
        and overlap == 0
        and candidate_duration is not None
        and candidate_duration <= 5
    )


def _projects_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_project = _project(left)
    right_project = _project(right)
    return left_project is None or right_project is None or left_project == right_project


def _project(entry: Mapping[str, Any]) -> str | None:
    return _optional_text(entry.get("project") or entry.get("active_project"))


def _is_open_candidate(candidate: Mapping[str, Any]) -> bool:
    return (
        _parse_dt(candidate.get("started_at")) is not None
        and (
            _parse_dt(candidate.get("ended_at")) is None
            or str(candidate.get("boundary_reason") or "") == "end_of_events"
        )
    )


def _commit_time(commit: Mapping[str, Any]) -> datetime | None:
    return (
        _parse_dt(commit.get("delivered_at"))
        or _parse_dt(commit.get("ended_at"))
        or _parse_dt(commit.get("started_at"))
    )


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
