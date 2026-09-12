"""Small domain models used by the ingestion and trace layers."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# Versions du contrat canonique que Core sait interpréter. Une version
# inconnue est refusée à l'ingestion (400) au lieu d'être lue avec les
# règles courantes comme si c'était une version 1.
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

SYSTEM_ACTIVITY_TYPES = {
    "screen_locked",
    "screen_unlocked",
    "system_sleep",
    "system_wake",
}
# Contexte faible : ne démarre ni ne prolonge une session de travail, s'y
# rattache quand du travail fort l'entoure ; jamais une preuve de workspace.
WEAK_CONTEXT_TYPES = {"app_activated", "window_focused"}
SUPPORTED_ACTIVITY_TYPES = {
    "agent_session",
    "app_activated",
    # Contexte de la fenêtre au premier plan (titre, document, URL réduite),
    # décision du 2026-09-12. Faible comme app_activated pour la
    # reconstruction ; jamais de contenu de fenêtre.
    "window_focused",
    "file_changed",
    "terminal_finished",
    "git_commit",
    # Dérivé par la couche Intelligence (pas 3) : Core l'accepte, le stocke
    # et l'expose par /context, sans le rendre.
    "session_summary",
    *SYSTEM_ACTIVITY_TYPES,
}


@dataclass(frozen=True)
class Activity:
    activity_type: str
    occurred_at: datetime
    source: str
    summary: str
    details: dict[str, Any]

    def __post_init__(self) -> None:
        if self.activity_type not in SUPPORTED_ACTIVITY_TYPES:
            raise ValueError(f"unsupported activity type: {self.activity_type}")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        if not self.source:
            raise ValueError("source must not be empty")
        if not self.summary:
            raise ValueError("summary must not be empty")

    @property
    def occurred_at_utc(self) -> datetime:
        return self.occurred_at.astimezone(timezone.utc)


@dataclass(frozen=True)
class CanonicalEvent:
    """Validated producer-owned event data before durable persistence."""

    event_id: str
    schema_version: int
    event_type: str
    producer_name: str
    producer_version: str | None
    producer_instance_id: str | None
    occurred_at: datetime
    details: dict[str, Any]


def canonical_event_fingerprint(event: CanonicalEvent) -> str:
    """Return the single canonical identity hash used by ingestion and storage."""
    significant = {
        "schema_version": event.schema_version,
        "type": event.event_type,
        "producer": {
            "name": event.producer_name,
            "version": event.producer_version,
            "instance_id": event.producer_instance_id,
        },
        "occurred_at": event.occurred_at.isoformat(),
        "details": event.details,
    }
    serialized = json.dumps(
        significant,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True)
class IngestedEvent:
    """Canonical event paired with Core's existing human-facing projection."""

    event: CanonicalEvent
    activity: Activity
    fingerprint: str
    legacy: bool = False


@dataclass(frozen=True)
class StoredActivity:
    id: int
    activity: Activity
    event_id: str
    schema_version: int
    producer_name: str
    producer_version: str | None
    producer_instance_id: str | None
    recorded_at: datetime
    duplicate: bool = False

    @property
    def type(self) -> str:
        return self.activity.activity_type

    @property
    def occurred_at(self) -> datetime:
        return self.activity.occurred_at

    @property
    def details(self) -> dict[str, Any]:
        return self.activity.details
