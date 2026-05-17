

from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.memory.extractor import last_session_context
from daemon.routes.runtime_ingestion import _parse_event_timestamp


def _build_state_payload(
    *,
    store_state: dict[str, Any],
    runtime_snapshot: Any,
    current_context_builder: CurrentContextBuilder,
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
        current_context_builder=current_context_builder,
        last_session_context_fn=last_session_context,
    )


def _build_debug_state_payload(
    *,
    store_state: dict[str, Any],
    runtime_snapshot: Any,
    current_context_builder: CurrentContextBuilder,
    get_session_fsm: Callable[[], Any] | None = None,
    get_current_context: Callable[[], Any] | None = None,
    get_recent_sessions: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    from daemon.routes.runtime_state_payloads import build_debug_state_payload

    return build_debug_state_payload(
        store_state=store_state,
        runtime_snapshot=runtime_snapshot,
        get_session_fsm=get_session_fsm,
        get_current_context=get_current_context,
        get_recent_sessions=get_recent_sessions,
        current_context_builder=current_context_builder,
        last_session_context_fn=last_session_context,
    )



def register_status_routes(
    app: Flask,
    *,
    bus: Any,
    store: Any,
    runtime_state: Any,
    current_context_builder: CurrentContextBuilder,
    get_session_fsm: Callable[[], Any] | None = None,
    get_current_context: Callable[[], Any] | None = None,
    get_recent_sessions: Callable[[int], Any] | None = None,
) -> None:
    @app.route("/ping", methods=["GET"])
    def ping():
        paused = runtime_state.touch_ping()
        return jsonify({"status": "ok", "version": "0.1.0", "paused": paused})

    @app.route("/state", methods=["GET"])
    def get_state():
        state = _build_state_payload(
            store_state=store.to_dict(),
            runtime_snapshot=runtime_state.get_runtime_snapshot(),
            current_context_builder=current_context_builder,
            get_session_fsm=get_session_fsm,
            get_current_context=get_current_context,
            get_recent_sessions=get_recent_sessions,
        )
        return jsonify(state)

    @app.route("/debug/state", methods=["GET"])
    def get_debug_state():
        debug_state = _build_debug_state_payload(
            store_state=store.to_dict(),
            runtime_snapshot=runtime_state.get_runtime_snapshot(),
            current_context_builder=current_context_builder,
            get_session_fsm=get_session_fsm,
            get_current_context=get_current_context,
            get_recent_sessions=get_recent_sessions,
        )
        return jsonify(debug_state)

    @app.route("/insights", methods=["GET"])
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
