from __future__ import annotations

from typing import Any, Callable

from flask import Flask, Response, jsonify, request, stream_with_context

from daemon.tools.pulse_tools import TOOL_DEFINITIONS, TOOL_MAP


def register_assistant_routes(
    app: Flask,
    *,
    cognitive_ask: Callable[..., dict],
    cognitive_ask_stream: Callable[..., Any],
    cognitive_ask_stream_with_tools: Callable[..., Any],
    llm: Any,
    build_context_snapshot: Callable[[], str],
    get_frozen_memory: Callable[[], str],
    get_available_models: Callable[[], list],
    get_selected_command_model: Callable[[], str],
    get_selected_summary_model: Callable[[], str],
    set_unified_model: Callable[[str], bool],
    persist_selected_models: Callable[[], None],
    ollama_ping: Callable[[], bool],
    llm_provider: Callable[[], Any],
) -> None:
    @app.route("/ask", methods=["POST"])
    def ask():
        data = request.get_json() or {}
        message = (data.get("message") or "").strip()
        max_tok = int(data.get("max_tokens", 600))

        result = cognitive_ask(
            message=message,
            llm=llm,
            context_snapshot=build_context_snapshot(),
            frozen_memory=get_frozen_memory(),
            max_tokens=max_tok,
        )
        status = 200 if result["ok"] else 503
        return jsonify(result), status

    @app.route("/ask/stream", methods=["POST"])
    def ask_stream():
        data = request.get_json() or {}
        message = (data.get("message") or "").strip()
        history = data.get("history") or []
        max_tok = int(data.get("max_tokens", 1200))
        use_tools = data.get("tools", True)  # activé par défaut

        ctx    = build_context_snapshot()
        frozen = get_frozen_memory()

        def generate():
            if use_tools:
                yield from cognitive_ask_stream_with_tools(
                    message          = message,
                    llm              = llm,
                    tools            = TOOL_DEFINITIONS,
                    tool_map         = TOOL_MAP,
                    context_snapshot = ctx,
                    frozen_memory    = frozen,
                    history          = history,
                    max_tokens       = max_tok,
                )
            else:
                yield from cognitive_ask_stream(
                    message          = message,
                    llm              = llm,
                    context_snapshot = ctx,
                    frozen_memory    = frozen,
                    history          = history,
                    max_tokens       = max_tok,
                )

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control":     "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route("/context")
    def get_context():
        return jsonify({"context": build_context_snapshot()})

    @app.route("/llm/models")
    def get_llm_models():
        available = get_available_models()
        selected_cmd = get_selected_command_model()
        selected_sum = get_selected_summary_model()
        selected_model = (selected_cmd or selected_sum or "").strip()
        ollama_online = ollama_ping()
        provider = llm_provider()
        provider_ok = bool(provider and getattr(provider, "is_operational", False))
        has_model = bool(selected_model)
        model_selected = has_model
        llm_ready = ollama_online and model_selected
        llm_active = llm_ready and provider_ok
        return jsonify({
            "provider": "ollama",
            "available_models": available,
            "selected_model": selected_model,
            "selected_command_model": selected_cmd,
            "selected_summary_model": selected_sum,
            "ollama_online": ollama_online,
            "model_selected": model_selected,
            "llm_ready": llm_ready,
            "llm_active": llm_active,
        })

    @app.route("/llm/model", methods=["POST"])
    def set_llm_model():
        data = request.get_json() or {}
        model = (data.get("model") or "").strip()
        if not model:
            return jsonify({"ok": False, "error": "missing_model"}), 400
        ok = set_unified_model(model)
        if not ok:
            return jsonify({"ok": False, "error": "unknown_model"}), 400
        persist_selected_models()
        selected = get_selected_command_model()
        return jsonify({
            "ok": True,
            "model": selected,
            "selected_model": selected,
            "selected_command_model": selected,
            "selected_summary_model": selected,
        })
