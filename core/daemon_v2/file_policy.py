"""File-noise policy shared by collection and historical projection.

Pure, à une exception nommée : ``inside_virtualenv_on_disk`` lit le disque et
ne sert qu'à la collecte. La projection de l'historique n'appelle que les
fonctions pures.
"""
from pathlib import Path
from typing import Any, Iterable

IGNORED_DIRECTORY_NAMES = {
    ".build",
    ".git",
    # Index GitNexus (base lbug + CSV régénérés à chaque analyse) : du churn
    # d'outillage, pas du travail — il remplissait /context jusqu'à la
    # troncature des fichiers.
    ".gitnexus",
    ".pytest_cache",
    ".swiftpm",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
# ``.git`` est aussi un fichier : celui d'un worktree lié ou d'un sous-module
# (une ligne ``gitdir:``), jamais un fichier de travail.
IGNORED_FILE_NAMES = {".DS_Store", ".git"}
IGNORED_FILE_SUFFIXES = {".pyc", ".db"}
# Un virtualenv se reconnaît à ce fichier, pas à son nom : ``.venv`` est dans
# la liste ci-dessus, ``DevNote-env`` ne l'était pas (13 059 ``file_changed``
# en neuf minutes le 2026-09-17, une entrée de résumé de 951 008 tokens).
VIRTUALENV_MARKER = "pyvenv.cfg"

def should_ignore(path: Path, workspace: Path) -> bool:
    try:
        relative_path = path.relative_to(workspace)
    except ValueError:
        return True
    return _is_noise(relative_path.parts[:-1], path)


def virtualenv_roots(paths: Iterable[str | Path]) -> frozenset[Path]:
    """Racines de virtualenv que ces chemins révèlent : le dossier de tout
    ``pyvenv.cfg`` observé, qu'il ait été créé, modifié ou supprimé.

    Pour la projection de l'historique : pure, sans lecture du disque. La même
    base rend la même projection, que le virtualenv existe encore ou non ;
    un ``input_hash`` se recalcule à l'identique des jours plus tard.
    """
    return frozenset(
        Path(path).parent for path in paths if Path(path).name == VIRTUALENV_MARKER
    )


def under_virtualenv(path: Path, roots: frozenset[Path]) -> bool:
    """``path`` est-il un virtualenv connu, ou sous l'un d'eux ?"""
    return bool(roots) and any(root == path or root in path.parents for root in roots)


def attributed_workspace(path: str, workspace: Any) -> str | None:
    """Workspace persisté d'un ``file_changed`` (chaîne, ou forme résolue
    ``{"workspace_root": …}``), ou ``None`` s'il ne contient pas ``path`` :
    un workspace historique incohérent est une attribution inconnue, pas la
    preuve que le fichier est du bruit."""
    if isinstance(workspace, dict):
        workspace = workspace.get("workspace_root")
    if workspace and not Path(path).is_relative_to(workspace):
        return None
    return workspace


def is_file_noise(
    path: str, workspace: str | None, virtualenvs: frozenset[Path]
) -> bool:
    """Le prédicat de bruit de l'historique, un seul pour ses deux lecteurs :
    la projection (``/context``, entrée des résumés) et l'affichage du
    journal. ``workspace`` sort de ``attributed_workspace``."""
    return bool(workspace and should_ignore(Path(path), Path(workspace))) or (
        under_virtualenv(Path(path), virtualenvs)
    )


def inside_virtualenv_on_disk(path: Path, workspace: Path) -> bool:
    """Un dossier entre ``workspace`` et ``path`` porte-t-il ``pyvenv.cfg`` ?

    Pour la collecte seulement : elle regarde le disque au moment du
    changement. ``path`` peut être un fichier ou un dossier ; le workspace
    lui-même n'est jamais un virtualenv à écarter.
    """
    try:
        relative = path.relative_to(workspace)
    except ValueError:
        return False
    current = workspace
    for part in relative.parts:
        current = current / part
        # Sur le fichier lui-même, le test est faux sans dommage.
        if (current / VIRTUALENV_MARKER).is_file():
            return True
    return False


def is_noise_path(path: Path) -> bool:
    """Même politique de bruit, sans workspace : pour un chemin observé hors
    collecte (le document d'une fenêtre), chaque dossier du chemin compte."""
    return _is_noise(path.parts[:-1], path)


def _is_noise(directory_parts: tuple[str, ...], path: Path) -> bool:
    return (
        any(part in IGNORED_DIRECTORY_NAMES for part in directory_parts)
        or path.name in IGNORED_FILE_NAMES
        or path.suffix in IGNORED_FILE_SUFFIXES
    )
