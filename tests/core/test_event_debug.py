from datetime import datetime

from daemon.core.event_bus import Event
from daemon.core.event_debug import describe_event_for_debug


def test_describe_file_event_for_debug():
    event = Event(
        type="file_modified",
        payload={"path": "/tmp/Pulse/daemon/main.py", "_actor": "user"},
        timestamp=datetime(2026, 5, 1, 16, 0, 0),
    )

    assert describe_event_for_debug(event) == {
        "type": "file_modified",
        "timestamp": "2026-05-01T16:00:00",
        "source": "filesystem",
        "bucket": "filesystem",
        "privacy": "path_sensitive",
        "retention": "session",
        "can_heartbeat": False,
        "duration_sec": None,
        "policy": {
            "source": "Filesystem watcher",
            "bucket": "Filesystem events",
            "privacy": "Path-sensitive metadata",
            "retention": "Session-scoped by default",
        },
        "payload_keys": ["_actor", "path"],
    }


def test_describe_clipboard_event_for_debug():
    event = Event(
        type="clipboard_updated",
        payload={"clipboard_context": "text", "length": 42},
        timestamp=datetime(2026, 5, 1, 16, 1, 0),
    )

    description = describe_event_for_debug(event)

    assert description["type"] == "clipboard_updated"
    assert description["source"] == "clipboard"
    assert description["bucket"] == "clipboard_activity"
    assert description["privacy"] == "content_sensitive"
    assert description["retention"] == "ephemeral"
    assert description["policy"] == {
        "source": "Clipboard activity",
        "bucket": "Clipboard timeline",
        "privacy": "Content-sensitive payload",
        "retention": "Ephemeral by default",
    }
    assert description["payload_keys"] == ["clipboard_context", "length"]


def test_describe_unknown_event_for_debug_is_conservative():
    event = Event(
        type="custom_event",
        payload={"value": 42},
        timestamp=datetime(2026, 5, 1, 16, 2, 0),
    )

    description = describe_event_for_debug(event)

    assert description["source"] == "unknown"
    assert description["bucket"] == "unknown"
    assert description["privacy"] == "unknown"
    assert description["retention"] == "debug_only"
    assert description["policy"] == {
        "source": "Unknown source",
        "bucket": "Unknown bucket",
        "privacy": "Unknown sensitivity",
        "retention": "Debug-only by default",
    }