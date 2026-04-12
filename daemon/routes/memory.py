from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, request


def register_memory_routes(
    app: Flask,
    *,
    memory_store: Any,
    session_memory: Any,
    get_frozen_memory_at: Callable[[], Any],
) -> None:
    @app.route("/memory")
    def memory_list():
        tier = request.args.get("tier")
        entries = memory_store.list_entries(tier=tier)
        frozen_at = get_frozen_memory_at()
        return jsonify({
            "entries": entries,
            "usage": memory_store.usage(),
            "frozen_at": frozen_at.isoformat() if frozen_at else None,
        })

    @app.route("/memory/write", methods=["POST"])
    def memory_write():
        data = request.get_json() or {}
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"ok": False, "error": "content manquant"}), 400
        result = memory_store.write(
            content=content,
            tier=data.get("tier", "session"),
            topic=data.get("topic", "general"),
            source=data.get("source", "llm"),
            old_text=data.get("old_text"),
        )
        return jsonify(result), (200 if result["ok"] else 422)

    @app.route("/memory/remove", methods=["POST"])
    def memory_remove():
        data = request.get_json() or {}
        old_text = (data.get("old_text") or "").strip()
        if not old_text:
            return jsonify({"ok": False, "error": "old_text manquant"}), 400
        result = memory_store.remove(
            tier=data.get("tier", "session"),
            old_text=old_text,
        )
        return jsonify(result), (200 if result["ok"] else 422)

    @app.route("/memory/usage")
    def memory_usage():
        frozen_at = get_frozen_memory_at()
        return jsonify({
            "usage": memory_store.usage(),
            "frozen_at": frozen_at.isoformat() if frozen_at else None,
        })

    @app.route("/search")
    def search_events():
        q = (request.args.get("q") or "").strip()
        limit = min(int(request.args.get("limit", 20)), 100)
        session = request.args.get("session")
        if not q:
            return jsonify({"error": "missing_query", "hint": "?q=<query>"}), 400
        results = session_memory.search_events(q, limit=limit, session_id=session)
        return jsonify({"query": q, "count": len(results), "results": results})
