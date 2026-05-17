"""Debug resume card routes — force resume card generation for local UI testing."""
from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.resume_card import (
    build_resume_card_context,
    generate_resume_card,
    generate_resume_card_with_debug,
)
from daemon.llm.lifecycle_policy import require_heavy_llm
from daemon.memory.extractor import get_recent_journal_entries


def _first_recent_session_value(recent_sessions: Any, key: str) -> Any:
    if not isinstance(recent_sessions, list):
        return None
    for item in recent_sessions:
        if not isinstance(item, dict):
            continue
        value = item.get(key)
        if value is not None and value != "" and value != []:
            return value
    return None


def register_resume_card_routes(
    app: Flask,
    *,
    bus: Any,
    runtime_state: Any,
    get_recent_sessions: Callable[[int], Any] | None = None,
    get_today_summary: Callable[[], dict[str, Any]] | None = None,
    resume_card_llm: Any = None,
) -> None:
    """Register debug resume card routes onto *app*."""

    def _build_debug_resume_card_context(data: dict[str, Any]) -> dict[str, Any]:
        runtime_snapshot = runtime_state.get_runtime_snapshot()
        present = runtime_snapshot.present

        try:
            sleep_minutes = float(data.get("sleep_minutes", 35))
        except (TypeError, ValueError):
            sleep_minutes = 35.0

        signals = runtime_snapshot.signals
        recent_sessions = get_recent_sessions(5) if get_recent_sessions is not None else []
        today_summary = get_today_summary() if get_today_summary is not None else {}
        current_window = today_summary.get("current_window") if isinstance(today_summary, dict) else None
        if not isinstance(current_window, dict):
            current_window = {}

        journal_project = present.active_project or current_window.get("project")
        recent_journal_entries = get_recent_journal_entries(5, project=journal_project)

        top_files: list[str] = []
        for candidate in [
            present.active_file,
            getattr(signals, "active_file", None) if signals is not None else None,
        ]:
            if candidate and candidate not in top_files:
                top_files.append(candidate)

        memory_payload = {
            "active_project": (
                present.active_project
                or current_window.get("project")
                or _first_recent_session_value(recent_sessions, "project")
            ),
            "probable_task": (
                present.probable_task
                or current_window.get("task")
                or current_window.get("probable_task")
                or _first_recent_session_value(recent_sessions, "task")
                or _first_recent_session_value(recent_sessions, "probable_task")
            ),
            "activity_level": (
                present.activity_level
                or current_window.get("activity")
                or current_window.get("activity_level")
                or _first_recent_session_value(recent_sessions, "activity_level")
            ),
            "duration_min": (
                present.session_duration_min
                or current_window.get("duration_min")
                or _first_recent_session_value(recent_sessions, "duration_min")
            ),
            "top_files": top_files[:8],
            "recent_files": top_files[:8],
            "recent_sessions": recent_sessions,
            "recent_journal_entries": recent_journal_entries,
            "today_summary": today_summary,
            "active_app": runtime_snapshot.latest_active_app,
            "window_title": getattr(signals, "window_title", None) if signals is not None else None,
            "diff_summary": runtime_snapshot.last_diff_summary,
            "work_block_started_at": current_window.get("started_at"),
            "work_block_ended_at": current_window.get("ended_at"),
        }
        context = build_resume_card_context(
            runtime_snapshot=runtime_snapshot,
            memory_payload=memory_payload,
            sleep_minutes=sleep_minutes,
            diff_summary=runtime_snapshot.last_diff_summary,
        )
        context["debug_forced"] = True
        return context

    @app.route("/debug/resume-card", methods=["POST"])
    def debug_resume_card():
        """Force a deterministic resume card event for local UI testing."""
        data = request.get_json(silent=True) or {}
        context = _build_debug_resume_card_context(data)
        card = generate_resume_card(context, llm=None)
        payload = card.to_event_payload()
        bus.publish("resume_card", payload)
        return jsonify({"ok": True, "mode": "deterministic", "card": payload})

    @app.route("/debug/resume-card/llm", methods=["POST"])
    def debug_resume_card_llm():
        """Force a resume card event using the configured LLM when available."""
        data = request.get_json(silent=True) or {}
        context = _build_debug_resume_card_context(data)
        heavy_allowed = require_heavy_llm(
            "debug_resume_card_llm",
            reason="explicit_debug_resume_card_llm",
        )
        card, debug = generate_resume_card_with_debug(
            context,
            llm=resume_card_llm if heavy_allowed else None,
        )
        payload = card.to_event_payload()
        bus.publish("resume_card", payload)
        return jsonify({
            "ok": True,
            "mode": "llm" if heavy_allowed and resume_card_llm is not None else "deterministic_fallback",
            "llm_available": heavy_allowed and resume_card_llm is not None,
            "card": payload,
            "debug": debug,
        })
