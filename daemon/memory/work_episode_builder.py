"""Pure work block and work episode builders.

This module is intentionally not wired into runtime, journal, or dashboard code
yet. It mirrors part of ``SessionMemory._cluster_work_events`` for Phase 2a
tranche 1; convergence with the existing session clustering should happen in a
later tranche once the episode model is proven by tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from daemon.memory.work_heartbeat import NON_WORK_TITLE_HINTS, classify_work_heartbeat


DEFAULT_WEAK_BRIDGE_MIN = 10
DEFAULT_BLOCK_GAP_MIN = 30
DEFAULT_EPISODE_GAP_MIN = 45

_FILE_EVENT_TYPES = {"file_created", "file_modified", "file_renamed", "file_deleted", "file_change"}
_APP_EVENT_TYPES = {"app_activated", "app_switch", "window_title_poll"}


@dataclass(frozen=True)
class WorkBlock:
    id: str
    started_at: str
    ended_at: str
    duration_min: int
    event_count: int
    project: str | None
    probable_task: str
    activity_level: str


@dataclass(frozen=True)
class WorkEpisode:
    id: str
    project: str | None
    probable_task: str
    activity_level: str
    started_at: str
    ended_at: str
    duration_min: int
    work_block_ids: tuple[str, ...]
    evidence_count: int
    confidence: float
    boundary_reason: str
    uncertainty_flags: tuple[str, ...]


def build_work_blocks(
    events: list[Mapping[str, Any]],
    *,
    weak_bridge_min: int = DEFAULT_WEAK_BRIDGE_MIN,
    block_gap_min: int = DEFAULT_BLOCK_GAP_MIN,
) -> list[WorkBlock]:
    """Build short work blocks from qualified heartbeats."""
    max_gap = timedelta(minutes=block_gap_min)
    max_weak_bridge = timedelta(minutes=weak_bridge_min)
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    last_strong_at: datetime | None = None

    for event in _normalize_events(events):
        heartbeat = classify_work_heartbeat(event)
        observed_at = event["timestamp"]

        if current and _boundary_reason(event) is not None:
            clusters.append(current)
            current = []
            last_strong_at = None
            continue

        if heartbeat.strength == "none":
            continue

        if current and observed_at - current[-1]["timestamp"] > max_gap:
            clusters.append(current)
            current = []
            last_strong_at = None

        if heartbeat.strength == "strong":
            current.append(event)
            last_strong_at = observed_at
            continue

        if heartbeat.strength == "weak":
            if current and last_strong_at is not None and observed_at - last_strong_at <= max_weak_bridge:
                current.append(event)
            continue

    if current:
        clusters.append(current)

    return [_block_from_cluster(cluster, index) for index, cluster in enumerate(clusters)]


def build_work_episodes(
    events: list[Mapping[str, Any]],
    *,
    weak_bridge_min: int = DEFAULT_WEAK_BRIDGE_MIN,
    block_gap_min: int = DEFAULT_BLOCK_GAP_MIN,
    episode_gap_min: int = DEFAULT_EPISODE_GAP_MIN,
) -> list[WorkEpisode]:
    """Build work episodes from all events so non-work boundaries are visible."""
    normalized_events = _normalize_events(events)
    blocks = build_work_blocks(
        normalized_events,
        weak_bridge_min=weak_bridge_min,
        block_gap_min=block_gap_min,
    )
    if not blocks:
        return []

    max_episode_gap = timedelta(minutes=episode_gap_min)
    episodes: list[WorkEpisode] = []
    current: list[WorkBlock] = [blocks[0]]

    for block in blocks[1:]:
        previous = current[-1]
        gap = _parse_datetime(block.started_at) - _parse_datetime(previous.ended_at)
        boundary = _boundary_between(normalized_events, previous.ended_at, block.started_at)
        if gap <= max_episode_gap and boundary is None and _compatible_blocks(previous, block):
            current.append(block)
            continue

        reason = boundary or ("long_gap" if gap > max_episode_gap else "scope_change")
        episodes.append(_episode_from_blocks(current, reason))
        current = [block]

    episodes.append(_episode_from_blocks(current, "end_of_events"))
    return episodes


def _normalize_events(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for event in events:
        timestamp = _coerce_datetime(event.get("timestamp"))
        if timestamp is None:
            continue
        normalized.append(
            {
                "type": str(event.get("type") or ""),
                "payload": dict(event.get("payload") or {}),
                "timestamp": timestamp,
            }
        )
    return sorted(normalized, key=lambda item: item["timestamp"])


def _block_from_cluster(cluster: list[dict[str, Any]], index: int) -> WorkBlock:
    started_at = cluster[0]["timestamp"]
    ended_at = cluster[-1]["timestamp"]
    duration_min = max(int((ended_at - started_at).total_seconds() / 60), 1)
    started_iso = started_at.isoformat()
    return WorkBlock(
        id=f"work-block-{started_iso}-{index}",
        started_at=started_iso,
        ended_at=ended_at.isoformat(),
        duration_min=duration_min,
        event_count=len(cluster),
        project=_project_from_events(cluster),
        probable_task=_probable_task_from_events(cluster),
        activity_level=_activity_level_from_events(cluster),
    )


def _episode_from_blocks(blocks: list[WorkBlock], boundary_reason: str) -> WorkEpisode:
    started_at = blocks[0].started_at
    ended_at = blocks[-1].ended_at
    evidence_count = sum(block.event_count for block in blocks)
    project = _first_known(block.project for block in reversed(blocks))
    duration_min = sum(block.duration_min for block in blocks)
    flags = _uncertainty_flags(blocks, project, evidence_count)
    return WorkEpisode(
        id=f"work-episode-{started_at}",
        project=project,
        probable_task=_dominant_value(block.probable_task for block in blocks) or "general",
        activity_level=_dominant_value(block.activity_level for block in blocks) or "unknown",
        started_at=started_at,
        ended_at=ended_at,
        duration_min=duration_min,
        work_block_ids=tuple(block.id for block in blocks),
        evidence_count=evidence_count,
        confidence=_confidence(evidence_count, project, flags),
        boundary_reason=boundary_reason,
        uncertainty_flags=flags,
    )


def _boundary_between(events: list[dict[str, Any]], after_iso: str, before_iso: str) -> str | None:
    after = _parse_datetime(after_iso)
    before = _parse_datetime(before_iso)
    for event in events:
        timestamp = event["timestamp"]
        if after < timestamp < before:
            reason = _boundary_reason(event)
            if reason is not None:
                return reason
    return None


def _boundary_reason(event: Mapping[str, Any]) -> str | None:
    event_type = str(event.get("type") or "")
    if event_type == "screen_locked":
        return "screen_locked"
    if event_type in {"app_activated", "window_title_poll"} and _has_non_work_title(event):
        return "non_work_title"
    return None


def _has_non_work_title(event: Mapping[str, Any]) -> bool:
    payload = event.get("payload") or {}
    title = str(payload.get("window_title") or payload.get("title") or "").lower()
    return bool(title and any(hint in title for hint in NON_WORK_TITLE_HINTS))


def _compatible_blocks(left: WorkBlock, right: WorkBlock) -> bool:
    if left.project and right.project and left.project != right.project:
        return False
    return True


def _probable_task_from_events(events: list[dict[str, Any]]) -> str:
    terminal_categories: list[str] = []
    git_event_count = 0
    terminal_event_count = 0
    file_event_count = 0
    assisted_event_count = 0

    for event in events:
        event_type = event.get("type")
        payload = event.get("payload") or {}
        if event_type in _FILE_EVENT_TYPES:
            file_event_count += 1
        if event_type in {"mcp_command_received", "mcp_decision", "claude_desktop_session"}:
            assisted_event_count += 1
        if event_type == "terminal_command_finished":
            terminal_event_count += 1
            category = str(payload.get("terminal_action_category") or "").strip().lower()
            if category:
                terminal_categories.append(category)
            command = str(payload.get("terminal_command") or "").strip()
            base = str(payload.get("terminal_command_base") or "").strip().lower()
            if category in {"vcs", "git"} or base == "git" or command.startswith("git "):
                git_event_count += 1

    if any(category in {"testing", "test"} for category in terminal_categories):
        return "tests"
    if any(category in {"debug", "debugging"} for category in terminal_categories):
        return "debug"
    if any(category == "build" for category in terminal_categories):
        return "build"
    if file_event_count:
        return "coding"
    if git_event_count >= 2:
        return "version_control"
    if assisted_event_count:
        return "assisted_workflow"
    if terminal_event_count:
        return "terminal_execution"
    return "general"


def _activity_level_from_events(events: list[dict[str, Any]]) -> str:
    if any(event.get("type") == "terminal_command_finished" for event in events):
        return "executing"
    if any(event.get("type") in _FILE_EVENT_TYPES for event in events):
        return "editing"
    if any(event.get("type") in _APP_EVENT_TYPES for event in events):
        return "navigating"
    return "unknown"


def _project_from_events(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        payload = event.get("payload") or {}
        for key in ("project", "active_project", "terminal_project"):
            value = payload.get(key)
            if value:
                return str(value)
        path = payload.get("path") or payload.get("file_path")
        if path:
            parts = Path(str(path)).parts
            for marker in ("Projets", "Projects"):
                if marker in parts:
                    idx = parts.index(marker)
                    if idx + 1 < len(parts):
                        return parts[idx + 1]
    return None


def _uncertainty_flags(blocks: list[WorkBlock], project: str | None, evidence_count: int) -> tuple[str, ...]:
    flags: list[str] = []
    if len(blocks) == 1:
        flags.append("single_block")
    if evidence_count <= 1:
        flags.append("low_evidence")
    if project is None:
        flags.append("unknown_project")
    if sum(block.duration_min for block in blocks) <= 1:
        flags.append("short_episode")
    return tuple(flags)


def _confidence(evidence_count: int, project: str | None, flags: tuple[str, ...]) -> float:
    confidence = 0.65
    if evidence_count >= 3:
        confidence += 0.15
    if project:
        confidence += 0.1
    if "low_evidence" in flags:
        confidence -= 0.1
    if "unknown_project" in flags:
        confidence -= 0.1
    return max(0.0, min(confidence, 0.95))


def _dominant_value(values: Any) -> str | None:
    counts: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _first_known(values: Any) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)
