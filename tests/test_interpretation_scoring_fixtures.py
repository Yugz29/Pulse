import json
from pathlib import Path


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "interpretation" / "scoring_scenarios.json"
REQUIRED_FAMILIES = {
    "code_editing",
    "terminal_tests_failed",
    "browser_read_only_exploration",
    "idle",
    "noisy_tool_assisted",
}
REQUIRED_EXPECTED_KEYS = {
    "probable_task",
    "activity_level",
    "focus_level",
}


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_interpretation_scoring_fixture_is_structured_and_portable():
    fixture = _load_fixture()

    assert fixture["schema_version"] == 1
    assert isinstance(fixture["scenarios"], list)
    assert fixture["scenarios"]

    families = {scenario["family"] for scenario in fixture["scenarios"]}
    assert REQUIRED_FAMILIES <= families

    serialized = json.dumps(fixture)
    assert "/Users/yugz" not in serialized

    for scenario in fixture["scenarios"]:
        assert scenario["name"]
        assert scenario["intent"]
        assert scenario["compute_args"]["observed_now"]
        assert scenario["compute_args"]["session_started_at"]
        assert isinstance(scenario["events"], list)
        assert scenario["events"]
        assert isinstance(scenario["notes"], list)

        expected = scenario["expected_minimal"]
        assert REQUIRED_EXPECTED_KEYS <= set(expected)
        assert "task_confidence_min" in expected or "task_confidence_max" in expected

        for event in scenario["events"]:
            assert event["type"]
            assert event["timestamp"]
            assert isinstance(event["payload"], dict)
