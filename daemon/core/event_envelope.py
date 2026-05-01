

"""Canonical event envelope contracts for Pulse.

This module introduces ActivityWatch-inspired event metadata without changing
the current EventBus pipeline yet.

Current pipeline:
- daemon.core.event_bus.Event remains the runtime transport object.

Target direction:
- PulseEventEnvelope describes where an event came from, which logical bucket it
  belongs to, how sensitive it is, and whether it can later become part of a
  timeline/span model.

Keep this module passive: no routing, no scoring, no persistence side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional


class PulseEventSource(str, Enum):
    """Physical or logical producer of an event."""

    SWIFT = "swift"
    DAEMON = "daemon"
    FILESYSTEM = "filesystem"
    APP = "app"
    TERMINAL = "terminal"
    CLIPBOARD = "clipboard"
    MCP = "mcp"
    LLM = "llm"
    GIT = "git"
    MEMORY = "memory"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class PulseEventBucket(str, Enum):
    """Logical stream used to group similar events.

    Inspired by ActivityWatch buckets, but kept intentionally small for Pulse.
    """

    FILESYSTEM = "filesystem"
    APP_ACTIVITY = "app_activity"
    TERMINAL_ACTIVITY = "terminal_activity"
    CLIPBOARD_ACTIVITY = "clipboard_activity"
    MCP_ACTIVITY = "mcp_activity"
    LLM_ACTIVITY = "llm_activity"
    GIT_ACTIVITY = "git_activity"
    MEMORY_ACTIVITY = "memory_activity"
    SYSTEM_ACTIVITY = "system_activity"
    UNKNOWN = "unknown"


class PulsePrivacyClass(str, Enum):
    """How sensitive an event payload is expected to be."""

    PUBLIC = "public"
    PATH_SENSITIVE = "path_sensitive"
    CONTENT_SENSITIVE = "content_sensitive"
    SECRET_SENSITIVE = "secret_sensitive"
    UNKNOWN = "unknown"


class PulseRetention(str, Enum):
    """Retention intent for future persistence/timeline layers."""

    EPHEMERAL = "ephemeral"
    SESSION = "session"
    PERSISTENT = "persistent"
    DEBUG_ONLY = "debug_only"


@dataclass(frozen=True)
class PulseEventEnvelope:
    """Metadata wrapper around a Pulse event payload.

    This is not a replacement for daemon.core.event_bus.Event yet.
    It is the target contract for the future watcher/bucket/timeline model.
    """

    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    source: PulseEventSource = PulseEventSource.UNKNOWN
    bucket: PulseEventBucket = PulseEventBucket.UNKNOWN
    privacy: PulsePrivacyClass = PulsePrivacyClass.UNKNOWN
    retention: PulseRetention = PulseRetention.SESSION
    duration_sec: Optional[float] = None
    can_heartbeat: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "timestamp": self.timestamp.isoformat(),
            "source": self.source.value,
            "bucket": self.bucket.value,
            "privacy": self.privacy.value,
            "retention": self.retention.value,
            "duration_sec": self.duration_sec,
            "can_heartbeat": self.can_heartbeat,
        }


def infer_bucket(event_type: str, source: PulseEventSource = PulseEventSource.UNKNOWN) -> PulseEventBucket:
    """Infer a logical bucket from a legacy event type/source.

    This helper is deliberately conservative. It should help migration without
    hiding unknown event families behind overconfident classifications.
    """
    if event_type.startswith("file_") or event_type == "file_change":
        return PulseEventBucket.FILESYSTEM
    if event_type in {"app_activated", "app_switch", "app_launched", "app_terminated"}:
        return PulseEventBucket.APP_ACTIVITY
    if event_type.startswith("terminal_"):
        return PulseEventBucket.TERMINAL_ACTIVITY
    if event_type.startswith("mcp_"):
        return PulseEventBucket.MCP_ACTIVITY
    if event_type.startswith("llm_"):
        return PulseEventBucket.LLM_ACTIVITY
    if event_type.startswith("git_") or "commit" in event_type:
        return PulseEventBucket.GIT_ACTIVITY
    if event_type.startswith("memory_") or event_type in {"resume_card"}:
        return PulseEventBucket.MEMORY_ACTIVITY
    if event_type in {"clipboard_updated"}:
        return PulseEventBucket.CLIPBOARD_ACTIVITY
    if event_type in {"screen_locked", "screen_unlocked", "user_idle", "user_active"}:
        return PulseEventBucket.SYSTEM_ACTIVITY

    if source == PulseEventSource.FILESYSTEM:
        return PulseEventBucket.FILESYSTEM
    if source == PulseEventSource.APP:
        return PulseEventBucket.APP_ACTIVITY
    if source == PulseEventSource.TERMINAL:
        return PulseEventBucket.TERMINAL_ACTIVITY
    if source == PulseEventSource.CLIPBOARD:
        return PulseEventBucket.CLIPBOARD_ACTIVITY
    if source == PulseEventSource.MCP:
        return PulseEventBucket.MCP_ACTIVITY
    if source == PulseEventSource.LLM:
        return PulseEventBucket.LLM_ACTIVITY
    if source == PulseEventSource.GIT:
        return PulseEventBucket.GIT_ACTIVITY
    if source == PulseEventSource.MEMORY:
        return PulseEventBucket.MEMORY_ACTIVITY
    if source == PulseEventSource.SYSTEM:
        return PulseEventBucket.SYSTEM_ACTIVITY

    return PulseEventBucket.UNKNOWN