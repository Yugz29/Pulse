"""Sessions candidates au résumé (spec v2 §7).

Intelligence ne reconstruit rien : les sessions closes viennent de
``GET /context/sessions`` déjà bornées, avec leur identité stable. Ici on ne
fait que lire la vue de Core et décider, avec une raison lisible, si une
session mérite un résumé.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import KNOWN_RECONSTRUCTION_VERSION
from .config import Config
from .core_client import CoreClient
from .state import JobState


_announced_versions: set[Any] = set()


def check_reconstruction_version(served: Any, *, source: str = "Core") -> str | None:
    """L'avertissement si ``served`` n'est pas la version connue, une fois par
    version et par processus, sur stderr (terminal et run.log). Rend le texte
    émis, ou ``None``."""
    if served == KNOWN_RECONSTRUCTION_VERSION or served in _announced_versions:
        return None
    _announced_versions.add(served)
    message = (
        f"⚠ {source} sert la reconstruction de sessions v{served} ; ce code a été validé "
        f"sur v{KNOWN_RECONSTRUCTION_VERSION} : vues et identifiants de session peuvent "
        "différer de ceux validés (daemon à redémarrer si son code est plus récent, "
        "ou constante KNOWN_RECONSTRUCTION_VERSION à relire)"
    )
    print(message, file=sys.stderr)
    return message


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"horodatage sans fuseau: {value}")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class SessionView:
    """Une session de travail telle que Core la rend, jamais modifiée."""

    raw: dict[str, Any]
    day: date

    @property
    def id(self) -> str:
        return str(self.raw["id"])

    @property
    def label(self) -> str:
        return str(self.raw.get("label", ""))

    @property
    def started_at(self) -> datetime:
        return _instant(self.raw["started_at"])

    @property
    def ended_at(self) -> datetime:
        return _instant(self.raw["last_activity_at"])

    @property
    def duration_minutes(self) -> int:
        return int(self.raw.get("duration_minutes", 0))

    @property
    def activity_count(self) -> int:
        return int(self.raw.get("activity_count", 0))

    @property
    def is_open(self) -> bool:
        return bool(self.raw.get("is_open", False))

    @property
    def reconstruction_version(self) -> int:
        return int(self.raw.get("reconstruction_version", 0))

    @property
    def source_event_ids(self) -> list[str]:
        return list(self.raw.get("source_event_ids", []))

    @property
    def projects(self) -> list[str]:
        return list(self.raw.get("projects", []))


@dataclass(frozen=True)
class Classified:
    session: SessionView
    candidate: bool
    reason: str


def lookback_days(now: datetime, config: Config) -> list[date]:
    """Aujourd'hui puis la veille (lookback_days = 1) : jamais plus loin."""
    today = now.astimezone().date()
    return [today - timedelta(days=offset) for offset in range(config.lookback_days + 1)]


def fetch_sessions(
    client: CoreClient,
    day: date,
    *,
    at: datetime | None = None,
) -> list[SessionView]:
    body = client.get_sessions(day, at=at)
    # Au premier contact avec Core, donc au démarrage de `list`, `summarize`,
    # `run` et `show <id>` : la version servie face à celle connue du code.
    check_reconstruction_version(body.get("reconstruction_version"))
    return [SessionView(raw=session, day=day) for session in body.get("sessions", [])]


def _core_known(session: SessionView) -> set[tuple[str, str, str]]:
    """Résumés que Core signalerait sur la vue (champ `summaries`, s'il existe)."""
    known = set()
    for entry in session.raw.get("summaries", []) or []:
        if isinstance(entry, dict):
            known.add(
                (
                    session.id,
                    str(entry.get("prompt_version")),
                    str(entry.get("model_id")),
                )
            )
    return known


def classify(
    session: SessionView,
    *,
    config: Config,
    model_id: str,
    known: set[tuple[str, str, str]],
) -> Classified:
    if session.is_open:
        return Classified(session, False, "session ouverte")
    if (
        session.duration_minutes < config.min_session_minutes
        and session.activity_count < config.min_session_activities
    ):
        return Classified(
            session,
            False,
            f"trop courte ({session.duration_minutes} min, "
            f"{session.activity_count} activités)",
        )
    key = (session.id, config.prompt_version, model_id)
    if key in known or key in _core_known(session):
        return Classified(
            session, False, f"résumé existant ({config.prompt_version}, {model_id})"
        )
    return Classified(session, True, "candidate")


def classify_sessions(
    client: CoreClient,
    *,
    now: datetime,
    config: Config,
    model_id: str,
    state: JobState,
    days: list[date] | None = None,
) -> list[Classified]:
    """Toutes les sessions des journées de lookback, classées, chronologiques.

    Une session dont l'id a disparu de /context/sessions depuis le dernier
    passage n'est simplement plus listée : rien à oublier, rien à nettoyer.
    """
    known = state.known_summaries()
    classified: list[Classified] = []
    for day in days if days is not None else lookback_days(now, config):
        for session in fetch_sessions(client, day, at=now):
            classified.append(
                classify(session, config=config, model_id=model_id, known=known)
            )
    classified.sort(key=lambda item: (item.session.ended_at, item.session.id))
    return classified


def select_candidates(
    client: CoreClient,
    *,
    now: datetime,
    config: Config,
    model_id: str,
    state: JobState,
) -> list[SessionView]:
    return [
        item.session
        for item in classify_sessions(
            client, now=now, config=config, model_id=model_id, state=state
        )
        if item.candidate
    ]


def find_session(
    client: CoreClient,
    session_id: str,
    *,
    now: datetime,
    config: Config,
    day: date | None = None,
) -> SessionView | None:
    days = [day] if day is not None else lookback_days(now, config)
    for candidate_day in days:
        for session in fetch_sessions(client, candidate_day, at=now):
            if session.id == session_id:
                return session
    return None
