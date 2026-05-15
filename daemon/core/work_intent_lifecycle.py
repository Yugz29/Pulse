from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


WorkIntentLifecycleAction = Literal["keep", "clear"]

IDLE_TIMEOUT_SECONDS = 30 * 60
_STRONG_BOUNDARY_REASONS = {"idle", "screen_lock"}


@dataclass(frozen=True)
class WorkIntentLifecycleDecision:
    action: WorkIntentLifecycleAction
    reason: str = "noop"


def evaluate_work_intent_lifecycle(
    *,
    present: Any,
    signals: Any | None = None,
    session_state: Any | None = None,
    now: datetime | None = None,
) -> WorkIntentLifecycleDecision:
    """Return the conservative lifecycle action for the active work intent.

    This helper is intentionally pure: it observes the current runtime projection
    and session transition, then returns a decision without mutating state.
    """
    intent = getattr(present, "work_intent", None)
    if intent is None:
        return WorkIntentLifecycleDecision("keep", "noop")
    if hasattr(intent, "is_expired") and intent.is_expired(now=now):
        return WorkIntentLifecycleDecision("clear", "expired")

    boundary_reason = str(getattr(session_state, "boundary_reason", "") or "")
    if (
        bool(getattr(session_state, "should_start_new_session", False))
        and boundary_reason in _STRONG_BOUNDARY_REASONS
    ):
        return WorkIntentLifecycleDecision("clear", "session_boundary")

    intent_project = _clean_text(getattr(intent, "project", None))
    active_project = _clean_text(
        getattr(present, "active_project", None)
        or getattr(signals, "active_project", None)
    )
    if intent_project and active_project and intent_project != active_project:
        return WorkIntentLifecycleDecision("clear", "project_changed")

    activity_level = _clean_text(
        getattr(present, "activity_level", None)
        or getattr(signals, "activity_level", None)
    )
    idle_seconds = _coerce_int(
        getattr(present, "user_idle_seconds", None)
        if getattr(present, "user_idle_seconds", None) is not None
        else getattr(signals, "user_idle_seconds", None)
    )
    if activity_level == "idle" and idle_seconds is not None and idle_seconds >= IDLE_TIMEOUT_SECONDS:
        return WorkIntentLifecycleDecision("clear", "idle_timeout")

    return WorkIntentLifecycleDecision("keep", "active")


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
