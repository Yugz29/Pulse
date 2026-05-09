from datetime import datetime, timedelta

from daemon.core.event_bus import Event, EventBus
from daemon.core.observation_qualification import qualify_observation
from daemon.core.signal_scorer import SignalScorer
from daemon.memory.work_episode_builder import build_work_episodes


BASE = datetime(2026, 5, 9, 10, 0, 0)
PROJECT_FILE = "/Users/yugz/Projets/Pulse/Pulse/daemon/core/signal_scorer.py"


def _event(event_type: str, payload: dict, minute: int = 0) -> Event:
    return Event(event_type, payload, timestamp=BASE + timedelta(minutes=minute))


def _bus_with(*events: Event) -> EventBus:
    bus = EventBus(max_size=50)
    for event in events:
        bus._queue.append(event)
    return bus


def _episode_events(*events: Event) -> list[dict]:
    return [
        {
            "type": event.type,
            "payload": event.payload,
            "timestamp": event.timestamp,
        }
        for event in events
    ]


def test_meaningful_user_file_qualification_matches_scorer_and_episodes():
    payload = {"path": PROJECT_FILE, "_actor": "user"}
    qualification = qualify_observation("file_modified", payload)
    event = _event("file_modified", payload)

    signals = SignalScorer(_bus_with(event)).compute(observed_now=BASE)
    episodes = build_work_episodes(_episode_events(event))

    assert qualification.can_anchor_project is True
    assert qualification.can_start_work_block is True
    assert signals.active_project == "Pulse"
    assert signals.active_file == PROJECT_FILE
    assert len(episodes) == 1
    assert episodes[0].probable_task == "coding"


def test_tool_assisted_file_qualification_matches_scorer_and_assisted_episode():
    payload = {
        "path": PROJECT_FILE,
        "_actor": "tool_assisted",
        "_automation_score": 0.8,
    }
    qualification = qualify_observation("file_modified", payload)
    event = _event("file_modified", payload)

    signals = SignalScorer(_bus_with(event)).compute(observed_now=BASE)
    episodes = build_work_episodes(_episode_events(event))

    assert qualification.actor == "tool_assisted"
    assert qualification.can_anchor_project is True
    assert qualification.can_start_work_block is True
    assert signals.active_project == "Pulse"
    assert signals.active_file == PROJECT_FILE
    assert signals.edited_file_count_10m == 0
    assert len(episodes) == 1
    assert "tool_assisted" in episodes[0].uncertainty_flags


def test_system_cache_file_qualification_matches_no_anchor_and_no_episode():
    payload = {
        "path": "/Users/yugz/.cache/huggingface/model/cache.json",
        "_actor": "system",
    }
    qualification = qualify_observation("file_modified", payload)
    event = _event("file_modified", payload)

    signals = SignalScorer(_bus_with(event)).compute(observed_now=BASE)
    episodes = build_work_episodes(_episode_events(event))

    assert qualification.evidence_strength == "noise"
    assert qualification.can_anchor_project is False
    assert qualification.can_start_work_block is False
    assert signals.active_project is None
    assert signals.active_file is None
    assert episodes == []


def test_user_presence_qualification_matches_activity_support_without_episode():
    payload = {"presence_state": "idle", "idle_seconds": 420, "source": "iokit"}
    qualification = qualify_observation("user_presence", payload)
    event = _event("user_presence", payload)

    signals = SignalScorer(_bus_with(event)).compute(observed_now=BASE)
    episodes = build_work_episodes(_episode_events(event))

    assert qualification.evidence_strength == "contextual"
    assert qualification.can_influence_activity is True
    assert qualification.can_start_work_block is False
    assert signals.user_presence_state == "idle"
    assert signals.user_idle_seconds == 420
    assert signals.focus_level == "idle"
    assert signals.activity_level == "idle"
    assert episodes == []


def test_window_title_qualification_matches_context_without_project_or_episode():
    payload = {
        "app_name": "Code",
        "window_title": "signal_scorer.py - Pulse - Visual Studio Code",
    }
    qualification = qualify_observation("window_title_poll", payload)
    event = _event("window_title_poll", payload)

    signals = SignalScorer(_bus_with(event)).compute(observed_now=BASE)
    episodes = build_work_episodes(_episode_events(event))

    assert qualification.evidence_strength == "contextual"
    assert qualification.can_start_work_block is False
    assert qualification.can_anchor_project is False
    assert signals.active_project is None
    assert episodes == []


def test_terminal_testing_qualification_matches_activity_and_current_episode_behavior():
    payload = {
        "terminal_command": "pytest tests/core/test_signal_scorer.py",
        "terminal_command_base": "pytest",
        "terminal_action_category": "testing",
        "terminal_project": "Pulse",
        "terminal_success": False,
        "test_result": {
            "framework": "pytest",
            "failed_count": 2,
            "passed_count": 64,
        },
    }
    qualification = qualify_observation("terminal_command_finished", payload)
    event = _event("terminal_command_finished", payload)

    signals = SignalScorer(_bus_with(event)).compute(observed_now=BASE)
    episodes = build_work_episodes(_episode_events(event))

    assert qualification.evidence_strength == "strong"
    assert qualification.can_influence_activity is True
    assert signals.active_project == "Pulse"
    assert signals.activity_level == "executing"
    assert signals.terminal_action_category == "testing"
    assert len(episodes) == 1
    assert episodes[0].probable_task == "tests"


def test_mcp_decision_qualification_matches_no_project_and_assisted_episode_divergence():
    payload = {
        "mcp_action_category": "inspection",
        "mcp_is_read_only": True,
        "mcp_decision": "allow",
        "mcp_summary": "Inspect repository status",
    }
    qualification = qualify_observation("mcp_decision", payload)
    event = _event("mcp_decision", payload)

    signals = SignalScorer(_bus_with(event)).compute(observed_now=BASE)
    episodes = build_work_episodes(_episode_events(event))

    assert qualification.actor == "tool_assisted"
    assert qualification.can_anchor_project is False
    assert qualification.can_start_work_block is False
    assert signals.active_project is None
    assert signals.active_file is None
    assert signals.probable_task == "exploration"
    assert len(episodes) == 1
    assert episodes[0].probable_task == "assisted_workflow"
    assert episodes[0].project is None
