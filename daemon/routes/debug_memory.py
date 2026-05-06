from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from flask import jsonify, request


def register_debug_memory_routes(
    app,
    *,
    get_work_episodes: Callable[..., dict[str, Any]] | None = None,
    get_journal_candidates: Callable[..., dict[str, Any]] | None = None,
    get_journal_comparison: Callable[..., dict[str, Any]] | None = None,
    get_commit_episode_links: Callable[..., dict[str, Any]] | None = None,
) -> None:
    """Register read-only Phase 2a debug memory routes."""

    def _parse_debug_date_query() -> tuple[datetime | None, Any | None]:
        raw_date = request.args.get("date")
        if not raw_date:
            return None, None
        try:
            return datetime.strptime(raw_date, "%Y-%m-%d"), None
        except ValueError:
            return None, (
                jsonify({
                    "error": "invalid_date",
                    "message": "date must use YYYY-MM-DD",
                }),
                400,
            )

    def _call_debug_date_callback(callback: Callable[..., dict[str, Any]], debug_date: datetime | None) -> dict[str, Any]:
        if debug_date is None:
            return callback()
        return callback(debug_date)

    @app.route("/debug/work-episodes")
    def get_debug_work_episodes_route():
        debug_date, error_response = _parse_debug_date_query()
        if error_response is not None:
            return error_response
        if get_work_episodes is None:
            now = debug_date or datetime.now()
            return jsonify(
                {
                    "date": now.date().isoformat(),
                    "generated_at": now.isoformat(),
                    "episode_count": 0,
                    "episodes": [],
                }
            )
        return jsonify(_call_debug_date_callback(get_work_episodes, debug_date))

    @app.route("/debug/journal-candidates")
    def get_debug_journal_candidates_route():
        debug_date, error_response = _parse_debug_date_query()
        if error_response is not None:
            return error_response
        if get_journal_candidates is None:
            now = debug_date or datetime.now()
            return jsonify(
                {
                    "date": now.date().isoformat(),
                    "generated_at": now.isoformat(),
                    "candidate_count": 0,
                    "ignored_count": 0,
                    "candidates": [],
                    "ignored": [],
                }
            )
        return jsonify(_call_debug_date_callback(get_journal_candidates, debug_date))

    @app.route("/debug/journal-comparison")
    def get_debug_journal_comparison_route():
        debug_date, error_response = _parse_debug_date_query()
        if error_response is not None:
            return error_response
        if get_journal_comparison is None:
            now = debug_date or datetime.now()
            return jsonify(
                {
                    "date": now.date().isoformat(),
                    "generated_at": now.isoformat(),
                    "journal_entry_count": 0,
                    "candidate_count": 0,
                    "matches": [],
                    "unmatched_journal_entries": [],
                    "unmatched_candidates": [],
                }
            )
        return jsonify(_call_debug_date_callback(get_journal_comparison, debug_date))

    @app.route("/debug/commit-episode-links")
    def get_debug_commit_episode_links_route():
        debug_date, error_response = _parse_debug_date_query()
        if error_response is not None:
            return error_response
        if get_commit_episode_links is None:
            now = debug_date or datetime.now()
            return jsonify(
                {
                    "date": now.date().isoformat(),
                    "generated_at": now.isoformat(),
                    "commit_count": 0,
                    "linked_count": 0,
                    "unlinked_count": 0,
                    "links": [],
                    "unlinked_commits": [],
                }
            )
        return jsonify(_call_debug_date_callback(get_commit_episode_links, debug_date))
