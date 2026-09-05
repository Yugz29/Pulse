"""Permissions locales des données de Pulse (politique du 2026-09-03).

``~/.pulse_v2/`` (trace, journaux, archives de transcripts, manifestes) et
``~/.pulse_core/`` (outbox durable) contiennent des commandes, des messages
de commit et des transcripts : dossiers ``0700``, fichiers ``0600``, umask
``077`` dans chaque point d'entrée avant la première création.

Sans Flask ni dépendance : importable par tous les producteurs et scripts.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


PRIVATE_UMASK = 0o077
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_GROUP_OR_OTHER = 0o077


def apply_private_umask() -> int:
    """À appeler en tête de chaque point d'entrée ; rend l'umask précédent."""
    return os.umask(PRIVATE_UMASK)


def private_roots() -> tuple[Path, ...]:
    """Les racines dont Pulse corrige les permissions s'il les trouve trop larges."""
    home = Path.home()
    return (home / ".pulse_v2", home / ".pulse_core")


def is_private_path(path: Path) -> bool:
    """Le chemin est-il sous une racine Pulse ?

    La comparaison lexicale de ``PurePath`` est sensible à la casse alors
    qu'APFS ne l'est pas : un chemin écrit ``~/.pulse_v2`` sous un ``$HOME``
    d'une autre casse désignait le même dossier sans être reconnu, donc sans
    être resserré en ``0700``/``0600``.

    Le repli demande au système, pas à une heuristique de casse : deux chemins
    ne sont rapprochés que si le noyau dit que ce sont le **même objet**
    (``st_dev``/``st_ino``). Sur un volume sensible à la casse, ``.PULSE_V2``
    et ``.pulse_v2`` restent donc deux dossiers distincts, et le second n'est
    pas reconnu — ce qui est correct. La reconnaissance s'élargit ;
    ``private_roots()`` ne bouge pas, donc l'ensemble des dossiers dont Pulse
    modifie le mode ne s'élargit jamais.
    """
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    roots: list[Path] = []
    for root in private_roots():
        try:
            resolved_root = root.resolve()
        except OSError:
            continue
        roots.append(resolved_root)
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            continue
        return True
    return _is_inside_by_identity(resolved, roots)


def _is_inside_by_identity(resolved: Path, roots: list[Path]) -> bool:
    """``resolved`` ou l'un de ses parents est-il le même objet qu'une racine ?"""
    root_identities: set[tuple[int, int]] = set()
    for root in roots:
        try:
            info = root.stat()
        except OSError:
            continue
        root_identities.add((info.st_dev, info.st_ino))
    if not root_identities:
        return False
    for candidate in (resolved, *resolved.parents):
        try:
            info = candidate.stat()
        except OSError:
            continue
        if (info.st_dev, info.st_ino) in root_identities:
            return True
    return False


def ensure_private_directory(path: Path) -> Path:
    """Crée ``path`` (et ses parents manquants) en ``0700``.

    Un dossier déjà présent n'est resserré que sous une racine Pulse : on ne
    change jamais le mode d'un dossier qui n'est pas le nôtre (``/tmp``, le
    ``tmp_path`` des tests, un ``PULSE_V2_DB_PATH`` arbitraire).
    """
    target = path.expanduser()
    missing: list[Path] = []
    cursor = target
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)
        except FileExistsError:
            pass
        # mkdir applique l'umask ambiant : on impose le mode voulu ensuite.
        os.chmod(directory, PRIVATE_DIRECTORY_MODE)
    if not missing and is_private_path(target):
        _restrict(target, PRIVATE_DIRECTORY_MODE)
    return target


def restrict_private_file(path: Path) -> None:
    """Ramène un fichier que Pulse a créé lui-même à ``0600`` s'il est plus large."""
    target = path.expanduser()
    if target.is_file():
        _restrict(target, PRIVATE_FILE_MODE)


def _restrict(target: Path, mode: int) -> None:
    current = stat.S_IMODE(target.stat().st_mode)
    if current & _GROUP_OR_OTHER:
        os.chmod(target, mode)
