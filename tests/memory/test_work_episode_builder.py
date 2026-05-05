from datetime import datetime, timedelta

from daemon.memory.work_episode_builder import build_work_blocks, build_work_episodes


BASE = datetime(2026, 5, 5, 9, 0, 0)
PROJECT_FILE = "/Users/yugz/Projets/Pulse/Pulse/daemon/memory/session.py"


def event(event_type, minute, payload=None):
    return {
        "type": event_type,
        "payload": payload or {},
        "timestamp": BASE + timedelta(minutes=minute),
    }


def strong_file(minute=0):
    return event(
        "file_modified",
        minute,
        {
            "path": PROJECT_FILE,
            "is_meaningful": True,
        },
    )


def strong_path(path, minute=0):
    return event(
        "file_modified",
        minute,
        {
            "path": f"/Users/yugz/Projets/Pulse/Pulse/{path}",
            "is_meaningful": True,
        },
    )


def weak_app(app_name, minute):
    return event(
        "app_activated",
        minute,
        {
            "app_name": app_name,
        },
    )


def git_command(command, minute=0):
    return event(
        "terminal_command_finished",
        minute,
        {
            "terminal_command": command,
            "terminal_command_base": "git",
            "terminal_project": "Pulse",
        },
    )


def test_user_presence_alone_creates_no_work_episode():
    events = [event("user_presence", 0, {"active": True})]

    assert build_work_blocks(events) == []
    assert build_work_episodes(events) == []


def test_weak_ai_and_dev_apps_alone_create_no_work_episode():
    events = [
        weak_app("ChatGPT", 0),
        weak_app("Cursor", 2),
    ]

    assert build_work_blocks(events) == []
    assert build_work_episodes(events) == []


def test_file_event_strong_creates_short_work_episode():
    episodes = build_work_episodes([strong_file()])

    assert len(episodes) == 1
    assert episodes[0].duration_min == 1
    assert episodes[0].evidence_count == 1
    assert episodes[0].probable_task == "coding"


def test_strong_plus_recent_weak_stays_in_same_work_episode():
    events = [
        strong_file(0),
        weak_app("ChatGPT", 5),
    ]

    blocks = build_work_blocks(events)
    episodes = build_work_episodes(events)

    assert len(blocks) == 1
    assert blocks[0].event_count == 2
    assert blocks[0].duration_min == 5
    assert len(episodes) == 1
    assert episodes[0].work_block_ids == (blocks[0].id,)
    assert episodes[0].evidence_count == 2


def test_git_status_alone_creates_no_work_episode():
    assert build_work_episodes([git_command("git status")]) == []


def test_non_work_title_cuts_episode_and_prevents_following_weak_bridge():
    events = [
        strong_file(0),
        event(
            "window_title_poll",
            2,
            {
                "app_name": "Chrome",
                "window_title": "Build log - YouTube",
            },
        ),
        weak_app("ChatGPT", 3),
    ]

    blocks = build_work_blocks(events)
    episodes = build_work_episodes(events)

    assert len(blocks) == 1
    assert blocks[0].event_count == 1
    assert blocks[0].duration_min == 1
    assert len(episodes) == 1
    assert episodes[0].evidence_count == 1
    assert episodes[0].ended_at == BASE.isoformat()


def test_two_strong_events_separated_by_long_gap_create_two_episodes():
    events = [
        strong_file(0),
        strong_file(60),
    ]

    episodes = build_work_episodes(events)

    assert len(episodes) == 2
    assert [episode.duration_min for episode in episodes] == [1, 1]


def test_screen_locked_between_strong_events_creates_two_episodes():
    events = [
        strong_file(0),
        event("screen_locked", 5),
        strong_file(6),
    ]

    blocks = build_work_blocks(events)
    episodes = build_work_episodes(events)

    assert len(blocks) == 2
    assert len(episodes) == 2
    assert episodes[0].boundary_reason == "screen_locked"


def test_scope_change_exposes_scope_debug_fields():
    events = [
        strong_path("docs/FR/work-episodes-model.md", 0),
        strong_path("daemon/memory/work_episode_builder.py", 18),
    ]

    episodes = build_work_episodes(events)

    assert len(episodes) == 2
    assert episodes[0].boundary_reason == "scope_change"
    assert episodes[0].dominant_scope == "docs"
    assert episodes[0].previous_scope is None
    assert episodes[0].next_scope == "work_episode"
    assert episodes[0].boundary_event_type == "file_modified"
    assert episodes[0].boundary_event_at == (BASE + timedelta(minutes=18)).isoformat()
    assert episodes[0].debug_reason == "split after 18 min gap and scope change docs -> work_episode"
    assert episodes[1].previous_scope == "docs"
    assert episodes[1].dominant_scope == "work_episode"


def test_screen_locked_boundary_exposes_boundary_event_debug_fields():
    events = [
        strong_file(0),
        event("screen_locked", 5),
        strong_file(6),
    ]

    episodes = build_work_episodes(events)

    assert episodes[0].boundary_reason == "screen_locked"
    assert episodes[0].boundary_event_type == "screen_locked"
    assert episodes[0].boundary_event_at == (BASE + timedelta(minutes=5)).isoformat()
    assert episodes[0].debug_reason == "split on boundary event screen_locked"


def test_work_episode_debug_counts_strong_and_weak_events():
    events = [
        strong_file(0),
        weak_app("ChatGPT", 4),
        strong_path("daemon/memory/current_context_builder.py", 8),
    ]

    episodes = build_work_episodes(events)

    assert len(episodes) == 1
    assert episodes[0].strong_event_count == 2
    assert episodes[0].weak_event_count == 1
    assert episodes[0].evidence_count == 3


def test_end_of_events_has_stable_debug_reason():
    episodes = build_work_episodes([strong_file(0)])

    assert len(episodes) == 1
    assert episodes[0].boundary_reason == "end_of_events"
    assert episodes[0].boundary_event_type is None
    assert episodes[0].boundary_event_at is None
    assert episodes[0].debug_reason == "episode open until end of observed events"


def test_docs_then_daemon_python_after_notable_gap_create_two_episodes():
    events = [
        strong_path("docs/FR/work-episodes-model.md", 0),
        strong_path("docs/EN/work-episodes-model.md", 4),
        strong_path("daemon/memory/session.py", 18),
    ]

    episodes = build_work_episodes(events)

    assert len(episodes) == 2
    assert episodes[0].probable_task == "writing"
    assert episodes[1].probable_task == "coding"


def test_swift_then_docs_after_notable_gap_create_two_episodes():
    events = [
        strong_path("App/App/DaemonBridgeModels.swift", 0),
        strong_path("AppTests/PulseViewModelInteractionsTests.swift", 4),
        strong_path("docs/FR/work-episodes-model.md", 20),
    ]

    episodes = build_work_episodes(events)

    assert len(episodes) == 2
    assert episodes[0].probable_task == "coding"
    assert episodes[1].probable_task == "writing"


def test_work_episode_builder_and_its_tests_stay_in_same_episode_when_close():
    events = [
        strong_path("daemon/memory/work_episode_builder.py", 0),
        strong_path("tests/memory/test_work_episode_builder.py", 8),
    ]

    episodes = build_work_episodes(events)

    assert len(episodes) == 1
    assert episodes[0].evidence_count == 2


def test_extractor_and_its_tests_stay_in_same_episode_when_close():
    events = [
        strong_path("daemon/memory/extractor.py", 0),
        strong_path("tests/memory/test_extractor.py", 8),
    ]

    episodes = build_work_episodes(events)

    assert len(episodes) == 1
    assert episodes[0].evidence_count == 2


def test_weak_only_between_different_strong_scopes_does_not_force_fusion_after_notable_gap():
    events = [
        strong_path("docs/FR/work-episodes-model.md", 0),
        weak_app("ChatGPT", 5),
        weak_app("Codex", 10),
        strong_path("daemon/memory/extractor.py", 18),
    ]

    episodes = build_work_episodes(events)

    assert len(episodes) == 2
    assert [episode.probable_task for episode in episodes] == ["writing", "coding"]


def test_same_scope_with_weak_support_and_short_gap_stays_one_episode():
    events = [
        strong_path("daemon/memory/session.py", 0),
        weak_app("ChatGPT", 5),
        strong_path("daemon/memory/current_context_builder.py", 9),
    ]

    episodes = build_work_episodes(events)

    assert len(episodes) == 1
    assert episodes[0].evidence_count == 3
