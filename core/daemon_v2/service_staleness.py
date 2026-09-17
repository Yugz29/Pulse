"""Un service launchd qui exécute une autre version que celle du checkout.

Le daemon, l'outbox worker et le watcher chargent le code au démarrage et ne
le rechargent jamais : après un merge dans core/, ils tournent sur l'ancien
code tant qu'ils ne sont pas redémarrés. Du 2026-09-06 au 11, le daemon a
ainsi servi schema_version 2 alors que main était au schéma 3, sans qu'aucun
affichage le montre.

`make status` compare la version que chaque service exécute (``version.py`` :
servie par ``/status`` pour le daemon, annoncée au démarrage pour le worker
et le watcher) à ``core/VERSION`` du checkout. Jusqu'à la 0.8.8.0, il
comparait l'heure de démarrage à la date du dernier commit sous core/ : un
docstring marquait les quatre services STALE, et une relance sans effet
levait l'alerte. Ce que la comparaison de versions ne voit pas : un
changement de code mergé sans bump de ``VERSION``.

Utilisation par status.sh :
`python -m daemon_v2.service_staleness <label> <pid> [version servie]`
affiche le suffixe de la ligne du service.
"""

from __future__ import annotations

import sys

from .version import UNKNOWN_VERSION, announced_version, read_version

# Services Python résidents qui annoncent leur version au démarrage.
ANNOUNCING_SERVICES = {
    "com.pulse.outbox-worker": "outbox-worker",
    "com.pulse.file-watcher": "file-watcher",
}
DAEMON_LABEL = "com.pulse.daemon"
OBSERVER_LABEL = "com.pulse.app-observer"


def staleness_suffix(running: str | None, checkout: str) -> str:
    """Le suffixe d'une ligne de service : version, ou STALE et pourquoi."""
    if checkout == UNKNOWN_VERSION:
        shown = running or "inconnue"
        return f" — version {shown} (core/VERSION illisible : non comparée)"
    if not running:
        return (
            " — STALE : version non annoncée (service antérieur à la 0.8.9.0), "
            "à redémarrer"
        )
    if running != checkout:
        return f" — STALE : exécute {running}, checkout en {checkout}, à redémarrer"
    return f" — version {running}"


def service_suffix(
    label: str, pid: int, *, served: str | None = None, checkout: str | None = None
) -> str:
    checkout = read_version() if checkout is None else checkout
    if label == DAEMON_LABEL:
        return staleness_suffix(served, checkout)
    if label in ANNOUNCING_SERVICES:
        return staleness_suffix(
            announced_version(ANNOUNCING_SERVICES[label], pid), checkout
        )
    if label == OBSERVER_LABEL:
        # Binaire Swift copié hors du dépôt à l'installation : une relance ne
        # recharge pas son code, une version de Core n'en dit rien.
        return " — non comparé (binaire installé, mis à jour par réinstallation)"
    return ""


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (2, 3):
        print(
            "usage: python -m daemon_v2.service_staleness <label> <pid> [version servie]",
            file=sys.stderr,
        )
        return 2
    served = args[2] if len(args) == 3 and args[2] else None
    print(service_suffix(args[0], int(args[1]), served=served))
    return 0


if __name__ == "__main__":
    sys.exit(main())
