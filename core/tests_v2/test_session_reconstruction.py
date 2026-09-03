from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from daemon_v2.analysis.timeline import reconstruct_session_views
from daemon_v2.analysis.timeline import configured_interruption_threshold
from daemon_v2.daily_trace import (
    build_daily_trace,
    render_daily_trace_html,
    render_daily_trace_markdown,
)
from daemon_v2.models import Activity
from daemon_v2.trace_store import TraceStore


BASE = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
PULSE = "/workspace/Pulse_Core"
DEVNOTE = "/workspace/DevNote"


def event(
    event_type: str,
    minutes: int,
    details: dict | None = None,
    event_id: int = 1,
) -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "occurred_at": (BASE + timedelta(minutes=minutes)).isoformat(),
        "details": details or {},
    }


def workspace(root: str) -> dict:
    return {
        "workspace": {
            "project_name": root.rsplit("/", 1)[-1],
            "workspace_root": root,
            "git_root": root,
            "resolution_method": "git",
            "resolution_confidence": "high",
        }
    }


def low_workspace(root: str) -> dict:
    return {
        "workspace": {
            "project_name": Path(root).name,
            "workspace_root": root,
            "git_root": None,
            "resolution_method": "cwd",
            "resolution_confidence": "low",
        }
    }


def reconstruct(
    *activities: dict,
    now: datetime | None = None,
) -> tuple[list[dict], list[dict]]:
    trace = {
        "date": BASE.date().isoformat(),
        "timezone": "UTC",
        "sessions": [{"activities": list(activities)}],
    }
    return reconstruct_session_views(
        trace,
        now=now or BASE + timedelta(minutes=10),
    )


@pytest.mark.parametrize(
    "event_type", ["terminal_finished", "file_changed", "git_commit"]
)
def test_real_work_starts_a_session(event_type):
    details = workspace(PULSE)
    if event_type == "terminal_finished":
        details["command"] = "pytest -q"
    elif event_type == "file_changed":
        details["path"] = f"{PULSE}/main.py"
    else:
        details["commit_hash"] = "abc1234def5678"
        details["branch"] = "main"
        details["message"] = "Fix typo"

    sessions, _passive = reconstruct(event(event_type, 0, details))

    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "Pulse_Core"
    assert sessions[0]["end_reason"] == "open"


def test_unlock_or_wake_alone_does_not_start_a_session():
    sessions, unresolved = reconstruct(
        event("screen_unlocked", 0),
        event("system_wake", 1, event_id=2),
    )

    assert sessions == []
    assert unresolved == []


@pytest.mark.parametrize("end_type", ["screen_locked", "system_sleep"])
def test_unconfirmed_interruption_does_not_extend_session(end_type):
    sessions, _passive = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        event("file_changed", 10, {**workspace(PULSE), "path": f"{PULSE}/a.py"}, 2),
        event(end_type, 20, event_id=3),
    )

    assert len(sessions) == 1
    assert sessions[0]["ended_at"] == (BASE + timedelta(minutes=10)).isoformat()
    assert sessions[0]["duration_seconds"] == 10 * 60
    assert sessions[0]["interruptions"] == []
    assert sessions[0]["end_reason"] == end_type


@pytest.mark.parametrize(
    ("stop_type", "resume_type"),
    [("screen_locked", "screen_unlocked"), ("system_sleep", "system_wake")],
)
def test_resume_transition_waits_for_new_work(stop_type, resume_type):
    sessions, _passive = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        event(stop_type, 20, event_id=2),
        event(resume_type, 50, event_id=3),
        event(
            "terminal_finished",
            55,
            {**workspace(PULSE), "command": "pytest"},
            4,
        ),
    )

    assert len(sessions) == 2
    assert sessions[0]["ended_at"] == BASE.isoformat()
    assert sessions[0]["active_duration_seconds"] == 0
    assert sessions[0]["interruptions"] == []
    assert sessions[1]["started_at"] == (BASE + timedelta(minutes=55)).isoformat()


def test_short_interruption_followed_by_same_workspace_keeps_session():
    sessions, _passive = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        event("screen_locked", 10, event_id=2),
        event("screen_unlocked", 11, event_id=3),
        event(
            "terminal_finished",
            12,
            {**workspace(PULSE), "command": "git status"},
            4,
        ),
    )

    assert len(sessions) == 1
    assert sessions[0]["duration_seconds"] == 12 * 60
    assert sessions[0]["active_duration_seconds"] == 11 * 60
    assert sessions[0]["interruptions"] == [
        {
            "type": "screen_locked",
            "started_at": (BASE + timedelta(minutes=10)).isoformat(),
            "ended_at": (BASE + timedelta(minutes=11)).isoformat(),
            "duration_seconds": 60,
        }
    ]


def test_unlock_without_later_strong_work_is_not_a_session_boundary():
    locked = event("screen_locked", 10, event_id=2)
    unlocked = event("screen_unlocked", 11, event_id=3)
    sessions, unresolved = reconstruct(
        event("file_changed", 0, {**workspace(PULSE), "path": f"{PULSE}/a.py"}),
        locked,
        unlocked,
        now=BASE + timedelta(minutes=20),
    )

    assert len(sessions) == 1
    assert sessions[0]["ended_at"] == BASE.isoformat()
    assert sessions[0]["interruptions"] == []
    assert locked not in sessions[0]["activities"]
    assert unlocked not in sessions[0]["activities"]
    assert unresolved == []


def test_isolated_system_wake_does_not_keep_old_session_open():
    wake = event("system_wake", 60, event_id=2)
    sessions, unresolved = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        wake,
        now=BASE + timedelta(minutes=70),
    )

    assert len(sessions) == 1
    assert sessions[0]["ended_at"] == BASE.isoformat()
    assert wake not in sessions[0]["activities"]
    assert unresolved == []


def test_duplicate_unlock_is_ignored_until_another_lock():
    first_unlock = event("screen_unlocked", 2, event_id=3)
    duplicate_unlock = event("screen_unlocked", 3, event_id=4)
    sessions, unresolved = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        event("screen_locked", 1, event_id=2),
        first_unlock,
        duplicate_unlock,
        event(
            "terminal_finished",
            4,
            {**workspace(PULSE), "command": "pytest"},
            5,
        ),
    )

    assert unresolved == []
    assert first_unlock in sessions[0]["activities"]
    assert duplicate_unlock not in sessions[0]["activities"]
    assert sessions[0]["interruptions"][0]["ended_at"] == (
        BASE + timedelta(minutes=2)
    ).isoformat()


def test_strong_work_after_long_system_interruption_starts_new_session():
    first_work = event(
        "file_changed",
        0,
        {**workspace(PULSE), "path": f"{PULSE}/main.py"},
    )
    later_work = event(
        "terminal_finished",
        89,
        {**workspace(PULSE), "command": "git status"},
        6,
    )
    sessions, unresolved = reconstruct(
        first_work,
        event("screen_locked", 23, event_id=2),
        event("screen_unlocked", 24, event_id=3),
        event("screen_unlocked", 25, event_id=4),
        event("system_wake", 80, event_id=5),
        later_work,
        now=BASE + timedelta(minutes=90),
    )

    assert unresolved == []
    assert len(sessions) == 2
    assert sessions[0]["started_at"] == first_work["occurred_at"]
    assert sessions[0]["ended_at"] == first_work["occurred_at"]
    assert sessions[0]["interruptions"] == []
    assert sessions[1]["started_at"] == later_work["occurred_at"]


def test_workspace_change_after_short_interruption_splits_session():
    sessions, _passive = reconstruct(
        event("file_changed", 0, {**workspace(PULSE), "path": f"{PULSE}/a.py"}),
        event("screen_locked", 10, event_id=2),
        event("screen_unlocked", 11, event_id=3),
        event(
            "file_changed",
            12,
            {**workspace(DEVNOTE), "path": f"{DEVNOTE}/app.js"},
            4,
        ),
    )

    assert len(sessions) == 2
    assert sessions[0]["end_reason"] == "workspace_changed"
    assert sessions[1]["project_name"] == "DevNote"


def test_application_context_never_starts_work_session():
    sessions, unresolved = reconstruct(
        event(
            "app_activated",
            0,
            {**workspace(PULSE), "app": "Visual Studio Code"},
        )
    )

    assert sessions == []
    assert len(unresolved) == 1


def test_interruption_threshold_is_configurable(monkeypatch):
    monkeypatch.setenv("PULSE_SESSION_INTERRUPTION_MINUTES", "2.5")

    assert configured_interruption_threshold() == timedelta(minutes=2.5)


def test_direct_historical_git_root_resolves_workspace():
    sessions, _passive = reconstruct(
        event(
            "terminal_finished",
            0,
            {"command": "git status", "git_root": PULSE},
        )
    )

    assert sessions[0]["workspace_root"] == PULSE
    assert sessions[0]["project_name"] == "Pulse_Core"


def test_events_are_ordered_by_instant_not_iso_string():
    first = event(
        "file_changed",
        0,
        {**workspace(PULSE), "path": f"{PULSE}/main.py"},
        event_id=1,
    )
    first["occurred_at"] = "2026-07-23T20:59:00+02:00"
    terminal = event(
        "terminal_finished",
        0,
        {**workspace(PULSE), "command": "git status"},
        event_id=4,
    )
    terminal["occurred_at"] = "2026-07-23T21:11:55+02:00"
    locked = event("screen_locked", 0, event_id=2)
    locked["occurred_at"] = "2026-07-23T19:10:32+00:00"
    unlocked = event("screen_unlocked", 0, event_id=3)
    unlocked["occurred_at"] = "2026-07-23T19:10:51+00:00"

    sessions, _passive = reconstruct(terminal, unlocked, locked, first)

    assert len(sessions) == 1
    assert sessions[0]["started_at"] == "2026-07-23T18:59:00+00:00"
    assert sessions[0]["interruptions"][0]["duration_seconds"] == 19


def test_inactivity_separates_sessions_without_inventing_work_time():
    sessions, _passive = reconstruct(
        event("file_changed", 0, {**workspace(PULSE), "path": f"{PULSE}/a.py"}),
        event(
            "terminal_finished",
            5,
            {**workspace(PULSE), "command": "pytest"},
            2,
        ),
        event(
            "file_changed",
            60,
            {**workspace(PULSE), "path": f"{PULSE}/b.py"},
            3,
        ),
    )

    assert len(sessions) == 2
    assert sessions[0]["ended_at"] == (BASE + timedelta(minutes=5)).isoformat()
    assert sessions[0]["duration_seconds"] == 5 * 60
    assert sessions[0]["end_reason"] == "inactivity"


def test_workspace_change_splits_projects_at_the_new_event():
    sessions, _passive = reconstruct(
        event("file_changed", 0, {**workspace(PULSE), "path": f"{PULSE}/a.py"}),
        event(
            "file_changed",
            15,
            {**workspace(DEVNOTE), "path": f"{DEVNOTE}/app.js"},
            2,
        ),
    )

    assert [item["project_name"] for item in sessions] == [
        "Pulse_Core",
        "DevNote",
    ]
    assert sessions[0]["end_reason"] == "workspace_changed"
    assert sessions[0]["ended_at"] == (BASE + timedelta(minutes=15)).isoformat()


def test_low_confidence_parent_is_promoted_by_nearby_high_context():
    home = str(Path.home())
    pulse = str(Path.home() / "Projets" / "Pulse" / "Pulse_Core")
    sessions, _passive = reconstruct(
        event(
            "terminal_finished",
            0,
            {**low_workspace(home), "command": "cd Projets/Pulse/Pulse_Core"},
        ),
        event(
            "terminal_finished",
            1,
            {**workspace(pulse), "command": "git status"},
            2,
        ),
    )

    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "Pulse_Core"
    assert sessions[0]["workspace_root"] == pulse
    assert sessions[0]["commands_executed"] == 2


def test_isolated_low_confidence_specific_path_remains_identifiable():
    root = "/work/client-alpha"
    sessions, _passive = reconstruct(
        event(
            "terminal_finished",
            0,
            {**low_workspace(root), "command": "make test"},
        )
    )

    assert sessions[0]["project_name"] == "client-alpha"
    assert sessions[0]["workspace_root"] == root


@pytest.mark.parametrize(
    "root",
    [
        str(Path.home()),
        str(Path.home() / "Projets"),
        "/tmp",
        "/",
    ],
)
def test_generic_low_confidence_cwd_is_not_a_project(root):
    sessions, _passive = reconstruct(
        event(
            "terminal_finished",
            0,
            {**low_workspace(root), "command": "pwd"},
        )
    )

    assert sessions[0]["project_name"] is None
    assert sessions[0]["workspace_root"] is None


def test_aggregates_unique_files_apps_and_total_events():
    sessions, _passive = reconstruct(
        event("file_changed", 0, {**workspace(PULSE), "path": f"{PULSE}/a.py"}),
        event("app_activated", 1, {"app": "Terminal"}, 2),
        event("app_activated", 2, {"app": "loginwindow"}, 3),
        event("file_changed", 3, {**workspace(PULSE), "path": f"{PULSE}/a.py"}, 4),
        event("app_activated", 4, {"app": "Visual Studio Code"}, 5),
        event(
            "terminal_finished",
            5,
            {**workspace(PULSE), "command": "pytest"},
            6,
        ),
    )

    session = sessions[0]
    assert session["event_count"] == 6
    assert session["files_changed"] == 1
    assert session["commands_executed"] == 1
    assert session["applications"] == ["Terminal", "Visual Studio Code"]


def test_unresolved_applications_are_promoted_by_later_same_workspace_work():
    middle = event("app_activated", 1, {"app": "Safari"}, 2)
    code = event("app_activated", 2, {"app": "Visual Studio Code"}, 3)
    sessions, unresolved = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        middle,
        code,
        event(
            "terminal_finished",
            3,
            {**workspace(PULSE), "command": "pytest"},
            4,
        ),
    )

    assert middle in sessions[0]["activities"]
    assert code in sessions[0]["activities"]
    assert sessions[0]["applications"] == ["Safari", "Visual Studio Code"]
    assert unresolved == []


def test_trailing_unresolved_application_is_not_beyond_session_end():
    trailing = event("app_activated", 1, {"app": "Safari"}, 2)
    sessions, unresolved = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "pytest"}),
        trailing,
    )

    session = sessions[0]
    assert trailing not in session["activities"]
    assert session["ended_at"] == BASE.isoformat()
    assert session["duration_seconds"] == 0
    assert session["active_duration_seconds"] == 0
    assert all(
        datetime.fromisoformat(session["started_at"])
        <= datetime.fromisoformat(activity["occurred_at"])
        <= datetime.fromisoformat(session["ended_at"])
        for activity in session["activities"]
    )
    assert trailing in unresolved[0]["activities"]


def test_rapid_application_changes_are_user_activity_without_workspace():
    terminal = event("app_activated", 0, {"app": "Terminal"})
    code = event("app_activated", 1, {"app": "Visual Studio Code"}, 2)
    safari = event("app_activated", 2, {"app": "Safari"}, 3)

    sessions, unresolved = reconstruct(terminal, code, safari)

    assert sessions == []
    assert len(unresolved) == 1
    assert unresolved[0]["project_name"] is None
    assert unresolved[0]["workspace_root"] is None
    assert unresolved[0]["applications"] == [
        "Terminal",
        "Visual Studio Code",
        "Safari",
    ]
    assert unresolved[0]["activities"] == [terminal, code, safari]
    assert unresolved[0]["started_at"] == terminal["occurred_at"]
    assert unresolved[0]["ended_at"] == safari["occurred_at"]


def test_unresolved_applications_are_not_assigned_across_workspace_change():
    terminal = event("app_activated", 1, {"app": "Terminal"}, 2)
    code = event("app_activated", 2, {"app": "Visual Studio Code"}, 3)

    sessions, unresolved = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        terminal,
        code,
        event(
            "terminal_finished",
            3,
            {**workspace(DEVNOTE), "command": "npm test"},
            4,
        ),
    )

    assert [session["workspace_root"] for session in sessions] == [
        PULSE,
        DEVNOTE,
    ]
    assert terminal not in sessions[0]["activities"]
    assert code not in sessions[1]["activities"]
    assert unresolved[0]["activities"] == [terminal, code]


@pytest.mark.parametrize(
    ("stop_type", "resume_type"),
    [("screen_locked", "screen_unlocked"), ("system_sleep", "system_wake")],
)
def test_system_transitions_are_interruptions_not_unresolved_activity(
    stop_type,
    resume_type,
):
    sessions, unresolved = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        event(stop_type, 1, event_id=2),
        event(resume_type, 2, event_id=3),
        event(
            "terminal_finished",
            3,
            {**workspace(PULSE), "command": "pytest"},
            4,
        ),
    )

    assert unresolved == []
    assert sessions[0]["interruptions"][0]["type"] == stop_type


def test_interruption_durations_and_activity_bounds_remain_coherent():
    trailing = event("app_activated", 13, {"app": "Safari"}, 5)
    sessions, _passive = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        event("screen_locked", 10, event_id=2),
        event("screen_unlocked", 11, event_id=3),
        event(
            "terminal_finished",
            12,
            {**workspace(PULSE), "command": "git status"},
            4,
        ),
        trailing,
    )

    session = sessions[0]
    assert session["duration_seconds"] == 12 * 60
    assert session["active_duration_seconds"] == 11 * 60
    assert session["interruptions"][0]["duration_seconds"] == 60
    assert trailing not in session["activities"]
    assert all(
        datetime.fromisoformat(session["started_at"])
        <= datetime.fromisoformat(activity["occurred_at"])
        <= datetime.fromisoformat(session["ended_at"])
        for activity in session["activities"]
    )


def test_recent_session_is_open_with_fixed_now():
    sessions, _passive = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "pytest"}),
        now=BASE + timedelta(minutes=10),
    )

    assert sessions[0]["end_reason"] == "open"


def test_legacy_cwd_remains_usable_without_workspace():
    sessions, _passive = reconstruct(
        event(
            "terminal_finished",
            0,
            {"command": "pytest", "cwd": PULSE},
        )
    )

    assert sessions[0]["workspace_root"] == PULSE
    assert sessions[0]["project_name"] == "Pulse_Core"


def test_json_and_markdown_exports_include_session_metadata(tmp_path):
    store = TraceStore(tmp_path / "pulse.sqlite3")
    store.append(
        Activity(
            "file_changed",
            BASE,
            "filesystem",
            f"Modified {PULSE}/main.py",
            {**workspace(PULSE), "path": f"{PULSE}/main.py"},
        )
    )
    store.append(
        Activity(
            "file_changed",
            BASE + timedelta(minutes=5),
            "filesystem",
            f"Modified {PULSE}/routes.py",
            {**workspace(PULSE), "path": f"{PULSE}/routes.py"},
        )
    )
    store.append(
        Activity(
            "screen_locked",
            BASE + timedelta(minutes=20),
            "system",
            "Screen locked",
            {},
        )
    )

    trace = build_daily_trace(store, date(2026, 7, 23), timezone.utc)
    session = trace["work_sessions"][0]
    markdown = render_daily_trace_markdown(trace, archive_mode=True)

    assert trace["passive_sessions"] is trace["unresolved_sessions"]
    assert session["project_name"] == "Pulse_Core"
    assert session["duration_seconds"] == 300
    assert session["interruptions"] == []
    assert session["end_reason"] == "screen_locked"
    assert "- Projet : Pulse\\_Core" in markdown
    assert "- Durée calendaire : 5 min" in markdown
    assert "- Durée active : 5 min" in markdown
    assert "- Fin : écran verrouillé" in markdown


def test_mixed_offsets_use_journal_timezone_in_json_markdown_and_html(tmp_path):
    store = TraceStore(tmp_path / "pulse.sqlite3")
    activities = [
        Activity(
            "terminal_finished",
            datetime.fromisoformat("2026-07-24T11:00:36+02:00"),
            "terminal",
            "Command succeeded: git status",
            {**workspace(PULSE), "command": "git status", "exit_code": 0},
        ),
        Activity(
            "file_changed",
            datetime.fromisoformat("2026-07-24T09:00:55+00:00"),
            "filesystem",
            f"Modified {PULSE}/main.py",
            {**workspace(PULSE), "path": f"{PULSE}/main.py", "event": "modified"},
        ),
        Activity(
            "screen_locked",
            datetime.fromisoformat("2026-07-24T09:01:10+00:00"),
            "system",
            "screen_locked",
            {},
        ),
        Activity(
            "screen_unlocked",
            datetime.fromisoformat("2026-07-24T09:02:15+00:00"),
            "system",
            "screen_unlocked",
            {},
        ),
        Activity(
            "terminal_finished",
            datetime.fromisoformat("2026-07-24T11:03:44+02:00"),
            "terminal",
            "Command succeeded: pytest -q",
            {**workspace(PULSE), "command": "pytest -q", "exit_code": 0},
        ),
    ]
    for activity in activities:
        store.append(activity)

    trace = build_daily_trace(
        store,
        date(2026, 7, 24),
        ZoneInfo("Europe/Paris"),
    )
    session = trace["work_sessions"][0]
    markdown = render_daily_trace_markdown(trace, archive_mode=True)
    html = render_daily_trace_html(trace, archive_mode=True)

    assert [
        activity["occurred_at"]
        for activity in session["activities"]
    ] == [
        "2026-07-24T11:00:36+02:00",
        "2026-07-24T09:00:55+00:00",
        "2026-07-24T09:01:10+00:00",
        "2026-07-24T09:02:15+00:00",
        "2026-07-24T11:03:44+02:00",
    ]
    assert session["started_at"] == "2026-07-24T11:00:36+02:00"
    assert session["ended_at"] == "2026-07-24T11:03:44+02:00"
    assert session["interruptions"][0]["started_at"] == (
        "2026-07-24T11:01:10+02:00"
    )
    assert session["interruptions"][0]["ended_at"] == (
        "2026-07-24T11:02:15+02:00"
    )

    assert "## Session 1 — 11:00–11:03" in markdown
    for expected in (
        "- 11:00 · **terminal\\_finished**",
        "- 11:00 · **file\\_changed**",
        "- 11:01 · **screen\\_locked**",
        "- 11:02 · **screen\\_unlocked**",
        "- 11:03 · **terminal\\_finished**",
    ):
        assert expected in markdown

    assert "<h2>Session 1 · 11:00–11:03" in html
    assert html.count("<time>11:00</time>") == 2
    assert "<time>11:01</time>" in html
    assert "<time>11:02</time>" in html
    assert "<time>11:03</time>" in html


# --- Identité stable des sessions (Core 0.5.0) ------------------------------


def _stored(store: TraceStore, event_type: str, moment: datetime, details: dict):
    summaries = {
        "terminal_finished": f"Command succeeded: {details.get('command', '')}",
        "file_changed": f"Modified {details.get('path', '')}",
        "git_commit": "Commit",
    }
    return store.append(
        Activity(event_type, moment, "test", summaries[event_type], details)
    )


def test_late_event_moves_labels_but_never_the_session_identity(tmp_path):
    # Le bug : l'ordinal work-N est recalculé à chaque reconstruction. Un
    # événement tardif (rejeu d'outbox, agent_session émis après coup) inséré
    # plus tôt dans la journée décale la numérotation, donc un résumé attaché
    # à « work-1 » désignait une autre session le lendemain.
    store = TraceStore(tmp_path / "trace.db")
    day = date(2026, 9, 2)
    zone = timezone.utc
    afternoon = datetime(2026, 9, 2, 14, 0, tzinfo=zone)
    details = {**workspace(PULSE)}
    _stored(store, "terminal_finished", afternoon, {**details, "command": "pytest -q", "exit_code": 0, "cwd": PULSE})
    _stored(store, "file_changed", afternoon + timedelta(minutes=5), {**details, "path": f"{PULSE}/a.py", "event": "modified"})
    now = afternoon + timedelta(hours=3)

    before = build_daily_trace(store, day, zone, now=now)["work_sessions"]
    assert [s["label"] for s in before] == ["work-1"]
    afternoon_id = before[0]["id"]
    assert len(afternoon_id) == 16 and int(afternoon_id, 16) >= 0
    assert before[0]["reconstruction_version"] == 1
    assert len(before[0]["source_event_ids"]) == 2

    # Un événement arrive après coup, daté du matin.
    _stored(store, "git_commit", datetime(2026, 9, 2, 10, 0, tzinfo=zone),
            {**details, "commit_hash": "abc1234def5678", "branch": "main", "message": "fix"})

    after = build_daily_trace(store, day, zone, now=now)["work_sessions"]
    assert [s["label"] for s in after] == ["work-1", "work-2"]
    morning, moved = after
    assert moved["id"] == afternoon_id
    assert moved["label"] == "work-2"
    assert morning["id"] != afternoon_id
    assert morning["activity_kind"] == "isolated"
    assert morning["source_event_ids"] != moved["source_event_ids"]


def test_session_identity_is_order_independent_and_composition_sensitive():
    from daemon_v2.analysis.timeline import session_identity

    a = {"id": 1, "event_id": "evt-a"}
    b = {"id": 2, "event_id": "evt-b"}
    c = {"id": 3, "event_id": "evt-c"}

    identity_ab, sources_ab = session_identity([a, b])
    identity_ba, sources_ba = session_identity([b, a])
    identity_abc, _ = session_identity([a, b, c])

    assert identity_ab == identity_ba
    assert sources_ab == sources_ba == ["evt-a", "evt-b"]
    assert identity_abc != identity_ab
    assert len(identity_ab) == 16
    # Sans event_id (fixtures, lignes historiques) : la clé de ligne sert de repli.
    fallback, sources = session_identity([{"id": 7}, {"id": 5}])
    assert sources == ["id:5", "id:7"] and len(fallback) == 16


def test_reconstructed_sessions_carry_identity_and_label():
    sessions, _unresolved = reconstruct(
        event("terminal_finished", 0, {**workspace(PULSE), "command": "make"}),
        event("file_changed", 5, {**workspace(PULSE), "path": f"{PULSE}/a.py"}, 2),
    )

    assert sessions[0]["label"] == "work-1"
    assert sessions[0]["source_event_ids"] == ["id:1", "id:2"]
    assert sessions[0]["id"] == session_identity_of(sessions[0])


def session_identity_of(session: dict) -> str:
    from daemon_v2.analysis.timeline import session_identity

    return session_identity(session["activities"])[0]


# --- agent_session hors identité des sessions (décision 2026-09-03) --------


def _agent_session_row(store: TraceStore, moment: datetime, root: str) -> None:
    store.append(
        Activity(
            "agent_session",
            moment,
            "agent",
            "Agent session (claude-code): Implémente le Context API",
            {
                "source_tool": "claude-code",
                "session_id": "session-1",
                "transcript_path": "/transcripts/session.jsonl",
                "summary_version": 2,
                "started_at": (moment - timedelta(minutes=1)).isoformat(),
                "ended_at": (moment + timedelta(minutes=1)).isoformat(),
                "first_prompt": "Implémente le Context API",
                **workspace(root),
            },
        )
    )


def test_late_agent_session_inside_a_session_never_moves_its_identity(tmp_path):
    # Cas relevé par l'audit externe : un agent_session est émis après coup
    # (hook SessionEnd, passage horaire launchd) avec un occurred_at qui tombe
    # au milieu d'une session déjà reconstruite — et peut-être déjà résumée.
    # Il ne doit ni rejoindre source_event_ids ni déplacer les bornes.
    store = TraceStore(tmp_path / "trace.db")
    day = date(2026, 9, 2)
    zone = timezone.utc
    afternoon = datetime(2026, 9, 2, 14, 0, tzinfo=zone)
    details = {**workspace(PULSE)}
    _stored(store, "terminal_finished", afternoon, {**details, "command": "pytest -q", "exit_code": 0, "cwd": PULSE})
    _stored(store, "file_changed", afternoon + timedelta(minutes=5), {**details, "path": f"{PULSE}/a.py", "event": "modified"})
    now = afternoon + timedelta(hours=3)
    identity_keys = ("id", "label", "source_event_ids", "started_at", "ended_at", "activity_count")

    before = build_daily_trace(store, day, zone, now=now)
    assert len(before["work_sessions"]) == 1
    reference = {key: before["work_sessions"][0][key] for key in identity_keys}
    assert len(reference["source_event_ids"]) == 2

    # L'agent_session arrive après coup, daté du milieu de la session.
    _agent_session_row(store, afternoon + timedelta(minutes=2), PULSE)

    after = build_daily_trace(store, day, zone, now=now)
    assert len(after["work_sessions"]) == 1
    assert {key: after["work_sessions"][0][key] for key in identity_keys} == reference
    assert all(
        activity["type"] != "agent_session"
        for activity in after["work_sessions"][0]["activities"]
    )
    # Ni session, ni activité non attribuée : il n'est visible que par
    # /context.last_agent_session, sans fenêtre.
    assert after["unresolved_sessions"] == []


def test_agent_session_no_longer_bridges_two_clusters_within_the_gap():
    # Effet de bord accepté (décision 2026-09-03) : comme signal fort, un
    # agent_session à moins de 30 min de deux grappes de travail les reliait
    # en une seule session. Il ne fusionne plus rien : deux sessions.
    details = {**workspace(PULSE)}
    sessions, unresolved = reconstruct(
        event("terminal_finished", 0, {**details, "command": "make"}, 1),
        event("file_changed", 5, {**details, "path": f"{PULSE}/a.py"}, 2),
        event("agent_session", 25, {**details, "source_tool": "claude-code"}, 3),
        event("terminal_finished", 45, {**details, "command": "make test"}, 4),
        event("file_changed", 50, {**details, "path": f"{PULSE}/b.py"}, 5),
        now=BASE + timedelta(minutes=60),
    )

    assert [session["source_event_ids"] for session in sessions] == [
        ["id:1", "id:2"],
        ["id:4", "id:5"],
    ]
    assert sessions[0]["end_reason"] == "inactivity"
    assert unresolved == []


def test_agent_session_alone_starts_nothing():
    sessions, unresolved = reconstruct(
        event("agent_session", 0, {**workspace(PULSE), "source_tool": "codex"}),
    )

    assert sessions == []
    assert unresolved == []


def test_agent_session_renders_apart_without_joining_any_work_session(tmp_path):
    # Affichage seulement : listé sous « Sessions d’agent » avec l'heure et
    # le résumé stocké, alors qu'il ne rejoint aucune session de travail et
    # que « Activité non attribuée » reste vide.
    store = TraceStore(tmp_path / "trace.db")
    day = date(2026, 9, 2)
    zone = timezone.utc
    moment = datetime(2026, 9, 2, 14, 2, tzinfo=zone)
    _agent_session_row(store, moment, PULSE)

    trace = build_daily_trace(store, day, zone, now=moment + timedelta(hours=3))
    markdown = render_daily_trace_markdown(trace, archive_mode=True)
    html = render_daily_trace_html(trace, archive_mode=True)

    assert trace["work_sessions"] == [] and trace["unresolved_sessions"] == []
    assert (
        "- 14:01–14:03 · Agent session (claude-code): "
        "Implémente le Context API (Pulse\\_Core)"
    ) in markdown
    assert "## Activité non attribuée" not in markdown
    assert (
        '<span class="time">14:01–14:03</span> '
        "Agent session (claude-code): Implémente le Context API (Pulse_Core)"
    ) in html
    assert '<a class="nav-main" href="#sessions-agent">Sessions d’agent</a>' in html


def test_agent_session_next_to_a_work_session_is_listed_apart_from_it(tmp_path):
    store = TraceStore(tmp_path / "trace.db")
    day = date(2026, 9, 2)
    zone = timezone.utc
    afternoon = datetime(2026, 9, 2, 14, 0, tzinfo=zone)
    details = {**workspace(PULSE)}
    _stored(store, "terminal_finished", afternoon, {**details, "command": "pytest -q", "exit_code": 0, "cwd": PULSE})
    _stored(store, "file_changed", afternoon + timedelta(minutes=5), {**details, "path": f"{PULSE}/a.py", "event": "modified"})
    _agent_session_row(store, afternoon + timedelta(minutes=2), PULSE)

    trace = build_daily_trace(store, day, zone, now=afternoon + timedelta(hours=3))
    markdown = render_daily_trace_markdown(trace, archive_mode=True)

    assert len(trace["work_sessions"]) == 1
    assert len(trace["work_sessions"][0]["source_event_ids"]) == 2
    session_block = markdown.split("## Sessions d’agent")[0]
    assert "Agent session (claude-code)" not in session_block
    assert "- 14:01–14:03 · Agent session (claude-code)" in markdown
