"""Builders for /state HTTP response payloads. No Flask dependency."""

from __future__ import annotations

from typing import Any, Callable

from daemon.core.current_context_adapters import current_context_to_legacy_signals_payload
from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.workspace_context import find_workspace_root
from daemon.memory.extractor import find_git_root, last_session_context


def serialize_current_context(current_context: Any) -> dict[str, Any]:
    """Serialize CurrentContext while staying compatible with legacy SessionContext."""
    signal_summary = getattr(current_context, "signal_summary", None)
    return {
        "id": getattr(current_context, "id", None),
        "session_id": getattr(current_context, "session_id", None),
        "started_at": getattr(current_context, "started_at", None),
        "ended_at": getattr(current_context, "ended_at", None),
        "boundary_reason": getattr(current_context, "boundary_reason", None),
        "duration_sec": getattr(current_context, "duration_sec", None),
        "active_project": getattr(current_context, "active_project", None),
        "active_file": getattr(current_context, "active_file", None),
        "probable_task": getattr(current_context, "probable_task", None),
        "activity_level": getattr(current_context, "activity_level", None),
        "focus_level": getattr(current_context, "focus_level", None),
        "task_confidence": getattr(current_context, "task_confidence", None),
        "user_presence_state": getattr(current_context, "user_presence_state", None),
        "user_idle_seconds": getattr(current_context, "user_idle_seconds", None),
        "user_presence_source": getattr(current_context, "user_presence_source", None),
        "terminal_action_category": getattr(current_context, "terminal_action_category", None),
        "terminal_project": getattr(current_context, "terminal_project", None),
        "terminal_cwd": getattr(current_context, "terminal_cwd", None),
        "terminal_command": getattr(current_context, "terminal_command", None),
        "terminal_success": getattr(current_context, "terminal_success", None),
        "terminal_exit_code": getattr(current_context, "terminal_exit_code", None),
        "terminal_duration_ms": getattr(current_context, "terminal_duration_ms", None),
        "terminal_summary": getattr(current_context, "terminal_summary", None),
        "active_app_duration_sec": getattr(signal_summary, "active_app_duration_sec", None),
        "active_window_title_duration_sec": getattr(signal_summary, "active_window_title_duration_sec", None),
        "app_switch_count_10m": getattr(signal_summary, "app_switch_count_10m", 0),
        "ai_app_switch_count_10m": getattr(signal_summary, "ai_app_switch_count_10m", 0),
    }


def serialize_runtime_debug(runtime_snapshot: Any) -> dict[str, Any]:
    return {
        "latest_active_app": runtime_snapshot.latest_active_app,
        "lock_marker_active": runtime_snapshot.lock_marker_active,
        "last_screen_locked_at": (
            runtime_snapshot.last_screen_locked_at.isoformat()
            if runtime_snapshot.last_screen_locked_at
            else None
        ),
        "memory_synced_at": (
            runtime_snapshot.memory_synced_at.isoformat()
            if runtime_snapshot.memory_synced_at
            else None
        ),
    }


def serialize_decision(decision: Any) -> dict[str, Any]:
    return {
        "action": decision.action,
        "level": decision.level,
        "reason": decision.reason,
        "payload": decision.payload,
    }


def serialize_session_fsm(session_fsm: Any) -> dict[str, Any]:
    return {
        "state": session_fsm.state,
        "session_started_at": session_fsm.session_started_at.isoformat() if session_fsm.session_started_at else None,
        "last_meaningful_activity_at": (
            session_fsm.last_meaningful_activity_at.isoformat()
            if session_fsm.last_meaningful_activity_at
            else None
        ),
        "last_screen_locked_at": session_fsm.last_screen_locked_at.isoformat() if session_fsm.last_screen_locked_at else None,
    }


def build_legacy_signals_payload(
    *,
    present: Any,
    active_app: str | None,
    signals: Any,
    current_context_builder: Any | None = None,
    last_session_context_fn: Callable[[str], str | None] = last_session_context,
) -> dict[str, Any]:
    builder = current_context_builder or CurrentContextBuilder()
    current_context = builder.build(
        present=present,
        active_app=active_app,
        signals=signals,
        find_git_root_fn=find_git_root,
        find_workspace_root_fn=find_workspace_root,
    )
    return current_context_to_legacy_signals_payload(
        current_context,
        signals=signals,
        last_session_line=(
            last_session_context_fn(current_context.active_project)
            if current_context.active_project
            else None
        ),
    )


def build_state_payload(
    *,
    store_state: dict[str, Any],
    runtime_snapshot: Any,
    get_session_fsm: Callable[[], Any] | None = None,
    get_current_context: Callable[[], Any] | None = None,
    get_recent_sessions: Callable[[int], Any] | None = None,
    current_context_builder: Any | None = None,
    last_session_context_fn: Callable[[str], str | None] = last_session_context,
) -> dict[str, Any]:
    present = runtime_snapshot.present
    state = {
        "active_app": runtime_snapshot.latest_active_app,
        "active_file": present.active_file,
        "active_project": present.active_project,
        "session_duration_min": present.session_duration_min,
        "last_event_type": store_state.get("last_event_type"),
        "runtime_paused": runtime_snapshot.paused,
        "present": present.to_dict(),
    }

    debug: dict[str, Any] = {
        "store": store_state,
        "runtime": serialize_runtime_debug(runtime_snapshot),
    }

    if runtime_snapshot.decision:
        decision_payload = serialize_decision(runtime_snapshot.decision)
        state["decision"] = decision_payload
        debug["decision"] = decision_payload
    if get_session_fsm is not None:
        session_fsm_payload = serialize_session_fsm(get_session_fsm())
        state["session_fsm"] = session_fsm_payload
        debug["session_fsm"] = session_fsm_payload
    if get_current_context is not None:
        current_context = get_current_context()
        if current_context is not None:
            context_payload = serialize_current_context(current_context)
            state["current_context"] = context_payload
            debug["current_context"] = context_payload
    if runtime_snapshot.signals:
        legacy_signals = build_legacy_signals_payload(
            present=present,
            active_app=state.get("active_app"),
            signals=runtime_snapshot.signals,
            current_context_builder=current_context_builder,
            last_session_context_fn=last_session_context_fn,
        )
        state["signals"] = legacy_signals
        debug["signals"] = legacy_signals
    if get_recent_sessions is not None:
        sessions = get_recent_sessions(8)
        if sessions:
            state["recent_sessions"] = sessions
            debug["recent_sessions"] = sessions
    state["debug"] = debug
    return state
