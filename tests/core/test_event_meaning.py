from __future__ import annotations

from datetime import datetime
from pathlib import Path

from daemon.core.event_meaning import EventMeaningPolicy


def test_lock_screen_event_publishes_but_is_not_runtime_relevant():
    decision = EventMeaningPolicy().classify("screen_locked", {})

    assert decision.publish_to_bus is True
    assert decision.runtime_relevant is False


def test_commit_editmsg_event_is_not_filtered_as_noise():
    decision = EventMeaningPolicy().classify(
        "file_modified",
        {"path": "/Users/yugz/Projets/Pulse/.git/COMMIT_EDITMSG"},
    )

    assert decision.publish_to_bus is True
    assert decision.runtime_relevant is True
    assert decision.dedupe_key is None


def test_screenshot_path_is_observe_only():
    decision = EventMeaningPolicy().classify_path(
        "/Users/yugz/Desktop/Capture d’écran 2026-04-21 à 10.32.18.png"
    )

    assert decision.file_significance == "observe_only"
    assert decision.publish_to_bus is True
    assert decision.runtime_relevant is False


def test_uuid_named_file_is_technical_noise():
    decision = EventMeaningPolicy().classify_path(
        "/Users/yugz/Library/Caches/events/1p_failed_events.bd63bb8f-c123-4dbe-8641-619c47b09fa0.json"
    )

    assert decision.file_significance == "technical_noise"


def test_pulse_internal_path_is_filtered():
    decision = EventMeaningPolicy().classify(
        "file_modified",
        {"path": str(Path.home() / ".pulse" / "facts.db")},
    )

    assert decision.file_significance == "technical_noise"
    assert decision.publish_to_bus is False
    assert decision.runtime_relevant is False


def test_clipboard_payload_strips_content():
    decision = EventMeaningPolicy().classify(
        "clipboard_updated",
        {"content": "secret", "content_kind": "code"},
    )

    assert decision.publish_to_bus is True
    assert decision.sanitized_payload == {"content_kind": "code"}
    assert "content" not in decision.sanitized_payload


def test_terminal_payload_strips_command_and_raw():
    decision = EventMeaningPolicy().classify(
        "terminal_command_finished",
        {"command": "cat ~/.ssh/id_rsa", "raw": "cat ~/.ssh/id_rsa", "cwd": "/tmp"},
    )

    assert decision.publish_to_bus is True
    assert decision.sanitized_payload == {"cwd": "/tmp"}
    assert "command" not in decision.sanitized_payload
    assert "raw" not in decision.sanitized_payload


def test_known_coalescible_file_event_is_coalescible():
    decision = EventMeaningPolicy().classify(
        "file_modified",
        {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"},
    )

    assert decision.coalescible is True
    assert decision.coalescing_priority == 0


def test_known_non_coalescible_type_is_not_coalescible():
    decision = EventMeaningPolicy().classify(
        "file_deleted",
        {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"},
    )

    assert decision.coalescible is False
    assert decision.coalescing_priority == -1


def test_same_dedupe_key_twice_within_window_is_duplicate():
    policy = EventMeaningPolicy()
    now = datetime(2026, 5, 6, 12, 0, 0)

    assert policy.should_dedupe("file_modified:/tmp/main.py", now=now) is False
    assert policy.should_dedupe("file_modified:/tmp/main.py", now=now) is True
