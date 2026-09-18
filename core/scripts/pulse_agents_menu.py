"""Menu SwiftBar « agents en attente » : lecture seule, sans Core ni modèle.

Lit les fichiers d'état écrits par ``pulse_agent_state.py`` et rend le
format SwiftBar (titre, ``---``, une ligne par session). Deux règles
d'affichage :

- une session dont le pid n'existe plus n'est pas affichée (crash, kill,
  redémarrage : pas de SessionEnd) ; sans pid connu, elle l'est tant que son
  fichier a moins de ``STALE_AFTER_HOURS`` ; ``waiting_for_you`` n'est jamais
  masqué avec le temps, une réponse attendue depuis deux heures reste en tête ;
- la ligne « Résumés à jour : dernier passage à HH:MM » lit
  ``last_complete_pass`` dans le ``state.json`` d'Intelligence. Elle reflète
  le dernier passage complet, relances manuelles comprises — ce n'est pas le
  « lot du jour » du compteur de l'étape 4. Rouge si aucun passage complet
  depuis le 06:30 du jour une fois 07:30 passé, vert sinon, gris avant 07:30.

Appelé par ``scripts/swiftbar/pulse-agents.5s.sh`` ; testé directement.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pulse_agent_state import (  # noqa: E402
    STALE_AFTER_HOURS,
    WAITING_FOR_YOU,
    WAITING_PERMISSION,
    WORKING,
    process_alive,
    read_state,
    state_dir,
)

DEFAULT_INTEL_STATE = Path.home() / ".pulse_intelligence" / "state.json"
INTEL_STATE_ENV = "PULSE_INTEL_STATE_PATH"

LABELS = {
    WAITING_PERMISSION: "attend une permission",
    WAITING_FOR_YOU: "attend ta suite",
    WORKING: "travaille",
}
COLORS = {WAITING_PERMISSION: "orange", WAITING_FOR_YOU: "orange", WORKING: "black"}
ORDER = {WAITING_PERMISSION: 0, WAITING_FOR_YOU: 1, WORKING: 2}
# Heure du lot planifié et heure à partir de laquelle son absence est une alerte.
BATCH_TIME = time(6, 30)
ALERT_TIME = time(7, 30)


def elapsed(since: str, now: datetime) -> str:
    minutes = int((now - datetime.fromisoformat(since)).total_seconds() // 60)
    if minutes < 1:
        return "à l'instant"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


def live_sessions(directory: Path, now: datetime, *, alive=process_alive) -> list[dict[str, Any]]:
    """Les sessions à afficher : pid vivant, ou pid inconnu et fichier récent."""
    rows = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        data = read_state(path)
        if not data or data.get("state") not in LABELS:
            continue
        pid = data.get("pid")
        if pid is None:
            try:
                age = now - datetime.fromisoformat(str(data.get("updated_at")))
            except ValueError:
                continue
            if age > timedelta(hours=STALE_AFTER_HOURS):
                continue
        elif not alive(pid):
            continue
        rows.append(data)
    rows.sort(key=lambda s: (ORDER[s["state"]], s.get("since") or ""))
    return rows


def agent_lines(rows: list[dict[str, Any]], now: datetime) -> list[str]:
    waiting = [s for s in rows if s["state"] != WORKING]
    lines = [f"⏳ {len(waiting)}" if waiting else "·", "---"]
    if not rows:
        lines.append("Aucune session d'agent")
    for s in rows:
        label = LABELS[s["state"]]
        lines.append(
            f"{s.get('project') or '?'} — {label} — depuis {elapsed(s['since'], now)}"
            f" | color={COLORS[s['state']]}"
        )
        lines.append(
            f"--{s.get('agent', '?')} {str(s.get('session_id', ''))[:8]} · {s.get('cwd') or ''}"
            " | font=Menlo size=11"
        )
    return lines


def summaries_line(intel_state: Path, now: datetime) -> str:
    """« Résumés à jour : dernier passage à HH:MM », d'après ``last_complete_pass``
    (UTC), jugé en heure locale. Passage complet = `run` arrivé au bout de sa
    fenêtre, planifié ou relancé à la main."""
    marker = None
    try:
        raw = json.loads(intel_state.read_text(encoding="utf-8")).get("last_complete_pass")
        if raw:
            marker = datetime.fromisoformat(str(raw))
            if marker.tzinfo is None:
                marker = marker.replace(tzinfo=timezone.utc)
    except (OSError, ValueError, AttributeError):
        marker = None
    local_now = now.astimezone()
    today_batch = datetime.combine(local_now.date(), BATCH_TIME, tzinfo=local_now.tzinfo)
    alert_from = datetime.combine(local_now.date(), ALERT_TIME, tzinfo=local_now.tzinfo)
    if marker is not None and marker >= today_batch:
        return f"Résumés à jour : dernier passage à {marker.astimezone().strftime('%H:%M')} | color=green"
    if marker is None:
        last = "aucun passage complet connu"
    else:
        local_marker = marker.astimezone()
        day = "hier" if local_marker.date() == local_now.date() - timedelta(days=1) else local_marker.strftime("%d/%m")
        last = f"dernier passage {day} {local_marker.strftime('%H:%M')}"
    if local_now >= alert_from:
        return f"Résumés en retard : {last}, aucun depuis 06:30 | color=red"
    return f"Résumés : {last}, le passage de 06:30 n'est pas encore attendu | color=gray"


def render(directory: Path, intel_state: Path | None, now: datetime | None = None, *, alive=process_alive) -> str:
    moment = now or datetime.now(timezone.utc)
    lines = agent_lines(live_sessions(directory, moment, alive=alive), moment)
    if intel_state is not None:
        lines += ["---", summaries_line(intel_state, moment)]
    return "\n".join(lines) + "\n"


def main() -> int:
    override = os.environ.get(INTEL_STATE_ENV)
    intel_state = Path(override).expanduser() if override else DEFAULT_INTEL_STATE
    sys.stdout.write(render(state_dir(), intel_state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
