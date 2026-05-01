from datetime import datetime

from daemon.core.context_probe_debug import describe_context_probe_request_for_debug
from daemon.core.context_probe_policy import ContextProbeKind
from daemon.core.context_probe_request import (
    approve_context_probe_request,
    create_context_probe_request,
    execute_context_probe_request,
    refuse_context_probe_request,
)


def test_describe_context_probe_request_for_debug_is_json_ready_without_metadata_values():
    request = create_context_probe_request(
        ContextProbeKind.SELECTED_TEXT,
        reason="Explain selected error",
        request_id="probe-1",
        created_at=datetime(2099, 5, 1, 18, 0, 0),
        ttl_sec=120,
        metadata={"raw_selection": "SECRET", "source": "test"},
    )

    description = describe_context_probe_request_for_debug(request)

    assert description == {
        "request_id": "probe-1",
        "kind": "selected_text",
        "status": "pending",
        "reason": "Explain selected error",
        "created_at": "2099-05-01T18:00:00",
        "expires_at": "2099-05-01T18:02:00",
        "decided_at": None,
        "executed_at": None,
        "decision_reason": None,
        "is_terminal": False,
        "is_expired": False,
        "policy": {
            "kind": "selected_text",
            "consent": "explicit_each_time",
            "privacy": "content_sensitive",
            "retention": "ephemeral",
            "allow_raw_value": False,
            "allow_persistent_storage": False,
            "requires_user_visible_reason": True,
            "max_chars": 2000,
        },
        "labels": {
            "kind": "Selected text",
            "consent": "Requires explicit approval every time",
            "privacy": "Content-sensitive context",
            "retention": "Ephemeral by default",
            "risk": "Sensitive",
        },
        "metadata_keys": ["raw_selection", "source"],
    }
    assert "SECRET" not in str(description)
    assert "metadata" not in description


def test_describe_context_probe_request_for_debug_labels_low_moderate_sensitive_and_blocked_risk():
    app_context = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="Need app metadata",
        request_id="probe-app",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )
    window_title = create_context_probe_request(
        ContextProbeKind.WINDOW_TITLE,
        reason="Need window title",
        request_id="probe-window",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )
    screen_snapshot = create_context_probe_request(
        ContextProbeKind.SCREEN_SNAPSHOT,
        reason="Need visual context",
        request_id="probe-screen",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )
    unknown = create_context_probe_request(
        "not_a_probe",
        reason="Unknown probe",
        request_id="probe-unknown",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )

    assert describe_context_probe_request_for_debug(app_context)["labels"]["risk"] == "Low"
    assert describe_context_probe_request_for_debug(window_title)["labels"]["risk"] == "Moderate"
    assert describe_context_probe_request_for_debug(screen_snapshot)["labels"]["risk"] == "Sensitive"
    assert describe_context_probe_request_for_debug(unknown)["labels"]["risk"] == "Blocked"


def test_describe_context_probe_request_for_debug_reflects_decision_and_execution_state():
    request = create_context_probe_request(
        ContextProbeKind.WINDOW_TITLE,
        reason="Need window metadata",
        request_id="probe-2",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )
    approved = approve_context_probe_request(
        request,
        decided_at=datetime(2026, 5, 1, 18, 1, 0),
        decision_reason="User accepted",
    )
    executed = execute_context_probe_request(
        approved,
        executed_at=datetime(2026, 5, 1, 18, 2, 0),
    )

    description = describe_context_probe_request_for_debug(executed)

    assert description["status"] == "executed"
    assert description["decided_at"] == "2026-05-01T18:01:00"
    assert description["executed_at"] == "2026-05-01T18:02:00"
    assert description["decision_reason"] == "User accepted"
    assert description["is_terminal"] is True
    assert description["labels"]["kind"] == "Window title"
    assert description["labels"]["consent"] == "Allowed for this session"
    assert description["labels"]["privacy"] == "Path-sensitive metadata"
    assert description["labels"]["retention"] == "Session-scoped by default"


def test_describe_context_probe_request_for_debug_refused_request():
    request = create_context_probe_request(
        ContextProbeKind.CLIPBOARD_SAMPLE,
        reason="Need clipboard sample",
        request_id="probe-3",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
    )
    refused = refuse_context_probe_request(
        request,
        decided_at=datetime(2026, 5, 1, 18, 1, 0),
        decision_reason="Too sensitive",
    )

    description = describe_context_probe_request_for_debug(refused)

    assert description["status"] == "refused"
    assert description["decision_reason"] == "Too sensitive"
    assert description["is_terminal"] is True
    assert description["labels"] == {
        "kind": "Clipboard sample",
        "consent": "Requires explicit approval every time",
        "privacy": "Content-sensitive context",
        "retention": "Ephemeral by default",
        "risk": "Sensitive",
    }