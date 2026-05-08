from datetime import datetime

import pytest

from daemon.core.context_probe_policy import ContextProbeKind
from daemon.core.context_probe_request import (
    ContextProbeRequestStatus,
    approve_context_probe_request,
    create_context_probe_request,
    refuse_context_probe_request,
)
from daemon.core.context_probe_store import ContextProbeRequestStore, requests_to_dicts


def _request(
    request_id: str,
    kind: ContextProbeKind = ContextProbeKind.APP_CONTEXT,
    *,
    created_at: datetime | None = None,
    ttl_sec: int = 300,
):
    return create_context_probe_request(
        kind,
        reason=f"Reason for {request_id}",
        request_id=request_id,
        created_at=created_at or datetime(2026, 5, 1, 18, 0, 0),
        ttl_sec=ttl_sec,
    )


def test_store_add_get_and_len():
    store = ContextProbeRequestStore()
    request = _request("probe-1")

    stored = store.add(request)

    assert stored is request
    assert store.get("probe-1") is request
    assert store.get("missing") is None
    assert len(store) == 1


def test_store_add_replaces_same_request_id():
    store = ContextProbeRequestStore()
    first = _request("probe-1", ContextProbeKind.APP_CONTEXT)
    second = _request("probe-1", ContextProbeKind.SELECTED_TEXT)

    store.add(first)
    store.add(second)

    assert store.get("probe-1") is second
    assert len(store) == 1


def test_store_update_requires_existing_request():
    store = ContextProbeRequestStore()
    request = _request("probe-1")
    approved = approve_context_probe_request(
        request,
        decided_at=datetime(2026, 5, 1, 18, 1, 0),
        decision_reason="accepted",
    )

    with pytest.raises(KeyError):
        store.update(approved)

    store.add(request)
    updated = store.update(approved)

    assert updated is approved
    assert store.get("probe-1") is approved


def test_store_list_orders_by_created_at_and_filters_status():
    store = ContextProbeRequestStore()
    later = _request("later", created_at=datetime(2026, 5, 1, 18, 2, 0))
    earlier = _request("earlier", created_at=datetime(2026, 5, 1, 18, 0, 0))
    refused = refuse_context_probe_request(
        _request("refused", created_at=datetime(2026, 5, 1, 18, 1, 0)),
        decided_at=datetime(2026, 5, 1, 18, 1, 30),
        decision_reason="too sensitive",
    )

    store.add(later)
    store.add(earlier)
    store.add(refused)

    assert [request.request_id for request in store.list()] == ["earlier", "refused", "later"]
    assert [request.request_id for request in store.list(status=ContextProbeRequestStatus.PENDING)] == ["earlier", "later"]
    assert [request.request_id for request in store.list(status="refused")] == ["refused"]
    assert [request.request_id for request in store.list(include_terminal=False)] == ["earlier", "later"]


def test_store_remove_and_clear():
    store = ContextProbeRequestStore()
    first = _request("probe-1")
    second = _request("probe-2")
    store.add(first)
    store.add(second)

    removed = store.remove("probe-1")

    assert removed is first
    assert store.get("probe-1") is None
    assert store.remove("missing") is None
    assert len(store) == 1

    store.clear()

    assert len(store) == 0
    assert store.list() == []


def test_store_expire_due_only_expires_pending_due_requests():
    store = ContextProbeRequestStore()
    now = datetime(2026, 5, 1, 18, 10, 0)
    due = _request("due", created_at=datetime(2026, 5, 1, 18, 0, 0), ttl_sec=60)
    future = _request("future", created_at=datetime(2026, 5, 1, 18, 9, 30), ttl_sec=120)
    already_refused = refuse_context_probe_request(
        _request("refused", created_at=datetime(2026, 5, 1, 18, 0, 0), ttl_sec=60),
        decided_at=datetime(2026, 5, 1, 18, 1, 0),
    )
    store.add(due)
    store.add(future)
    store.add(already_refused)

    expired = store.expire_due(now=now)

    assert [request.request_id for request in expired] == ["due"]
    assert store.get("due").status is ContextProbeRequestStatus.EXPIRED
    assert store.get("due").decided_at == now
    assert store.get("due").decision_reason == "expired"
    assert store.get("future").status is ContextProbeRequestStatus.PENDING
    assert store.get("refused").status is ContextProbeRequestStatus.REFUSED


def test_store_remove_terminal_removes_only_terminal_requests_ordered_by_created_at():
    store = ContextProbeRequestStore()
    pending = _request("pending", created_at=datetime(2026, 5, 1, 18, 3, 0))
    refused = refuse_context_probe_request(
        _request("refused", created_at=datetime(2026, 5, 1, 18, 1, 0)),
        decided_at=datetime(2026, 5, 1, 18, 2, 0),
    )
    approved = approve_context_probe_request(
        _request("approved", created_at=datetime(2026, 5, 1, 18, 0, 0)),
        decided_at=datetime(2026, 5, 1, 18, 1, 0),
    )
    store.add(pending)
    store.add(refused)
    store.add(approved)

    removed = store.remove_terminal()

    assert [request.request_id for request in removed] == ["refused"]
    assert store.get("refused") is None
    assert store.get("pending") is pending
    assert store.get("approved") is approved


def test_requests_to_dicts_returns_json_ready_payloads_without_metadata_values():
    request = create_context_probe_request(
        ContextProbeKind.CLIPBOARD_SAMPLE,
        reason="Need clipboard sample",
        request_id="probe-1",
        created_at=datetime(2026, 5, 1, 18, 0, 0),
        metadata={"raw_clipboard": "SECRET", "source": "test"},
    )

    payloads = requests_to_dicts([request])

    assert payloads[0]["request_id"] == "probe-1"
    assert payloads[0]["kind"] == "clipboard_sample"
    assert payloads[0]["metadata_keys"] == ["raw_clipboard", "source"]
    assert "metadata" not in payloads[0]
    assert "SECRET" not in str(payloads)


def test_store_list_rejects_invalid_status_string():
    store = ContextProbeRequestStore()

    with pytest.raises(ValueError):
        store.list(status="not_a_status")