"""In-memory queue for lightweight LLM requests handled by the Swift app.

This queue is intentionally non-durable for the MVP. If Pulse or the Swift app
restarts while a request is pending, the already-written deterministic journal
fallback remains the reliable source of truth.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional


PENDING = "pending"
IN_PROGRESS = "in_progress"
GENERATED = "generated"
FAILED = "failed"

TERMINAL_STATUSES = {GENERATED, FAILED}


@dataclass
class LightweightLLMRequest:
    id: str
    kind: str
    prompt: str
    max_tokens: int
    created_at: str
    status: str = PENDING
    claimed_at: Optional[str] = None
    completed_at: Optional[str] = None
    text: str = ""
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "prompt": self.prompt,
            "max_tokens": self.max_tokens,
            "created_at": self.created_at,
            "status": self.status,
        }


class LightweightLLMQueue:
    def __init__(self, *, max_items: int = 50, ttl_seconds: int = 3600) -> None:
        self.max_items = max(int(max_items), 1)
        self.ttl = timedelta(seconds=max(int(ttl_seconds), 1))
        self._items: list[LightweightLLMRequest] = []
        self._lock = threading.Lock()

    def enqueue(
        self,
        *,
        kind: str,
        prompt: str,
        max_tokens: int = 160,
        metadata: Optional[dict[str, Any]] = None,
    ) -> LightweightLLMRequest:
        now = datetime.now()
        item = LightweightLLMRequest(
            id=str(uuid.uuid4()),
            kind=str(kind or "").strip(),
            prompt=str(prompt or "").strip(),
            max_tokens=max(int(max_tokens or 0), 1),
            created_at=now.isoformat(),
            metadata=dict(metadata or {}),
        )
        if not item.kind:
            raise ValueError("kind_required")
        if not item.prompt:
            raise ValueError("prompt_required")

        with self._lock:
            self._purge_locked(now=now)
            self._items.append(item)
            overflow = len(self._items) - self.max_items
            if overflow > 0:
                del self._items[:overflow]
            return item

    def claim_next(self) -> Optional[LightweightLLMRequest]:
        now = datetime.now()
        with self._lock:
            self._purge_locked(now=now)
            for item in self._items:
                if item.status == PENDING:
                    item.status = IN_PROGRESS
                    item.claimed_at = now.isoformat()
                    return item
        return None

    def complete(
        self,
        request_id: str,
        *,
        status: str,
        text: str = "",
        error: Optional[str] = None,
    ) -> LightweightLLMRequest:
        normalized_status = str(status or "").strip()
        if normalized_status not in TERMINAL_STATUSES:
            raise ValueError("invalid_status")
        now = datetime.now()
        with self._lock:
            self._purge_locked(now=now)
            for item in self._items:
                if item.id == request_id:
                    item.status = normalized_status
                    item.text = str(text or "")
                    item.error = str(error).strip() if error else None
                    item.completed_at = now.isoformat()
                    return item
        raise KeyError("request_not_found")

    def snapshot(self) -> list[LightweightLLMRequest]:
        with self._lock:
            self._purge_locked(now=datetime.now())
            return list(self._items)

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._purge_locked(now=datetime.now())
            counts = {
                "pending": 0,
                "in_progress": 0,
                "completed": 0,
                "failed": 0,
            }
            terminal_items: list[LightweightLLMRequest] = []
            for item in self._items:
                if item.status == PENDING:
                    counts["pending"] += 1
                elif item.status == IN_PROGRESS:
                    counts["in_progress"] += 1
                elif item.status == GENERATED:
                    counts["completed"] += 1
                    terminal_items.append(item)
                elif item.status == FAILED:
                    counts["failed"] += 1
                    terminal_items.append(item)

            last_result = None
            if terminal_items:
                latest = max(terminal_items, key=lambda item: _parse_iso(item.completed_at or item.created_at))
                last_result = {
                    "id": latest.id,
                    "kind": latest.kind,
                    "status": latest.status,
                    "error": latest.error,
                    "completed_at": latest.completed_at,
                }
            return {
                "queue": counts,
                "last_result": last_result,
            }

    def _purge_locked(self, *, now: datetime) -> None:
        cutoff = now - self.ttl
        self._items = [
            item
            for item in self._items
            if _parse_iso(item.created_at) >= cutoff
        ]


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.min
