"""Empreinte du code qu'un service exécute, comparable à celle du checkout.

La version seule ne suffit pas : un changement de code mergé sans bump de
``VERSION`` la laisse intacte. La date du dernier commit ne suffit pas non
plus : un docstring rétabli (#106, 2026-09-17) marquait les quatre services
STALE. L'empreinte tranche sur le contenu : chaque fichier ``.py`` de
``daemon_v2`` est réduit à son arbre syntaxique, docstrings retirées. Un
commentaire, une docstring ou une remise en forme ne la changent pas ; toute
instruction modifiée, ajoutée ou retirée la change, bump ou pas. ``VERSION``
et ``requirements.txt`` en font partie : une version servie fausse ou une
dépendance déclarée nouvelle demandent aussi une relance.

Pure lecture du dossier de Core, sans Git ni sous-processus. Le paquet entier
compte pour chaque service, pas seulement les modules qu'il charge : une
approximation du côté sûr, un STALE de trop se lève par une relance.

L'observateur Swift est un binaire copié hors du dépôt : on ne peut pas le
recalculer depuis le checkout sans le reconstruire. Son empreinte est celle
de ses sources (octets), notée à l'installation à côté du binaire.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = CORE_ROOT / "daemon_v2"
OBSERVER_ROOT = CORE_ROOT / "macos_observer"
# Hors empreinte Python : ni tests, ni scripts shell (relus à chaque
# exécution), ni documentation.
EXTRA_FILES = ("VERSION", "requirements.txt")
FINGERPRINT_LENGTH = 12
_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _normalized_source(source: bytes) -> bytes:
    """L'arbre syntaxique sans docstrings ; les octets tels quels si le
    fichier ne se parse pas (même repli des deux côtés de la comparaison)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return source
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_OWNERS) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            # Retirée, pas remplacée : en ajouter ou en ôter une ne change
            # rien. Un corps fait de sa seule docstring vaut ``pass``.
            node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(tree, include_attributes=False).encode("utf-8")


def _digest(entries: list[tuple[str, bytes]]) -> str | None:
    if not entries:
        return None
    digest = hashlib.sha256()
    for name, content in sorted(entries):
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()[:FINGERPRINT_LENGTH]


def python_fingerprint(core_root: Path = CORE_ROOT) -> str | None:
    """Empreinte du code Python de Core, ``None`` si rien n'est lisible."""
    package = core_root / "daemon_v2"
    entries: list[tuple[str, bytes]] = []
    try:
        for path in package.rglob("*.py"):
            entries.append(
                (path.relative_to(core_root).as_posix(), _normalized_source(path.read_bytes()))
            )
        for name in EXTRA_FILES:
            extra = core_root / name
            # Absent et vide ne se confondent pas avec « contenu X ».
            entries.append((name, extra.read_bytes() if extra.is_file() else b"\0absent"))
    except OSError:
        return None
    return _digest(entries) if any(name.endswith(".py") for name, _ in entries) else None


def observer_source_fingerprint(observer_root: Path = OBSERVER_ROOT) -> str | None:
    """Empreinte des sources Swift de l'observateur : ``Package.swift``,
    ``Package.resolved`` s'il existe, et ``Sources/``. Octets bruts."""
    entries: list[tuple[str, bytes]] = []
    try:
        for name in ("Package.swift", "Package.resolved"):
            if (observer_root / name).is_file():
                entries.append((name, (observer_root / name).read_bytes()))
        for path in (observer_root / "Sources").rglob("*"):
            if path.is_file():
                entries.append((path.relative_to(observer_root).as_posix(), path.read_bytes()))
    except OSError:
        return None
    return _digest(entries)


def file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
