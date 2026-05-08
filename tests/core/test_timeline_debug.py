

from datetime import datetime

from daemon.core.event_envelope import PulseEventBucket, PulsePrivacyClass, PulseRetention
from daemon.core.timeline_debug import describe_timeline_span_for_debug
from daemon.core.timeline_span import TimelineSpan, TimelineSpanKind


def test_describe_timeline_span_for_debug_is_json_ready_without_raw_metadata_values():
    span = TimelineSpan(
        span_id="span-1",
        started_at=datetime(2026, 5, 1, 14, 0, 0),
        ended_at=datetime(2026, 5, 1, 14, 30, 0),
        kind=TimelineSpanKind.WORK,
        title="Pulse — coding",
        project="Pulse",
        activity_level="editing",
        probable_task="coding",
        confidence=0.82,
        buckets=(PulseEventBucket.FILESYSTEM,),
        privacy=PulsePrivacyClass.PATH_SENSITIVE,
        retention=PulseRetention.SESSION,
        evidence_event_count=12,
        metadata={"raw_path": "/tmp/Pulse/daemon/main.py", "source": "current_context"},
    )

    assert describe_timeline_span_for_debug(span) == {
        "span_id": "span-1",
        "kind": "work",
        "title": "Pulse — coding",
        "started_at": "2026-05-01T14:00:00",
        "ended_at": "2026-05-01T14:30:00",
        "duration_sec": 1800.0,
        "duration_min": 30,
        "project": "Pulse",
        "activity_level": "editing",
        "probable_task": "coding",
        "confidence": 0.82,
        "buckets": ["filesystem"],
        "privacy": "path_sensitive",
        "retention": "session",
        "evidence_event_count": 12,
        "policy": {
            "privacy": "Path-sensitive span",
            "retention": "Session-scoped by default",
            "confidence": "High confidence",
        },
        "metadata_keys": ["raw_path", "source"],
    }


def test_describe_timeline_span_for_debug_does_not_expose_metadata_values():
    span = TimelineSpan(
        span_id="span-secret",
        started_at=datetime(2026, 5, 1, 15, 0, 0),
        ended_at=datetime(2026, 5, 1, 15, 5, 0),
        kind=TimelineSpanKind.DEBUG,
        title="Sensitive debug span",
        confidence=0.5,
        privacy=PulsePrivacyClass.CONTENT_SENSITIVE,
        retention=PulseRetention.EPHEMERAL,
        metadata={"terminal_command": "cat ~/.ssh/id_rsa", "raw_output": "SECRET"},
    )

    description = describe_timeline_span_for_debug(span)

    assert description["metadata_keys"] == ["raw_output", "terminal_command"]
    assert "cat ~/.ssh/id_rsa" not in str(description)
    assert "SECRET" not in str(description)
    assert description["policy"] == {
        "privacy": "Content-sensitive span",
        "retention": "Ephemeral by default",
        "confidence": "Medium confidence",
    }


def test_describe_timeline_span_for_debug_confidence_labels():
    low = TimelineSpan(
        span_id="low",
        started_at=datetime(2026, 5, 1, 16, 0, 0),
        ended_at=datetime(2026, 5, 1, 16, 1, 0),
        confidence=0.2,
    )
    none = TimelineSpan(
        span_id="none",
        started_at=datetime(2026, 5, 1, 16, 0, 0),
        ended_at=datetime(2026, 5, 1, 16, 1, 0),
        confidence=0.0,
    )

    assert describe_timeline_span_for_debug(low)["policy"]["confidence"] == "Low confidence"
    assert describe_timeline_span_for_debug(none)["policy"]["confidence"] == "No confidence score"


def test_describe_timeline_span_for_debug_unknown_defaults():
    span = TimelineSpan(
        span_id="unknown",
        started_at=datetime(2026, 5, 1, 17, 0, 0),
        ended_at=datetime(2026, 5, 1, 17, 1, 0),
    )

    description = describe_timeline_span_for_debug(span)

    assert description["kind"] == "unknown"
    assert description["privacy"] == "unknown"
    assert description["retention"] == "session"
    assert description["policy"] == {
        "privacy": "Unknown span sensitivity",
        "retention": "Session-scoped by default",
        "confidence": "No confidence score",
    }
    assert description["metadata_keys"] == []