from daemon.core.observation_qualification import qualify_observation


def test_meaningful_user_file_event_is_strong_work_evidence():
    qualification = qualify_observation(
        "file_modified",
        {
            "path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py",
            "_actor": "user",
        },
    )

    assert qualification.evidence_strength == "strong"
    assert qualification.actor == "user"
    assert qualification.sensitivity == "medium"
    assert qualification.can_persist is True
    assert qualification.can_anchor_project is True
    assert qualification.can_anchor_file is True
    assert qualification.can_start_work_block is True
    assert qualification.can_influence_activity is True


def test_tool_assisted_file_event_can_anchor_assisted_work():
    qualification = qualify_observation(
        "file_modified",
        {
            "path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py",
            "_actor": "tool_assisted",
        },
    )

    assert qualification.evidence_strength == "strong"
    assert qualification.actor == "tool_assisted"
    assert qualification.can_anchor_project is True
    assert qualification.can_start_work_block is True
    assert qualification.can_influence_activity is True


def test_system_cache_file_event_is_noise_without_work_influence():
    qualification = qualify_observation(
        "file_modified",
        {
            "path": "/Users/yugz/.cache/huggingface/model/cache.json",
            "_actor": "system",
        },
    )

    assert qualification.evidence_strength == "noise"
    assert qualification.actor == "system"
    assert qualification.can_persist is False
    assert qualification.can_anchor_project is False
    assert qualification.can_start_work_block is False
    assert qualification.can_influence_activity is False


def test_window_title_is_contextual_sensitive_and_redacted_before_storage():
    qualification = qualify_observation(
        "window_title_poll",
        {
            "app_name": "Code",
            "window_title": "Pulse — yugz@example.com — /Users/yugz/Projects/Pulse",
        },
    )

    assert qualification.evidence_strength == "contextual"
    assert qualification.sensitivity == "high"
    assert qualification.requires_redaction is True
    assert qualification.can_start_work_block is False
    assert qualification.can_anchor_project is False
    assert qualification.can_anchor_file is True


def test_terminal_testing_failed_with_test_result_is_strong_sensitive_activity():
    qualification = qualify_observation(
        "terminal_command_finished",
        {
            "terminal_command": "pytest tests/core/test_signal_scorer.py",
            "terminal_action_category": "testing",
            "terminal_success": False,
            "terminal_project": "Pulse",
            "test_result": {
                "framework": "pytest",
                "failed_count": 2,
                "passed_count": 64,
            },
        },
    )

    assert qualification.evidence_strength == "strong"
    assert qualification.sensitivity == "high"
    assert qualification.requires_redaction is True
    assert qualification.can_persist is True
    assert qualification.can_anchor_project is True
    assert qualification.can_start_work_block is True
    assert qualification.can_influence_activity is True
    assert "test_result" in qualification.reasons


def test_mcp_decision_is_tool_context_not_user_work_block():
    qualification = qualify_observation(
        "mcp_decision",
        {
            "command": "pytest tests/core/test_signal_scorer.py --token secret",
            "mcp_action_category": "testing",
            "mcp_decision": "allow",
        },
    )

    assert qualification.evidence_strength == "contextual"
    assert qualification.actor == "tool_assisted"
    assert qualification.sensitivity == "high"
    assert qualification.requires_redaction is True
    assert qualification.can_anchor_project is False
    assert qualification.can_start_work_block is False
    assert qualification.can_influence_activity is True


def test_clipboard_update_is_sensitive_context_not_work_block():
    qualification = qualify_observation(
        "clipboard_updated",
        {"content_kind": "stacktrace", "char_count": 1200},
    )

    assert qualification.evidence_strength == "contextual"
    assert qualification.sensitivity == "high"
    assert qualification.requires_redaction is True
    assert qualification.can_anchor_project is False
    assert qualification.can_start_work_block is False
    assert qualification.can_influence_activity is False


def test_iokit_user_presence_is_contextual_activity_support_only():
    qualification = qualify_observation(
        "user_presence",
        {"presence_state": "idle", "idle_seconds": 420, "source": "iokit"},
    )

    assert qualification.evidence_strength == "contextual"
    assert qualification.sensitivity == "low"
    assert qualification.can_influence_activity is True
    assert qualification.can_anchor_project is False
    assert qualification.can_start_work_block is False


def test_screen_lock_events_are_strong_lifecycle_not_project_anchor():
    for event_type in ("screen_locked", "screen_unlocked"):
        qualification = qualify_observation(event_type, {})

        assert qualification.evidence_strength == "strong"
        assert qualification.actor == "system"
        assert qualification.sensitivity == "low"
        assert qualification.can_influence_activity is True
        assert qualification.can_anchor_project is False
        assert qualification.can_start_work_block is False


def test_internal_daemon_events_are_contextual_non_work():
    for event_type in ("context_probe_executed", "llm_loading", "llm_ready", "resume_card"):
        qualification = qualify_observation(event_type, {"project": "Pulse"})

        assert qualification.evidence_strength == "contextual"
        assert qualification.actor == "system"
        assert qualification.can_anchor_project is False
        assert qualification.can_anchor_file is False
        assert qualification.can_start_work_block is False
        assert qualification.can_influence_activity is False
