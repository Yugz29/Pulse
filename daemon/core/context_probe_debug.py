

"""Passive debug helpers for context probe requests.

This module prepares future approval/consent UI rendering. It does not execute
probes, persist requests, mutate runtime state, or expose raw metadata values.
"""

from __future__ import annotations

from typing import Any

from daemon.core.context_probe_policy import ContextProbeConsent, ContextProbeKind
from daemon.core.context_probe_request import ContextProbeRequest


def describe_context_probe_request_for_debug(request: ContextProbeRequest) -> dict[str, Any]:
    """Return a debug/approval-friendly description of a probe request."""
    return {
        "request_id": request.request_id,
        "kind": request.kind.value,
        "status": request.status.value,
        "reason": request.reason,
        "created_at": request.created_at.isoformat(),
        "expires_at": request.expires_at.isoformat() if request.expires_at else None,
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
        "executed_at": request.executed_at.isoformat() if request.executed_at else None,
        "decision_reason": request.decision_reason,
        "is_terminal": request.is_terminal,
        "is_expired": request.is_expired,
        "policy": request.policy.to_dict(),
        "labels": {
            "kind": _kind_label(request.kind),
            "consent": _consent_label(request.policy.consent),
            "privacy": _privacy_label(request),
            "retention": _retention_label(request),
            "risk": _risk_label(request),
        },
        "metadata_keys": sorted(request.metadata.keys()),
    }


def _kind_label(kind: ContextProbeKind) -> str:
    labels = {
        ContextProbeKind.APP_CONTEXT: "Application context",
        ContextProbeKind.WINDOW_TITLE: "Window title",
        ContextProbeKind.SELECTED_TEXT: "Selected text",
        ContextProbeKind.CLIPBOARD_SAMPLE: "Clipboard sample",
        ContextProbeKind.SCREEN_SNAPSHOT: "Screen snapshot",
        ContextProbeKind.UNKNOWN: "Unknown probe",
    }
    return labels[kind]


def _consent_label(consent: ContextProbeConsent) -> str:
    labels = {
        ContextProbeConsent.NONE: "No consent required",
        ContextProbeConsent.IMPLICIT_SESSION: "Allowed for this session",
        ContextProbeConsent.EXPLICIT_EACH_TIME: "Requires explicit approval every time",
        ContextProbeConsent.BLOCKED: "Blocked by default",
    }
    return labels[consent]


def _privacy_label(request: ContextProbeRequest) -> str:
    labels = {
        "public": "Low sensitivity metadata",
        "path_sensitive": "Path-sensitive metadata",
        "content_sensitive": "Content-sensitive context",
        "secret_sensitive": "Potential secret-sensitive context",
        "unknown": "Unknown sensitivity",
    }
    return labels[request.policy.privacy.value]


def _retention_label(request: ContextProbeRequest) -> str:
    labels = {
        "ephemeral": "Ephemeral by default",
        "session": "Session-scoped by default",
        "persistent": "Persistent storage candidate",
        "debug_only": "Debug-only by default",
    }
    return labels[request.policy.retention.value]


def _risk_label(request: ContextProbeRequest) -> str:
    if request.policy.consent is ContextProbeConsent.BLOCKED:
        return "Blocked"
    if request.policy.privacy.value in {"secret_sensitive", "content_sensitive"}:
        return "Sensitive"
    if request.policy.privacy.value == "path_sensitive":
        return "Moderate"
    return "Low"