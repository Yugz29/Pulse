

from dataclasses import replace
from datetime import datetime

from daemon.core.context_probe_executor import (
    build_context_probe_execution_plan,
    can_execute_context_probe,
)
from daemon.core.context_probe_policy import ContextProbeKind
from daemon.core.context_probe_request import (
    approve_context_probe_request,
    create_context_probe_request,
    refuse_context_probe_request,
)


def test_execution_plan_allows_approved_non_expired_request():
    request = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="Need app context",
        request_id="probe-1",
        created_at=datetime(2099, 5, 1, 18, 0, 0),
    )
    approved = approve_context_probe_request(
        request,
        decided_at=datetime(2099, 5, 1, 18, 1, 0),
        decision_reason="User accepted",
    )

    plan = build_context_probe_execution_plan(approved)

    assert plan.allowed is True
    assert plan.blocked_reason is None
    assert plan.requires_runtime_probe is True
    assert plan.request_id == "probe-1"
    assert plan.kind == "app_context"
    assert plan.policy["consent"] == "implicit_session"
    assert can_execute_context_probe(approved) is True


def test_execution_plan_blocks_pending_and_refused_requests():
    pending = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="Need app context",
        request_id="probe-pending",
        created_at=datetime(2099, 5, 1, 18, 0, 0),
    )
    refused = refuse_context_probe_request(
        pending,
        decided_at=datetime(2099, 5, 1, 18, 1, 0),
        decision_reason="No",
    )

    pending_plan = build_context_probe_execution_plan(pending)
    refused_plan = build_context_probe_execution_plan(refused)

    assert pending_plan.allowed is False
    assert pending_plan.blocked_reason == "request_not_approved:pending"
    assert pending_plan.requires_runtime_probe is False
    assert can_execute_context_probe(pending) is False

    assert refused_plan.allowed is False
    assert refused_plan.blocked_reason == "request_not_approved:refused"
    assert refused_plan.requires_runtime_probe is False
    assert can_execute_context_probe(refused) is False


def test_execution_plan_blocks_expired_approved_request():
    request = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="Need app context",
        request_id="probe-expired",
        created_at=datetime(2020, 1, 1, 0, 0, 0),
        ttl_sec=0,
    )
    approved = approve_context_probe_request(
        request,
        decided_at=datetime(2020, 1, 1, 0, 0, 1),
    )

    plan = build_context_probe_execution_plan(approved)

    assert plan.allowed is False
    assert plan.blocked_reason == "request_expired"
    assert plan.requires_runtime_probe is False
    assert can_execute_context_probe(approved) is False


def test_execution_plan_blocks_unknown_policy():
    request = create_context_probe_request(
        "not_a_probe",
        reason="Try unknown probe",
        request_id="probe-unknown",
        created_at=datetime(2099, 5, 1, 18, 0, 0),
    )
    approved = approve_context_probe_request(
        request,
        decided_at=datetime(2099, 5, 1, 18, 1, 0),
    )

    plan = build_context_probe_execution_plan(approved)

    assert plan.allowed is False
    assert plan.blocked_reason == "policy_blocked"
    assert plan.requires_runtime_probe is False
    assert plan.policy["consent"] == "blocked"
    assert can_execute_context_probe(approved) is False


def test_execution_plan_blocks_policy_with_persistent_storage_enabled():
    request = create_context_probe_request(
        ContextProbeKind.APP_CONTEXT,
        reason="Need app context",
        request_id="probe-persistent",
        created_at=datetime(2099, 5, 1, 18, 0, 0),
    )
    unsafe_policy = replace(request.policy, allow_persistent_storage=True)
    unsafe_request = replace(request, policy=unsafe_policy)
    approved = approve_context_probe_request(
        unsafe_request,
        decided_at=datetime(2099, 5, 1, 18, 1, 0),
    )

    plan = build_context_probe_execution_plan(approved)

    assert plan.allowed is False
    assert plan.blocked_reason == "persistent_storage_not_allowed_by_gate"
    assert plan.requires_runtime_probe is False
    assert can_execute_context_probe(approved) is False


def test_execution_plan_to_dict_is_json_ready():
    request = create_context_probe_request(
        ContextProbeKind.WINDOW_TITLE,
        reason="Need window title",
        request_id="probe-dict",
        created_at=datetime(2099, 5, 1, 18, 0, 0),
    )
    approved = approve_context_probe_request(
        request,
        decided_at=datetime(2099, 5, 1, 18, 1, 0),
    )

    assert build_context_probe_execution_plan(approved).to_dict() == {
        "request_id": "probe-dict",
        "kind": "window_title",
        "allowed": True,
        "blocked_reason": None,
        "requires_runtime_probe": True,
        "policy": {
            "kind": "window_title",
            "consent": "implicit_session",
            "privacy": "path_sensitive",
            "retention": "session",
            "allow_raw_value": False,
            "allow_persistent_storage": False,
            "requires_user_visible_reason": True,
            "max_chars": 256,
        },
    }