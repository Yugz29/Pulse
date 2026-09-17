"""La version que ce processus exécute, lue une fois, au démarrage.

``CORE_VERSION`` est le contenu de ``core/VERSION`` au moment où le processus
importe ce module : un service launchd ne recharge jamais son code, donc la
version qu'il annonce reste celle du code qu'il exécute, même après un merge
dans le checkout. Relire le fichier à chaque requête dirait la version du
checkout, pas celle du processus.

Un fichier absent, illisible ou vide donne ``UNKNOWN_VERSION``, jamais une
erreur : la collecte ne dépend pas d'un fichier de version.

Le daemon sert sa version sur ``GET /status``. Worker et file-watcher ne
servent rien : ils l'annoncent au démarrage dans ``<données>/run/<service>.json``
(pid et version, rien d'autre), que ``make status`` relit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .private_files import ensure_private_directory, restrict_private_file
from .runtime_config import select_database_path

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
UNKNOWN_VERSION = "unknown"


def read_version(path: Path = VERSION_FILE) -> str:
    try:
        return path.read_text(encoding="utf-8").strip() or UNKNOWN_VERSION
    except (OSError, UnicodeDecodeError):
        return UNKNOWN_VERSION


CORE_VERSION = read_version()


def announce_directory() -> Path:
    # À côté de la base : un Core jetable (PULSE_V2_DB_PATH) n'écrase pas
    # l'annonce de la production.
    return select_database_path().parent / "run"


def announce(service: str, *, directory: Path | None = None) -> None:
    """Écrit la version de ce processus. Ne lève jamais : un service qui ne
    peut pas s'annoncer tourne quand même, et ``make status`` le dira."""
    target = (directory or announce_directory()) / f"{service}.json"
    try:
        ensure_private_directory(target.parent)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"pid": os.getpid(), "version": CORE_VERSION}),
            encoding="utf-8",
        )
        restrict_private_file(temporary)
        temporary.replace(target)
    except OSError:
        pass


def announced_version(
    service: str, pid: int, *, directory: Path | None = None
) -> str | None:
    """La version annoncée par ce pid, ``None`` si l'annonce manque, est
    illisible ou vient d'un autre processus (une exécution précédente)."""
    target = (directory or announce_directory()) / f"{service}.json"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("pid") != pid:
        return None
    version = data.get("version")
    return version if isinstance(version, str) and version else None
