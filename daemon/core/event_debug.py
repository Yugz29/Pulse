"""Passive debug helpers for Pulse events.

This module prepares the future raw event browser/timeline inspector without
changing EventBus, routing, scoring, persistence, or memory behavior.
"""

from __future__ import annotations

from typing import Any

from daemon.core.event_bus import Event
from daemon.core.event_envelope import (
    envelope_from_legacy_event,
    summarize_envelope_policy,
)


def describe_event_for_debug(event: Event) -> dict[str, Any]:
    """Return a debug-friendly description of a legacy EventBus event.

    The returned dict is JSON-ready and intentionally descriptive. It should be
    safe to expose in a developer/debug UI, but it does not redact the payload.
    Future callers must still decide whether to hide payload details based on
    the `policy.privacy` hint.
    """
    envelope = envelope_from_legacy_event(
        event.type,
        event.payload,
        timestamp=event.timestamp,
    )
    return {
        "type": event.type,
        "timestamp": event.timestamp.isoformat(),
        "source": envelope.source.value,
        "bucket": envelope.bucket.value,
        "privacy": envelope.privacy.value,
        "retention": envelope.retention.value,
        "can_heartbeat": envelope.can_heartbeat,
        "duration_sec": envelope.duration_sec,
        "policy": summarize_envelope_policy(envelope),
        "payload_keys": sorted(event.payload.keys()),
    }