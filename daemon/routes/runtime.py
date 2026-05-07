"""Runtime route aggregator — wires all sub-routers onto the Flask app."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.context_probe_store import ContextProbeRequestStore
from daemon.memory.extractor import last_session_context
from daemon.routes.debug_memory import register_debug_memory_routes
from daemon.routes.runtime_debug_routes import register_debug_routes
from daemon.routes.runtime_feed_routes import register_feed_routes
from daemon.routes.runtime_ingestion import register_ingestion_routes, _parse_event_timestamp
from daemon.routes.runtime_probe_routes import register_probe_routes
from daemon.routes.runtime_daemon_routes import register_daemon_routes
from daemon.routes.runtime_resume_card_routes import register_resume_card_routes

_current_context_builder = CurrentContextBuilder()


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

    register_ingestion_routes(app, bus=bus, runtime_state=runtime_state)

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
                "timestamp": event.timestamp.isoformat(),
            }
            for event in recent
            if (since_dt is None or event.timestamp > since_dt)
        ]
        return jsonify(events)
