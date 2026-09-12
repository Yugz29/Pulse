"""Pure file-noise policy shared by collection and historical projection."""
from pathlib import Path

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
IGNORED_FILE_NAMES = {".DS_Store"}
IGNORED_FILE_SUFFIXES = {".pyc", ".db"}

def should_ignore(path: Path, workspace: Path) -> bool:
    try:
        relative_path = path.relative_to(workspace)
    except ValueError:
        return True
    return _is_noise(relative_path.parts[:-1], path)


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
