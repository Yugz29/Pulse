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
    return (
        any(part in IGNORED_DIRECTORY_NAMES for part in relative_path.parts[:-1])
        or path.name in IGNORED_FILE_NAMES
        or path.suffix in IGNORED_FILE_SUFFIXES
    )
