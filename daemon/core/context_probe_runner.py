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


_FOCUSED_TEXT_KINDS = {
    ContextProbeKind.FOCUSED_ELEMENT_TEXT,
    ContextProbeKind.SELECTED_TEXT,
}
_FOCUSED_TEXT_ALLOWED_ROLES = {"AXTextArea", "AXTextField", "AXComboBox"}
_FOCUSED_TEXT_BLOCKED_ROLES = {"AXSecureTextField", "AXWebArea"}
_FOCUSED_TEXT_SOURCES = {"focused_element_text", "selected_text"}
_TEXT_RESULT_SOURCES_BY_KIND = {
    ContextProbeKind.CLIPBOARD_SAMPLE: "next_clipboard_text",
    ContextProbeKind.MANUAL_CONTEXT_NOTE: "manual_context_note",
}


def submit_accessibility_text_probe_result(
    request: ContextProbeRequest,
    payload: Mapping[str, Any],
    *,
    captured_at: Optional[datetime] = None,
) -> ContextProbeResult:
    """Accept a Swift content probe result after validating policy and payload."""
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

    if request.kind in _FOCUSED_TEXT_KINDS:
        return _submit_focused_text_probe_result(request, payload, now)
    if request.kind in _TEXT_RESULT_SOURCES_BY_KIND:
        return _submit_plain_text_probe_result(request, payload, now)

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


def _submit_focused_text_probe_result(
    request: ContextProbeRequest,
    payload: Mapping[str, Any],
    now: datetime,
) -> ContextProbeResult:
    role = _str_or_none(payload.get("role"))
    if role in _FOCUSED_TEXT_BLOCKED_ROLES:
        return _blocked_submit_result(request, now, "forbidden_role")
    if role not in _FOCUSED_TEXT_ALLOWED_ROLES:
        return _blocked_submit_result(request, now, "unsupported_role")

    source = _str_or_none(payload.get("source"))
    if source not in _FOCUSED_TEXT_SOURCES:
        return _blocked_submit_result(request, now, "unsupported_source")
    if request.kind is ContextProbeKind.SELECTED_TEXT and source != "selected_text":
        return _blocked_submit_result(request, now, "kind_source_mismatch")

    raw_value = payload.get("text", payload.get("value"))
    value = _str_or_none(raw_value)
    if value is None:
        return _blocked_submit_result(request, now, "missing_text")

    redaction = redact_context_probe_value(
        value,
        max_chars=request.policy.max_chars or 2_000,
    )
    original_char_count = _payload_char_count(payload, value)

    return ContextProbeResult(
        request_id=request.request_id,
        kind=request.kind.value,
        captured=True,
        data={
            "app_name": _str_or_none(payload.get("app_name")),
            "bundle_id": _str_or_none(payload.get("bundle_id")),
            "role": role,
            "source": source,
            "char_count": original_char_count,
            "client_truncated": bool(payload.get("truncated", False)),
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


def _submit_plain_text_probe_result(
    request: ContextProbeRequest,
    payload: Mapping[str, Any],
    now: datetime,
) -> ContextProbeResult:
    source = _str_or_none(payload.get("source"))
    if source != _TEXT_RESULT_SOURCES_BY_KIND[request.kind]:
        return _blocked_submit_result(request, now, "kind_source_mismatch")

    value = _str_or_none(payload.get("text", payload.get("value")))
    if value is None:
        return _blocked_submit_result(request, now, "missing_text")

    redaction = redact_context_probe_value(
        value,
        max_chars=request.policy.max_chars or 2_000,
    )
    original_char_count = _payload_char_count(payload, value)

    return ContextProbeResult(
        request_id=request.request_id,
        kind=request.kind.value,
        captured=True,
        data={
            "source": source,
            "content_kind": _str_or_none(payload.get("content_kind")) or "text",
            "char_count": original_char_count,
            "client_truncated": bool(payload.get("truncated", False)),
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


def _payload_char_count(payload: Mapping[str, Any], value: str) -> int:
    try:
        return max(int(payload.get("char_count", len(value))), 0)
    except (TypeError, ValueError):
        return len(value)


def submit_context_probe_result(
    request: ContextProbeRequest,
    payload: Mapping[str, Any],
    *,
    captured_at: Optional[datetime] = None,
) -> ContextProbeResult:
    """Alias for the generic content result submission path."""
    return submit_accessibility_text_probe_result(request, payload, captured_at=captured_at)


def _blocked_submit_result(
    request: ContextProbeRequest,
    now: datetime,
    reason: str,
) -> ContextProbeResult:
    return ContextProbeResult(
        request_id=request.request_id,
        kind=request.kind.value,
        captured=False,
        data={},
        privacy=request.policy.privacy.value,
        retention=request.policy.retention.value,
        captured_at=now,
        blocked_reason=reason,
    )


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
