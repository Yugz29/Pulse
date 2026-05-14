from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from threading import RLock
from typing import Any, Iterable, Mapping, Optional

from daemon.core.uid import new_uid
from daemon.runtime_state import WorkIntent


class WorkIntentCandidateStatus(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REFUSED = "refused"
    EXPIRED = "expired"


@dataclass(frozen=True)
class WorkIntentCandidate:
    candidate_id: str
    summary: str
    source: str
    confidence: float
    project: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_refs: tuple[str, ...] = ()
    status: WorkIntentCandidateStatus = WorkIntentCandidateStatus.CANDIDATE

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and datetime.now() >= self.expires_at

    @property
    def is_active(self) -> bool:
        return self.status is WorkIntentCandidateStatus.CANDIDATE and not self.is_expired

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "summary": self.summary,
            "source": self.source,
            "confidence": self.confidence,
            "project": self.project,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "evidence_refs": list(self.evidence_refs),
            "status": self.status.value,
            "is_active": self.is_active,
        }

    def to_work_intent(self) -> WorkIntent:
        return WorkIntent(
            summary=self.summary,
            source=self.source,
            confidence=self.confidence,
            project=self.project,
            created_at=self.created_at,
            expires_at=self.expires_at,
            evidence_refs=self.evidence_refs,
        )


class WorkIntentCandidateStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._candidates: dict[str, WorkIntentCandidate] = {}
        self._refused_evidence_refs: set[str] = set()

    def maybe_create_from_probe_result(
        self,
        *,
        probe_request: Any,
        result: Mapping[str, Any],
        project: str | None,
        active_work_intent: WorkIntent | None,
        now: Optional[datetime] = None,
    ) -> Optional[WorkIntentCandidate]:
        source = _source_from_result(result)
        if source not in {"manual_context_note", "next_clipboard_text"}:
            return None
        if _work_intent_is_active(active_work_intent, now=now):
            return None

        evidence_ref = f"context_probe:{probe_request.request_id}"
        created_at = now or datetime.now()
        summary = _bounded_summary(((result.get("data") or {}).get("redacted_value")))
        if not summary:
            return None

        candidate_source = "clipboard_sample" if source == "next_clipboard_text" else source
        confidence = 0.65 if candidate_source == "clipboard_sample" else 0.9
        candidate_project = _clean_project(project) or _project_from_request_metadata(probe_request)

        with self._lock:
            if evidence_ref in self._refused_evidence_refs:
                return None
            if self._active_for_project_locked(candidate_project) is not None:
                return None
            candidate = WorkIntentCandidate(
                candidate_id=new_uid(),
                summary=summary,
                source=candidate_source,
                confidence=confidence,
                project=candidate_project,
                created_at=created_at,
                expires_at=created_at + timedelta(hours=2),
                evidence_refs=(evidence_ref,),
            )
            self._candidates[candidate.candidate_id] = candidate
            return candidate

    def list(self, *, include_terminal: bool = True) -> list[WorkIntentCandidate]:
        self.expire_due()
        with self._lock:
            candidates = list(self._candidates.values())
        if not include_terminal:
            candidates = [candidate for candidate in candidates if candidate.is_active]
        return sorted(candidates, key=lambda candidate: candidate.created_at or datetime.min)

    def get(self, candidate_id: str) -> Optional[WorkIntentCandidate]:
        self.expire_due()
        with self._lock:
            return self._candidates.get(candidate_id)

    def accept(self, candidate_id: str) -> WorkIntentCandidate:
        self.expire_due()
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            if not candidate.is_active:
                raise ValueError("Only active work intent candidates can be accepted")
            accepted = replace(candidate, status=WorkIntentCandidateStatus.ACCEPTED)
            self._candidates[candidate_id] = accepted
            return accepted

    def refuse(self, candidate_id: str) -> WorkIntentCandidate:
        self.expire_due()
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            if candidate.status is not WorkIntentCandidateStatus.CANDIDATE:
                raise ValueError("Only active work intent candidates can be refused")
            refused = replace(candidate, status=WorkIntentCandidateStatus.REFUSED)
            self._candidates[candidate_id] = refused
            self._refused_evidence_refs.update(refused.evidence_refs)
            return refused

    def expire_due(self, *, now: Optional[datetime] = None) -> list[WorkIntentCandidate]:
        current_time = now or datetime.now()
        expired: list[WorkIntentCandidate] = []
        with self._lock:
            for candidate_id, candidate in list(self._candidates.items()):
                if candidate.status is not WorkIntentCandidateStatus.CANDIDATE:
                    continue
                if candidate.expires_at is None or candidate.expires_at > current_time:
                    continue
                updated = replace(candidate, status=WorkIntentCandidateStatus.EXPIRED)
                self._candidates[candidate_id] = updated
                expired.append(updated)
        return expired

    def _active_for_project_locked(self, project: str | None) -> Optional[WorkIntentCandidate]:
        for candidate in self._candidates.values():
            if not candidate.is_active:
                continue
            if (candidate.project or None) == (project or None):
                return candidate
        return None


def candidates_to_dicts(candidates: Iterable[WorkIntentCandidate]) -> list[dict[str, Any]]:
    return [candidate.to_dict() for candidate in candidates]


def _source_from_result(result: Mapping[str, Any]) -> str:
    data = result.get("data") or {}
    return str(data.get("source") or result.get("kind") or "").strip()


def _bounded_summary(value: Any) -> str:
    summary = " ".join(str(value or "").split())
    return summary[:240]


def _project_from_request_metadata(probe_request: Any) -> str | None:
    metadata = getattr(probe_request, "metadata", None)
    if not isinstance(metadata, Mapping):
        return None
    return _clean_project(metadata.get("project"))


def _clean_project(value: Any) -> str | None:
    project = str(value or "").strip()
    return project[:120] or None


def _work_intent_is_active(intent: WorkIntent | None, *, now: Optional[datetime] = None) -> bool:
    if intent is None or not intent.summary:
        return False
    if intent.expires_at is None:
        return True
    return intent.expires_at > (now or datetime.now())
