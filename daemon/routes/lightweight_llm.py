from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.runtime_mode import is_lab_enabled
from daemon.routes.lab_surface import lab_surface_disabled_response, lab_surface_metadata


def register_lightweight_llm_routes(
    app: Flask,
    *,
    lightweight_queue: Any,
    apply_result: Callable[..., dict[str, Any]],
) -> None:
    @app.route("/llm/lightweight/status")
    def get_lightweight_status():
        return jsonify({
            **lightweight_queue.status(),
            **lab_surface_metadata(),
        })

    @app.route("/llm/lightweight/pending")
    def get_lightweight_pending():
        if not is_lab_enabled():
            return jsonify({
                "request": None,
                **lab_surface_metadata(),
            })
        item = lightweight_queue.claim_next()
        if item is None:
            return jsonify({
                "request": None,
                **lab_surface_metadata(),
            })
        return jsonify({
            "request": item.public_payload(),
            **lab_surface_metadata(),
        })

    @app.route("/llm/lightweight/result", methods=["POST"])
    def post_lightweight_result():
        if not is_lab_enabled():
            return lab_surface_disabled_response("llm_lightweight_result")
        data = request.get_json() or {}
        request_id = str(data.get("id") or "").strip()
        status = str(data.get("status") or "").strip()
        if not request_id:
            return jsonify({"ok": False, "error": "id_required"}), 400
        if status not in {"generated", "failed"}:
            return jsonify({"ok": False, "error": "invalid_status"}), 400

        result = apply_result(
            request_id=request_id,
            status=status,
            text=str(data.get("text") or ""),
            error=data.get("error"),
        )
        response_status = 200 if result.get("ok") else int(result.get("http_status") or 400)
        result.pop("http_status", None)
        return jsonify(result), response_status
