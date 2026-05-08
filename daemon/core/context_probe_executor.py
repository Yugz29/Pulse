"""Passive execution gate for future context probes.

This module does not execute probes or capture context. It only centralizes the
rules that decide whether a previously created ContextProbeRequest is eligible
for execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from daemon.core.context_probe_request import (
    ContextProbeRequest,
    ContextProbeRequestStatus,
)


@dataclass(frozen=True)
class ContextProbeExecutionPlan:
    """Passive execution decision for a context probe request."""

    request_id: str
    kind: str
    allowed: bool
    blocked_reason: str | None
    requires_runtime_probe: bool
    policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "request_id": self.request_id,
            "kind": self.kind,
            "allowed": self.allowed,
            "blocked_reason": self.blocked_reason,
            "requires_runtime_probe": self.requires_runtime_probe,
            "policy": self.policy,
        }


def can_execute_context_probe(request: ContextProbeRequest) -> bool:
    """Return whether a context probe request is eligible for execution."""
    return build_context_probe_execution_plan(request).allowed


def build_context_probe_execution_plan(request: ContextProbeRequest) -> ContextProbeExecutionPlan:
    """Build a passive execution plan without running the probe.

    A request may execute only when:
    - it is approved;
    - it is not expired;
    - its policy is not blocked;
    - its policy does not allow persistent storage by default.
    """
    blocked_reason = _blocked_reason(request)
    return ContextProbeExecutionPlan(
        request_id=request.request_id,
        kind=request.kind.value,
        allowed=blocked_reason is None,
        blocked_reason=blocked_reason,
        requires_runtime_probe=blocked_reason is None,
        policy=request.policy.to_dict(),
    )


def _blocked_reason(request: ContextProbeRequest) -> str | None:
    if request.status is not ContextProbeRequestStatus.APPROVED:
        return f"request_not_approved:{request.status.value}"
    if request.is_expired:
        return "request_expired"
    if request.policy.consent.value == "blocked":
        return "policy_blocked"
    if request.policy.allow_persistent_storage:
        return "persistent_storage_not_allowed_by_gate"
    return None
