from datetime import datetime
from types import SimpleNamespace

from daemon.core.context_probe_policy import ContextProbeKind
from daemon.core.context_probe_request import (
    approve_context_probe_request,
    create_context_probe_request,
    refuse_context_probe_request,
)
from daemon.core.context_probe_runner import run_app_context_probe


def _approved_request(kind: ContextProbeKind | str = ContextProbeKind.APP_CONTEXT):
    request = create_context_probe_request(
        kind,
        reason="Need context",
        request_id="probe-1",
        created_at=datetime(2099, 5, 1, 18, 0, 0),
    )
    return approve_context_probe_request(
        request,
        decided_at=datetime(2099, 5, 1, 18, 1, 0),
        decision_reason="User accepted",
    )


def test_run_app_context_probe_captures_only_lightweight_context_fields():
    request = _approved_request()
    context = SimpleNamespace(
        active_app="Code",
        active_project="Pulse",
        activity_level="editing",
        probable_task="coding",
        active_file="/tmp/Pulse/daemon/secret.py",
    )

    result = run_app_context_probe(
        request,
        context,
        captured_at=datetime(2099, 5, 1, 18, 2, 0),
    )

    assert result.captured is True
    assert result.blocked_reason is None
    assert result.request_id == "probe-1"
    assert result.kind == "app_context"
    assert result.privacy == "public"
    assert result.retention == "session"
    assert result.data == {
        "active_app": "Code",
        "active_project": "Pulse",
        "activity_level": "editing",
        "probable_task": "coding",
    }
    assert "active_file" not in result.data
    assert "/tmp/Pulse/daemon/secret.py" not in str(result.to_dict())


def test_run_app_context_probe_blocks_pending_refused_and_expired_requests():
    pending = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="Need app context",
        request_id="pending",
        created_at=datetime(2099, 5, 1, 18, 0, 0),
    )
    refused = refuse_context_probe_request(
        pending,
        decided_at=datetime(2099, 5, 1, 18, 1, 0),
        decision_reason="No",
    )
    expired = approve_context_probe_request(
        create_context_probe_request(
            ContextProbeKind.APP_CONTEXT,
            reason="Expired app context",
            request_id="expired",
            created_at=datetime(2020, 1, 1, 0, 0, 0),
            ttl_sec=0,
        ),
        decided_at=datetime(2020, 1, 1, 0, 0, 1),
    )
    context = SimpleNamespace(active_app="Code")

    pending_result = run_app_context_probe(pending, context, captured_at=datetime(2099, 5, 1, 18, 2, 0))
    refused_result = run_app_context_probe(refused, context, captured_at=datetime(2099, 5, 1, 18, 2, 0))
    expired_result = run_app_context_probe(expired, context, captured_at=datetime(2099, 5, 1, 18, 2, 0))

    assert pending_result.captured is False
    assert pending_result.blocked_reason == "request_not_approved:pending"
    assert pending_result.data == {}

    assert refused_result.captured is False
    assert refused_result.blocked_reason == "request_not_approved:refused"
    assert refused_result.data == {}

    assert expired_result.captured is False
    assert expired_result.blocked_reason == "request_expired"
    assert expired_result.data == {}


def test_run_app_context_probe_rejects_approved_unsupported_probe_kind():
    request = _approved_request(ContextProbeKind.SELECTED_TEXT)
    context = SimpleNamespace(
        active_app="Code",
        active_project="Pulse",
        selected_text="SECRET",
    )

    result = run_app_context_probe(
        request,
        context,
        captured_at=datetime(2099, 5, 1, 18, 2, 0),
    )

    assert result.captured is False
    assert result.kind == "selected_text"
    assert result.blocked_reason == "unsupported_probe_kind"
    assert result.data == {}
    assert "SECRET" not in str(result.to_dict())


def test_run_app_context_probe_rejects_unknown_blocked_policy_before_kind_check():
    request = _approved_request("not_a_probe")
    context = SimpleNamespace(active_app="Code")

    result = run_app_context_probe(
        request,
        context,
        captured_at=datetime(2099, 5, 1, 18, 2, 0),
    )

    assert result.captured is False
    assert result.kind == "unknown"
    assert result.blocked_reason == "policy_blocked"
    assert result.data == {}


def test_run_app_context_probe_normalizes_missing_and_blank_context_values():
    request = _approved_request()
    context = SimpleNamespace(
        active_app="  ",
        active_project=None,
        activity_level="reading",
        probable_task="  debug  ",
    )

    result = run_app_context_probe(
        request,
        context,
        captured_at=datetime(2099, 5, 1, 18, 2, 0),
    )

    assert result.captured is True
    assert result.data == {
        "active_app": None,
        "active_project": None,
        "activity_level": "reading",
        "probable_task": "debug",
    }


def test_context_probe_result_to_dict_is_json_ready():
    request = _approved_request()
    context = SimpleNamespace(
        active_app="Code",
        active_project="Pulse",
        activity_level="editing",
        probable_task="coding",
    )

    result = run_app_context_probe(
        request,
        context,
        captured_at=datetime(2099, 5, 1, 18, 2, 0),
    )

    assert result.to_dict() == {
        "request_id": "probe-1",
        "kind": "app_context",
        "captured": True,
        "data": {
            "active_app": "Code",
            "active_project": "Pulse",
            "activity_level": "editing",
            "probable_task": "coding",
        },
        "privacy": "public",
        "retention": "session",
        "captured_at": "2099-05-01T18:02:00",
        "blocked_reason": None,
    }
