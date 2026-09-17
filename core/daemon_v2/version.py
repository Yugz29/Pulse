"""La version que ce processus exécute, lue une fois, au démarrage.

``CORE_VERSION`` est le contenu de ``core/VERSION`` au moment où le processus
importe ce module : un service launchd ne recharge jamais son code, donc la
version qu'il annonce reste celle du code qu'il exécute, même après un merge
dans le checkout. Relire le fichier à chaque requête dirait la version du
checkout, pas celle du processus.

Un fichier absent, illisible ou vide donne ``UNKNOWN_VERSION``, jamais une
erreur : la collecte ne dépend pas d'un fichier de version.

``CODE_FINGERPRINT`` (``code_fingerprint.py``) est calculée au même moment :
la version se lit, l'empreinte décide. Deux services de même version peuvent
exécuter un code différent (changement mergé sans bump).

Le daemon sert les deux sur ``GET /status``. Worker et file-watcher ne servent
rien : ils les annoncent au démarrage dans ``<données>/run/<service>.json``
(pid, version, empreinte, rien d'autre), que ``make status`` relit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .code_fingerprint import python_fingerprint
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
# ``None`` si le dossier de Core est illisible : l'état sera « inconnu ».
CODE_FINGERPRINT = python_fingerprint()


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
            json.dumps(
                {
                    "pid": os.getpid(),
                    "version": CORE_VERSION,
                    "code_fingerprint": CODE_FINGERPRINT,
                }
            ),
            encoding="utf-8",
        )
        restrict_private_file(temporary)
        temporary.replace(target)
    except OSError:
        pass


def announced(
    service: str, pid: int, *, directory: Path | None = None
) -> dict[str, str | None] | None:
    """Ce que ce pid a annoncé (``version``, ``code_fingerprint``), ``None``
    si l'annonce manque, est illisible ou vient d'un autre processus (une
    exécution précédente)."""
    target = (directory or announce_directory()) / f"{service}.json"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("pid") != pid:
        return None

    def text(key: str) -> str | None:
        value = data.get(key)
        return value if isinstance(value, str) and value else None

    return {"version": text("version"), "code_fingerprint": text("code_fingerprint")}
