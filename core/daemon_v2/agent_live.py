"""Les sessions d'agent vivantes, dans le format commun, pour la page.

Étape 1 bis du mode continu. Source : le dossier d'état écrit par les hooks
(``scripts/pulse_agent_state_hook.sh``, v0 du 2026-09-18), un fichier JSON
par session avec ``state``, ``since``, ``pid``, ``cwd``, ``project`` et
``transcript_path``. Le dossier absent, illisible ou vide rend une liste vide :
le bloc reste muet, Core n'en dépend pour rien d'autre.

Ce module ne sait rien d'un agent en particulier : les actions (commandes,
fichiers, tests) sont lues via l'adaptateur qui comprend le transcript désigné
par ``transcript_path`` — aujourd'hui ``agent_transcript``, pour Claude Code,
seul producteur de ces fichiers d'état. Le format qu'il rend est celui défini
dans ``agent_actions`` ; c'est aussi l'adaptateur qui fournit l'identité et le
libellé affiché de l'agent (``AGENT_KIND``/``AGENT_LABEL``).

Une session est vivante si son ``pid`` existe encore ; sans pid connu, si son
fichier a moins de ``STALE_AFTER_HOURS``. La même règle que le plugin
SwiftBar, tenue ici en quelques lignes plutôt qu'importée de ``scripts/`` :
le daemon ne charge pas les scripts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .agent_actions import STATE_UNKNOWN
from .agent_transcript import AGENT_KIND as DEFAULT_AGENT
from .agent_transcript import AGENT_LABEL
from .agent_transcript import read_transcript

STATE_DIR_ENV = "PULSE_AGENT_STATE_DIR"
DEFAULT_STATE_DIR = Path.home() / ".pulse_v2" / "run" / "agents"
STALE_AFTER_HOURS = 12
STATE_LABELS = {
    "working": "travaille",
    "waiting_permission": "attend une permission",
    "waiting_for_you": "attend ta suite",
}


def default_state_dir() -> Path:
    override = os.environ.get(STATE_DIR_ENV)
    return Path(override).expanduser() if override else DEFAULT_STATE_DIR


def live_agent_sessions(
    directory: Path | None = None,
    *,
    now: datetime | None = None,
    states: dict | None = None,
) -> list[dict[str, Any]]:
    """Une entrée par session vivante, la plus ancienne d'abord."""
    folder = directory if directory is not None else default_state_dir()
    moment = now or datetime.now(timezone.utc)
    found: list[dict[str, Any]] = []
    try:
        paths = sorted(folder.glob("*.json"))
    except OSError:
        return found
    for path in paths:
        state = _read_json(path)
        if state is None or not _alive(state, moment):
            continue
        transcript_path = state.get("transcript_path")
        transcript = (
            read_transcript(transcript_path, states=states)
            if isinstance(transcript_path, str) and transcript_path
            else None
        )
        agent_kind = state.get("agent") or DEFAULT_AGENT
        found.append(
            {
                "agent": agent_kind,
                "agent_label": AGENT_LABEL if agent_kind == DEFAULT_AGENT else agent_kind,
                "session_id": str(state.get("session_id") or ""),
                "project": state.get("project"),
                "cwd": state.get("cwd"),
                "state": state.get("state"),
                "state_label": STATE_LABELS.get(str(state.get("state")), STATE_UNKNOWN),
                "since": state.get("since"),
                "transcript_path": transcript_path if isinstance(transcript_path, str) else None,
                "transcript": transcript,
            }
        )
    found.sort(key=lambda s: s.get("since") or "")
    return found


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _alive(state: dict[str, Any], now: datetime) -> bool:
    pid = state.get("pid")
    if pid is None:
        try:
            updated = datetime.fromisoformat(str(state.get("updated_at")))
        except ValueError:
            return False
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return now - updated <= timedelta(hours=STALE_AFTER_HOURS)
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True
