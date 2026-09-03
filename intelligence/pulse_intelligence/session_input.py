"""Vue de session → entrée du modèle (spec v2 §7).

L'entrée est la vue renvoyée par Core, telle quelle, sérialisée à clés
triées ; son sha256 est ``input_hash``. Intelligence n'y retire ni n'y
ajoute de faits. Deux annexes, sous des clés séparées, s'il y a lieu : la
reprise du résumé précédent de la même journée, et le dernier
``agent_session`` dont l'intervalle chevauche la session — les deux lus sur
``GET /context?at=<fin de session>``, jamais sur ``/trace``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .selection import SessionView


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
    context: dict[str, Any], session: SessionView
) -> dict[str, Any] | None:
    """La reprise du résumé précédent de la même journée locale, sinon rien.

    Le résumé de la session elle-même (régénération sous une autre version)
    n'est pas une continuité : il est écarté.
    """
    previous = context.get("last_session_summary")
    if not isinstance(previous, dict):
        return None
    if previous.get("id") == session.id:
        return None
    ended = _instant(previous.get("session_ended_at"))
    if ended is None or ended.astimezone().date() != session.day:
        return None
    return {
        "id": previous.get("id"),
        "label": previous.get("label"),
        "reprise": previous.get("reprise"),
    }


def agent_session_annex(
    context: dict[str, Any], session: SessionView
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
    return {
        "agent": agent.get("agent"),
        "started_at": agent.get("started_at"),
        "ended_at": agent.get("ended_at"),
        "summary": agent.get("summary"),
    }


def build_model_input(
    session: SessionView, context: dict[str, Any]
) -> dict[str, Any]:
    """``session`` est la vue Core intacte ; les annexes sont à part."""
    return {
        "session": copy.deepcopy(session.raw),
        "previous_summary": previous_summary_annex(context, session),
        "agent_session": agent_session_annex(context, session),
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
