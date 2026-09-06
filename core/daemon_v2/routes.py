"""HTTP routes for activity ingestion and daily trace retrieval."""

from datetime import date, datetime, timezone
from pathlib import Path
import re

from flask import Blueprint, Response, current_app, jsonify, request

from .agent_sessions import count_grown_sessions
from .context_snapshot import (
    DEFAULT_WINDOW_MINUTES,
    MAX_WINDOW_MINUTES,
    MIN_WINDOW_MINUTES,
    build_context_snapshot,
    build_day_sessions,
)
from .daily_trace import (
    export_stored_activity,
    build_available_days,
    build_daily_summary,
    build_daily_trace,
    primary_workspace,
    render_available_days_html,
    render_daily_trace_html,
    render_daily_trace_markdown,
)
from .event_logger import log_ingested_event, validation_error_summary
from .ingest import IgnoredActivity, InvalidActivity, normalize_event
from .trace_store import EventConflictError


api = Blueprint("pulse", __name__)
TRACE_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_trace_date(value: str) -> date:
    if not TRACE_DATE_PATTERN.fullmatch(value):
        raise ValueError
    return date.fromisoformat(value)


def _parse_window(value: str | None) -> int:
    if value is None:
        return DEFAULT_WINDOW_MINUTES
    try:
        window = int(value)
    except ValueError:
        window = -1
    if not MIN_WINDOW_MINUTES <= window <= MAX_WINDOW_MINUTES:
        raise ValueError(
            "window must be an integer number of minutes between "
            f"{MIN_WINDOW_MINUTES} and {MAX_WINDOW_MINUTES}"
        )
    return window


def _parse_reference_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise ValueError("at must be an ISO 8601 timestamp with a timezone")
    return parsed.astimezone(timezone.utc)


def _status_context(snapshot: dict) -> dict:
    """Compact view of the Context API for /status: the first consumer."""
    session = snapshot["current_session"]
    workspace = snapshot["workspace"]
    return {
        "session_open": session is not None,
        "duration_minutes": session["duration_minutes"] if session else None,
        "projects": session["projects"] if session else [],
        "workspace": workspace["path"] if workspace else None,
    }


def _build_status(trace):
    summary = build_daily_summary(trace)
    snapshot = build_context_snapshot(
        current_app.config["TRACE_STORE"],
        reference_at=datetime.now(timezone.utc),
    )
    last_event = None
    if trace["sessions"]:
        activity = trace["sessions"][-1]["activities"][-1]
        last_event = {
            "type": activity["type"],
            "occurred_at": activity["occurred_at"],
            "summary": activity["summary"],
        }
    database_path = Path(current_app.config["DATABASE_PATH"])
    return {
        "daemon": "running",
        "url": f"{current_app.config['CORE_BASE_URL']}/",
        "database_path": str(database_path),
        "database_exists": database_path.exists(),
        "date": trace["date"],
        "event_count": trace["activity_count"],
        "displayed_session_count": summary["session_count"],
        "git_commit_count": summary["git_commit_count"],
        "last_event": last_event,
        "primary_workspace": primary_workspace(trace),
        "terminal_watcher": "external; source the Zsh script separately",
        # Déclencheur mesurable de l'item « Segments de reprise » : None =
        # manifeste illisible (non-vu), jamais transformé en faux zéro.
        "grown_agent_sessions": count_grown_sessions(
            current_app.config.get("AGENT_SESSIONS_MANIFEST_PATH")
        ),
        "context": _status_context(snapshot),
    }


@api.get("/")
def get_home():
    trace = build_daily_trace(current_app.config["TRACE_STORE"])
    return Response(
        render_daily_trace_html(trace, system_status=_build_status(trace)),
        mimetype="text/html",
    )


@api.get("/status")
def get_status():
    trace = build_daily_trace(current_app.config["TRACE_STORE"])
    return jsonify(_build_status(trace))


@api.get("/context")
def get_context():
    """Context API (pas 2 de la roadmap V3): the present, without a model."""
    try:
        window = _parse_window(request.args.get("window"))
        reference_at = _parse_reference_at(request.args.get("at"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(
        build_context_snapshot(
            current_app.config["TRACE_STORE"],
            reference_at=reference_at,
            window_minutes=window,
        )
    )


@api.get("/context/sessions")
def get_context_sessions():
    """Closed work sessions of a local day, in the current_session form."""
    try:
        reference_at = _parse_reference_at(request.args.get("at"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    raw_date = request.args.get("date")
    if raw_date is None:
        selected_day = reference_at.astimezone().date()
    else:
        try:
            selected_day = _parse_trace_date(raw_date)
        except ValueError:
            return jsonify({"error": "invalid date; expected YYYY-MM-DD"}), 400
    return jsonify(
        build_day_sessions(
            current_app.config["TRACE_STORE"],
            day=selected_day,
            reference_at=reference_at,
        )
    )


@api.post("/activities")
def post_activity():
    try:
        ingested = normalize_event(request.get_json(silent=True))
    except IgnoredActivity:
        return "", 204
    except InvalidActivity as exc:
        log_ingested_event(
            activity=None,
            status="rejected",
            error=validation_error_summary(exc.field, str(exc)),
        )
        return (
            jsonify(
                {
                    "error": {
                        "code": "invalid_event",
                        "field": exc.field,
                        "message": str(exc),
                    }
                }
            ),
            400,
        )

    try:
        stored = current_app.config["TRACE_STORE"].append_event(ingested)
    except EventConflictError as exc:
        log_ingested_event(
            activity=ingested.activity,
            status="conflict",
        )
        return (
            jsonify(
                {
                    "accepted": False,
                    "event_id": exc.event_id,
                    "error": {
                        "code": "event_id_conflict",
                        "field": "event_id",
                        "message": str(exc),
                    },
                }
            ),
            409,
        )
    log_ingested_event(
        activity=stored.activity,
        status="duplicate" if stored.duplicate else "created",
    )
    return (
        jsonify(
            {
                "accepted": True,
                "event_id": stored.event_id,
                "duplicate": stored.duplicate,
                "recorded_at": stored.recorded_at.isoformat(),
            }
        ),
        200 if stored.duplicate else 201,
    )


@api.get("/activities/<event_id>")
def get_activity(event_id: str):
    """Ajout de lecture pure sous gel fonctionnel (audit 2026-09-06, défaut 3).

    The stored row for one producer event_id, in the export form of the
    JSON trace: what Core accepted, after its own normalization, never a
    reconstruction. A consumer that lost its local state reads this before
    regenerating anything. Writing and the 409 on conflict are untouched.
    """
    stored = current_app.config["TRACE_STORE"].activity_by_event_id(event_id)
    if stored is None:
        return (
            jsonify({"error": {"code": "unknown_event_id", "event_id": event_id}}),
            404,
        )
    return jsonify(export_stored_activity(stored))


@api.get("/trace/today")
@api.get("/trace/today.json")
def get_today_trace():
    trace = build_daily_trace(current_app.config["TRACE_STORE"])
    return jsonify(trace)


@api.get("/trace/days")
def get_trace_days():
    return jsonify(build_available_days(current_app.config["TRACE_STORE"]))


@api.get("/days")
def get_days():
    available_days = build_available_days(current_app.config["TRACE_STORE"])
    return Response(
        render_available_days_html(available_days),
        mimetype="text/html",
    )


@api.get("/day/<date_value>")
def get_day(date_value):
    try:
        selected_date = _parse_trace_date(date_value)
    except ValueError:
        return jsonify({"error": "invalid date; expected YYYY-MM-DD"}), 400
    trace = build_daily_trace(
        current_app.config["TRACE_STORE"],
        day=selected_date,
    )
    return Response(
        render_daily_trace_html(
            trace,
            trace_json_url=f"/trace/{date_value}",
            trace_markdown_url=f"/trace/{date_value}.md",
            archive_mode=True,
        ),
        mimetype="text/html",
    )


@api.get("/trace/<date_value>")
def get_dated_trace(date_value):
    try:
        selected_date = _parse_trace_date(date_value)
    except ValueError:
        return jsonify({"error": "invalid date; expected YYYY-MM-DD"}), 400
    return jsonify(
        build_daily_trace(
            current_app.config["TRACE_STORE"],
            day=selected_date,
        )
    )


@api.get("/trace/<date_value>.md")
def get_dated_trace_markdown(date_value):
    try:
        selected_date = _parse_trace_date(date_value)
    except ValueError:
        return jsonify({"error": "invalid date; expected YYYY-MM-DD"}), 400
    trace = build_daily_trace(
        current_app.config["TRACE_STORE"],
        day=selected_date,
    )
    return Response(
        render_daily_trace_markdown(trace, archive_mode=True),
        mimetype="text/markdown",
    )


@api.get("/trace/today.md")
def get_today_trace_markdown():
    trace = build_daily_trace(current_app.config["TRACE_STORE"])
    return Response(render_daily_trace_markdown(trace), mimetype="text/markdown")
