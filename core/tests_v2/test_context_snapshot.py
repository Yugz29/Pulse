import json
from datetime import datetime, timedelta, timezone

import pytest

from daemon_v2.context_snapshot import build_context_snapshot
from daemon_v2.models import Activity
from daemon_v2.trace_store import TraceStore


REFERENCE = datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)
PULSE = "/workspace/Pulse"
DEVNOTE = "/workspace/DevNote"


def at(minutes: int) -> datetime:
    """Instant relative to REFERENCE (negative = in the past)."""
    return REFERENCE + timedelta(minutes=minutes)


def workspace_details(root: str) -> dict:
    return {
        "workspace": {
            "project_name": root.rsplit("/", 1)[-1],
            "workspace_root": root,
            "git_root": root,
            "resolution_method": "git",
            "resolution_confidence": "high",
        }
    }


def terminal(
    minutes: int,
    command: str,
    *,
    exit_code: int = 0,
    root: str = PULSE,
    git: dict | None = None,
) -> Activity:
    details = {
        "command": command,
        "exit_code": exit_code,
        "cwd": root,
        **workspace_details(root),
    }
    if git is not None:
        details["git"] = git
    return Activity(
        "terminal_finished",
        at(minutes),
        "terminal",
        f"Command {'succeeded' if exit_code == 0 else f'failed ({exit_code})'}: {command}",
        details,
    )


def file_changed(
    minutes: int,
    path: str,
    *,
    event: str = "modified",
    root: str = PULSE,
) -> Activity:
    return Activity(
        "file_changed",
        at(minutes),
        "filesystem",
        f"{event.capitalize()} {root}/{path}",
        {"path": f"{root}/{path}", "event": event, "workspace": root},
    )


def commit(
    minutes: int,
    commit_hash: str,
    message: str,
    *,
    root: str = PULSE,
    branch: str = "main",
) -> Activity:
    return Activity(
        "git_commit",
        at(minutes),
        "git",
        f"Commit {commit_hash[:7]} on {branch}: {message.splitlines()[0]}",
        {
            "commit_hash": commit_hash,
            "repository": root.rsplit("/", 1)[-1],
            "git_root": root,
            "branch": branch,
            "message": message,
        },
    )


def app(minutes: int, name: str) -> Activity:
    return Activity(
        "app_activated", at(minutes), "application", f"Activated {name}", {"app": name}
    )


def agent_session(
    minutes: int,
    *,
    ended_minutes: int,
    root: str = PULSE,
    first_prompt: str = "Implémente le Context API",
) -> Activity:
    return Activity(
        "agent_session",
        at(minutes),
        "agent",
        f"Agent session (claude-code): {first_prompt}",
        {
            "source_tool": "claude-code",
            "session_id": f"session-{minutes}",
            "transcript_path": "/transcripts/session.jsonl",
            "summary_version": 2,
            "started_at": at(minutes).isoformat(),
            "ended_at": at(ended_minutes).isoformat(),
            "first_prompt": first_prompt,
            "workspace": root,
        },
    )


def make_store(tmp_path, *activities: Activity) -> TraceStore:
    store = TraceStore(tmp_path / "trace.db")
    for activity in activities:
        store.append(activity)
    return store


def snapshot(store, *, reference_at=REFERENCE, window_minutes=120) -> dict:
    return build_context_snapshot(
        store,
        reference_at=reference_at,
        window_minutes=window_minutes,
        local_timezone=timezone.utc,
    )


def working_session(*, offset: int = 0) -> list[Activity]:
    """A realistic open session ending a few minutes before REFERENCE."""
    return [
        app(-60 + offset, "Terminal"),
        terminal(-58 + offset, "pytest -q", git={
            "branch": "main", "dirty": True, "git_root": PULSE,
            "head": "abc1234", "repository": "Pulse",
            "staged": 1, "unstaged": 0, "untracked": 0,
        }),
        file_changed(-50 + offset, "docs/VISION.md", event="created"),
        file_changed(-49 + offset, "core/README.md"),
        file_changed(-48 + offset, ".gitignore"),
        app(-47 + offset, "Code"),
        app(-46 + offset, "Terminal"),
        terminal(-40 + offset, "make test", exit_code=1),
        commit(-30 + offset, "6264d1a5058b4fa3", "chore: restructuration\n\ncorps"),
        terminal(-20 + offset, "git push origin main --tags", exit_code=1),
        terminal(-10 + offset, "make dev", exit_code=130),
        file_changed(-5 + offset, "core/README.md"),
    ]


# --- Déterminisme -----------------------------------------------------------


def test_two_identical_calls_only_differ_by_generated_at(tmp_path):
    store = make_store(tmp_path, *working_session())

    first = snapshot(store)
    second = snapshot(store)

    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_rows_dated_after_the_reference_instant_do_not_change_the_answer(tmp_path):
    store = make_store(tmp_path, *working_session())
    before = snapshot(store)
    before.pop("generated_at")

    store.append(commit(+10, "ffffffff00000000", "plus tard"))
    store.append(agent_session(+20, ended_minutes=+30))
    after = snapshot(store)
    after.pop("generated_at")

    assert after == before


# --- Cas nominaux -----------------------------------------------------------


def test_open_session_fills_every_block_with_bounded_facts(tmp_path):
    store = make_store(tmp_path, *working_session())

    result = snapshot(store)

    assert result["schema_version"] == 1
    assert result["reference_at"] == "2026-09-02T14:00:00+00:00"
    assert result["window_minutes"] == 120
    assert result["timezone"] == "UTC"

    assert result["workspace"] == {
        "path": PULSE,
        "project": "Pulse",
        "resolution": "session",
        "git": {
            "branch": "main",
            "dirty": True,
            "last_commit": {
                "hash": "6264d1a",
                "message": "chore: restructuration",
                "occurred_at": "2026-09-02T13:30:00+00:00",
            },
        },
    }

    session = result["current_session"]
    assert session["is_open"] is True
    assert session["started_at"] == "2026-09-02T13:02:00+00:00"
    assert session["last_activity_at"] == "2026-09-02T13:55:00+00:00"
    assert session["duration_minutes"] == 53
    assert session["projects"] == ["Pulse"]
    # The Terminal activation at -60 precedes the first work signal: it is
    # unresolved activity, not part of the session.
    assert session["apps"] == [
        {"name": "Code", "activations": 1},
        {"name": "Terminal", "activations": 1},
    ]
    assert session["files"] == {
        "created": ["docs/VISION.md"],
        "modified": ["core/README.md", ".gitignore"],
        "deleted": [],
        "truncated": False,
    }
    assert session["git"] == {
        "commits": [{"hash": "6264d1a", "message": "chore: restructuration"}],
        "push_observed": True,
    }
    assert session["terminal"] == {
        "tests_passed": ["pytest -q"],
        "tests_failed": ["make test"],
        "errors": ["make test", "git push origin main --tags"],
        "truncated": False,
    }
    assert session["signals"] == [
        "app_activated",
        "file_changed",
        "git_commit",
        "terminal_finished",
    ]
    assert result["recent_sessions"] == []
    assert result["isolated_signals"] == []
    assert result["last_agent_session"] is None


def test_window_keeps_the_closed_session_out_of_the_current_one(tmp_path):
    earlier = [
        terminal(-110, "pytest -q"),
        file_changed(-105, "a.py"),
        file_changed(-100, "b.py"),
        commit(-95, "1111111aaaaaaaa", "feat: a"),
        terminal(-90, "make test", exit_code=1),
    ]
    store = make_store(tmp_path, *earlier, *working_session())

    result = snapshot(store)

    assert result["current_session"]["started_at"] == "2026-09-02T13:02:00+00:00"
    assert len(result["recent_sessions"]) == 1
    recent = result["recent_sessions"][0]
    assert recent["started_at"] == "2026-09-02T12:10:00+00:00"
    assert recent["ended_at"] == "2026-09-02T12:30:00+00:00"
    assert recent["duration_minutes"] == 20
    assert recent["projects"] == ["Pulse"]
    assert recent["headline"] == {
        "commits": 1,
        "files_changed": 2,
        "tests_failed": 1,
        "errors": 1,
    }


def test_recent_sessions_are_bounded_to_three_most_recent_first(tmp_path):
    activities = []
    for index, start in enumerate((-1000, -800, -600, -400)):
        activities.append(terminal(start, f"pytest -q tests/{index}"))
        activities.append(file_changed(start + 5, f"file{index}.py"))
    store = make_store(tmp_path, *activities)

    result = snapshot(store, window_minutes=1440)

    assert result["current_session"] is None
    ends = [session["ended_at"] for session in result["recent_sessions"]]
    assert ends == [
        "2026-09-02T07:25:00+00:00",
        "2026-09-02T04:05:00+00:00",
        "2026-09-02T00:45:00+00:00",
    ]


# --- Cas limites ------------------------------------------------------------


def test_empty_store_returns_nulls_and_empty_lists(tmp_path):
    store = make_store(tmp_path)

    result = snapshot(store)

    assert result["workspace"] is None
    assert result["current_session"] is None
    assert result["recent_sessions"] == []
    assert result["isolated_signals"] == []
    assert result["last_agent_session"] is None


def test_activity_older_than_the_gap_means_no_current_session(tmp_path):
    store = make_store(
        tmp_path,
        terminal(-50, "pytest -q"),
        file_changed(-45, "a.py"),
        file_changed(-40, "b.py"),
    )

    result = snapshot(store)

    assert result["current_session"] is None
    assert result["workspace"] == {
        "path": PULSE,
        "project": "Pulse",
        "resolution": "last_observed",
        "git": None,
    }
    assert [s["ended_at"] for s in result["recent_sessions"]] == [
        "2026-09-02T13:20:00+00:00"
    ]


def test_old_agent_session_survives_the_window_alone(tmp_path):
    store = make_store(
        tmp_path,
        terminal(-3000, "pytest -q"),
        file_changed(-2995, "a.py"),
        agent_session(-2990, ended_minutes=-2900),
    )

    result = snapshot(store)

    assert result["workspace"] is None
    assert result["current_session"] is None
    assert result["recent_sessions"] == []
    assert result["isolated_signals"] == []
    assert result["last_agent_session"] == {
        "agent": "claude-code",
        "started_at": "2026-08-31T12:10:00+00:00",
        "ended_at": "2026-08-31T13:40:00+00:00",
        "workspace": PULSE,
        "summary": "Agent session (claude-code): Implémente le Context API",
        "age_minutes": 2900,
    }


def test_session_without_resolved_workspace_is_still_returned(tmp_path):
    store = make_store(
        tmp_path,
        Activity(
            "terminal_finished", at(-20), "terminal", "Command succeeded: ls",
            {"command": "ls", "exit_code": 0, "cwd": "/tmp"},
        ),
        Activity(
            "file_changed", at(-15), "filesystem", "Modified /tmp/notes.txt",
            {"path": "/tmp/notes.txt", "event": "modified"},
        ),
        app(-10, "Notes"),
    )

    result = snapshot(store)

    assert result["workspace"] is None
    session = result["current_session"]
    assert session is not None
    assert session["projects"] == []
    assert session["files"]["modified"] == ["/tmp/notes.txt"]


def test_two_workspaces_in_one_session_expose_both_and_pick_the_dominant(tmp_path):
    # Low-confidence DevNote signals inside a high-confidence Pulse session
    # stay in the same session (resolver rule), so both projects are seen.
    low_devnote = {
        "workspace": {
            "project_name": "DevNote",
            "workspace_root": DEVNOTE,
            "git_root": None,
            "resolution_method": "cwd",
            "resolution_confidence": "low",
        }
    }
    store = make_store(
        tmp_path,
        terminal(-30, "pytest -q"),
        file_changed(-28, "a.py"),
        Activity(
            "terminal_finished", at(-25), "terminal", "Command succeeded: cat notes.md",
            {"command": "cat notes.md", "exit_code": 0, "cwd": DEVNOTE, **low_devnote},
        ),
        file_changed(-20, "b.py"),
    )

    result = snapshot(store)

    assert result["current_session"]["projects"] == ["Pulse", "DevNote"]
    assert result["workspace"]["path"] == PULSE
    assert result["workspace"]["resolution"] == "session"


def test_isolated_strong_signal_goes_to_isolated_signals_not_current_session(tmp_path):
    store = make_store(
        tmp_path,
        commit(-90, "abcdef0123456789", "fix: seul", root=DEVNOTE),
        *working_session(),
    )

    result = snapshot(store)

    assert result["isolated_signals"] == [
        {
            "type": "git_commit",
            "occurred_at": "2026-09-02T12:30:00+00:00",
            "summary": "Commit abcdef0 on main: fix: seul",
        }
    ]
    assert result["current_session"]["started_at"] == "2026-09-02T13:02:00+00:00"
    assert all(
        s["started_at"] != "2026-09-02T12:30:00+00:00"
        for s in result["recent_sessions"]
    )


def test_interrupted_command_is_not_an_error(tmp_path):
    store = make_store(
        tmp_path,
        terminal(-20, "pytest -q"),
        file_changed(-15, "a.py"),
        terminal(-10, "make dev", exit_code=130),
        terminal(-5, "python broken.py", exit_code=2),
    )

    terminal_block = snapshot(store)["current_session"]["terminal"]

    assert terminal_block["errors"] == ["python broken.py"]


def test_pasted_prompt_never_appears_in_the_answer(tmp_path):
    prompt = (
        "Pulse — micro-jalon\n"
        "Contexte :\nLes routes existent.\n"
        "Objectif :\nVérifier le rendu.\n"
        "À faire :\nConserver les événements.\n"
        "Validation attendue :\nLes tests passent."
    )
    store = make_store(
        tmp_path,
        terminal(-20, "pytest -q"),
        file_changed(-15, "a.py"),
        terminal(-10, prompt, exit_code=127),
        terminal(-8, "[prompt collé : 9 lignes, 180 caractères]", exit_code=127),
        # A lone pasted prompt far from any session would be an isolated
        # strong signal: it must not surface there either.
        terminal(-110, prompt, exit_code=127),
    )

    rendered = json.dumps(snapshot(store), ensure_ascii=False)

    assert "Contexte :" not in rendered
    assert "micro-jalon" not in rendered
    assert "prompt collé" not in rendered


def test_files_are_bounded_to_twenty_per_category(tmp_path):
    activities = [terminal(-40, "pytest -q")]
    activities += [
        file_changed(-30 + index // 10, f"src/module_{index:02d}.py")
        for index in range(25)
    ]
    store = make_store(tmp_path, *activities)

    files = snapshot(store)["current_session"]["files"]

    assert len(files["modified"]) == 20
    assert files["modified"][0] == "src/module_00.py"
    assert files["truncated"] is True
    assert files["created"] == [] and files["deleted"] == []


def test_apps_are_ranked_by_activations_then_name_and_bounded_to_five(tmp_path):
    activities = [terminal(-30, "pytest -q"), file_changed(-29, "a.py")]
    for minute, name in enumerate(
        ["Zed", "Code", "Terminal", "Code", "Safari", "Mail", "Notes", "Terminal"]
    ):
        activities.append(app(-28 + minute, name))
    activities.append(file_changed(-10, "b.py"))  # confirms the activations
    store = make_store(tmp_path, *activities)

    apps = snapshot(store)["current_session"]["apps"]

    assert apps == [
        {"name": "Code", "activations": 2},
        {"name": "Terminal", "activations": 2},
        {"name": "Mail", "activations": 1},
        {"name": "Notes", "activations": 1},
        {"name": "Safari", "activations": 1},
    ]


def test_invalid_inputs_are_rejected(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(ValueError):
        build_context_snapshot(store, reference_at=REFERENCE, window_minutes=4)
    with pytest.raises(ValueError):
        build_context_snapshot(store, reference_at=REFERENCE, window_minutes=1441)
    with pytest.raises(ValueError):
        build_context_snapshot(
            store, reference_at=REFERENCE.replace(tzinfo=None)
        )
