from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from daemon.core.uid import new_uid

ALLOWED_CANDIDATE_STATUSES = {
    "pending",
    "accepted",
    "edited",
    "rejected",
    "expired",
    "contradicted",
    "archived",
}

ALLOWED_MEMORY_TYPES = {
    "project_pattern",
    "workflow_pattern",
    "tool_usage",
    "caution",
}

FORBIDDEN_MEMORY_TYPES = {
    "medical",
    "financial",
    "identity",
    "private_life",
    "credential",
    "psychological_profile",
    "sensitive_preference",
}

SENSITIVE_LEVELS = {
    "secret",
    "credential",
    "medical",
    "financial",
    "identity",
    "private_life",
    "psychological_profile",
    "sensitive_preference",
    "sensitive",
}

ALLOWED_SENSITIVITY_LEVELS = {
    "low",
    "medium",
    "non_sensitive",
}

DEFAULT_EXPIRATION_POLICY = "pending_candidates_expire_unreviewed"
DEFAULT_REJECTION_POLICY = "do_not_repropose_without_new_stronger_evidence"
DEFAULT_CONTRADICTION_POLICY = "mark_contradicted_and_require_human_review"


class MemoryCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryCandidate:
    id: str
    status: str
    memory_type: str
    claim: str
    confidence: float
    sensitivity: dict[str, Any]
    created_at: str
    updated_at: str
    expires_at: str | None
    expiration_policy: str
    evidence: list[dict[str, Any]]
    human_review: dict[str, Any]
    rejection_policy: str
    contradiction_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "memory_type": self.memory_type,
            "claim": self.claim,
            "confidence": self.confidence,
            "sensitivity": self.sensitivity,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "expiration_policy": self.expiration_policy,
            "evidence": self.evidence,
            "human_review": self.human_review,
            "rejection_policy": self.rejection_policy,
            "contradiction_policy": self.contradiction_policy,
        }


class MemoryCandidateStore:
    """Local review store for memory candidates.

    This store is intentionally separate from MemoryStore and SessionMemory. It
    records reviewable candidates only; it does not generate, promote, inject, or
    render stable memory.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or (Path.home() / ".pulse" / "memory" / "candidates.sqlite"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def create_manual_candidate(
        self,
        *,
        memory_type: str,
        claim: str,
        confidence: float = 0.0,
        sensitivity: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        expires_at: str | None = None,
        expiration_policy: str = DEFAULT_EXPIRATION_POLICY,
    ) -> dict[str, Any]:
        self._validate_memory_type(memory_type)
        clean_claim = self._validate_claim(claim)
        clean_confidence = self._validate_confidence(confidence)
        clean_sensitivity = self._validate_sensitivity(sensitivity)
        clean_evidence = self._validate_evidence(evidence)
        now = self._now()
        candidate = MemoryCandidate(
            id=new_uid(),
            status="pending",
            memory_type=memory_type,
            claim=clean_claim,
            confidence=clean_confidence,
            sensitivity=clean_sensitivity,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
            expiration_policy=expiration_policy or DEFAULT_EXPIRATION_POLICY,
            evidence=clean_evidence,
            human_review={
                "required": True,
                "reviewed_at": None,
                "decision": None,
                "reviewer": None,
                "edited_claim": None,
                "trace": [],
            },
            rejection_policy=DEFAULT_REJECTION_POLICY,
            contradiction_policy=DEFAULT_CONTRADICTION_POLICY,
        )
        with self._lock:
            with self._connect() as conn:
                self._insert(conn, candidate)
                conn.commit()
        return candidate.to_dict()

    def list_candidates(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            if status not in ALLOWED_CANDIDATE_STATUSES:
                raise MemoryCandidateError("invalid_status")
            where = "WHERE status = ?"
            params.append(status)
        params.append(min(max(int(limit), 1), 100))
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM memory_candidates
                    {where}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    tuple(params),
                ).fetchall()
        return [self._row_to_candidate(row).to_dict() for row in rows]

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM memory_candidates WHERE id = ?",
                    (candidate_id,),
                ).fetchone()
        return self._row_to_candidate(row).to_dict() if row else None

    def accept(self, candidate_id: str, *, reviewer: str = "human") -> dict[str, Any] | None:
        return self._review(candidate_id, status="accepted", decision="accepted", reviewer=reviewer)

    def edit(self, candidate_id: str, *, claim: str, reviewer: str = "human") -> dict[str, Any] | None:
        clean_claim = self._validate_claim(claim)
        return self._review(
            candidate_id,
            status="edited",
            decision="edited",
            reviewer=reviewer,
            claim=clean_claim,
            edited_claim=clean_claim,
        )

    def reject(self, candidate_id: str, *, reviewer: str = "human", reason: str | None = None) -> dict[str, Any] | None:
        clean_reason = reason.strip() if isinstance(reason, str) else ""
        return self._review(
            candidate_id,
            status="rejected",
            decision="rejected",
            reviewer=reviewer,
            review_extra={"reason": clean_reason or "human_rejected"},
        )

    def archive(self, candidate_id: str, *, reviewer: str = "human") -> dict[str, Any] | None:
        return self._review(candidate_id, status="archived", decision="archived", reviewer=reviewer)

    def delete(self, candidate_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute("DELETE FROM memory_candidates WHERE id = ?", (candidate_id,))
                conn.commit()
        return cursor.rowcount > 0

    def _review(
        self,
        candidate_id: str,
        *,
        status: str,
        decision: str,
        reviewer: str,
        claim: str | None = None,
        edited_claim: str | None = None,
        review_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if status not in ALLOWED_CANDIDATE_STATUSES:
            raise MemoryCandidateError("invalid_status")
        now = self._now()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM memory_candidates WHERE id = ?",
                    (candidate_id,),
                ).fetchone()
                if row is None:
                    return None
                candidate = self._row_to_candidate(row)
                human_review = dict(candidate.human_review)
                trace = list(human_review.get("trace") or [])
                event = {
                    "decision": decision,
                    "reviewer": reviewer,
                    "reviewed_at": now,
                }
                if edited_claim is not None:
                    event["edited_claim"] = edited_claim
                if review_extra:
                    event.update(review_extra)
                trace.append(event)
                human_review.update({
                    "required": True,
                    "reviewed_at": now,
                    "decision": decision,
                    "reviewer": reviewer,
                    "edited_claim": edited_claim,
                    "trace": trace,
                })
                conn.execute(
                    """
                    UPDATE memory_candidates
                    SET status = ?,
                        claim = ?,
                        updated_at = ?,
                        human_review_json = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        claim if claim is not None else candidate.claim,
                        now,
                        json.dumps(human_review, ensure_ascii=True, sort_keys=True),
                        candidate_id,
                    ),
                )
                conn.commit()
        return self.get_candidate(candidate_id)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_candidates (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    sensitivity_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    expiration_policy TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    human_review_json TEXT NOT NULL,
                    rejection_policy TEXT NOT NULL,
                    contradiction_policy TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_candidates_status_created
                ON memory_candidates(status, created_at)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert(self, conn: sqlite3.Connection, candidate: MemoryCandidate) -> None:
        conn.execute(
            """
            INSERT INTO memory_candidates (
                id,
                status,
                memory_type,
                claim,
                confidence,
                sensitivity_json,
                created_at,
                updated_at,
                expires_at,
                expiration_policy,
                evidence_json,
                human_review_json,
                rejection_policy,
                contradiction_policy
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.id,
                candidate.status,
                candidate.memory_type,
                candidate.claim,
                candidate.confidence,
                json.dumps(candidate.sensitivity, ensure_ascii=True, sort_keys=True),
                candidate.created_at,
                candidate.updated_at,
                candidate.expires_at,
                candidate.expiration_policy,
                json.dumps(candidate.evidence, ensure_ascii=True, sort_keys=True),
                json.dumps(candidate.human_review, ensure_ascii=True, sort_keys=True),
                candidate.rejection_policy,
                candidate.contradiction_policy,
            ),
        )

    def _row_to_candidate(self, row: sqlite3.Row) -> MemoryCandidate:
        return MemoryCandidate(
            id=row["id"],
            status=row["status"],
            memory_type=row["memory_type"],
            claim=row["claim"],
            confidence=row["confidence"],
            sensitivity=json.loads(row["sensitivity_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            expiration_policy=row["expiration_policy"],
            evidence=json.loads(row["evidence_json"]),
            human_review=json.loads(row["human_review_json"]),
            rejection_policy=row["rejection_policy"],
            contradiction_policy=row["contradiction_policy"],
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _validate_memory_type(memory_type: str) -> None:
        if memory_type in FORBIDDEN_MEMORY_TYPES:
            raise MemoryCandidateError("forbidden_memory_type")
        if memory_type not in ALLOWED_MEMORY_TYPES:
            raise MemoryCandidateError("invalid_memory_type")

    @staticmethod
    def _validate_claim(claim: str) -> str:
        clean_claim = (claim or "").strip()
        if not clean_claim:
            raise MemoryCandidateError("claim_required")
        if len(clean_claim) > 280:
            raise MemoryCandidateError("claim_too_long")
        return clean_claim

    @staticmethod
    def _validate_confidence(confidence: float) -> float:
        clean_confidence = float(confidence)
        if clean_confidence < 0.0 or clean_confidence > 1.0:
            raise MemoryCandidateError("invalid_confidence")
        return clean_confidence

    @staticmethod
    def _validate_sensitivity(sensitivity: dict[str, Any] | None) -> dict[str, Any]:
        clean_sensitivity = sensitivity or {"level": "low", "reason": "manual_non_sensitive_candidate"}
        if not isinstance(clean_sensitivity, dict):
            raise MemoryCandidateError("invalid_sensitivity")
        level = str(clean_sensitivity.get("level") or "").strip().lower()
        if level in SENSITIVE_LEVELS:
            raise MemoryCandidateError("sensitive_candidate_refused")
        if level not in ALLOWED_SENSITIVITY_LEVELS:
            raise MemoryCandidateError("invalid_sensitivity")
        return clean_sensitivity

    @staticmethod
    def _validate_evidence(evidence: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        if evidence is None:
            return []
        if not isinstance(evidence, list):
            raise MemoryCandidateError("invalid_evidence")
        if any(not isinstance(item, dict) for item in evidence):
            raise MemoryCandidateError("invalid_evidence_item")
        return evidence
