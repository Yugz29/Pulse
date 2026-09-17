"""Un service launchd qui n'exécute pas le code du checkout.

Le daemon, l'outbox worker et le watcher chargent le code au démarrage et ne
le rechargent jamais : après un merge dans core/, ils tournent sur l'ancien
code tant qu'ils ne sont pas redémarrés. Du 2026-09-06 au 11, le daemon a
ainsi servi schema_version 2 alors que main était au schéma 3, sans qu'aucun
affichage le montre.

Trois états, jamais deux : « à jour », « STALE », « INCONNU ». L'empreinte du
code décide (``code_fingerprint.py``), la version se lit à côté. Un service
qui n'annonce rien n'est pas déclaré à jour ni périmé : on ne sait pas.

Jusqu'à la 0.8.8.0, `make status` comparait l'heure de démarrage à la date du
dernier commit sous core/ : un docstring marquait les quatre services STALE,
et une relance levait l'alerte de l'observateur sans recharger son binaire.

Utilisation par status.sh :
`python -m daemon_v2.service_staleness <label> <pid> [version servie] [empreinte servie]`
affiche le suffixe de la ligne du service.
À l'installation de l'observateur :
`python -m daemon_v2.service_staleness --record-observer <binaire installé>`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .code_fingerprint import (
    file_sha256,
    observer_source_fingerprint,
    python_fingerprint,
)
from .private_files import restrict_private_file
from .version import announced, read_version

UP_TO_DATE = "à jour"
STALE = "STALE"
UNKNOWN = "INCONNU"

# Services Python résidents qui annoncent version et empreinte au démarrage.
ANNOUNCING_SERVICES = {
    "com.pulse.outbox-worker": "outbox-worker",
    "com.pulse.file-watcher": "file-watcher",
}
DAEMON_LABEL = "com.pulse.daemon"
OBSERVER_LABEL = "com.pulse.app-observer"
OBSERVER_BINARY = Path.home() / ".pulse_v2" / "bin" / "PulseApplicationObserver"


@dataclass(frozen=True)
class Verdict:
    state: str
    detail: str

    def suffix(self) -> str:
        return f" — {self.state} : {self.detail}"


def python_service_verdict(
    running_version: str | None,
    running_fingerprint: str | None,
    *,
    checkout_version: str,
    checkout_fingerprint: str | None,
) -> Verdict:
    shown = running_version or "non annoncée"
    if not running_fingerprint:
        return Verdict(
            UNKNOWN,
            f"version {shown}, aucune empreinte de code annoncée "
            "(service antérieur à la 0.8.9.0 ?) ; redémarrer pour savoir",
        )
    if not checkout_fingerprint:
        return Verdict(UNKNOWN, f"version {shown}, code du checkout illisible")
    if running_fingerprint == checkout_fingerprint:
        return Verdict(UP_TO_DATE, f"version {shown}, code {running_fingerprint}")
    if running_version != checkout_version:
        return Verdict(
            STALE,
            f"exécute {shown}, checkout en {checkout_version} ; à redémarrer",
        )
    return Verdict(
        STALE,
        f"version {shown} comme le checkout, mais code {running_fingerprint} "
        f"au lieu de {checkout_fingerprint} (changement sans bump) ; à redémarrer",
    )


def observer_record_path(binary: Path) -> Path:
    return binary.with_name(binary.name + ".json")


def record_observer(binary: Path, *, observer_root: Path | None = None) -> bool:
    """Note, à l'installation, de quelles sources vient ce binaire."""
    sources = (
        observer_source_fingerprint(observer_root)
        if observer_root is not None
        else observer_source_fingerprint()
    )
    binary_sha = file_sha256(binary)
    if sources is None or binary_sha is None:
        return False
    target = observer_record_path(binary)
    target.write_text(
        json.dumps({"source_fingerprint": sources, "binary_sha256": binary_sha}),
        encoding="utf-8",
    )
    restrict_private_file(target)
    return True


def observer_verdict(
    binary: Path = OBSERVER_BINARY, *, observer_root: Path | None = None
) -> Verdict:
    """Le binaire installé vient-il des sources du checkout ?

    Une relance ne met pas ce binaire à jour : périmé veut dire réinstaller
    (``install_observers_launchd.sh``), ce qui redemande l'Accessibilité.
    """
    try:
        record = json.loads(observer_record_path(binary).read_text(encoding="utf-8"))
        recorded_sources = record["source_fingerprint"]
        recorded_binary = record["binary_sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return Verdict(
            UNKNOWN,
            "binaire installé sans empreinte de ses sources (antérieur à la "
            "0.8.9.0) ; une réinstallation la notera",
        )
    if file_sha256(binary) != recorded_binary:
        return Verdict(UNKNOWN, "binaire remplacé hors du script d'installation")
    current = (
        observer_source_fingerprint(observer_root)
        if observer_root is not None
        else observer_source_fingerprint()
    )
    if current is None:
        return Verdict(UNKNOWN, "sources Swift du checkout illisibles")
    if current == recorded_sources:
        return Verdict(UP_TO_DATE, f"binaire des sources {current}")
    return Verdict(
        STALE,
        f"binaire des sources {recorded_sources}, checkout en {current} ; "
        "à réinstaller (une relance ne suffit pas)",
    )


def service_suffix(
    label: str,
    pid: int,
    *,
    served_version: str | None = None,
    served_fingerprint: str | None = None,
) -> str:
    if label == OBSERVER_LABEL:
        return observer_verdict().suffix()
    if label == DAEMON_LABEL:
        version, fingerprint = served_version, served_fingerprint
    elif label in ANNOUNCING_SERVICES:
        announce = announced(ANNOUNCING_SERVICES[label], pid) or {}
        version, fingerprint = announce.get("version"), announce.get("code_fingerprint")
    else:
        return ""
    return python_service_verdict(
        version,
        fingerprint,
        checkout_version=read_version(),
        checkout_fingerprint=python_fingerprint(),
    ).suffix()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "--record-observer":
        return 0 if record_observer(Path(args[1])) else 1
    if not 2 <= len(args) <= 4 or args[0].startswith("--"):
        print(
            "usage: python -m daemon_v2.service_staleness <label> <pid> "
            "[version servie] [empreinte servie]\\n"
            "       python -m daemon_v2.service_staleness --record-observer <binaire>",
            file=sys.stderr,
        )
        return 2
    served = [value or None for value in args[2:]] + [None, None]
    print(
        service_suffix(
            args[0], int(args[1]), served_version=served[0], served_fingerprint=served[1]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
