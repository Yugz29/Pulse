from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, request


def register_mcp_routes(
    app: Flask,
    *,
    bus: Any,
    get_pending_command: Callable[[], Any],
    intercept_command: Callable[[str, str], dict],
    receive_decision: Callable[[str | None, str | None], bool],
    get_scoring_status: Callable[[], dict],
    log: Any,
) -> None:
    @app.route("/mcp/pending")
    def mcp_pending():
        cmd = get_pending_command()
        if cmd is None:
            return "", 204
        return jsonify(cmd)

    @app.route("/mcp/intercept", methods=["POST"])
    def mcp_intercept():
        data = request.get_json() or {}
        command = data.get("command", "")
        tool_use_id = data.get("tool_use_id", "unknown")
        log.info("/mcp/intercept : tool_use_id=%s command=%r", tool_use_id, command)
        bus.publish("mcp_command_received", {"command": command, "tool_use_id": tool_use_id})
        result = intercept_command(command, tool_use_id)
        bus.publish(
            "mcp_decision",
            {
                "tool_use_id": tool_use_id,
                "decision": result.get("decision"),
                "allowed": result.get("allowed"),
            },
        )
        return jsonify(result)

    @app.route("/mcp/decision", methods=["POST"])
    def mcp_decision():
        data = request.get_json() or {}
        tool_use_id = data.get("tool_use_id")
        decision = data.get("decision")
        ok = receive_decision(tool_use_id, decision)
        bus.publish("mcp_decision", {"tool_use_id": tool_use_id, "decision": decision})
        return jsonify({"ok": ok})

    @app.route("/scoring/status")
    def scoring_status():
        return jsonify(get_scoring_status())
