"""État d'une session d'agent Claude Code, un fichier par session, hors trace.db.

v0 du signal « l'agent attend » (décision de chantier du 2026-09-18) : les
hooks Claude Code appellent ``pulse_agent_state_hook.sh``, qui délègue ici.
Rien ne passe par Core ni par le modèle ; le plugin SwiftBar
(``pulse_agents_menu.py``) lit le dossier et affiche.

Trois états, ``since`` ne bouge que quand l'état change :

- ``working`` — posé par SessionStart, UserPromptSubmit et PostToolUse
  (un agent qui appelle un outil travaille, quel que soit l'état d'avant ;
  c'est aussi ce qui lève ``waiting_permission``).
- ``waiting_permission`` — posé par Notification ``permission_prompt``.
- ``waiting_for_you`` (« attend ta suite ») — posé par Stop, levé par
  UserPromptSubmit. Jamais masqué avec le temps : une réponse attendue
  depuis deux heures reste affichée. Notification ``idle_prompt`` ne change
  rien : Stop l'a déjà dit.

SessionEnd supprime le fichier. Les autres événements (SubagentStop,
PreToolUse, PreCompact…) sont ignorés.

Le fichier porte le pid du processus ``claude`` lui-même, trouvé en
remontant l'arbre des processus depuis le hook (Claude Code lance la
commande via un shell intermédiaire) : le plugin s'en sert pour écarter
les sessions mortes sans fichier de fin.

Aucun contenu de prompt n'est écrit : un prompt peut contenir un secret.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR_ENV = "PULSE_AGENT_STATE_DIR"
DEFAULT_STATE_DIR = Path.home() / ".pulse_v2" / "run" / "agents"

WORKING = "working"
WAITING_PERMISSION = "waiting_permission"
WAITING_FOR_YOU = "waiting_for_you"
STATES = (WORKING, WAITING_PERMISSION, WAITING_FOR_YOU)

# Nom du processus Claude Code tel que `ps -o comm=` le rend.
AGENT_PROCESS_NAMES = ("claude",)
MAX_TREE_DEPTH = 8
# Sans pid, un fichier non mis à jour depuis ce délai n'est plus affiché.
STALE_AFTER_HOURS = 12
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def state_dir() -> Path:
    override = os.environ.get(STATE_DIR_ENV)
    return Path(override).expanduser() if override else DEFAULT_STATE_DIR


def state_path(directory: Path, agent: str, session_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in session_id)
    return directory / f"{agent}-{safe}.json"


# --- Arbre des processus --------------------------------------------------------


def _process_row(pid: int) -> tuple[int, str, str] | None:
    """(ppid, comm, args) de ``pid`` via ``ps``, ou None s'il n'existe plus."""
    try:
        out = subprocess.run(
            ["ps", "-o", "ppid=,comm=,args=", "-p", str(pid)],
            capture_output=True, text=True, check=False, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    parts = out.split(None, 2)
    if len(parts) < 2:
        return None
    ppid = int(parts[0])
    comm = parts[1]
    args = parts[2] if len(parts) > 2 else ""
    return ppid, comm, args


def is_agent_process(comm: str, args: str) -> bool:
    name = Path(comm).name
    if name in AGENT_PROCESS_NAMES:
        return True
    first = args.split(None, 1)[0] if args else ""
    return Path(first).name in AGENT_PROCESS_NAMES


def resolve_agent_pid(start_pid: int, *, rows=_process_row) -> int | None:
    """Le pid du processus Claude Code au-dessus de ``start_pid``, ou None.

    Remonte les parents (au plus ``MAX_TREE_DEPTH``) jusqu'au premier dont
    le nom est ``claude`` : le hook tourne sous un shell intermédiaire, son
    ``$PPID`` n'est pas l'agent. ``start_pid`` lui-même est examiné en
    premier, au cas où le shell aurait remplacé son image par ``exec``.
    """
    pid = start_pid
    for _ in range(MAX_TREE_DEPTH):
        row = rows(pid)
        if row is None:
            return None
        ppid, comm, args = row
        if is_agent_process(comm, args):
            return pid
        if ppid <= 1:
            return None
        pid = ppid
    return None


def process_alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


# --- Transitions ------------------------------------------------------------------


def next_state(event: str, payload: dict[str, Any], current: str | None) -> str | None:
    """L'état après ``event``, ``None`` si l'événement ne change rien."""
    if event in ("SessionStart", "UserPromptSubmit", "PostToolUse"):
        return WORKING
    if event == "Stop":
        return WAITING_FOR_YOU
    if event == "Notification":
        kind = str(payload.get("notification_type") or payload.get("matcher") or "")
        if kind == "permission_prompt":
            return WAITING_PERMISSION
        return None
    return None


def read_state(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, PRIVATE_DIR_MODE)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True, ensure_ascii=False))
    os.chmod(temporary, PRIVATE_FILE_MODE)
    os.replace(temporary, path)


def apply_event(
    payload: dict[str, Any],
    *,
    directory: Path,
    hook_pid: int,
    now: datetime | None = None,
    agent: str = "claude-code",
    rows=_process_row,
) -> str:
    """Applique un événement de hook au fichier de sa session.

    Rend une courte description pour le journal (``ignored``, ``removed``,
    ``working -> waiting_for_you``…). Ne lève jamais pour un payload
    incomplet : un hook ne doit pas gêner l'agent.
    """
    event = str(payload.get("hook_event_name") or "")
    session_id = str(payload.get("session_id") or "")
    if not event or not session_id:
        return "ignored: payload sans hook_event_name ou session_id"
    path = state_path(directory, agent, session_id)
    if event == "SessionEnd":
        try:
            path.unlink()
        except FileNotFoundError:
            return "already removed"
        return "removed"
    current = read_state(path)
    target = next_state(event, payload, current.get("state") if current else None)
    if target is None:
        return f"ignored: {event}"
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    previous = current.get("state") if current else None
    data: dict[str, Any] = dict(current or {})
    cwd = payload.get("cwd") or data.get("cwd")
    # Le chemin du transcript live : lu par le bloc « Session en cours »
    # (étape 1 bis), jamais par le résumé de nuit. Gardé d'un événement à
    # l'autre si un payload ne le porte pas.
    transcript_path = payload.get("transcript_path") or data.get("transcript_path")
    data.update(
        {
            "agent": agent,
            "session_id": session_id,
            "state": target,
            "updated_at": moment,
            "cwd": cwd,
            "project": Path(str(cwd)).name if cwd else None,
            "transcript_path": transcript_path if isinstance(transcript_path, str) and transcript_path else None,
        }
    )
    if previous != target or "since" not in data:
        data["since"] = moment
    if not process_alive(data.get("pid")):
        data["pid"] = resolve_agent_pid(hook_pid, rows=rows)
    write_state(path, data)
    return f"{previous or '-'} -> {target}"


def sweep_dead(directory: Path) -> list[Path]:
    """Retire les fichiers dont le pid n'existe plus (crash, kill, redémarrage).

    Un fichier sans pid (aucun processus ``claude`` trouvé au-dessus du
    hook : autre lanceur, CI) n'est pas mort, il est inconnu : il reste, et
    seul SessionEnd le retire ; le menu le masque après ``STALE_AFTER``.
    """
    removed = []
    if not directory.is_dir():
        return removed
    for path in directory.glob("*.json"):
        data = read_state(path)
        if data is None or data.get("pid") is None or process_alive(data.get("pid")):
            continue
        try:
            path.unlink()
            removed.append(path)
        except FileNotFoundError:
            pass
    return removed


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    hook_pid = int(args[0]) if args else os.getppid()
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if len(args) > 1 and args[1]:
        # Le matcher du hook Notification, passé par l'installateur : la
        # transition ne dépend pas du nom du champ dans le payload.
        payload.setdefault("notification_type", args[1])
    directory = state_dir()
    verdict = apply_event(payload, directory=directory, hook_pid=hook_pid)
    swept = sweep_dead(directory)
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
    short_id = str(payload.get("session_id") or "-")[:8]
    print(f"[agent-state] {stamp} session={short_id} event={payload.get('hook_event_name', '-')} {verdict}"
          + (f" swept={len(swept)}" if swept else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
