"""Vue de session → entrée du modèle (spec v2 §7).

L'entrée est la vue renvoyée par Core, telle quelle, sérialisée à clés
triées ; son sha256 est ``input_hash``. Intelligence n'y retire ni n'y
ajoute de faits. Deux annexes, sous des clés séparées, s'il y a lieu : la
reprise du résumé précédent de la même journée, et le dernier
``agent_session`` dont l'intervalle chevauche la session — les deux lus sur
``GET /context?at=<fin de session>``, jamais sur ``/trace``.

Références stables (schéma ``open`` v3)
---------------------------------------

Chaque fait de l'entrée est désignable depuis la sortie par une référence
``<type>:<clé>`` ; ``input_references`` énumère celles qui existent et le
validateur rejette toute autre. Les clés sont celles que Core sert déjà,
sans réécriture de la vue :

- ``path:<chemin>`` — un chemin de ``files.created``, ``modified`` ou ``deleted`` ;
- ``commit:<hash>`` — le ``hash`` d'un ``git.commits[]`` ;
- ``event:<id>`` — un ``source_event_ids[]`` (la vue n'en porte pas le
  contenu : référence possible, rarement utile) ;
- ``app:<nom>`` — un ``apps[].name`` ;
- ``test_passed:<commande>``, ``test_failed:<commande>``, ``error:<texte>`` —
  les listes de ``terminal`` ;
- ``signal:<nom>`` — un ``signals[]`` ;
- ``agent_request:0`` — l'annexe ``agent_session`` (une seule par entrée) ;
- ``previous_summary:<i>`` — le i-ième point du ``open`` de l'annexe
  ``previous_summary``, découpé par ``split_open_text``.

Core sert ``open`` en une seule chaîne ; les points y sont des phrases. Le
découpage est déterministe et identique côté entrée (``open_items`` de
l'annexe) et côté validateur, et son inverse est ``render_open_items``
(``session_summary``). Il n'y a ni ``git:push_observed`` ni aucune référence
à une absence : une absence d'observation ne se cite pas, elle se dit.

Les références ne changent pas la vue Core. Elles n'ajoutent aux annexes
(``open_items``, ``ref``) que lorsque ``references=True`` — c'est-à-dire pour
les prompts au schéma ``open`` v3 (``uses_open_items``) ; l'entrée des
prompts v1 et v2, et donc leur ``input_hash``, restent octet pour octet
celles d'avant.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .selection import SessionView


# Les prompts dont `open` est une chaîne libre (contrat d'origine). Tout
# autre prompt attend la liste d'objets du schéma v3 et reçoit une entrée
# référencée.
LEGACY_OPEN_PROMPT_VERSIONS = frozenset({"v1", "v2"})


def uses_open_items(prompt_version: str) -> bool:
    """Le prompt attend-il des points ouverts référencés (schéma v3) ?"""
    return prompt_version not in LEGACY_OPEN_PROMPT_VERSIONS


# Un point par phrase : fin de phrase suivie d'un blanc, ou point-virgule.
_OPEN_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\s*;\s+")


def split_open_text(text: Any) -> list[str]:
    """Les points d'un ``open`` servi par Core (une chaîne), dans l'ordre.

    Déterministe, sans jugement : c'est le seul découpage que le validateur
    et l'annexe partagent. Une liste (aucun résumé émis à ce jour n'en porte)
    est reprise telle quelle, chaîne par chaîne."""
    if isinstance(text, list):
        return [item.strip() for item in text if isinstance(item, str) and item.strip()]
    if not isinstance(text, str):
        return []
    return [part.strip() for part in _OPEN_BOUNDARY.split(text) if part.strip()]


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def previous_summary_annex(
    context: dict[str, Any], session: SessionView, *, references: bool = False
) -> dict[str, Any] | None:
    """La reprise du résumé précédent de la même journée locale, sinon rien.

    Le résumé de la session elle-même (régénération sous une autre version)
    n'est pas une continuité : il est écarté. Avec ``references``, le ``open``
    reçu est aussi donné point par point sous ``open_items``, chacun avec la
    référence ``previous_summary:<i>`` que la sortie devra citer pour le
    reprendre.
    """
    previous = context.get("last_session_summary")
    if not isinstance(previous, dict):
        return None
    if previous.get("id") == session.id:
        return None
    ended = _instant(previous.get("session_ended_at"))
    if ended is None or ended.astimezone().date() != session.day:
        return None
    annex: dict[str, Any] = {
        "id": previous.get("id"),
        "label": previous.get("label"),
        "reprise": previous.get("reprise"),
    }
    if references:
        reprise = previous.get("reprise")
        received = reprise.get("open") if isinstance(reprise, dict) else None
        annex["open_items"] = [
            {"ref": f"previous_summary:{index}", "text": text}
            for index, text in enumerate(split_open_text(received))
        ]
    return annex


def agent_session_annex(
    context: dict[str, Any], session: SessionView, *, references: bool = False
) -> dict[str, Any] | None:
    """Le dernier agent_session s'il chevauche la session, sinon rien."""
    agent = context.get("last_agent_session")
    if not isinstance(agent, dict):
        return None
    started = _instant(agent.get("started_at"))
    ended = _instant(agent.get("ended_at"))
    if started is None or ended is None:
        return None
    if started > session.ended_at or ended < session.started_at:
        return None
    annex: dict[str, Any] = {
        "agent": agent.get("agent"),
        "started_at": agent.get("started_at"),
        "ended_at": agent.get("ended_at"),
        "summary": agent.get("summary"),
    }
    if references:
        annex["ref"] = "agent_request:0"
    return annex


def build_model_input(
    session: SessionView, context: dict[str, Any], *, references: bool = False
) -> dict[str, Any]:
    """``session`` est la vue Core intacte ; les annexes sont à part.

    ``references`` ajoute aux annexes les identifiants du schéma ``open`` v3
    (voir l'en-tête du module) ; la vue elle-même n'est jamais réécrite.
    """
    return {
        "session": copy.deepcopy(session.raw),
        "previous_summary": previous_summary_annex(context, session, references=references),
        "agent_session": agent_session_annex(context, session, references=references),
    }


def serialize_input(model_input: dict[str, Any]) -> str:
    return json.dumps(
        model_input,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def input_hash(serialized: str) -> str:
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def input_paths(session: SessionView) -> set[str]:
    """Les chemins que le modèle a le droit de citer : ceux de la vue, rien d'autre."""
    files = session.raw.get("files", {})
    paths: set[str] = set()
    if isinstance(files, dict):
        for category in ("created", "modified", "deleted"):
            for path in files.get(category, []) or []:
                if isinstance(path, str) and path:
                    paths.add(path)
    return paths


@dataclass(frozen=True)
class InputReferences:
    """Ce que la sortie a le droit de citer, calculé depuis l'entrée du modèle.

    ``refs`` est l'ensemble complet ; ``previous_open`` donne le texte de
    chaque ``previous_summary:<i>`` (dans l'ordre) pour la règle D1 ;
    ``agent_requests`` les références ``agent_request:<i>`` pour la règle
    des points ``requested``.
    """

    refs: frozenset[str]
    paths: frozenset[str]
    previous_open: tuple[str, ...]
    agent_requests: tuple[str, ...]

    def __contains__(self, ref: object) -> bool:
        return ref in self.refs


def _strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str) and value]


def input_references(model_input: dict[str, Any]) -> InputReferences:
    """Toutes les références valides pour cette entrée, et rien d'autre.

    Même principe que ``input_paths`` pour ``central_files`` : une référence
    qui n'est pas ici n'existe pas, quel que soit son air de vraisemblance.
    L'énumération ne dépend pas de ``references=True`` : les clés viennent de
    la vue Core, les annexes ne font que les rendre visibles au modèle.
    """
    session = model_input.get("session") or {}
    refs: set[str] = set()
    paths: set[str] = set()
    files = session.get("files") if isinstance(session, dict) else None
    if isinstance(files, dict):
        for category in ("created", "modified", "deleted"):
            paths.update(_strings(files.get(category)))
    refs.update(f"path:{path}" for path in paths)
    git = session.get("git") if isinstance(session, dict) else None
    if isinstance(git, dict):
        for commit in git.get("commits") or []:
            if isinstance(commit, dict) and isinstance(commit.get("hash"), str) and commit["hash"]:
                refs.add(f"commit:{commit['hash']}")
    if isinstance(session, dict):
        refs.update(f"event:{event_id}" for event_id in _strings(session.get("source_event_ids")))
        refs.update(f"signal:{name}" for name in _strings(session.get("signals")))
        for app in session.get("apps") or []:
            if isinstance(app, dict) and isinstance(app.get("name"), str) and app["name"]:
                refs.add(f"app:{app['name']}")
        terminal = session.get("terminal")
        if isinstance(terminal, dict):
            refs.update(f"test_passed:{command}" for command in _strings(terminal.get("tests_passed")))
            refs.update(f"test_failed:{command}" for command in _strings(terminal.get("tests_failed")))
            refs.update(f"error:{text}" for text in _strings(terminal.get("errors")))

    previous = model_input.get("previous_summary")
    previous_open: tuple[str, ...] = ()
    if isinstance(previous, dict):
        reprise = previous.get("reprise")
        received = reprise.get("open") if isinstance(reprise, dict) else None
        previous_open = tuple(split_open_text(received))
        refs.update(f"previous_summary:{index}" for index in range(len(previous_open)))

    agent_requests: tuple[str, ...] = ()
    if isinstance(model_input.get("agent_session"), dict):
        agent_requests = ("agent_request:0",)
        refs.update(agent_requests)

    return InputReferences(
        refs=frozenset(refs),
        paths=frozenset(paths),
        previous_open=previous_open,
        agent_requests=agent_requests,
    )
