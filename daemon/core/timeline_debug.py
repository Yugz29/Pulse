

"""Passive debug helpers for timeline spans.

This module prepares future timeline inspector/debug UI rendering without
persisting spans, mutating runtime state, or exposing raw metadata values.
"""

from __future__ import annotations

from typing import Any

from daemon.core.timeline_span import TimelineSpan


def describe_timeline_span_for_debug(span: TimelineSpan) -> dict[str, Any]:
    """Return a debug-friendly description of a TimelineSpan.

    The returned dict is JSON-ready and intentionally avoids exposing raw
    metadata values. Future UI layers can use metadata_keys to indicate what
    supporting data exists without leaking sensitive details by default.
    """
    return {
        "span_id": span.span_id,
        "kind": span.kind.value,
        "title": span.title,
        "started_at": span.started_at.isoformat(),
        "ended_at": span.ended_at.isoformat(),
        "duration_sec": span.duration_sec,
        "duration_min": span.duration_min,
        "project": span.project,
        "activity_level": span.activity_level,
        "probable_task": span.probable_task,
        "confidence": span.confidence,
        "buckets": [bucket.value for bucket in span.buckets],
        "privacy": span.privacy.value,
        "retention": span.retention.value,
        "evidence_event_count": span.evidence_event_count,
        "policy": {
            "privacy": _privacy_label(span),
            "retention": _retention_label(span),
            "confidence": _confidence_label(span),
        },
        "metadata_keys": sorted(span.metadata.keys()),
    }


def _privacy_label(span: TimelineSpan) -> str:
    labels = {
        "public": "Low sensitivity span",
        "path_sensitive": "Path-sensitive span",
        "content_sensitive": "Content-sensitive span",
        "secret_sensitive": "Potential secret-sensitive span",
        "unknown": "Unknown span sensitivity",
    }
    return labels[span.privacy.value]


def _retention_label(span: TimelineSpan) -> str:
    labels = {
        "ephemeral": "Ephemeral by default",
        "session": "Session-scoped by default",
        "persistent": "Persistent timeline candidate",
        "debug_only": "Debug-only by default",
    }
    return labels[span.retention.value]


def _confidence_label(span: TimelineSpan) -> str:
    if span.confidence >= 0.75:
        return "High confidence"
    if span.confidence >= 0.4:
        return "Medium confidence"
    if span.confidence > 0:
        return "Low confidence"
    return "No confidence score"