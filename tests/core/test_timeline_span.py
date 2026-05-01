

from datetime import datetime

from daemon.core.event_envelope import PulseEventBucket, PulsePrivacyClass, PulseRetention
from daemon.core.timeline_span import TimelineSpan, TimelineSpanKind


def test_timeline_span_to_dict_is_json_ready():
    span = TimelineSpan(
        span_id="span-1",
        started_at=datetime(2026, 5, 1, 14, 0, 0),
        ended_at=datetime(2026, 5, 1, 14, 45, 30),
        kind=TimelineSpanKind.WORK,
        title="Travail sur Pulse",
        project="Pulse",
        activity_level="editing",
        probable_task="coding",
        confidence=0.82,
        buckets=(PulseEventBucket.FILESYSTEM, PulseEventBucket.TERMINAL_ACTIVITY),
        privacy=PulsePrivacyClass.PATH_SENSITIVE,
        retention=PulseRetention.SESSION,
        evidence_event_count=12,
        metadata={"source": "test"},
    )

    assert span.to_dict() == {
        "span_id": "span-1",
        "started_at": "2026-05-01T14:00:00",
        "ended_at": "2026-05-01T14:45:30",
        "duration_sec": 2730.0,
        "duration_min": 45,
        "kind": "work",
        "title": "Travail sur Pulse",
        "project": "Pulse",
        "activity_level": "editing",
        "probable_task": "coding",
        "confidence": 0.82,
        "buckets": ["filesystem", "terminal_activity"],
        "privacy": "path_sensitive",
        "retention": "session",
        "evidence_event_count": 12,
        "metadata": {"source": "test"},
    }


def test_timeline_span_defaults_are_conservative():
    span = TimelineSpan(
        span_id="span-unknown",
        started_at=datetime(2026, 5, 1, 15, 0, 0),
        ended_at=datetime(2026, 5, 1, 15, 5, 0),
    )

    assert span.kind is TimelineSpanKind.UNKNOWN
    assert span.title == ""
    assert span.project is None
    assert span.activity_level is None
    assert span.probable_task is None
    assert span.confidence == 0.0
    assert span.buckets == ()
    assert span.privacy is PulsePrivacyClass.UNKNOWN
    assert span.retention is PulseRetention.SESSION
    assert span.evidence_event_count == 0
    assert span.metadata == {}


def test_timeline_span_duration_is_clamped_to_zero_when_end_precedes_start():
    span = TimelineSpan(
        span_id="span-invalid",
        started_at=datetime(2026, 5, 1, 15, 10, 0),
        ended_at=datetime(2026, 5, 1, 15, 0, 0),
    )

    assert span.duration_sec == 0.0
    assert span.duration_min == 0