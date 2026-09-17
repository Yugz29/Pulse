"""Worktrees Git liés : à quel dépôt principal ils appartiennent, et lesquels existent.

Depuis le 2026-09-17, toute branche autre que main se travaille dans un
worktree (``AGENTS.md``). Un worktree lié a pour ``.git`` un **fichier** d'une
ligne, ``gitdir: <principal>/.git/worktrees/<nom>`` ; ce dossier porte un
fichier ``commondir`` qui ramène au ``.git`` du dépôt principal. Un sous-module
a lui aussi un ``.git`` en fichier, mais pas de ``commondir`` : il n'est pas
rattaché.

Collecte seulement : ces fonctions lisent le disque ou lancent Git. Rien ici
n'est appelé par la projection de l'historique, qui ne relit que ce que les
événements ont persisté.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def main_repository_root(root: Path) -> Path | None:
    """Racine du dépôt principal quand ``root`` est un worktree lié, sinon ``None``.

    Lit la ligne ``gitdir:`` du fichier ``.git``, sans lancer Git. Tout ce qui
    ne ressemble pas exactement à un worktree lié rend ``None`` : dépôt
    ordinaire, sous-module, dépôt nu, fichier illisible.
    """
    try:
        dot_git = root / ".git"
        if not dot_git.is_file():
            return None
        first_line = dot_git.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        if not first_line.startswith("gitdir:"):
            return None
        git_dir = Path(first_line[len("gitdir:"):].strip())
        if not git_dir.is_absolute():
            git_dir = root / git_dir
        common_file = git_dir / "commondir"
        if not common_file.is_file():
            return None
        common = Path(common_file.read_text(encoding="utf-8").strip())
        if not common.is_absolute():
            common = git_dir / common
        common = common.resolve()
        if common.name != ".git":
            return None
        return common.parent
    except (OSError, IndexError, ValueError):
        return None


def repository_name(root: Path) -> str:
    """Nom du projet d'un dossier Git : celui du dépôt principal pour un
    worktree lié (``Pulse``, pas ``Pulse-live``), le sien sinon."""
    return (main_repository_root(root) or root).name


def linked_worktrees(repository: Path, *, timeout: float = 5.0) -> list[Path]:
    """Worktrees liés de ``repository`` qui existent sur le disque.

    ``git worktree list --porcelain`` ; le premier bloc est le dépôt principal
    et n'est jamais rendu. Un worktree marqué ``prunable``, nu, ou dont le
    dossier a disparu est écarté. Toute erreur de Git rend une liste vide :
    ne pas savoir n'aveugle pas ce qui est déjà observé.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    found: list[Path] = []
    blocks = [block for block in completed.stdout.split("\n\n") if block.strip()]
    for block in blocks[1:]:
        lines = block.splitlines()
        if not lines or not lines[0].startswith("worktree "):
            continue
        if any(line == "bare" or line.startswith("prunable") for line in lines[1:]):
            continue
        path = Path(lines[0][len("worktree "):])
        if path.is_dir():
            found.append(path)
    return found
