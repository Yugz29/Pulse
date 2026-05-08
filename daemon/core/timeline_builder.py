"""Passive helpers to build timeline spans from existing context objects.

This module does not read EventBus, persist spans, score activity, or change the
runtime. It only converts already-computed context into the passive TimelineSpan
contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from daemon.core.event_envelope import PulseEventBucket, PulsePrivacyClass, PulseRetention
from daemon.core.timeline_span import TimelineSpan, TimelineSpanKind
from daemon.core.uid import new_uid


_CONTEXT_FILE_BUCKETS = (PulseEventBucket.FILESYSTEM,)
_CONTEXT_EXECUTION_BUCKETS = (PulseEventBucket.TERMINAL_ACTIVITY,)


def span_from_current_context(
    context: Any,
    *,
    started_at: datetime,
    ended_at: datetime,
    span_id: Optional[str] = None,
    title: Optional[str] = None,
) -> TimelineSpan:
    """Build a passive TimelineSpan from an already computed CurrentContext.

    The function is intentionally conservative and duck-typed: CurrentContext is
    the intended input, but tests/tools can pass compatible objects while the
    timeline model is still being introduced.
    """
    activity_level = _str_or_none(getattr(context, "activity_level", None))
    probable_task = _str_or_none(getattr(context, "probable_task", None))
    active_project = _str_or_none(getattr(context, "active_project", None))
    active_file = _str_or_none(getattr(context, "active_file", None))
    terminal_action_category = _str_or_none(getattr(context, "terminal_action_category", None))
    effective_task = _effective_task_from_context(
        probable_task=probable_task,
        terminal_action_category=terminal_action_category,
    )
    confidence = _confidence_from_context(context)
    kind = _kind_from_context(
        activity_level=activity_level,
        probable_task=effective_task,
        terminal_action_category=terminal_action_category,
    )
    buckets = _buckets_from_context(active_file=active_file, activity_level=activity_level)
    privacy = _privacy_from_context(active_file=active_file, activity_level=activity_level)

    return TimelineSpan(
        span_id=span_id or new_uid(),
        started_at=started_at,
        ended_at=ended_at,
        kind=kind,
        title=title or _title_from_context(
            kind=kind,
            project=active_project,
            task=effective_task,
            terminal_action_category=terminal_action_category,
        ),
        project=active_project,
        activity_level=activity_level,
        probable_task=effective_task,
        confidence=confidence,
        buckets=buckets,
        privacy=privacy,
        retention=PulseRetention.SESSION,
        evidence_event_count=0,
        metadata=_metadata_from_context(terminal_action_category=terminal_action_category),
    )


def _kind_from_context(
    *,
    activity_level: Optional[str],
    probable_task: Optional[str],
    terminal_action_category: Optional[str] = None,
) -> TimelineSpanKind:
    task = (probable_task or "").lower()
    activity = (activity_level or "").lower()
    terminal_action = (terminal_action_category or "").lower()

    if task in {"debug", "debugging"} or terminal_action in {"debug", "debugging"}:
        return TimelineSpanKind.DEBUG
    if activity in {"executing", "execution"}:
        return TimelineSpanKind.EXECUTION
    if activity in {"reading", "navigating"}:
        return TimelineSpanKind.READING
    if activity in {"editing", "coding"} or task in {"coding", "development", "feature"}:
        return TimelineSpanKind.WORK
    if activity in {"idle", "locked"}:
        return TimelineSpanKind.BREAK
    return TimelineSpanKind.UNKNOWN


def _buckets_from_context(*, active_file: Optional[str], activity_level: Optional[str]) -> tuple[PulseEventBucket, ...]:
    buckets: list[PulseEventBucket] = []
    if active_file:
        buckets.extend(_CONTEXT_FILE_BUCKETS)
    if (activity_level or "").lower() in {"executing", "execution"}:
        buckets.extend(_CONTEXT_EXECUTION_BUCKETS)
    return tuple(dict.fromkeys(buckets))


def _privacy_from_context(*, active_file: Optional[str], activity_level: Optional[str]) -> PulsePrivacyClass:
    if (activity_level or "").lower() in {"executing", "execution"}:
        return PulsePrivacyClass.CONTENT_SENSITIVE
    if active_file:
        return PulsePrivacyClass.PATH_SENSITIVE
    return PulsePrivacyClass.UNKNOWN


def _effective_task_from_context(
    *,
    probable_task: Optional[str],
    terminal_action_category: Optional[str],
) -> Optional[str]:
    task = (probable_task or "").strip()
    if task and task.lower() != "general":
        return task
    return _terminal_task_label(terminal_action_category) or task or None


def _terminal_task_label(terminal_action_category: Optional[str]) -> Optional[str]:
    category = (terminal_action_category or "").strip().lower()
    if not category:
        return None
    labels = {
        "testing": "tests",
        "test": "tests",
        "inspection": "inspection",
        "vcs": "version control",
        "git": "version control",
        "debug": "debug",
        "debugging": "debug",
        "build": "build",
        "execution": "terminal execution",
        "command": "terminal execution",
    }
    return labels.get(category, category.replace("_", " "))


def _title_from_context(
    *,
    kind: TimelineSpanKind,
    project: Optional[str],
    task: Optional[str],
    terminal_action_category: Optional[str] = None,
) -> str:
    project_label = project or "Projet inconnu"
    terminal_label = _terminal_task_label(terminal_action_category)
    task_label = terminal_label or task
    if kind is TimelineSpanKind.UNKNOWN and not task_label:
        return project_label
    task_label = task_label or kind.value
    return f"{project_label} — {task_label}"


def _confidence_from_context(context: Any) -> float:
    raw = getattr(context, "task_confidence", None)
    if raw is None:
        signal_summary = getattr(context, "signal_summary", None)
        raw = getattr(signal_summary, "task_confidence", None) if signal_summary is not None else None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return min(max(value, 0.0), 1.0)


def _metadata_from_context(*, terminal_action_category: Optional[str]) -> dict[str, str]:
    metadata = {"source": "current_context"}
    if terminal_action_category:
        metadata["terminal_action_category"] = terminal_action_category
    return metadata


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
