"""Domaines dont Pulse n'observe jamais la fenêtre (décision du 2026-09-12).

Une messagerie web dans un navigateur n'est pas couverte par la liste
d'applications ignorées de l'observateur : le titre de l'onglet porte
l'adresse du compte, l'URL le service. Pour ces domaines, Core refuse le
``window_focused`` à l'ingestion (204, comme une commande ignorée) : ni
titre ni URL n'entrent en base ; l'``app_activated`` du navigateur reste.

La liste vit dans ``~/.pulse_v2/ignored_domains`` (un hôte par ligne, ``#``
commentaires, un hôte couvre ses sous-domaines). Quand le fichier existe, il
remplace la liste par défaut ; ``PULSE_V2_IGNORED_DOMAINS`` désigne un autre
fichier (tests). Relue quand son horodatage change, jamais à chaque requête.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_IGNORED_DOMAINS: tuple[str, ...] = (
    "mail.google.com",
    "outlook.office.com",
    "outlook.live.com",
    "mail.proton.me",
)

_cache: tuple[Path, float | None, frozenset[str]] | None = None


def ignored_domains_path() -> Path:
    configured = os.environ.get("PULSE_V2_IGNORED_DOMAINS", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".pulse_v2" / "ignored_domains"


def parse_ignored_domains(contents: str) -> frozenset[str]:
    hosts = set()
    for line in contents.splitlines():
        entry = line.split("#", 1)[0].strip().lower().rstrip(".")
        if entry:
            hosts.add(entry)
    return frozenset(hosts)


def load_ignored_domains() -> frozenset[str]:
    """La liste du fichier s'il existe (même vide), sinon la liste par défaut."""
    global _cache
    path = ignored_domains_path()
    try:
        mtime: float | None = path.stat().st_mtime
    except OSError:
        mtime = None
    if _cache is not None and _cache[0] == path and _cache[1] == mtime:
        return _cache[2]
    if mtime is None:
        hosts = frozenset(DEFAULT_IGNORED_DOMAINS)
    else:
        try:
            hosts = parse_ignored_domains(path.read_text(encoding="utf-8"))
        except OSError:
            hosts = frozenset(DEFAULT_IGNORED_DOMAINS)
    _cache = (path, mtime, hosts)
    return hosts


def is_ignored_host(host: str | None) -> bool:
    """``host`` est un domaine ignoré ou l'un de ses sous-domaines."""
    if not host:
        return False
    candidate = host.lower().rstrip(".")
    for domain in load_ignored_domains():
        if candidate == domain or candidate.endswith("." + domain):
            return True
    return False
