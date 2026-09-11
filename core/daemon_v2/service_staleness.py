"""Un service launchd plus vieux que le code qu'il est censé exécuter.

Le daemon, l'outbox worker, le watcher et l'observateur chargent le code au
démarrage et ne le rechargent jamais : après un merge dans core/, ils
tournent sur l'ancien code tant qu'ils ne sont pas redémarrés. Du
2026-09-06 au 11, le daemon a ainsi servi schema_version 2 alors que main
était au schéma 3, sans qu'aucun affichage le montre. `make status`
compare l'heure de démarrage de chaque service (ps -o etime) à la date du
dernier commit touchant core/ sur la branche courante, et écrit STALE.

Utilisation par status.sh : `python -m daemon_v2.service_staleness <pid> <epoch>`
affiche « STALE » si le processus a démarré avant l'epoch, rien sinon.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone


def elapsed_seconds(etime: str) -> int:
    """`ps -o etime=` : ``[[jj-]hh:]mm:ss``, sans dépendre de la locale."""
    text = etime.strip()
    days = 0
    if "-" in text:
        day_text, text = text.split("-", 1)
        days = int(day_text)
    parts = [int(part) for part in text.split(":")]
    if len(parts) == 2:
        hours, (minutes, seconds) = 0, parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"etime inattendu : {etime!r}")
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def started_at(etime: str, *, now: datetime) -> datetime:
    return now - timedelta(seconds=elapsed_seconds(etime))


def is_stale(started: datetime, *, code_changed_at: datetime) -> bool:
    """Démarré strictement avant le dernier commit du code : périmé."""
    return started < code_changed_at


def process_started_at(pid: int, *, now: datetime | None = None) -> datetime | None:
    """L'heure de démarrage d'un processus vivant, ``None`` s'il n'existe pas."""
    result = subprocess.run(
        ["ps", "-o", "etime=", "-p", str(pid)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return started_at(result.stdout, now=now or datetime.now(timezone.utc))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m daemon_v2.service_staleness <pid> <code_changed_epoch>", file=sys.stderr)
        return 2
    pid, epoch = int(args[0]), int(args[1])
    started = process_started_at(pid)
    if started is None:
        return 0
    if is_stale(started, code_changed_at=datetime.fromtimestamp(epoch, tz=timezone.utc)):
        print("STALE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
