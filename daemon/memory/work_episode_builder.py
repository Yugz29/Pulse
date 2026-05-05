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
DEFAULT_SCOPE_SHIFT_GAP_MIN = 12

_FILE_EVENT_TYPES = {"file_created", "file_modified", "file_renamed", "file_deleted", "file_change"}
_APP_EVENT_TYPES = {"app_activated", "app_switch", "window_title_poll"}
_BUSINESS_SCOPES = {
    "work_episode",
    "extractor",
    "docs",
    "tests",
    "app_swift",
    "memory",
    "routes",
    "daemon_python",
}


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
    dominant_scope: str | None = None
    previous_scope: str | None = None
    next_scope: str | None = None
    strong_event_count: int = 0
    weak_event_count: int = 0
    boundary_event_type: str | None = None
    boundary_event_at: str | None = None
    debug_reason: str | None = None


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
    episode_groups = _cluster_episode_events(
        normalized_events,
        weak_bridge_min=weak_bridge_min,
        block_gap_min=block_gap_min,
        episode_gap_min=episode_gap_min,
    )
    dominant_scopes = [_dominant_scope(group["events"]) for group in episode_groups]
    return [
        _episode_from_event_group(
            group["events"],
            index,
            str(group["reason"]),
            previous_scope=dominant_scopes[index - 1] if index > 0 else None,
            next_scope=dominant_scopes[index + 1] if index + 1 < len(dominant_scopes) else None,
            boundary_event=group.get("boundary_event"),
        )
        for index, group in enumerate(episode_groups)
    ]


def _cluster_episode_events(
    events: list[dict[str, Any]],
    *,
    weak_bridge_min: int,
    block_gap_min: int,
    episode_gap_min: int,
) -> list[dict[str, Any]]:
    max_block_gap = timedelta(minutes=block_gap_min)
    max_episode_gap = timedelta(minutes=episode_gap_min)
    max_weak_bridge = timedelta(minutes=weak_bridge_min)
    max_scope_shift_gap = timedelta(minutes=DEFAULT_SCOPE_SHIFT_GAP_MIN)
    groups: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    last_strong_at: datetime | None = None
    last_strong_scope: str | None = None

    for event in events:
        heartbeat = classify_work_heartbeat(event)
        observed_at = event["timestamp"]

        boundary = _boundary_reason(event)
        if current and boundary is not None:
            groups.append({"events": current, "reason": boundary, "boundary_event": event})
            current = []
            last_strong_at = None
            last_strong_scope = None
            continue

        if heartbeat.strength == "none":
            continue

        if current and observed_at - current[-1]["timestamp"] > max_block_gap:
            groups.append({"events": current, "reason": "long_gap", "boundary_event": event})
            current = []
            last_strong_at = None
            last_strong_scope = None

        if heartbeat.strength == "strong":
            event_scope = _scope_from_event(event)
            if (
                current
                and last_strong_at is not None
                and observed_at - last_strong_at > max_scope_shift_gap
                and not _scopes_compatible(last_strong_scope, event_scope)
            ):
                groups.append({"events": current, "reason": "scope_change", "boundary_event": event})
                current = []

            if current and last_strong_at is not None and observed_at - last_strong_at > max_episode_gap:
                groups.append({"events": current, "reason": "long_gap", "boundary_event": event})
                current = []

            current.append(event)
            last_strong_at = observed_at
            last_strong_scope = event_scope
            continue

        if heartbeat.strength == "weak":
            if current and last_strong_at is not None and observed_at - last_strong_at <= max_weak_bridge:
                current.append(event)
            continue

    if current:
        groups.append({"events": current, "reason": "end_of_events", "boundary_event": None})
    return groups


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


def _episode_from_event_group(
    events: list[dict[str, Any]],
    index: int,
    boundary_reason: str,
    *,
    previous_scope: str | None,
    next_scope: str | None,
    boundary_event: Mapping[str, Any] | None,
) -> WorkEpisode:
    block = _block_from_cluster(events, index)
    evidence_count = len(events)
    project = block.project
    flags = _uncertainty_flags([block], project, evidence_count)
    dominant_scope = _dominant_scope(events)
    strong_count = _heartbeat_count(events, "strong")
    weak_count = _heartbeat_count(events, "weak")
    boundary_event_type = str(boundary_event.get("type")) if boundary_event else None
    boundary_event_at = boundary_event.get("timestamp").isoformat() if boundary_event and boundary_event.get("timestamp") else None
    return WorkEpisode(
        id=f"work-episode-{block.started_at}",
        project=project,
        probable_task=block.probable_task,
        activity_level=block.activity_level,
        started_at=block.started_at,
        ended_at=block.ended_at,
        duration_min=block.duration_min,
        work_block_ids=(block.id,),
        evidence_count=evidence_count,
        confidence=_confidence(evidence_count, project, flags),
        boundary_reason=boundary_reason,
        uncertainty_flags=flags,
        dominant_scope=dominant_scope,
        previous_scope=previous_scope,
        next_scope=next_scope,
        strong_event_count=strong_count,
        weak_event_count=weak_count,
        boundary_event_type=boundary_event_type,
        boundary_event_at=boundary_event_at,
        debug_reason=_debug_reason(
            boundary_reason=boundary_reason,
            dominant_scope=dominant_scope,
            previous_scope=previous_scope,
            next_scope=next_scope,
            boundary_event=boundary_event,
            events=events,
        ),
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


def _dominant_scope(events: list[dict[str, Any]]) -> str | None:
    scopes = [
        _scope_from_event(event)
        for event in events
        if classify_work_heartbeat(event).strength == "strong"
    ]
    business_scope = _dominant_value(scope for scope in scopes if scope in _BUSINESS_SCOPES)
    if business_scope:
        return business_scope
    return _dominant_value(scope for scope in scopes if scope != "unknown") or (scopes[-1] if scopes else None)


def _heartbeat_count(events: list[dict[str, Any]], strength: str) -> int:
    return sum(1 for event in events if classify_work_heartbeat(event).strength == strength)


def _debug_reason(
    *,
    boundary_reason: str,
    dominant_scope: str | None,
    previous_scope: str | None,
    next_scope: str | None,
    boundary_event: Mapping[str, Any] | None,
    events: list[dict[str, Any]],
) -> str | None:
    if boundary_reason == "scope_change":
        gap_min = _gap_from_last_strong_to_boundary(events, boundary_event)
        source = dominant_scope or "unknown"
        target = next_scope or _scope_from_event(boundary_event) if boundary_event else "unknown"
        gap_label = f"{gap_min} min" if gap_min is not None else "unknown"
        return f"split after {gap_label} gap and scope change {source} -> {target}"
    if boundary_reason in {"screen_locked", "non_work_title"}:
        event_type = str(boundary_event.get("type") or boundary_reason) if boundary_event else boundary_reason
        return f"split on boundary event {event_type}"
    if boundary_reason == "long_gap":
        gap_min = _gap_from_last_event_to_boundary(events, boundary_event)
        gap_label = f"{gap_min} min" if gap_min is not None else "unknown"
        return f"split after {gap_label} long gap"
    if boundary_reason == "end_of_events":
        return "episode open until end of observed events"
    if previous_scope and dominant_scope and previous_scope != dominant_scope:
        return f"episode starts after scope change {previous_scope} -> {dominant_scope}"
    return None


def _gap_from_last_strong_to_boundary(
    events: list[dict[str, Any]],
    boundary_event: Mapping[str, Any] | None,
) -> int | None:
    if not boundary_event:
        return None
    boundary_at = boundary_event.get("timestamp")
    strong_events = [event for event in events if classify_work_heartbeat(event).strength == "strong"]
    if not strong_events or not isinstance(boundary_at, datetime):
        return None
    return max(int((boundary_at - strong_events[-1]["timestamp"]).total_seconds() / 60), 0)


def _gap_from_last_event_to_boundary(
    events: list[dict[str, Any]],
    boundary_event: Mapping[str, Any] | None,
) -> int | None:
    if not events or not boundary_event:
        return None
    boundary_at = boundary_event.get("timestamp")
    if not isinstance(boundary_at, datetime):
        return None
    return max(int((boundary_at - events[-1]["timestamp"]).total_seconds() / 60), 0)


def _scope_from_event(event: Mapping[str, Any]) -> str:
    payload = event.get("payload") or {}
    path = payload.get("path") or payload.get("file_path")
    if path:
        return _scope_from_path(str(path))
    event_type = str(event.get("type") or "")
    if event_type == "terminal_command_finished":
        command = str(payload.get("terminal_command") or "").strip()
        base = str(payload.get("terminal_command_base") or "").strip().lower()
        if base == "git" or command.startswith("git "):
            return "git"
    return "unknown"


def _scope_from_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name
    if "/docs/" in normalized:
        return "docs"
    if name in {"work_episode_builder.py", "test_work_episode_builder.py"}:
        return "work_episode"
    if name in {"extractor.py", "test_extractor.py"}:
        return "extractor"
    if "/daemon/routes/" in normalized:
        return "routes"
    if "/daemon/memory/" in normalized:
        return "memory"
    if "/daemon/" in normalized and name.endswith(".py"):
        return "daemon_python"
    if "/App/App/" in normalized and name.endswith(".swift"):
        return "app_swift"
    if "/AppTests/" in normalized and name.endswith(".swift"):
        return "app_swift"
    if "/tests/" in normalized:
        return "tests"
    return "unknown"


def _scopes_compatible(left: str | None, right: str | None) -> bool:
    left_scope = left or "unknown"
    right_scope = right or "unknown"
    if left_scope == "unknown" or right_scope == "unknown":
        return True
    if left_scope == right_scope:
        return True
    compatible_pairs = {
        frozenset({"work_episode", "tests"}),
        frozenset({"extractor", "tests"}),
        frozenset({"app_swift", "tests"}),
    }
    return frozenset({left_scope, right_scope}) in compatible_pairs


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
        scope = _scope_from_event(event)
        if event_type in _FILE_EVENT_TYPES:
            file_event_count += 1
            if scope == "docs":
                terminal_categories.append("writing")
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
    if any(category == "writing" for category in terminal_categories):
        return "writing"
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
