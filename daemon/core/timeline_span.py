

"""Passive timeline span contracts for Pulse.

A span is a human-readable time interval derived from events/signals later in the
pipeline. This module only defines the target contract for the future timeline;
it does not infer spans, persist them, score them, or change runtime behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional

from daemon.core.event_envelope import PulseEventBucket, PulsePrivacyClass, PulseRetention


class TimelineSpanKind(str, Enum):
    """High-level span categories for the future timeline view."""

    WORK = "work"
    BREAK = "break"
    DEBUG = "debug"
    READING = "reading"
    EXECUTION = "execution"
    SYSTEM = "system"
    MEMORY = "memory"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TimelineSpan:
    """Passive description of a coherent time interval.

    TimelineSpan is intentionally separate from EventBus.Event. Events are raw
    observations; spans are later derived intervals that explain what happened
    over time.
    """

    span_id: str
    started_at: datetime
    ended_at: datetime
    kind: TimelineSpanKind = TimelineSpanKind.UNKNOWN
    title: str = ""
    project: Optional[str] = None
    activity_level: Optional[str] = None
    probable_task: Optional[str] = None
    confidence: float = 0.0
    buckets: tuple[PulseEventBucket, ...] = field(default_factory=tuple)
    privacy: PulsePrivacyClass = PulsePrivacyClass.UNKNOWN
    retention: PulseRetention = PulseRetention.SESSION
    evidence_event_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def duration_sec(self) -> float:
        """Return the span duration in seconds, clamped to zero."""
        return max((self.ended_at - self.started_at).total_seconds(), 0.0)

    @property
    def duration_min(self) -> int:
        """Return the span duration rounded down to minutes."""
        return int(self.duration_sec // 60)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "span_id": self.span_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "duration_sec": self.duration_sec,
            "duration_min": self.duration_min,
            "kind": self.kind.value,
            "title": self.title,
            "project": self.project,
            "activity_level": self.activity_level,
            "probable_task": self.probable_task,
            "confidence": self.confidence,
            "buckets": [bucket.value for bucket in self.buckets],
            "privacy": self.privacy.value,
            "retention": self.retention.value,
            "evidence_event_count": self.evidence_event_count,
            "metadata": dict(self.metadata),
        }