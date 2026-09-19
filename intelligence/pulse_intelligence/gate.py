"""Garde du lot : un lot par jour, réveil complet, capot ouvert, batterie au-dessus du plancher.

Le lot planifié de 06:30 partait quand le Mac dormait capot fermé : launchd
le lançait dans un DarkWake de deux secondes, le Mac se rendormait, et le
lot n'avançait que par tranches de 2 à 20 s jusqu'au réveil complet (lots
des 10 au 15 et du 19 septembre 2026, 4 h 33 d'horloge pour dix minutes de
calcul le 19). `caffeinate` n'y peut rien.

Un agent launchd interroge cette garde toutes les quinze minutes ; elle
répond dans cet ordre (décision 2026-09-19) :

1. le lot du jour est-il déjà fait ? `last_complete_pass` (UTC) postérieur
   au début du cycle en cours (06:30 en heure locale, la veille avant
   06:30) : sortie muette, rien dans `run.log` ;
2. le Mac est-il en réveil complet ? (`pmset -g systemstate` : la capacité
   `Graphics` manque en DarkWake) : reporté, capacités lues dans la ligne ;
3. le capot est-il fermé ? (`AppleClamshellState` dans `ioreg`) : reporté ;
4. le Mac est-il sur batterie sous le plancher ? (`pmset -g batt`) : reporté ;
5. sinon le lot part.

Un report n'écrit qu'une ligne par cycle dans le journal (`gate.json` à
côté de `state.json` retient la dernière écriture). Une source illisible
n'arrête pas le lot : un poste sans batterie ou sans capot n'a rien à
reporter.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from .state import JobState, ensure_private_home

CYCLE_START = time(6, 30)
BATTERY_FLOOR = 40  # pour cent ; à ajuster sur les niveaux journalisés par le wrapper
PMSET = ("/usr/bin/pmset", "-g", "batt")
SYSTEMSTATE = ("/usr/bin/pmset", "-g", "systemstate")
FULL_WAKE_CAPABILITY = "Graphics"
IOREG = ("/usr/sbin/ioreg", "-r", "-k", "AppleClamshellState", "-d", "4")
GATE_FILE = "gate.json"

GO = "go"
DONE = "done"
DEFERRED = "deferred"


@dataclass(frozen=True)
class PowerState:
    on_ac: bool | None  # None : source illisible (pas de batterie, pmset absent)
    lid_closed: bool | None  # None : pas de capot ou ioreg illisible
    charge: int | None = None  # None : pas de batterie ou niveau illisible
    capabilities: tuple[str, ...] | None = None  # None : systemstate illisible


@dataclass(frozen=True)
class Verdict:
    outcome: str
    reason: str = ""


def parse_cycle_start(value: str) -> time:
    """``HH:MM`` en heure locale : l'heure à laquelle commence le lot du jour."""
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError(f"heure attendue au format HH:MM : {value!r}") from exc
    return parsed.time()


def cycle_threshold(now: datetime, cycle_start: time = CYCLE_START) -> datetime:
    """Le début du cycle en cours : aujourd'hui à ``cycle_start`` si l'heure
    est passée, sinon hier. Calculé en heure locale, rendu avec son fuseau."""
    if now.tzinfo is None:
        raise ValueError("now doit porter un fuseau")
    local = now.astimezone()
    threshold = local.replace(
        hour=cycle_start.hour, minute=cycle_start.minute, second=0, microsecond=0
    )
    if local < threshold:
        threshold -= timedelta(days=1)
    return threshold


def pass_done_since(state: JobState, threshold: datetime) -> bool:
    marker = state.last_complete_pass_at()
    return marker is not None and marker >= threshold


def parse_pmset(text: str) -> tuple[bool | None, int | None]:
    """Première ligne : ``Now drawing from 'AC Power'`` ou ``'Battery Power'``."""
    lines = [line for line in text.splitlines() if line.strip()]
    first = lines[0] if lines else ""
    if "AC Power" in first:
        on_ac: bool | None = True
    elif "Battery Power" in first:
        on_ac = False
    else:
        on_ac = None
    match = re.search(r"(\d{1,3})%", text)
    charge = int(match.group(1)) if match else None
    return on_ac, charge


def parse_ioreg(text: str) -> bool | None:
    """``"AppleClamshellState" = Yes`` : capot fermé. Absent : pas de capot."""
    match = re.search(r'"AppleClamshellState"\s*=\s*(Yes|No)', text)
    if match is None:
        return None
    return match.group(1) == "Yes"


def parse_systemstate(text: str) -> tuple[str, ...] | None:
    """``Current System Capabilities are: CPU Graphics Audio Network`` en
    réveil complet ; sans ``Graphics`` en DarkWake. ``None`` si absent."""
    match = re.search(r"Current System Capabilities are:\s*(.*)", text)
    if match is None:
        return None
    return tuple(match.group(1).split())


def full_wake(capabilities: tuple[str, ...] | None) -> bool | None:
    if capabilities is None:
        return None
    return FULL_WAKE_CAPABILITY in capabilities


def _read(command: tuple[str, ...]) -> str:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=10, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def read_power_state() -> PowerState:
    on_ac, charge = parse_pmset(_read(PMSET))
    return PowerState(
        on_ac=on_ac,
        lid_closed=parse_ioreg(_read(IOREG)),
        charge=charge,
        capabilities=parse_systemstate(_read(SYSTEMSTATE)),
    )


def decide(
    state: JobState,
    now: datetime,
    power: PowerState,
    cycle_start: time = CYCLE_START,
    battery_floor: int = BATTERY_FLOOR,
) -> Verdict:
    if pass_done_since(state, cycle_threshold(now, cycle_start)):
        return Verdict(DONE)
    if full_wake(power.capabilities) is False:
        read = " ".join(power.capabilities) or "aucune"
        return Verdict(DEFERRED, f"pas en réveil complet (capacités lues : {read})")
    if power.lid_closed:
        return Verdict(DEFERRED, "capot fermé")
    if power.on_ac is False and power.charge is not None and power.charge < battery_floor:
        return Verdict(DEFERRED, f"sur batterie à {power.charge} %, plancher {battery_floor} %")
    return Verdict(GO)


# --- une ligne « lot reporté » par cycle ------------------------------------


def _read_gate_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def deferred_already_logged(path: Path, threshold: datetime) -> bool:
    """Vrai si un report a déjà été journalisé depuis le début du cycle."""
    logged = _read_gate_file(path).get("deferred_logged_at")
    if not logged:
        return False
    try:
        parsed = datetime.fromisoformat(logged)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= threshold


def record_deferred_logged(path: Path, now: datetime) -> None:
    ensure_private_home(path.parent)
    payload = _read_gate_file(path)
    payload["deferred_logged_at"] = now.astimezone(timezone.utc).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
