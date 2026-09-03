"""Deterministic, model-free snapshot of the present: the Context API.

Pas 2 de la roadmap V3 (``docs/specs/2026-09-02-context-api.md``). Pure
module: a store, a reference instant and a window in, a JSON-serialisable
dict out. It reuses the session reconstruction, the single workspace
resolver (decision 5A) and the terminal classification helpers, and never
reads the disk, git, the network or the clock — ``generated_at`` is the
only clock read and the only field allowed to differ between two calls.

Same store + same ``reference_at`` + same ``window_minutes`` → same dict.
"""

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

from .analysis.projects import (
    WorkspaceIdentity,
    is_weak_workspace,
    persisted_workspace_identity,
)
from .analysis.terminal import (
    is_interrupted_exit,
    is_test_command,
    parse_git_command,
    useful_command_lines,
)
from .analysis.timeline import (
    RECONSTRUCTION_VERSION,
    app_activation_counts,
    display_file_path,
    is_strong_work_activity,
    reconstruct_session_views,
)
from .models import SUPPORTED_ACTIVITY_TYPES, StoredActivity
from .session_tracker import DEFAULT_SESSION_GAP
from .trace_store import TraceStore


# 2 depuis Core 0.5.0 : l'id de session est un hash stable, plus un ordinal.
SCHEMA_VERSION = 2
DEFAULT_WINDOW_MINUTES = 120
MIN_WINDOW_MINUTES = 5
MAX_WINDOW_MINUTES = 1440

MAX_APPS = 5
MAX_FILES_PER_CATEGORY = 20
MAX_TERMINAL_LINES = 10
MAX_RECENT_SESSIONS = 3
MAX_ISOLATED_SIGNALS = 10

FILE_CATEGORIES = ("created", "modified", "deleted")


def build_context_snapshot(
    store: TraceStore,
    *,
    reference_at: datetime,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    local_timezone: tzinfo | None = None,
) -> dict[str, Any]:
    """Answer « que se passe-t-il en ce moment ? » from persisted facts only.

    ``reference_at`` must be timezone-aware; every timestamp in the result
    is UTC ISO 8601 with offset. ``local_timezone`` only decides where local
    days start (sessions never cross local midnight, exactly like the daily
    trace); it defaults to the machine zone like ``build_daily_trace``.
    """
    if reference_at.tzinfo is None:
        raise ValueError("reference_at must include a timezone")
    if not MIN_WINDOW_MINUTES <= window_minutes <= MAX_WINDOW_MINUTES:
        raise ValueError(
            "window_minutes must be between "
            f"{MIN_WINDOW_MINUTES} and {MAX_WINDOW_MINUTES}"
        )

    zone = local_timezone or datetime.now().astimezone().tzinfo or timezone.utc
    reference_utc = reference_at.astimezone(timezone.utc)
    window_start = reference_utc - timedelta(minutes=window_minutes)

    sessions, activities = _reconstruct_days(
        store,
        reference_at=reference_utc,
        window_start=window_start,
        zone=zone,
    )
    windowed = [
        activity
        for activity in activities
        if _instant(activity["occurred_at"]) >= window_start
    ]
    current = _select_current_session(sessions, reference_utc)

    workspace_root, workspace_name, resolution = _resolve_workspace(
        current, windowed
    )
    workspace = None
    if workspace_root is not None:
        # Git facts follow the resolution: the whole current session when the
        # workspace comes from it (a 5-minute window on a 3-hour session must
        # still know the session's last commit), the window otherwise.
        git_scope = (
            current["activities"]
            if resolution == "session" and current is not None
            else windowed
        )
        workspace = {
            "path": workspace_root,
            "project": workspace_name,
            "resolution": resolution,
            "git": _workspace_git(workspace_root, git_scope),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_at": reference_utc.isoformat(),
        "window_minutes": window_minutes,
        "timezone": _zone_name(zone, reference_utc),
        "workspace": workspace,
        "current_session": (
            _current_session_view(current) if current is not None else None
        ),
        "recent_sessions": _recent_sessions(
            sessions, current, window_start
        ),
        "isolated_signals": _isolated_signals(sessions, window_start),
        "last_agent_session": _last_agent_session(store, reference_utc),
        "last_session_summary": _last_session_summary(store, reference_utc),
    }


# --- Loading and reconstruction -------------------------------------------


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _utc(value: str | datetime) -> str:
    moment = _instant(value) if isinstance(value, str) else value
    return moment.astimezone(timezone.utc).isoformat()


def _zone_name(zone: tzinfo, at: datetime) -> str:
    # Same naming rule as build_daily_trace: IANA key when available,
    # otherwise the fixed offset in force at the reference instant.
    key = getattr(zone, "key", None)
    if key:
        return str(key)
    if zone == timezone.utc:
        return "UTC"
    offset = at.astimezone(zone).utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def _activity_view(stored: StoredActivity) -> dict[str, Any]:
    return {
        "id": stored.id,
        "event_id": stored.event_id,
        "type": stored.type,
        "occurred_at": stored.occurred_at.isoformat(),
        "summary": stored.activity.summary,
        "details": stored.details,
    }


def _reconstruct_days(
    store: TraceStore,
    *,
    reference_at: datetime,
    window_start: datetime,
    zone: tzinfo,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Work sessions of every local day the window touches, plus activities.

    Each day is reconstructed exactly like the daily trace (a session never
    crosses local midnight) from the whole day, so a session that started
    before the window keeps its real bounds. Rows dated after
    ``reference_at`` are excluded: the answer for a fixed instant must not
    change when later rows arrive.
    """
    sessions: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    day: date = window_start.astimezone(zone).date()
    last_day = reference_at.astimezone(zone).date()
    while day <= last_day:
        day_sessions, day_activities = _reconstruct_day(
            store, day=day, reference_at=reference_at, zone=zone
        )
        sessions.extend(day_sessions)
        activities.extend(day_activities)
        day += timedelta(days=1)
    return sessions, activities


def _reconstruct_day(
    store: TraceStore,
    *,
    day: date,
    reference_at: datetime,
    zone: tzinfo,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One local day, reconstructed like the daily trace, up to reference_at."""
    day_start = datetime.combine(day, time.min, zone)
    day_end = min(
        day_start + timedelta(days=1),
        reference_at + timedelta(microseconds=1),
    )
    if day_end <= day_start:
        return [], []
    views = [
        _activity_view(stored)
        for stored in store.activities_between(day_start, day_end)
    ]
    if not views:
        return [], []
    trace = {
        "date": day.isoformat(),
        "timezone": _zone_name(zone, reference_at),
        "sessions": [{"activities": views}],
    }
    work_sessions, _unresolved = reconstruct_session_views(
        trace,
        now=reference_at.astimezone(zone),
    )
    return work_sessions, views


def _session_end(session: dict[str, Any]) -> datetime:
    return _instant(session["ended_at"])


def _select_current_session(
    sessions: list[dict[str, Any]],
    reference_at: datetime,
) -> dict[str, Any] | None:
    """The work session with the latest activity inside the session gap.

    Nothing inside the gap means « rien en cours » — the last closed session
    is never substituted, that absence is information.
    """
    candidates = [
        session
        for session in sessions
        if session.get("activity_kind") == "work"
        and reference_at - _session_end(session) <= DEFAULT_SESSION_GAP
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (_session_end(s), s["id"]))


# --- Workspace --------------------------------------------------------------


def _activity_identity(activity: dict[str, Any]) -> WorkspaceIdentity | None:
    identity = persisted_workspace_identity(activity)
    if identity.root is None or is_weak_workspace(identity.root):
        return None
    return identity


def _is_useful_for_workspace(activity: dict[str, Any]) -> bool:
    if activity["type"] == "app_activated":
        return False
    if activity["type"] == "terminal_finished":
        return bool(
            useful_command_lines(activity.get("details", {}).get("command"))
        )
    return True


def _session_projects(
    session: dict[str, Any],
) -> list[tuple[str, str, int]]:
    """(root, project name, activity count) in order of first appearance."""
    order: list[str] = []
    names: dict[str, str] = {}
    counts: dict[str, int] = {}
    for activity in session["activities"]:
        identity = _activity_identity(activity)
        if identity is None or not _is_useful_for_workspace(activity):
            continue
        root = identity.root
        assert root is not None
        if root not in counts:
            order.append(root)
            names[root] = identity.project_name or root.rsplit("/", 1)[-1]
            counts[root] = 0
        counts[root] += 1
    return [(root, names[root], counts[root]) for root in order]


def _dominant_workspace(
    session: dict[str, Any],
) -> tuple[str, str] | None:
    projects = _session_projects(session)
    if not projects:
        return None
    # Most observed root wins; ties go to the session's attributed workspace,
    # then to the smallest path — never to iteration order.
    attributed = session.get("workspace_root")
    top = max(count for _root, _name, count in projects)
    best = [item for item in projects if item[2] == top]
    preferred = [item for item in best if item[0] == attributed]
    root, name, _count = (
        preferred[0] if preferred else min(best, key=lambda item: item[0])
    )
    return root, name


def _resolve_workspace(
    current: dict[str, Any] | None,
    windowed: list[dict[str, Any]],
) -> tuple[str | None, str | None, str]:
    if current is not None:
        dominant = _dominant_workspace(current)
        if dominant is not None:
            return dominant[0], dominant[1], "session"
        return None, None, "none"
    for activity in reversed(windowed):
        if not _is_useful_for_workspace(activity):
            continue
        identity = _activity_identity(activity)
        if identity is not None:
            assert identity.root is not None
            return (
                identity.root,
                identity.project_name or identity.root.rsplit("/", 1)[-1],
                "last_observed",
            )
    return None, None, "none"


def _workspace_git(
    workspace_root: str,
    activities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Git facts persisted in the given events for this workspace.

    Never the disk at render time (decision of 2026-08-30): branch and
    dirtiness come from the terminal producer's git context, the last
    commit from git_commit events. ``dirty`` is null when no terminal
    event carried a status. ``None`` when no event carries git facts.
    """
    branch: str | None = None
    dirty: bool | None = None
    last_commit: dict[str, Any] | None = None
    observed = False
    for activity in activities:
        details = activity.get("details", {})
        if activity["type"] == "terminal_finished":
            git = details.get("git")
            if not isinstance(git, dict) or git.get("git_root") != workspace_root:
                continue
            observed = True
            if isinstance(git.get("branch"), str) and git["branch"]:
                branch = git["branch"]
            if isinstance(git.get("dirty"), bool):
                dirty = git["dirty"]
        elif activity["type"] == "git_commit":
            if details.get("git_root") != workspace_root:
                continue
            observed = True
            if isinstance(details.get("branch"), str) and details["branch"]:
                branch = details["branch"]
            commit = _commit_view(activity)
            if commit is not None:
                last_commit = {
                    **commit,
                    "occurred_at": _utc(activity["occurred_at"]),
                }
    if not observed:
        return None
    return {"branch": branch, "dirty": dirty, "last_commit": last_commit}


# --- Sessions ---------------------------------------------------------------


def _duration_minutes(session: dict[str, Any]) -> int:
    seconds = (
        _session_end(session) - _instant(session["started_at"])
    ).total_seconds()
    return max(0, int(seconds // 60))


def _commit_view(activity: dict[str, Any]) -> dict[str, str] | None:
    details = activity.get("details", {})
    commit_hash = details.get("commit_hash")
    message = details.get("message")
    if not isinstance(commit_hash, str) or not commit_hash:
        return None
    first_line = (
        message.splitlines()[0]
        if isinstance(message, str) and message.splitlines()
        else ""
    )
    return {"hash": commit_hash[:7], "message": first_line}


def _terminal_facts(
    activities: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str], bool]:
    """(tests passed, tests failed, error lines, push observed).

    Same rules as the daily summary: only useful lines (pasted prompts and
    Pulse inspection commands excluded), an interrupted command (exit 130)
    is not an error.
    """
    passed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    push_observed = False
    for activity in activities:
        if activity["type"] != "terminal_finished":
            continue
        details = activity.get("details", {})
        lines = useful_command_lines(details.get("command"))
        if not lines:
            continue
        exit_code = details.get("exit_code")
        succeeded = exit_code == 0
        for line in lines:
            if is_test_command(line):
                target = passed if succeeded else failed
                if line not in target:
                    target.append(line)
            if parse_git_command(line).action == "push":
                push_observed = True
        if (
            isinstance(exit_code, int)
            and not isinstance(exit_code, bool)
            and exit_code != 0
            and not is_interrupted_exit(exit_code)
        ):
            for line in lines:
                if line not in errors:
                    errors.append(line)
    return passed, failed, errors, push_observed


def _file_facts(
    activities: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], int]:
    """Display paths per category, deduplicated, in order of first appearance."""
    files: dict[str, list[str]] = {category: [] for category in FILE_CATEGORIES}
    distinct: set[str] = set()
    for activity in activities:
        if activity["type"] != "file_changed":
            continue
        details = activity.get("details", {})
        path = details.get("path")
        event = details.get("event", details.get("change"))
        if not isinstance(path, str) or not path or event not in files:
            continue
        distinct.add(path)
        display_path = display_file_path(path, details.get("workspace"))
        if display_path not in files[event]:
            files[event].append(display_path)
    return files, len(distinct)


def _bounded(values: list[str], limit: int) -> tuple[list[str], bool]:
    return values[:limit], len(values) > limit


def _identity_fields(session: dict[str, Any]) -> dict[str, Any]:
    """Stable identity (Core 0.5.0): the hash is the key, the label is display."""
    return {
        "id": session["id"],
        "label": session["label"],
        "source_event_ids": list(session["source_event_ids"]),
        "reconstruction_version": RECONSTRUCTION_VERSION,
    }


def _current_session_view(
    session: dict[str, Any],
    *,
    is_open: bool = True,
) -> dict[str, Any]:
    activities = session["activities"]
    apps = sorted(
        app_activation_counts(session).items(),
        key=lambda item: (-item[1], item[0]),
    )[:MAX_APPS]
    files, _distinct = _file_facts(activities)
    bounded_files: dict[str, Any] = {}
    files_truncated = False
    for category in FILE_CATEGORIES:
        bounded_files[category], truncated = _bounded(
            files[category], MAX_FILES_PER_CATEGORY
        )
        files_truncated = files_truncated or truncated
    bounded_files["truncated"] = files_truncated

    passed, failed, errors, push_observed = _terminal_facts(activities)
    tests_passed, truncated_passed = _bounded(passed, MAX_TERMINAL_LINES)
    tests_failed, truncated_failed = _bounded(failed, MAX_TERMINAL_LINES)
    error_lines, truncated_errors = _bounded(errors, MAX_TERMINAL_LINES)

    commits = [
        commit
        for commit in (
            _commit_view(activity)
            for activity in activities
            if activity["type"] == "git_commit"
        )
        if commit is not None
    ]
    present_types = {activity["type"] for activity in activities}
    return {
        **_identity_fields(session),
        "started_at": _utc(session["started_at"]),
        "last_activity_at": _utc(session["ended_at"]),
        "duration_minutes": _duration_minutes(session),
        "is_open": is_open,
        "activity_count": len(activities),
        "projects": [name for _root, name, _count in _session_projects(session)],
        "apps": [{"name": name, "activations": count} for name, count in apps],
        "files": bounded_files,
        "git": {"commits": commits, "push_observed": push_observed},
        "terminal": {
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "errors": error_lines,
            "truncated": truncated_passed or truncated_failed or truncated_errors,
        },
        "signals": [
            activity_type
            for activity_type in sorted(SUPPORTED_ACTIVITY_TYPES)
            if activity_type in present_types
        ],
    }


def _recent_session_view(session: dict[str, Any]) -> dict[str, Any]:
    activities = session["activities"]
    _files, distinct_files = _file_facts(activities)
    _passed, failed, errors, _push = _terminal_facts(activities)
    commit_count = sum(
        1 for activity in activities if activity["type"] == "git_commit"
    )
    return {
        **_identity_fields(session),
        "started_at": _utc(session["started_at"]),
        "ended_at": _utc(session["ended_at"]),
        "duration_minutes": _duration_minutes(session),
        "projects": [name for _root, name, _count in _session_projects(session)],
        "headline": {
            "commits": commit_count,
            "files_changed": distinct_files,
            "tests_failed": len(failed),
            "errors": len(errors),
        },
    }


def _recent_sessions(
    sessions: list[dict[str, Any]],
    current: dict[str, Any] | None,
    window_start: datetime,
) -> list[dict[str, Any]]:
    closed = [
        session
        for session in sessions
        if session.get("activity_kind") == "work"
        and (current is None or session["id"] != current["id"])
        and _session_end(session) >= window_start
    ]
    closed.sort(key=lambda s: (_session_end(s), s["id"]), reverse=True)
    return [_recent_session_view(session) for session in closed[:MAX_RECENT_SESSIONS]]


def _isolated_signals(
    sessions: list[dict[str, Any]],
    window_start: datetime,
) -> list[dict[str, Any]]:
    isolated = [
        session
        for session in sessions
        if session.get("activity_kind") == "isolated"
        and _instant(session["started_at"]) >= window_start
    ]
    isolated.sort(key=lambda s: (_instant(s["started_at"]), s["id"]), reverse=True)
    signals = []
    for session in isolated:
        activity = next(
            (
                candidate
                for candidate in session["activities"]
                if is_strong_work_activity(candidate)
            ),
            session["activities"][0],
        )
        summary = _signal_summary(activity)
        if summary is None:
            continue
        signals.append(
            {
                "type": activity["type"],
                "occurred_at": _utc(activity["occurred_at"]),
                "summary": summary,
            }
        )
        if len(signals) == MAX_ISOLATED_SIGNALS:
            break
    return signals


def _signal_summary(activity: dict[str, Any]) -> str | None:
    """One line per isolated signal, never a raw command or a pasted prompt."""
    details = activity.get("details", {})
    if activity["type"] == "terminal_finished":
        lines = useful_command_lines(details.get("command"))
        return lines[-1] if lines else None
    if activity["type"] == "file_changed":
        event = details.get("event", details.get("change", "changed"))
        path = details.get("path")
        if not isinstance(path, str) or not path:
            return None
        return (
            f"{str(event).capitalize()} "
            f"{display_file_path(path, details.get('workspace'))}"
        )
    return activity["summary"]


# --- Derived events without a window ----------------------------------------


def _last_session_summary(
    store: TraceStore,
    reference_at: datetime,
) -> dict[str, Any] | None:
    """The most recent session_summary, same window-free rule as agent sessions.

    Ordered by occurred_at (the summarized session's end) then by row id,
    which follows generated_at for a regenerated summary of the same session.
    """
    stored = store.latest_activity_of_type("session_summary", before=reference_at)
    if stored is None:
        return None
    details = stored.details
    ended_at = details.get("session_ended_at")
    try:
        ended = (
            _instant(ended_at)
            if isinstance(ended_at, str) and ended_at
            else stored.occurred_at
        )
    except ValueError:
        ended = stored.occurred_at
    if ended.tzinfo is None:
        ended = stored.occurred_at
    reprise = details.get("reprise", {})
    structured = details.get("structured", {})
    age_seconds = (reference_at - ended.astimezone(timezone.utc)).total_seconds()
    return {
        "session_id": details.get("session_id"),
        "session_ended_at": _utc(ended),
        "reprise": {
            key: reprise.get(key) for key in ("doing", "stopped_at", "open")
        },
        "confidence": structured.get("confidence"),
        "age_minutes": max(0, int(age_seconds // 60)),
    }


# --- Agent sessions ---------------------------------------------------------


def _last_agent_session(
    store: TraceStore,
    reference_at: datetime,
) -> dict[str, Any] | None:
    stored = store.latest_activity_of_type("agent_session", before=reference_at)
    if stored is None:
        return None
    details = stored.details
    started_at = details.get("started_at")
    ended_at = details.get("ended_at")
    started = (
        _instant(started_at)
        if isinstance(started_at, str) and started_at
        else stored.occurred_at
    )
    ended = (
        _instant(ended_at)
        if isinstance(ended_at, str) and ended_at
        else stored.occurred_at
    )
    workspace = details.get("workspace")
    if isinstance(workspace, dict):
        workspace = workspace.get("workspace_root")
    age_seconds = (reference_at - ended.astimezone(timezone.utc)).total_seconds()
    return {
        "agent": details.get("source_tool"),
        "started_at": _utc(started),
        "ended_at": _utc(ended),
        "workspace": workspace if isinstance(workspace, str) and workspace else None,
        # Le résumé figé de l'événement dérivé, jamais le transcript.
        "summary": stored.activity.summary,
        "age_minutes": max(0, int(age_seconds // 60)),
    }
