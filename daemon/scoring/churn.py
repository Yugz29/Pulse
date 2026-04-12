"""
Port de churn.ts (Cortex) — calcul du churn Git via subprocess.
Compte le nombre de commits touchant un fichier sur les 30 derniers jours.
"""

import subprocess
from functools import lru_cache
from pathlib import Path


def get_churn(file_path: str, project_path: str | None = None) -> int:
    """
    Retourne le nombre de commits ayant touché file_path dans les 30 derniers jours.
    Retourne 0 si git n'est pas disponible ou si le fichier n'est pas tracké.
    """
    path = Path(file_path)
    cwd  = project_path or str(path.parent)

    try:
        result = subprocess.run(
            [
                "git", "log",
                "--since=30 days ago",
                "--oneline",
                "--follow",    # suit les renames
                "--",
                str(path),
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return 0
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        return len(lines)

    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return 0


def get_churn_batch(file_paths: list[str], project_path: str) -> dict[str, int]:
    """
    Calcule le churn pour un ensemble de fichiers en un seul appel git.
    Plus efficace que d'appeler get_churn() fichier par fichier sur un projet entier.
    """
    try:
        result = subprocess.run(
            [
                "git", "log",
                "--since=30 days ago",
                "--name-only",
                "--pretty=format:",
            ],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {p: 0 for p in file_paths}

        counts: dict[str, int] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # git retourne des chemins relatifs à la racine du dépôt
            abs_path = str(Path(project_path) / line)
            counts[abs_path] = counts.get(abs_path, 0) + 1

        return {p: counts.get(p, 0) for p in file_paths}

    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {p: 0 for p in file_paths}


def get_git_root(path: str) -> str | None:
    """Retourne la racine du dépôt git contenant path, ou None."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(Path(path).parent if Path(path).is_file() else path),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None
