from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
import threading
from typing import Any, Optional


VALID_PROPOSAL_STATUS = {"pending", "accepted", "refused", "expired", "executed"}
TERMINAL_PROPOSAL_STATUS = {"accepted", "refused", "expired", "executed"}
VALID_METADATA_NAMESPACES = {"transport", "details"}
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass
class Proposal:
    id: str
    type: str
    trigger: str
    title: str
    summary: str
    rationale: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    proposed_action: str = ""
    status: str = "pending"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    decided_at: str | None = None
    lifecycle: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_initial_state()
        self.evidence = [dict(item) for item in self.evidence]
        self.metadata = dict(self.metadata)
        if not self.lifecycle:
            self._append_lifecycle_event("created", at=self.created_at)
            self._append_lifecycle_event(self.status, at=self.updated_at)

    def _validate_initial_state(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Proposal.id must be a non-empty string")
        self._validate_convention("type", self.type)
        self._validate_convention("trigger", self.trigger)
        self._validate_convention("proposed_action", self.proposed_action)
        for field_name in ("title", "summary", "rationale"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Proposal.{field_name} must be a non-empty string")
        if self.status != "pending":
            raise ValueError("Proposal initial status must be 'pending'")
        if not isinstance(self.confidence, (int, float)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("Proposal.confidence must be between 0.0 and 1.0")
        if not isinstance(self.evidence, list) or any(not isinstance(item, dict) for item in self.evidence):
            raise ValueError("Proposal.evidence must be a list of dict items")
        if not isinstance(self.metadata, dict):
            raise ValueError("Proposal.metadata must be a dict")
        unknown_namespaces = set(self.metadata.keys()) - VALID_METADATA_NAMESPACES
        if unknown_namespaces:
            raise ValueError(
                f"Proposal.metadata only supports namespaces {sorted(VALID_METADATA_NAMESPACES)}, "
                f"got {sorted(unknown_namespaces)}"
            )

    def _validate_convention(self, field_name: str, value: str) -> None:
        if not isinstance(value, str) or not _SNAKE_CASE_RE.match(value):
            raise ValueError(f"Proposal.{field_name} must use snake_case")

    def set_status(self, status: str) -> None:
        if status not in VALID_PROPOSAL_STATUS:
            raise ValueError(f"Invalid proposal status: {status}")
        if status == self.status:
            return
        if self.status in TERMINAL_PROPOSAL_STATUS:
            raise ValueError(
                f"Cannot transition proposal from terminal status {self.status!r} to {status!r}"
            )
        self.status = status
        now = _now_iso()
        self.updated_at = now
        if status != "pending":
            self.decided_at = now
        self._append_lifecycle_event(status, at=now)

    def _append_lifecycle_event(self, status: str, *, at: str) -> None:
        if self.lifecycle and self.lifecycle[-1]["status"] == status:
            return
        self.lifecycle.append({"status": status, "at": at})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "trigger": self.trigger,
            "title": self.title,
            "summary": self.summary,
            "rationale": self.rationale,
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "proposed_action": self.proposed_action,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "decided_at": self.decided_at,
            "lifecycle": list(self.lifecycle),
            "metadata": dict(self.metadata),
        }


class ProposalStore:
    """
    File minimaliste de propositions avec historique et résolution bloquante.

    Le store reste volontairement simple :
    - insertion ordonnée via le dict Python
    - une proposition peut être récupérée en attente, résolue ou expirée
    - les propositions résolues restent dans le store pour audit léger
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._proposals: dict[str, Proposal] = {}

    def add(self, proposal: Proposal) -> Proposal:
        with self._condition:
            if proposal.id in self._proposals:
                raise ValueError(f"Proposal already exists: {proposal.id}")
            if proposal.status != "pending":
                raise ValueError("ProposalStore only accepts pending proposals")
            self._proposals[proposal.id] = proposal
            self._condition.notify_all()
            return proposal

    def get(self, proposal_id: str) -> Optional[Proposal]:
        with self._lock:
            return self._proposals.get(proposal_id)

    def get_pending(self, *, proposal_type: str | None = None) -> Optional[Proposal]:
        with self._lock:
            for proposal in self._proposals.values():
                if proposal.status != "pending":
                    continue
                if proposal_type is not None and proposal.type != proposal_type:
                    continue
                return proposal
        return None

    def list_pending(self, *, proposal_type: str | None = None) -> list[Proposal]:
        with self._lock:
            return [
                proposal
                for proposal in self._proposals.values()
                if proposal.status == "pending"
                and (proposal_type is None or proposal.type == proposal_type)
            ]

    def resolve(self, proposal_id: str, status: str) -> Optional[Proposal]:
        if status not in TERMINAL_PROPOSAL_STATUS:
            raise ValueError(f"ProposalStore.resolve expects a terminal status, got: {status}")
        with self._condition:
            proposal = self._proposals.get(proposal_id)
            if proposal is None or proposal.status != "pending":
                return None
            proposal.set_status(status)
            self._condition.notify_all()
            return proposal

    def wait_for_resolution(self, proposal_id: str, timeout: float) -> Optional[Proposal]:
        with self._condition:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return None

            deadline = datetime.now().timestamp() + timeout
            while proposal.status == "pending":
                remaining = deadline - datetime.now().timestamp()
                if remaining <= 0:
                    proposal.set_status("expired")
                    self._condition.notify_all()
                    return proposal
                self._condition.wait(timeout=remaining)
                proposal = self._proposals.get(proposal_id)
                if proposal is None:
                    return None
            return proposal

    def list_all(self) -> list[Proposal]:
        with self._lock:
            return list(self._proposals.values())

    def list_history(self, *, limit: int | None = None) -> list[Proposal]:
        with self._lock:
            proposals = list(self._proposals.values())
        proposals.reverse()
        if limit is not None:
            return proposals[:limit]
        return proposals

    def clear(self) -> None:
        with self._condition:
            self._proposals.clear()
            self._condition.notify_all()


proposal_store = ProposalStore()
