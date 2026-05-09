"""Event ingestion pipeline — /event route and all pre-bus processing. No other routes."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.event_actor import EventActorClassifier
from daemon.core.file_event_coalescer import FileEventCoalescer
from daemon.core.workspace_context import extract_project_name, find_workspace_root
from daemon.interpreter.command_interpreter import CommandInterpreter

_actor_classifier = EventActorClassifier()
_terminal_interpreter = CommandInterpreter()

_TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({
    "terminal_command_started",
    "terminal_command_finished",
})

_BUS_FILE_EVENT_TYPES: frozenset[str] = frozenset({
    "file_created", "file_modified", "file_renamed",
    "file_deleted", "file_change",
})

_FILE_ACTOR_EVENT_TYPES: frozenset[str] = frozenset({
    "file_modified", "file_created", "file_renamed", "file_deleted",
})


def register_ingestion_routes(
    app: Flask,
    *,
    bus: Any,
    runtime_state: Any,
) -> FileEventCoalescer:
    """Register /event onto *app*. Returns the FileEventCoalescer for shutdown."""

    def _publish_to_bus(
        event_type: str,
        payload: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> None:
        if timestamp is None:
            bus.publish(event_type, payload)
        else:
            bus.publish(event_type, payload, timestamp)

    coalescer = FileEventCoalescer(publisher=_publish_to_bus)

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

        if event_type in _FILE_ACTOR_EVENT_TYPES:
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

        coalescer.publish(event_type, payload, observed_at)
        return jsonify({"ok": True})

    return coalescer


def _should_publish_to_bus(
    event_type: str,
    payload: dict[str, Any],
    runtime_state: Any = None,
) -> bool:
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


def _normalize_terminal_event_payload(
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from daemon.core.terminal_event_normalizer import (
        coerce_int,
        split_command,
        terminal_action_category,
        terminal_category_summary,
    )
    from daemon.core.test_result_parser import parse_test_result

    command = str(payload.pop("command", "") or payload.pop("raw", "")).strip()
    output_summary = str(
        payload.get("stdout_summary")
        or payload.get("test_output_summary")
        or payload.get("output_summary")
        or ""
    ).strip()
    cwd = str(payload.get("cwd", "")).strip() or None
    shell = str(payload.get("shell", "")).strip() or None
    terminal_program = str(payload.get("terminal_program", "")).strip() or None
    exit_code = coerce_int(payload.get("exit_code"))
    duration_ms = coerce_int(payload.get("duration_ms"))

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
    action_category = terminal_action_category(command, interpretation)
    base_cmd = split_command(command)[0]

    if interpretation.needs_llm:
        raw_summary = terminal_category_summary(action_category)
    else:
        raw_summary = interpretation.translated

    if exit_code is not None:
        status_prefix = "\u2713" if exit_code == 0 else "\u2717"
        summary = f"{status_prefix} {raw_summary}"
    else:
        summary = raw_summary

    normalized.update({
        "terminal_command": command,
        "terminal_command_base": base_cmd,
        "terminal_action_category": action_category,
        "terminal_is_read_only": interpretation.is_read_only,
        "terminal_affects": list(interpretation.affects),
        "terminal_success": (exit_code == 0) if exit_code is not None else None,
        "terminal_summary": summary,
    })
    test_result = parse_test_result(
        command=command,
        terminal_action_category=action_category,
        success=normalized["terminal_success"],
        exit_code=exit_code,
        output_summary=output_summary,
    )
    if test_result:
        normalized["test_result"] = test_result
    return normalized


def _parse_event_timestamp(raw: Any) -> datetime | None:
    from daemon.core.terminal_event_normalizer import parse_event_timestamp
    return parse_event_timestamp(raw)
