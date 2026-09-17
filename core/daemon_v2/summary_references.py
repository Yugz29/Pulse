"""Références ``oN`` d'un résumé stocké, résolues vers les événements sources.

Un résumé cite des faits par leur référence (``o77``) ; l'événement stocké
porte ``observation_sources``, la table référence → ``event_id`` qu'Intelligence
a recopiée de la même réponse de Core que l'entrée du modèle. Résoudre par
cette table ne reprojette rien : les lignes de ``trace.db`` sont immuables, la
référence garde donc le sens qu'elle avait quand le modèle l'a lue, quelles
que soient depuis la reconstruction, la version des observations ou la liste
de bruit des fichiers.

Règle de liaison, stricte : une référence n'est liée que hors citation et
présente dans la table du résumé. Dans une citation (le message d'un commit
peut contenir « o7 » pour tout autre chose), le texte reste tel quel. Hors
citation et non résolue, elle est « non vérifiable ». Une vérification qui
échoue (événement absent, type inattendu, date hors des bornes de la session)
donne « non vérifiable », jamais un fait approximatif.

Lecture seule, sans modèle et sans le code d'Intelligence.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .analysis.timeline import display_file_path
from .models import StoredActivity
from .trace_store import TraceStore


REFERENCE = re.compile(r"\bo[1-9][0-9]*\b")
# Une citation va de son guillemet ouvrant à son fermant ; sans fermant, elle
# court jusqu'à la fin du texte : on préfère ne pas lier que lier à tort.
_QUOTES = {"«": "»", "“": "”", '"': '"'}

RESOLVED = "resolved"
UNVERIFIABLE = "unverifiable"

# Nature du fait d'après le type de l'événement source, comme la projection
# ``work_observations`` la décide. Les faits ``window`` ne sont jamais montrés
# au modèle : ils n'ont pas de place dans la table d'un résumé.
_FACT_KINDS = {
    "git_commit": "commit",
    "terminal_finished": "command",
    "file_changed": "file",
    "screen_locked": "marker",
    "screen_unlocked": "marker",
    "system_sleep": "marker",
    "system_wake": "marker",
}
# Type d'événement qu'exige la nature d'un point ``open`` pour sa preuve.
_EVIDENCE_EVENT_TYPES = {
    "command_failure": "terminal_finished",
    "recorded_statement": "git_commit",
}


def split_references(text: str) -> list[tuple[str, str]]:
    """Le texte en fragments ``("text" | "quote" | "ref", fragment)``.

    La concaténation des fragments rend le texte à l'identique. Seules les
    références hors citation sortent en ``"ref"``.
    """
    segments: list[tuple[str, str]] = []

    def plain(chunk: str) -> None:
        cursor = 0
        for match in REFERENCE.finditer(chunk):
            if match.start() > cursor:
                segments.append(("text", chunk[cursor:match.start()]))
            segments.append(("ref", match.group()))
            cursor = match.end()
        if cursor < len(chunk):
            segments.append(("text", chunk[cursor:]))

    position = start = 0
    while position < len(text):
        closing = _QUOTES.get(text[position])
        if closing is None:
            position += 1
            continue
        end = text.find(closing, position + 1)
        end = len(text) if end < 0 else end + 1
        plain(text[start:position])
        segments.append(("quote", text[position:end]))
        position = start = end
    plain(text[start:])
    return segments


def cited_references(texts: list[str | None]) -> list[str]:
    """Références hors citation de ces textes, sans doublon, dans l'ordre."""
    found: dict[str, None] = {}
    for text in texts:
        for kind, fragment in split_references(text or ""):
            if kind == "ref":
                found.setdefault(fragment)
    return list(found)


def resolve_references(
    store: TraceStore,
    details: dict[str, Any],
    *,
    texts: list[str | None],
    open_items: list[dict[str, Any]],
    started_at: datetime | None,
    ended_at: datetime | None,
) -> dict[str, dict[str, Any]]:
    """Chaque référence citée (textes hors citation, preuves des points
    ``open``), résolue ou « non vérifiable », par numéro croissant."""
    # Une preuve impose le type de son événement ; deux natures
    # contradictoires pour une même référence ne se vérifient pas.
    expected: dict[str, set[str]] = {ref: set() for ref in cited_references(texts)}
    for item in open_items:
        for ref in item.get("evidence", []):
            if REFERENCE.fullmatch(ref):
                wanted = expected.setdefault(ref, set())
                event_type = _EVIDENCE_EVENT_TYPES.get(item.get("kind"))
                if event_type:
                    wanted.add(event_type)
    sources = details.get("observation_sources")
    return {
        ref: _resolve(store, sources, ref, expected[ref], started_at, ended_at)
        for ref in sorted(expected, key=lambda value: int(value[1:]))
    }


def _unverifiable(ref: str, reason: str) -> dict[str, Any]:
    return {"ref": ref, "status": UNVERIFIABLE, "reason": reason}


def _resolve(
    store: TraceStore,
    sources: Any,
    ref: str,
    expected_types: set[str],
    started_at: datetime | None,
    ended_at: datetime | None,
) -> dict[str, Any]:
    if not isinstance(sources, dict):
        return _unverifiable(ref, "résumé sans table de sources")
    event_ids = sources.get(ref)
    if (
        not isinstance(event_ids, list)
        or not event_ids
        or any(not isinstance(value, str) or not value for value in event_ids)
    ):
        return _unverifiable(ref, "référence absente des sources du résumé")
    if started_at is None or ended_at is None:
        return _unverifiable(ref, "bornes de session absentes du résumé")
    events: list[StoredActivity] = []
    for event_id in event_ids:
        stored = store.activity_by_event_id(event_id)
        if stored is None:
            return _unverifiable(ref, "événement source introuvable")
        events.append(stored)
    types = {stored.type for stored in events}
    event_type = next(iter(types))
    fact_kind = _FACT_KINDS.get(event_type)
    if len(types) != 1 or fact_kind is None:
        return _unverifiable(ref, "type d’événement inattendu")
    if expected_types and expected_types != {event_type}:
        return _unverifiable(ref, "type d’événement inattendu pour ce point")
    if fact_kind != "file" and len(events) != 1:
        return _unverifiable(ref, "sources incohérentes")
    start, end = _utc(started_at), _utc(ended_at)
    if any(not start <= _utc(stored.occurred_at) <= end for stored in events):
        return _unverifiable(ref, "événement hors des bornes de la session")
    events.sort(key=lambda stored: (_utc(stored.occurred_at), stored.id))
    fact = _fact(fact_kind, events)
    if fact is None:
        return _unverifiable(ref, "sources incohérentes")
    return {
        "ref": ref,
        "status": RESOLVED,
        "kind": fact_kind,
        "at": _utc(events[0].occurred_at).isoformat(),
        **fact,
    }


def _fact(kind: str, events: list[StoredActivity]) -> dict[str, Any] | None:
    details = events[0].details
    if kind == "commit":
        return {
            "hash": _text(details.get("commit_hash")),
            "branch": _text(details.get("branch")),
            "message": _text(details.get("message")),
        }
    if kind == "command":
        command = _text(details.get("command"))
        if command is None:
            return None
        exit_code = details.get("exit_code")
        return {
            "command": command,
            "exit_code": exit_code if type(exit_code) is int else None,
            "cwd": _text(details.get("cwd")),
        }
    if kind == "marker":
        return {"event": events[0].type}
    # Un fait ``file`` regroupe les notifications d'un même chemin : les
    # transitions successives, comptées comme dans la projection.
    paths = {stored.details.get("path") for stored in events}
    path = next(iter(paths))
    if len(paths) != 1 or not isinstance(path, str) or not path:
        return None
    changes: list[dict[str, Any]] = []
    for stored in events:
        change = stored.details.get("event", stored.details.get("change"))
        if change not in {"created", "modified", "deleted"}:
            return None
        if changes and changes[-1]["event"] == change:
            changes[-1]["count"] += 1
        else:
            changes.append({"event": change, "count": 1})
    return {
        "path": display_file_path(path, details.get("workspace")),
        "changes": changes,
        "last_at": _utc(events[-1].occurred_at).isoformat(),
    }


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
