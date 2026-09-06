"""Client HTTP de Pulse Core : le seul lien entre Intelligence et Core.

Trois routes du contrat public (spec v2 §4) : GET /context (Context API,
schema_version 2), GET /context/sessions (sessions de travail d'une journée,
seule source de sessions closes) et POST /activities (ingestion canonique).
Un Core arrêté se traduit par CoreUnavailable, jamais par une trace de pile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests


EXPECTED_SCHEMA_VERSION = 2


class CoreUnavailable(RuntimeError):
    """Core injoignable (connexion refusée, timeout)."""


class CoreError(RuntimeError):
    """Core a répondu, mais pas ce qui était attendu."""


@dataclass(frozen=True)
class PostResult:
    status_code: int
    accepted: bool
    duplicate: bool
    event_id: str | None
    error: dict[str, Any] | None


class CoreClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 5.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._session = session or requests.Session()

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        try:
            return self._session.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout_s,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise CoreUnavailable(f"Core injoignable sur {self.base_url}: {exc}") from exc

    @staticmethod
    def _json(response: requests.Response, path: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise CoreError(f"{path}: réponse non JSON ({response.status_code})") from exc

    @staticmethod
    def _check_schema(body: dict[str, Any], path: str) -> dict[str, Any]:
        version = body.get("schema_version")
        if version != EXPECTED_SCHEMA_VERSION:
            raise CoreError(
                f"{path}: schema_version {version!r}, attendu {EXPECTED_SCHEMA_VERSION} "
                "(Core ≥ 0.5.0 requis)"
            )
        return body

    @staticmethod
    def _at_param(at: datetime | None) -> dict[str, str]:
        if at is None:
            return {}
        if at.tzinfo is None:
            raise ValueError("at doit porter un fuseau")
        return {"at": at.astimezone(timezone.utc).isoformat()}

    def status(self) -> dict[str, Any]:
        response = self._request("GET", "/status")
        if response.status_code != 200:
            raise CoreError(f"/status: {response.status_code}")
        return self._json(response, "/status")

    def get_context(
        self,
        *,
        at: datetime | None = None,
        window_minutes: int | None = None,
    ) -> dict[str, Any]:
        params = self._at_param(at)
        if window_minutes is not None:
            params["window"] = str(window_minutes)
        response = self._request("GET", "/context", params=params)
        if response.status_code != 200:
            raise CoreError(f"/context: {response.status_code} {response.text[:200]}")
        return self._check_schema(self._json(response, "/context"), "/context")

    def get_sessions(
        self,
        day: date,
        *,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        """GET /context/sessions?date= : les sessions de travail d'une journée."""
        params = {"date": day.isoformat(), **self._at_param(at)}
        response = self._request("GET", "/context/sessions", params=params)
        if response.status_code != 200:
            raise CoreError(
                f"/context/sessions: {response.status_code} {response.text[:200]}"
            )
        return self._check_schema(
            self._json(response, "/context/sessions"), "/context/sessions"
        )

    def get_activity(self, event_id: str) -> dict[str, Any] | None:
        """GET /activities/<event_id> : l'événement tel que Core l'a stocké,
        ou ``None`` s'il ne le connaît pas (404).

        Un Core injoignable lève ``CoreUnavailable`` comme pour ``/context`` ;
        toute autre réponse est une ``CoreError``. Un Core antérieur à cette
        route répond 404 : le chemin normal reprend, comme avant.
        """
        response = self._request("GET", f"/activities/{event_id}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise CoreError(
                f"/activities/{event_id}: {response.status_code} {response.text[:200]}"
            )
        body = self._json(response, "/activities")
        if not isinstance(body, dict):
            raise CoreError(f"/activities/{event_id}: réponse inexploitable")
        return body

    def post_activity(self, payload: dict[str, Any]) -> PostResult:
        response = self._request("POST", "/activities", json=payload)
        body = self._json(response, "/activities") if response.content else {}
        if response.status_code in {200, 201}:
            return PostResult(
                status_code=response.status_code,
                accepted=bool(body.get("accepted", True)),
                duplicate=bool(body.get("duplicate", response.status_code == 200)),
                event_id=body.get("event_id"),
                error=None,
            )
        return PostResult(
            status_code=response.status_code,
            accepted=False,
            duplicate=False,
            event_id=body.get("event_id") if isinstance(body, dict) else None,
            error=body.get("error") if isinstance(body, dict) else None,
        )
