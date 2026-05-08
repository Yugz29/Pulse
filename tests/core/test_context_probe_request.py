

from datetime import datetime, timedelta

import pytest

from daemon.core.context_probe_policy import ContextProbeConsent, ContextProbeKind
from daemon.core.context_probe_request import (
    ContextProbeRequestStatus,
    approve_context_probe_request,
    cancel_context_probe_request,
    create_context_probe_request,
    execute_context_probe_request,
    expire_context_probe_request,
    refuse_context_probe_request,
)
from daemon.core.event_envelope import PulsePrivacyClass, PulseRetention


def test_create_context_probe_request_uses_default_policy_and_expiry():
    created_at = datetime(2026, 5, 1, 18, 0, 0)

    request = create_context_probe_request(
        ContextProbeKind.SELECTED_TEXT,
        reason="Explain selected error",
        request_id="probe-1",
        created_at=created_at,
        ttl_sec=120,
        metadata={"raw_selection": "secret text", "source": "test"},
    )

    assert request.request_id == "probe-1"
    assert request.kind is ContextProbeKind.SELECTED_TEXT
    assert request.reason == "Explain selected error"
    assert request.status is ContextProbeRequestStatus.PENDING
    assert request.created_at == created_at
    assert request.expires_at == created_at + timedelta(seconds=120)
    assert request.policy.consent is ContextProbeConsent.EXPLICIT_EACH_TIME
    assert request.policy.privacy is PulsePrivacyClass.CONTENT_SENSITIVE
    assert request.policy.retention is PulseRetention.EPHEMERAL
    assert request.is_terminal is False


def test_context_probe_request_to_dict_is_json_ready_without_raw_metadata_values():
    created_at = datetime(2026, 5, 1, 18, 0, 0)
    request = create_context_probe_request(
        "clipboard_sample",
        reason="  Need clipboard context  ",
        request_id="probe-2",
        created_at=created_at,
        ttl_sec=60,
        metadata={"clipboard_raw": "SECRET", "source": "test"},
    )

    payload = request.to_dict()

    assert payload["request_id"] == "probe-2"
    assert payload["kind"] == "clipboard_sample"
    assert payload["reason"] == "Need clipboard context"
    assert payload["status"] == "pending"
    assert payload["created_at"] == "2026-05-01T18:00:00"
    assert payload["expires_at"] == "2026-05-01T18:01:00"
    assert payload["metadata_keys"] == ["clipboard_raw", "source"]
    assert payload["is_terminal"] is False
    assert "SECRET" not in str(payload)
    assert "metadata" not in payload


def test_empty_reason_falls_back_to_generic_reason():
    request = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="   ",
        request_id="probe-empty-reason",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )

    assert request.reason == "Context probe requested"


def test_approve_refuse_and_expire_transitions_from_pending():
    created_at = datetime(2026, 5, 1, 18, 0, 0)
    decided_at = datetime(2026, 5, 1, 18, 1, 0)
    request = create_context_probe_request(
        ContextProbeKind.SCREEN_SNAPSHOT,
        reason="Need visual context",
        request_id="probe-3",
        created_at=created_at,
    )

    approved = approve_context_probe_request(request, decided_at=decided_at, decision_reason="User accepted")
    refused = refuse_context_probe_request(request, decided_at=decided_at, decision_reason="Too sensitive")
    expired = expire_context_probe_request(request, decided_at=decided_at)

    assert approved.status is ContextProbeRequestStatus.APPROVED
    assert approved.decided_at == decided_at
    assert approved.decision_reason == "User accepted"
    assert approved.is_terminal is False

    assert refused.status is ContextProbeRequestStatus.REFUSED
    assert refused.decided_at == decided_at
    assert refused.decision_reason == "Too sensitive"
    assert refused.is_terminal is True

    assert expired.status is ContextProbeRequestStatus.EXPIRED
    assert expired.decided_at == decided_at
    assert expired.decision_reason == "expired"
    assert expired.is_terminal is True

    assert request.status is ContextProbeRequestStatus.PENDING


def test_execute_requires_approved_request():
    created_at = datetime(2026, 5, 1, 18, 0, 0)
    executed_at = datetime(2026, 5, 1, 18, 2, 0)
    request = create_context_probe_request(
        ContextProbeKind.WINDOW_TITLE,
        reason="Need window metadata",
        request_id="probe-4",
        created_at=created_at,
    )
    approved = approve_context_probe_request(request, decided_at=datetime(2026, 5, 1, 18, 1, 0))

    executed = execute_context_probe_request(approved, executed_at=executed_at)

    assert executed.status is ContextProbeRequestStatus.EXECUTED
    assert executed.executed_at == executed_at
    assert executed.is_terminal is True

    with pytest.raises(ValueError, match="Only approved context probe requests can be executed"):
        execute_context_probe_request(request)


def test_cancel_allowed_for_non_terminal_requests_only():
    request = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="Need app context",
        request_id="probe-5",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )
    approved = approve_context_probe_request(request, decided_at=datetime(2026, 5, 1, 18, 1, 0))
    refused = refuse_context_probe_request(request, decided_at=datetime(2026, 5, 1, 18, 1, 0))

    cancelled_pending = cancel_context_probe_request(request, decision_reason="No longer needed")
    cancelled_approved = cancel_context_probe_request(approved)

    assert cancelled_pending.status is ContextProbeRequestStatus.CANCELLED
    assert cancelled_pending.decision_reason == "No longer needed"
    assert cancelled_pending.is_terminal is True
    assert cancelled_approved.status is ContextProbeRequestStatus.CANCELLED
    assert cancelled_approved.decision_reason == "cancelled"

    with pytest.raises(ValueError, match="Terminal context probe requests cannot transition"):
        cancel_context_probe_request(refused)


def test_pending_only_transitions_reject_non_pending_requests():
    request = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="Need app context",
        request_id="probe-6",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )
    approved = approve_context_probe_request(request, decided_at=datetime(2026, 5, 1, 18, 1, 0))

    with pytest.raises(ValueError, match="Only pending context probe requests can transition this way"):
        approve_context_probe_request(approved)

    with pytest.raises(ValueError, match="Only pending context probe requests can transition this way"):
        refuse_context_probe_request(approved)

    with pytest.raises(ValueError, match="Only pending context probe requests can transition this way"):
        expire_context_probe_request(approved)


def test_request_expiry_property_uses_expires_at():
    expired = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="Expired request",
        request_id="probe-expired",
        created_at=datetime(2020, 1, 1, 0, 0, 0),
        ttl_sec=0,
    )
    no_expiry = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="No expiry request",
        request_id="probe-no-expiry",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )
    no_expiry = type(no_expiry)(
        request_id=no_expiry.request_id,
        kind=no_expiry.kind,
        reason=no_expiry.reason,
        policy=no_expiry.policy,
        status=no_expiry.status,
        created_at=no_expiry.created_at,
        expires_at=None,
        metadata=no_expiry.metadata,
    )

    assert expired.is_expired is True
    assert no_expiry.is_expired is False