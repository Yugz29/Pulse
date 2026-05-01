

"""In-memory store for context probe requests.

This store is intentionally passive: it keeps request lifecycle state in memory
so future routes can list, approve, refuse, expire, or cancel probe requests.
It does not execute probes, capture context, or persist data to disk.
"""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Iterable, Optional

from daemon.core.context_probe_request import (
    ContextProbeRequest,
    ContextProbeRequestStatus,
    expire_context_probe_request,
)


class ContextProbeRequestStore:
    """Thread-safe in-memory store for ContextProbeRequest objects."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._requests: dict[str, ContextProbeRequest] = {}

    def add(self, request: ContextProbeRequest) -> ContextProbeRequest:
        """Add or replace a request by id."""
        with self._lock:
            self._requests[request.request_id] = request
            return request

    def get(self, request_id: str) -> Optional[ContextProbeRequest]:
        """Return a request by id, if present."""
        with self._lock:
            return self._requests.get(request_id)

    def update(self, request: ContextProbeRequest) -> ContextProbeRequest:
        """Update an existing request by id.

        Raises KeyError if the request does not already exist. This avoids
        silently creating lifecycle records through update paths.
        """
        with self._lock:
            if request.request_id not in self._requests:
                raise KeyError(request.request_id)
            self._requests[request.request_id] = request
            return request

    def list(
        self,
        *,
        status: ContextProbeRequestStatus | str | None = None,
        include_terminal: bool = True,
    ) -> list[ContextProbeRequest]:
        """Return stored requests ordered by creation time."""
        status_filter = _coerce_status(status) if status is not None else None
        with self._lock:
            requests = list(self._requests.values())

        if status_filter is not None:
            requests = [request for request in requests if request.status is status_filter]
        if not include_terminal:
            requests = [request for request in requests if not request.is_terminal]
        return sorted(requests, key=lambda request: request.created_at)

    def remove(self, request_id: str) -> Optional[ContextProbeRequest]:
        """Remove and return a request, if present."""
        with self._lock:
            return self._requests.pop(request_id, None)

    def expire_due(self, *, now: Optional[datetime] = None) -> list[ContextProbeRequest]:
        """Expire pending requests whose expiry time has passed."""
        current_time = now or datetime.now()
        expired: list[ContextProbeRequest] = []
        with self._lock:
            for request in list(self._requests.values()):
                if request.status is not ContextProbeRequestStatus.PENDING:
                    continue
                if request.expires_at is None or request.expires_at > current_time:
                    continue
                updated = expire_context_probe_request(request, decided_at=current_time)
                self._requests[updated.request_id] = updated
                expired.append(updated)
        return expired

    def remove_terminal(self) -> list[ContextProbeRequest]:
        """Remove and return all terminal requests."""
        removed: list[ContextProbeRequest] = []
        with self._lock:
            for request_id, request in list(self._requests.items()):
                if request.is_terminal:
                    removed.append(self._requests.pop(request_id))
        return sorted(removed, key=lambda request: request.created_at)

    def clear(self) -> None:
        """Remove all stored requests."""
        with self._lock:
            self._requests.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._requests)


def requests_to_dicts(requests: Iterable[ContextProbeRequest]) -> list[dict]:
    """Return JSON-ready request dictionaries."""
    return [request.to_dict() for request in requests]


def _coerce_status(status: ContextProbeRequestStatus | str) -> ContextProbeRequestStatus:
    if isinstance(status, ContextProbeRequestStatus):
        return status
    return ContextProbeRequestStatus(str(status))