from datetime import datetime

from daemon.core.event_envelope import (
    PulseEventBucket,
    PulseEventEnvelope,
    PulseEventSource,
    PulsePrivacyClass,
    PulseRetention,
    envelope_from_legacy_event,
    infer_bucket,
    infer_source,
)


def test_event_envelope_to_dict_is_json_ready():
    envelope = PulseEventEnvelope(
        event_type="file_modified",
        payload={"path": "/tmp/Pulse/daemon/main.py"},
        timestamp=datetime(2026, 5, 1, 12, 30, 0),
        source=PulseEventSource.FILESYSTEM,
        bucket=PulseEventBucket.FILESYSTEM,
        privacy=PulsePrivacyClass.PATH_SENSITIVE,
        retention=PulseRetention.SESSION,
        duration_sec=2.5,
        can_heartbeat=True,
    )

    assert envelope.to_dict() == {
        "event_type": "file_modified",
        "payload": {"path": "/tmp/Pulse/daemon/main.py"},
        "timestamp": "2026-05-01T12:30:00",
        "source": "filesystem",
        "bucket": "filesystem",
        "privacy": "path_sensitive",
        "retention": "session",
        "duration_sec": 2.5,
        "can_heartbeat": True,
    }


def test_event_envelope_defaults_are_conservative():
    envelope = PulseEventEnvelope(event_type="custom_event")

    assert envelope.event_type == "custom_event"
    assert envelope.payload == {}
    assert envelope.source is PulseEventSource.UNKNOWN
    assert envelope.bucket is PulseEventBucket.UNKNOWN
    assert envelope.privacy is PulsePrivacyClass.UNKNOWN
    assert envelope.retention is PulseRetention.SESSION
    assert envelope.duration_sec is None
    assert envelope.can_heartbeat is False


def test_envelope_from_legacy_event_infers_source_and_bucket():
    envelope = envelope_from_legacy_event(
        "file_modified",
        {"path": "/tmp/Pulse/daemon/main.py"},
        timestamp=datetime(2026, 5, 1, 13, 0, 0),
    )

    assert envelope.event_type == "file_modified"
    assert envelope.payload == {"path": "/tmp/Pulse/daemon/main.py"}
    assert envelope.timestamp == datetime(2026, 5, 1, 13, 0, 0)
    assert envelope.source is PulseEventSource.FILESYSTEM
    assert envelope.bucket is PulseEventBucket.FILESYSTEM
    assert envelope.privacy is PulsePrivacyClass.UNKNOWN
    assert envelope.retention is PulseRetention.SESSION


def test_envelope_from_legacy_event_keeps_unknowns_conservative():
    envelope = envelope_from_legacy_event(
        "custom_event",
        {"value": 42},
        timestamp=datetime(2026, 5, 1, 13, 5, 0),
    )

    assert envelope.source is PulseEventSource.UNKNOWN
    assert envelope.bucket is PulseEventBucket.UNKNOWN
    assert envelope.payload == {"value": 42}


def test_envelope_from_legacy_event_allows_explicit_source_and_bucket_override():
    envelope = envelope_from_legacy_event(
        "custom_event",
        {"value": 42},
        timestamp=datetime(2026, 5, 1, 13, 10, 0),
        source=PulseEventSource.DAEMON,
        bucket=PulseEventBucket.SYSTEM_ACTIVITY,
    )

    assert envelope.source is PulseEventSource.DAEMON
    assert envelope.bucket is PulseEventBucket.SYSTEM_ACTIVITY


def test_infer_bucket_from_known_legacy_event_types():
    assert infer_bucket("file_modified") is PulseEventBucket.FILESYSTEM
    assert infer_bucket("file_change") is PulseEventBucket.FILESYSTEM
    assert infer_bucket("app_activated") is PulseEventBucket.APP_ACTIVITY
    assert infer_bucket("terminal_command_finished") is PulseEventBucket.TERMINAL_ACTIVITY
    assert infer_bucket("mcp_command_received") is PulseEventBucket.MCP_ACTIVITY
    assert infer_bucket("llm_ready") is PulseEventBucket.LLM_ACTIVITY
    assert infer_bucket("git_commit") is PulseEventBucket.GIT_ACTIVITY
    assert infer_bucket("confirmed_commit") is PulseEventBucket.GIT_ACTIVITY
    assert infer_bucket("memory_sync") is PulseEventBucket.MEMORY_ACTIVITY
    assert infer_bucket("resume_card") is PulseEventBucket.MEMORY_ACTIVITY
    assert infer_bucket("clipboard_updated") is PulseEventBucket.CLIPBOARD_ACTIVITY
    assert infer_bucket("screen_locked") is PulseEventBucket.SYSTEM_ACTIVITY


def test_infer_bucket_from_source_when_event_type_is_unknown():
    assert infer_bucket("custom", PulseEventSource.FILESYSTEM) is PulseEventBucket.FILESYSTEM
    assert infer_bucket("custom", PulseEventSource.APP) is PulseEventBucket.APP_ACTIVITY
    assert infer_bucket("custom", PulseEventSource.TERMINAL) is PulseEventBucket.TERMINAL_ACTIVITY
    assert infer_bucket("custom", PulseEventSource.CLIPBOARD) is PulseEventBucket.CLIPBOARD_ACTIVITY
    assert infer_bucket("custom", PulseEventSource.MCP) is PulseEventBucket.MCP_ACTIVITY
    assert infer_bucket("custom", PulseEventSource.LLM) is PulseEventBucket.LLM_ACTIVITY
    assert infer_bucket("custom", PulseEventSource.GIT) is PulseEventBucket.GIT_ACTIVITY
    assert infer_bucket("custom", PulseEventSource.MEMORY) is PulseEventBucket.MEMORY_ACTIVITY
    assert infer_bucket("custom", PulseEventSource.SYSTEM) is PulseEventBucket.SYSTEM_ACTIVITY


def test_infer_bucket_unknown_stays_unknown():
    assert infer_bucket("custom_event") is PulseEventBucket.UNKNOWN


def test_infer_source_from_known_legacy_event_types():
    assert infer_source("file_modified") is PulseEventSource.FILESYSTEM
    assert infer_source("file_change") is PulseEventSource.FILESYSTEM
    assert infer_source("app_activated") is PulseEventSource.APP
    assert infer_source("terminal_command_finished") is PulseEventSource.TERMINAL
    assert infer_source("clipboard_updated") is PulseEventSource.CLIPBOARD
    assert infer_source("mcp_command_received") is PulseEventSource.MCP
    assert infer_source("llm_ready") is PulseEventSource.LLM
    assert infer_source("git_commit") is PulseEventSource.GIT
    assert infer_source("confirmed_commit") is PulseEventSource.GIT
    assert infer_source("memory_sync") is PulseEventSource.MEMORY
    assert infer_source("resume_card") is PulseEventSource.MEMORY
    assert infer_source("screen_locked") is PulseEventSource.SYSTEM


def test_infer_source_from_payload_when_event_type_is_unknown():
    assert infer_source("custom", {"terminal_command": "pytest"}) is PulseEventSource.TERMINAL
    assert infer_source("custom", {"terminal_action_category": "test"}) is PulseEventSource.TERMINAL
    assert infer_source("custom", {"mcp_tool": "shell"}) is PulseEventSource.MCP
    assert infer_source("custom", {"mcp_action_category": "risky_command"}) is PulseEventSource.MCP
    assert infer_source("custom", {"commit_sha": "abc123"}) is PulseEventSource.GIT
    assert infer_source("custom", {"commit_message": "feat: add event envelope"}) is PulseEventSource.GIT
    assert infer_source("custom", {"path": "/tmp/file.py"}) is PulseEventSource.FILESYSTEM
    assert infer_source("custom", {"app_name": "Code"}) is PulseEventSource.APP


def test_infer_source_unknown_stays_unknown():
    assert infer_source("custom_event") is PulseEventSource.UNKNOWN
    assert infer_source("custom_event", {"value": 42}) is PulseEventSource.UNKNOWN
