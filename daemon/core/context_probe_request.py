

"""Passive request contracts for future context probes.

A ContextProbeRequest represents an intent to read contextual information before
any probe executes. It carries the reason, the safety policy, and the approval
state needed for human-controlled context access.

This module does not capture data, execute probes, persist requests, or mutate
runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Mapping, Optional

from daemon.core.context_probe_policy import ContextProbeKind, ContextProbePolicy, policy_for_probe
from daemon.core.uid import new_uid


class ContextProbeRequestStatus(str, Enum):
    """Lifecycle states for a context probe request."""

    PENDING = "pending"
    APPROVED = "approved"
    REFUSED = "refused"
    EXPIRED = "expired"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


_TERMINAL_STATUSES = {
    ContextProbeRequestStatus.REFUSED,
    ContextProbeRequestStatus.EXPIRED,
    ContextProbeRequestStatus.EXECUTED,
    ContextProbeRequestStatus.CANCELLED,
}


@dataclass(frozen=True)
class ContextProbeRequest:
    """Passive description of a requested context probe."""

    request_id: str
    kind: ContextProbeKind
    reason: str
    policy: ContextProbePolicy
    status: ContextProbeRequestStatus = ContextProbeRequestStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    decision_reason: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """Return whether the request can no longer transition normally."""
        return self.status in _TERMINAL_STATUSES

    @property
    def is_expired(self) -> bool:
        """Return whether the request is past its expiry time."""
        return self.expires_at is not None and datetime.now() >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation without raw metadata values."""
        return {
            "request_id": self.request_id,
            "kind": self.kind.value,
            "reason": self.reason,
            "policy": self.policy.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "decision_reason": self.decision_reason,
            "metadata_keys": sorted(self.metadata.keys()),
            "is_terminal": self.is_terminal,
        }


def create_context_probe_request(
    kind: ContextProbeKind | str,
    *,
    reason: str,
    request_id: Optional[str] = None,
    created_at: Optional[datetime] = None,
    ttl_sec: int = 300,
    metadata: Mapping[str, Any] | None = None,
) -> ContextProbeRequest:
    """Create a pending context probe request with the default policy."""
    created = created_at or datetime.now()
    policy = policy_for_probe(kind)
    clean_reason = reason.strip()
    if not clean_reason:
        clean_reason = "Context probe requested"

    return ContextProbeRequest(
        request_id=request_id or new_uid(),
        kind=policy.kind,
        reason=clean_reason,
        policy=policy,
        created_at=created,
        expires_at=created + timedelta(seconds=max(ttl_sec, 0)),
        metadata=metadata or {},
    )


def approve_context_probe_request(
    request: ContextProbeRequest,
    *,
    decided_at: Optional[datetime] = None,
    decision_reason: Optional[str] = None,
) -> ContextProbeRequest:
    """Return an approved copy of a pending request."""
    _ensure_pending(request)
    return replace(
        request,
        status=ContextProbeRequestStatus.APPROVED,
        decided_at=decided_at or datetime.now(),
        decision_reason=decision_reason,
    )


def refuse_context_probe_request(
    request: ContextProbeRequest,
    *,
    decided_at: Optional[datetime] = None,
    decision_reason: Optional[str] = None,
) -> ContextProbeRequest:
    """Return a refused copy of a pending request."""
    _ensure_pending(request)
    return replace(
        request,
        status=ContextProbeRequestStatus.REFUSED,
        decided_at=decided_at or datetime.now(),
        decision_reason=decision_reason,
    )


def expire_context_probe_request(
    request: ContextProbeRequest,
    *,
    decided_at: Optional[datetime] = None,
) -> ContextProbeRequest:
    """Return an expired copy of a pending request."""
    _ensure_pending(request)
    return replace(
        request,
        status=ContextProbeRequestStatus.EXPIRED,
        decided_at=decided_at or datetime.now(),
        decision_reason="expired",
    )


def execute_context_probe_request(
    request: ContextProbeRequest,
    *,
    executed_at: Optional[datetime] = None,
) -> ContextProbeRequest:
    """Return an executed copy of an approved request.

    Execution here means only a lifecycle transition. This function does not run
    any actual context probe.
    """
    if request.status is not ContextProbeRequestStatus.APPROVED:
        raise ValueError("Only approved context probe requests can be executed")
    return replace(
        request,
        status=ContextProbeRequestStatus.EXECUTED,
        executed_at=executed_at or datetime.now(),
    )


def cancel_context_probe_request(
    request: ContextProbeRequest,
    *,
    decided_at: Optional[datetime] = None,
    decision_reason: Optional[str] = None,
) -> ContextProbeRequest:
    """Return a cancelled copy of a non-terminal request."""
    if request.is_terminal:
        raise ValueError("Terminal context probe requests cannot transition")
    return replace(
        request,
        status=ContextProbeRequestStatus.CANCELLED,
        decided_at=decided_at or datetime.now(),
        decision_reason=decision_reason or "cancelled",
    )


def _ensure_pending(request: ContextProbeRequest) -> None:
    if request.status is not ContextProbeRequestStatus.PENDING:
        raise ValueError("Only pending context probe requests can transition this way")