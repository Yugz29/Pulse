from datetime import datetime
from types import SimpleNamespace

from daemon.core.event_envelope import PulseEventBucket, PulsePrivacyClass, PulseRetention
from daemon.core.timeline_builder import span_from_current_context
from daemon.core.timeline_span import TimelineSpanKind


def test_span_from_current_context_builds_work_span_from_editing_context():
    context = SimpleNamespace(
        active_project="Pulse",
        active_file="/tmp/Pulse/daemon/runtime.py",
        probable_task="coding",
        activity_level="editing",
        task_confidence=0.82,
    )

    span = span_from_current_context(
        context,
        started_at=datetime(2026, 5, 1, 14, 0, 0),
        ended_at=datetime(2026, 5, 1, 14, 30, 0),
        span_id="span-1",
    )

    assert span.kind is TimelineSpanKind.WORK
    assert span.title == "Pulse — coding"
    assert span.project == "Pulse"
    assert span.activity_level == "editing"
    assert span.probable_task == "coding"
    assert span.confidence == 0.82
    assert span.buckets == (PulseEventBucket.FILESYSTEM,)
    assert span.privacy is PulsePrivacyClass.PATH_SENSITIVE
    assert span.retention is PulseRetention.SESSION
    assert span.metadata == {"source": "current_context"}
    assert span.duration_min == 30


def test_span_from_current_context_builds_execution_span():
    context = SimpleNamespace(
        active_project="Pulse",
        active_file="/tmp/Pulse/tests/test_runtime_routes.py",
        probable_task="testing",
        activity_level="executing",
        task_confidence=0.91,
    )

    span = span_from_current_context(
        context,
        started_at=datetime(2026, 5, 1, 15, 0, 0),
        ended_at=datetime(2026, 5, 1, 15, 5, 0),
        span_id="span-exec",
    )

    assert span.kind is TimelineSpanKind.EXECUTION
    assert span.buckets == (PulseEventBucket.FILESYSTEM, PulseEventBucket.TERMINAL_ACTIVITY)
    assert span.privacy is PulsePrivacyClass.CONTENT_SENSITIVE
    assert span.confidence == 0.91


def test_span_from_current_context_clamps_confidence_and_accepts_custom_title():
    context = SimpleNamespace(
        active_project="Pulse",
        active_file=None,
        probable_task="debug",
        activity_level="reading",
        task_confidence=3.5,
    )

    span = span_from_current_context(
        context,
        started_at=datetime(2026, 5, 1, 16, 0, 0),
        ended_at=datetime(2026, 5, 1, 16, 10, 0),
        span_id="span-debug",
        title="Analyse ciblée",
    )

    assert span.kind is TimelineSpanKind.DEBUG
    assert span.title == "Analyse ciblée"
    assert span.confidence == 1.0
    assert span.buckets == ()
    assert span.privacy is PulsePrivacyClass.UNKNOWN


def test_span_from_current_context_defaults_conservatively():
    context = SimpleNamespace()

    span = span_from_current_context(
        context,
        started_at=datetime(2026, 5, 1, 17, 0, 0),
        ended_at=datetime(2026, 5, 1, 17, 1, 0),
        span_id="span-unknown",
    )

    assert span.kind is TimelineSpanKind.UNKNOWN
    assert span.title == "Projet inconnu"
    assert span.project is None
    assert span.activity_level is None
    assert span.probable_task is None
    assert span.confidence == 0.0
    assert span.buckets == ()
    assert span.privacy is PulsePrivacyClass.UNKNOWN