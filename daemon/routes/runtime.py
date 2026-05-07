from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.context_probe_store import ContextProbeRequestStore
from daemon.core.event_actor import EventActorClassifier
from daemon.core.file_event_coalescer import FileEventCoalescer
from daemon.core.workspace_context import extract_project_name, find_workspace_root
from daemon.interpreter.command_interpreter import CommandInterpreter
from daemon.memory.extractor import last_session_context
from daemon.routes.debug_memory import register_debug_memory_routes
from daemon.routes.runtime_debug_routes import register_debug_routes
from daemon.routes.runtime_feed_routes import register_feed_routes
from daemon.routes.runtime_probe_routes import register_probe_routes
from daemon.routes.runtime_daemon_routes import register_daemon_routes
from daemon.routes.runtime_resume_card_routes import register_resume_card_routes

_actor_classifier = EventActorClassifier()
_current_context_builder = CurrentContextBuilder()
_terminal_interpreter = CommandInterpreter()

_TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({
    "terminal_command_started",
    "terminal_command_finished",
})
_TERMINAL_TEST_COMMANDS: frozenset[str] = frozenset({
    "pytest", "tox", "nosetests", "nose2", "unittest",
})
_TERMINAL_BUILD_COMMANDS: frozenset[str] = frozenset({
    "xcodebuild", "make", "cmake", "ninja",
})
_TERMINAL_SETUP_COMMANDS: frozenset[str] = frozenset({
    "brew", "pip", "pip3", "npm", "pnpm", "yarn", "uv", "poetry", "cargo",
})


# Helper to serialize current_context for /state route
def _serialize_current_context(current_context: Any) -> dict[str, Any]:
    from daemon.routes.runtime_state_payloads import serialize_current_context
    return serialize_current_context(current_context)


def _build_state_payload(
    *,
    store_state: dict[str, Any],
    runtime_snapshot: Any,
    get_session_fsm: Callable[[], Any] | None = None,
    get_current_context: Callable[[], Any] | None = None,
    get_recent_sessions: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    from daemon.routes.runtime_state_payloads import build_state_payload
    return build_state_payload(
        store_state=store_state,
        runtime_snapshot=runtime_snapshot,
        get_session_fsm=get_session_fsm,
        get_current_context=get_current_context,
        get_recent_sessions=get_recent_sessions,
        current_context_builder=_current_context_builder,
        last_session_context_fn=last_session_context,
    )


def register_runtime_routes(
    app: Flask,
    *,
    bus: Any,
    store: Any,
    runtime_state: Any,
    get_session_fsm: Callable[[], Any] | None = None,
    get_current_context: Callable[[], Any] | None = None,
    get_recent_sessions: Callable[[int], Any] | None = None,
    get_today_summary: Callable[[], dict[str, Any]] | None = None,
    get_today_work_episodes: Callable[[], dict[str, Any]] | None = None,
    get_today_journal_candidates: Callable[[], dict[str, Any]] | None = None,
    get_today_journal_comparison: Callable[[], dict[str, Any]] | None = None,
    get_today_commit_episode_links: Callable[[], dict[str, Any]] | None = None,
    context_probe_store: ContextProbeRequestStore | None = None,
    llm_unload_background: Callable[[], None],
    llm_warmup_background: Callable[[], None],
    shutdown_runtime: Callable[[], None],
    log: Any,
    resume_card_llm: Any = None,
) -> None:
    probe_store = context_probe_store or ContextProbeRequestStore()

    def _publish_to_bus(
        event_type: str,
        payload: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> None:
        if timestamp is None:
            bus.publish(event_type, payload)
        else:
            bus.publish(event_type, payload, timestamp)

    file_event_coalescer = FileEventCoalescer(
        publisher=_publish_to_bus,
    )

    register_debug_memory_routes(
        app,
        get_work_episodes=get_today_work_episodes,
        get_journal_candidates=get_today_journal_candidates,
        get_journal_comparison=get_today_journal_comparison,
        get_commit_episode_links=get_today_commit_episode_links,
    )

    register_debug_routes(
        app,
        bus=bus,
        runtime_state=runtime_state,
        current_context_builder=_current_context_builder,
        parse_timestamp_fn=_parse_event_timestamp,
    )

    register_feed_routes(
        app,
        bus=bus,
        parse_timestamp_fn=_parse_event_timestamp,
        get_today_summary=get_today_summary,
    )

    register_probe_routes(
        app,
        bus=bus,
        runtime_state=runtime_state,
        probe_store=probe_store,
        current_context_builder=_current_context_builder,
    )

    register_daemon_routes(
        app,
        bus=bus,
        runtime_state=runtime_state,
        shutdown_runtime=shutdown_runtime,
        llm_unload_background=llm_unload_background,
        llm_warmup_background=llm_warmup_background,
        log=log,
    )

    register_resume_card_routes(
        app,
        bus=bus,
        runtime_state=runtime_state,
        get_recent_sessions=get_recent_sessions,
        get_today_summary=get_today_summary,
        resume_card_llm=resume_card_llm,
    )

    @app.route("/ping")
    def ping():
        paused = runtime_state.touch_ping()
        return jsonify({"status": "ok", "version": "0.1.0", "paused": paused})

    @app.route("/event", methods=["POST"])
    def receive_event():
        data = request.get_json() or {}
        event_type = data.get("type", "unknown")
        observed_at = _parse_event_timestamp(data.get("timestamp"))
        payload = {
            key: value
            for key, value in data.items()
            if key not in {"type", "timestamp"}
        }
        if runtime_state.is_paused():
            return jsonify({"ok": True, "paused": True, "ignored": True})

        if event_type in {"app_activated", "app_switch"}:
            app_name = payload.get("app_name")
            if app_name:
                runtime_state.set_latest_active_app(app_name)

        if event_type in _TERMINAL_EVENT_TYPES:
            payload = _normalize_terminal_event_payload(event_type, payload)

        if not _should_publish_to_bus(event_type, payload, runtime_state):
            return jsonify({"ok": True, "filtered": True})

        if event_type in {"file_modified", "file_created", "file_renamed", "file_deleted"}:
            recent = bus.recent(60)
            attribution = _actor_classifier.classify(
                event_type,
                payload,
                latest_app=runtime_state.get_latest_active_app(),
                recent_events=recent,
            )
            payload["_actor"]            = attribution.actor
            payload["_actor_confidence"] = attribution.confidence
            payload["_automation_score"] = attribution.automation_score
            payload["_noise_policy"]     = attribution.noise_policy

        file_event_coalescer.publish(event_type, payload, observed_at)
        return jsonify({"ok": True})

    @app.route("/state")
    def get_state():
        state = _build_state_payload(
            store_state=store.to_dict(),
            runtime_snapshot=runtime_state.get_runtime_snapshot(),
            get_session_fsm=get_session_fsm,
            get_current_context=get_current_context,
            get_recent_sessions=get_recent_sessions,
        )
        return jsonify(state)

    @app.route("/insights")
    def get_insights():
        try:
            limit = int(request.args.get("limit", 25))
        except (TypeError, ValueError):
            limit = 25
        limit = min(max(limit, 1), 100)

        since_raw = request.args.get("since")
        since_dt = _parse_event_timestamp(since_raw) if since_raw else None

        recent = bus.recent(limit)

        events = [
            {
                "type": event.type,
                "payload": event.payload,
                "timestamp": event.timestamp.isoformat()
            }
            for event in recent
            if (since_dt is None or event.timestamp > since_dt)
        ]
        return jsonify(events)


# ── Bus entry filter ──────────────────────────────────────────────────────────

_BUS_FILE_EVENT_TYPES: frozenset[str] = frozenset({
    "file_created", "file_modified", "file_renamed",
    "file_deleted", "file_change",
})


def _should_publish_to_bus(event_type: str, payload: dict, runtime_state: Any = None) -> bool:
    """
    Décide si un event doit entrer dans l'EventBus.

    Délègue à EventMeaningPolicy. Les décisions de filtrage écran verrouillé
    sont appliquées ici avant la politique, car elles dépendent du runtime_state.
    """
    from daemon.core.event_meaning import _default_policy

    if runtime_state is not None and runtime_state.is_screen_locked():
        if event_type not in {"screen_locked", "screen_unlocked"}:
            return False

    decision = _default_policy.classify(event_type, payload)
    if decision.sanitized_payload is not None:
        payload.clear()
        payload.update(decision.sanitized_payload)
    return decision.publish_to_bus


def _normalize_terminal_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    command = str(payload.pop("command", "") or payload.pop("raw", "")).strip()
    cwd = str(payload.get("cwd", "")).strip() or None
    shell = str(payload.get("shell", "")).strip() or None
    terminal_program = str(payload.get("terminal_program", "")).strip() or None
    exit_code = _coerce_int(payload.get("exit_code"))
    duration_ms = _coerce_int(payload.get("duration_ms"))

    normalized: dict[str, Any] = {
        "source": "terminal",
        "kind": "finished" if event_type == "terminal_command_finished" else "started",
    }

    if shell:
        normalized["terminal_shell"] = shell
    if terminal_program:
        normalized["terminal_program"] = terminal_program
    if cwd:
        normalized["terminal_cwd"] = cwd
        normalized["terminal_project"] = extract_project_name(cwd)
        workspace_root = find_workspace_root(cwd)
        if workspace_root:
            normalized["terminal_workspace_root"] = str(workspace_root)

    if exit_code is not None:
        normalized["terminal_exit_code"] = exit_code
    if duration_ms is not None:
        normalized["terminal_duration_ms"] = duration_ms

    if not command:
        return normalized

    interpretation = _terminal_interpreter.interpret(command)
    action_category = _terminal_action_category(command, interpretation)
    base_cmd = _split_command(command)[0]

    if interpretation.needs_llm:
        raw_summary = _terminal_category_summary(action_category)
    else:
        raw_summary = interpretation.translated

    if exit_code is not None:
        status_prefix = "\u2713" if exit_code == 0 else "\u2717"
        summary = f"{status_prefix} {raw_summary}"
    else:
        summary = raw_summary

    normalized.update(
        {
            "terminal_command": command,
            "terminal_command_base": base_cmd,
            "terminal_action_category": action_category,
            "terminal_is_read_only": interpretation.is_read_only,
            "terminal_affects": list(interpretation.affects),
            "terminal_success": (exit_code == 0) if exit_code is not None else None,
            "terminal_summary": summary,
        }
    )
    return normalized


def _parse_event_timestamp(raw: Any) -> datetime | None:
    from daemon.core.terminal_event_normalizer import parse_event_timestamp
    return parse_event_timestamp(raw)


def _terminal_action_category(command: str, interpretation) -> str:
    from daemon.core.terminal_event_normalizer import terminal_action_category
    return terminal_action_category(command, interpretation)


def _terminal_category_summary(category: str) -> str:
    from daemon.core.terminal_event_normalizer import terminal_category_summary
    return terminal_category_summary(category)


def _split_command(command: str) -> tuple[str, list[str]]:
    from daemon.core.terminal_event_normalizer import split_command
    return split_command(command)


def _coerce_int(value: Any) -> int | None:
    from daemon.core.terminal_event_normalizer import coerce_int
    return coerce_int(value)
