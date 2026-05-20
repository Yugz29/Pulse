

from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.memory.extractor import last_session_context
from daemon.runtime_mode import get_pulse_mode, is_lab_enabled
from daemon.routes.runtime_ingestion import _parse_event_timestamp


def _build_state_payload(
    *,
    store_state: dict[str, Any],
    runtime_snapshot: Any,
    current_context_builder: CurrentContextBuilder,
    get_session_fsm: Callable[[], Any] | None = None,
    get_current_context: Callable[[], Any] | None = None,
    get_recent_sessions: Callable[[int], Any] | None = None,
    include_debug: bool = False,
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
        include_debug=include_debug,
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
    def _include_debug_in_state() -> bool:
        raw = str(request.args.get("include_debug") or "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _session_fsm_health() -> str:
        if get_session_fsm is None:
            return "not_checked"
        try:
            return "ok" if get_session_fsm() is not None else "missing"
        except Exception:
            return "unavailable"

    @app.route("/ping", methods=["GET"])
    def ping():
        paused = runtime_state.touch_ping()
        return jsonify({"status": "ok", "version": "0.1.0", "paused": paused})

    @app.route("/health/core", methods=["GET"])
    def get_core_health():
        mode = get_pulse_mode()
        lab_enabled = is_lab_enabled()
        checks = {
            "runtime": "ok",
            "ping": "ok",
            "runtime_state": "ok" if runtime_state is not None else "missing",
            "event_bus": "ok" if bus is not None else "missing",
            "feed_source": "ok" if bus is not None else "missing",
            "scoring": "available",
            "session_fsm": _session_fsm_health(),
            "lab_services": "not_required" if not lab_enabled else "enabled",
        }
        failed = {
            key: value
            for key, value in checks.items()
            if value in {"missing", "unavailable"}
        }
        return jsonify({
            "status": "ok" if not failed else "degraded",
            "pulse_mode": mode,
            "experimental_enabled": lab_enabled,
            "checks": checks,
            "failed": failed,
        })

    @app.route("/state", methods=["GET"])
    def get_state():
        state = _build_state_payload(
            store_state=store.to_dict(),
            runtime_snapshot=runtime_state.get_runtime_snapshot(),
            current_context_builder=current_context_builder,
            get_session_fsm=get_session_fsm,
            get_current_context=get_current_context,
            get_recent_sessions=get_recent_sessions,
            include_debug=_include_debug_in_state(),
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
