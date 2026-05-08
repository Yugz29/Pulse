

"""Passive safety policy contracts for future context probes.

Context probes are optional, explicit context reads such as current app/window
metadata, selected text, clipboard samples, or a future screen snapshot.

This module does not capture anything. It only defines the policy surface that
must exist before any probe implementation is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from daemon.core.event_envelope import PulsePrivacyClass, PulseRetention


class ContextProbeKind(str, Enum):
    """Supported future probe categories."""

    APP_CONTEXT = "app_context"
    WINDOW_TITLE = "window_title"
    SELECTED_TEXT = "selected_text"
    CLIPBOARD_SAMPLE = "clipboard_sample"
    SCREEN_SNAPSHOT = "screen_snapshot"
    UNKNOWN = "unknown"


class ContextProbeConsent(str, Enum):
    """Consent level required before a probe may run."""

    NONE = "none"
    IMPLICIT_SESSION = "implicit_session"
    EXPLICIT_EACH_TIME = "explicit_each_time"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ContextProbePolicy:
    """Safety policy attached to a future context probe.

    The policy is intentionally conservative. Probe implementations should use
    this as a hard pre-flight contract before reading any contextual data.
    """

    kind: ContextProbeKind
    consent: ContextProbeConsent
    privacy: PulsePrivacyClass
    retention: PulseRetention
    allow_raw_value: bool = False
    allow_persistent_storage: bool = False
    requires_user_visible_reason: bool = True
    max_chars: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "kind": self.kind.value,
            "consent": self.consent.value,
            "privacy": self.privacy.value,
            "retention": self.retention.value,
            "allow_raw_value": self.allow_raw_value,
            "allow_persistent_storage": self.allow_persistent_storage,
            "requires_user_visible_reason": self.requires_user_visible_reason,
            "max_chars": self.max_chars,
        }


def policy_for_probe(kind: ContextProbeKind | str) -> ContextProbePolicy:
    """Return the default safety policy for a probe kind.

    Defaults are deliberately strict:
    - metadata probes can run with session-level consent;
    - content probes require explicit per-use consent;
    - raw values are never allowed by default;
    - persistent storage is never allowed by default.
    """
    probe_kind = _coerce_probe_kind(kind)

    if probe_kind is ContextProbeKind.APP_CONTEXT:
        return ContextProbePolicy(
            kind=probe_kind,
            consent=ContextProbeConsent.IMPLICIT_SESSION,
            privacy=PulsePrivacyClass.PUBLIC,
            retention=PulseRetention.SESSION,
            max_chars=256,
        )

    if probe_kind is ContextProbeKind.WINDOW_TITLE:
        return ContextProbePolicy(
            kind=probe_kind,
            consent=ContextProbeConsent.IMPLICIT_SESSION,
            privacy=PulsePrivacyClass.PATH_SENSITIVE,
            retention=PulseRetention.SESSION,
            max_chars=256,
        )

    if probe_kind is ContextProbeKind.SELECTED_TEXT:
        return ContextProbePolicy(
            kind=probe_kind,
            consent=ContextProbeConsent.EXPLICIT_EACH_TIME,
            privacy=PulsePrivacyClass.CONTENT_SENSITIVE,
            retention=PulseRetention.EPHEMERAL,
            max_chars=2_000,
        )

    if probe_kind is ContextProbeKind.CLIPBOARD_SAMPLE:
        return ContextProbePolicy(
            kind=probe_kind,
            consent=ContextProbeConsent.EXPLICIT_EACH_TIME,
            privacy=PulsePrivacyClass.CONTENT_SENSITIVE,
            retention=PulseRetention.EPHEMERAL,
            max_chars=1_000,
        )

    if probe_kind is ContextProbeKind.SCREEN_SNAPSHOT:
        return ContextProbePolicy(
            kind=probe_kind,
            consent=ContextProbeConsent.EXPLICIT_EACH_TIME,
            privacy=PulsePrivacyClass.CONTENT_SENSITIVE,
            retention=PulseRetention.EPHEMERAL,
            max_chars=None,
        )

    return ContextProbePolicy(
        kind=ContextProbeKind.UNKNOWN,
        consent=ContextProbeConsent.BLOCKED,
        privacy=PulsePrivacyClass.UNKNOWN,
        retention=PulseRetention.DEBUG_ONLY,
        max_chars=None,
    )


def is_probe_allowed_by_default(kind: ContextProbeKind | str) -> bool:
    """Return whether a probe may run without explicit per-use consent."""
    policy = policy_for_probe(kind)
    return policy.consent in {ContextProbeConsent.NONE, ContextProbeConsent.IMPLICIT_SESSION}


def _coerce_probe_kind(kind: ContextProbeKind | str) -> ContextProbeKind:
    if isinstance(kind, ContextProbeKind):
        return kind
    try:
        return ContextProbeKind(str(kind))
    except ValueError:
        return ContextProbeKind.UNKNOWN