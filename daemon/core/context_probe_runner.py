"""Minimal context probe runners.

This module executes only bounded probe categories introduced so far.
It does not read the screen, clipboard, selected text, files, or window content
itself. It only extracts fields from an already available runtime/context object
after the execution gate has allowed the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from daemon.core.context_probe_executor import build_context_probe_execution_plan
from daemon.core.context_probe_policy import ContextProbeKind
from daemon.core.context_probe_request import ContextProbeRequest
from daemon.core.context_probe_redaction import redact_context_probe_value


@dataclass(frozen=True)
class ContextProbeResult:
    """Result of a context probe execution."""

    request_id: str
    kind: str
    captured: bool
    data: Mapping[str, Any]
    privacy: str
    retention: str
    captured_at: datetime
    blocked_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "request_id": self.request_id,
            "kind": self.kind,
            "captured": self.captured,
            "data": dict(self.data),
            "privacy": self.privacy,
            "retention": self.retention,
            "captured_at": self.captured_at.isoformat(),
            "blocked_reason": self.blocked_reason,
        }


def run_app_context_probe(
    request: ContextProbeRequest,
    context: Any,
    *,
    captured_at: Optional[datetime] = None,
) -> ContextProbeResult:
    """Run the minimal app_context probe after checking the execution gate.

    The probe extracts only lightweight runtime context fields:
    - active_app
    - active_project
    - activity_level
    - probable_task

    It intentionally does not return active_file or any raw content.
    """
    plan = build_context_probe_execution_plan(request)
    now = captured_at or datetime.now()

    if not plan.allowed:
        return ContextProbeResult(
            request_id=request.request_id,
            kind=request.kind.value,
            captured=False,
            data={},
            privacy=request.policy.privacy.value,
            retention=request.policy.retention.value,
            captured_at=now,
            blocked_reason=plan.blocked_reason,
        )

    if request.kind is not ContextProbeKind.APP_CONTEXT:
        return ContextProbeResult(
            request_id=request.request_id,
            kind=request.kind.value,
            captured=False,
            data={},
            privacy=request.policy.privacy.value,
            retention=request.policy.retention.value,
            captured_at=now,
            blocked_reason="unsupported_probe_kind",
        )

    return ContextProbeResult(
        request_id=request.request_id,
        kind=request.kind.value,
        captured=True,
        data={
            "active_app": _str_or_none(getattr(context, "active_app", None)),
            "active_project": _str_or_none(getattr(context, "active_project", None)),
            "activity_level": _str_or_none(getattr(context, "activity_level", None)),
            "probable_task": _str_or_none(getattr(context, "probable_task", None)),
        },
        privacy=request.policy.privacy.value,
        retention=request.policy.retention.value,
        captured_at=now,
        blocked_reason=None,
    )


def run_window_title_probe(
    request: ContextProbeRequest,
    context: Any,
    *,
    captured_at: Optional[datetime] = None,
) -> ContextProbeResult:
    """Run a redacted window_title probe after checking the execution gate.

    The raw window title must already be available on the provided context
    object. This runner does not query macOS, Accessibility APIs, or any window
    system directly.
    """
    plan = build_context_probe_execution_plan(request)
    now = captured_at or datetime.now()

    if not plan.allowed:
        return ContextProbeResult(
            request_id=request.request_id,
            kind=request.kind.value,
            captured=False,
            data={},
            privacy=request.policy.privacy.value,
            retention=request.policy.retention.value,
            captured_at=now,
            blocked_reason=plan.blocked_reason,
        )

    if request.kind is not ContextProbeKind.WINDOW_TITLE:
        return ContextProbeResult(
            request_id=request.request_id,
            kind=request.kind.value,
            captured=False,
            data={},
            privacy=request.policy.privacy.value,
            retention=request.policy.retention.value,
            captured_at=now,
            blocked_reason="unsupported_probe_kind",
        )

    raw_title = _str_or_none(getattr(context, "window_title", None))
    if raw_title is None:
        return ContextProbeResult(
            request_id=request.request_id,
            kind=request.kind.value,
            captured=False,
            data={},
            privacy=request.policy.privacy.value,
            retention=request.policy.retention.value,
            captured_at=now,
            blocked_reason="missing_window_title",
        )

    redaction = redact_context_probe_value(
        raw_title,
        max_chars=request.policy.max_chars or 256,
    )
    return ContextProbeResult(
        request_id=request.request_id,
        kind=request.kind.value,
        captured=True,
        data={
            "redacted_value": redaction.redacted_value,
            "redaction_flags": [flag.value for flag in redaction.flags],
            "original_length": redaction.original_length,
            "redacted_length": redaction.redacted_length,
            "was_redacted": redaction.was_redacted,
        },
        privacy=request.policy.privacy.value,
        retention=request.policy.retention.value,
        captured_at=now,
        blocked_reason=None,
    )


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None