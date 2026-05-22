import json
from datetime import datetime
from pathlib import Path

import pytest

from daemon.core.event_bus import EventBus
from daemon.core.signal_scorer import SignalScorer


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "interpretation" / "scoring_scenarios.json"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _load_scenarios() -> list[dict]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return fixture["scenarios"]


@pytest.mark.parametrize("scenario", _load_scenarios(), ids=lambda scenario: scenario["name"])
def test_signal_scorer_matches_golden_interpretation_scenarios(scenario):
    bus = EventBus(max_size=100)
    for event in scenario["events"]:
        bus.publish(
            event["type"],
            dict(event["payload"]),
            timestamp=_parse_time(event["timestamp"]),
        )

    scorer = SignalScorer(bus)
    compute_args = scenario["compute_args"]
    signals = scorer.compute(
        observed_now=_parse_time(compute_args["observed_now"]),
        session_started_at=_parse_time(compute_args["session_started_at"]),
    )
    expected = scenario["expected_minimal"]

    assert signals.probable_task == expected["probable_task"]
    assert signals.activity_level == expected["activity_level"]
    assert signals.focus_level == expected["focus_level"]

    if "task_confidence_min" in expected:
        assert signals.task_confidence >= expected["task_confidence_min"]
    if "task_confidence_max" in expected:
        assert signals.task_confidence <= expected["task_confidence_max"]
    if "active_project" in expected:
        assert signals.active_project == expected["active_project"]
    if "active_file_suffix" in expected:
        assert signals.active_file is not None
        assert signals.active_file.endswith(expected["active_file_suffix"])
    if "edited_file_count_10m" in expected:
        assert signals.edited_file_count_10m == expected["edited_file_count_10m"]
    if "terminal_action_category" in expected:
        assert signals.terminal_action_category == expected["terminal_action_category"]
    if "terminal_success" in expected:
        assert signals.terminal_success is expected["terminal_success"]
