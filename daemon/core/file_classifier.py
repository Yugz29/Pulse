"""
file_classifier.py — Classification des chemins de fichiers.

Source de vérité unique pour la distinction technique_noise / meaningful / neutral
et pour la classification par type (source, test, config, docs, assets, other).

Importé par :
  - signal_scorer.py  (filtrage des events avant scoring)
  - state_store.py    (filtrage avant mise à jour de active_file)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# ── Bruit récurrent à faible valeur produit ──────────────────────────────────

_SCREENSHOT_MARKERS = (
    "capture d’écran",
    "capture d'ecran",
    "capture d'écran",
    "screenshot",
)

_SCREENSHOT_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".heic",
    ".tiff",
    ".webp",
)


def _is_screenshot_capture(name: str) -> bool:
    lower_name = name.lower()
    return (
        lower_name.endswith(_SCREENSHOT_EXTENSIONS)
        and any(marker in lower_name for marker in _SCREENSHOT_MARKERS)
    )


# ── Pulse interne ─────────────────────────────────────────────────────────────

def is_pulse_internal_path(path: str) -> bool:
    """Retourne True si le chemin pointe vers ~/.pulse/."""
    pulse_home = Path.home() / ".pulse"
    try:
        candidate = Path(path)
    except Exception:
        return False
    return candidate == pulse_home or pulse_home in candidate.parents


# ── Classification par type ───────────────────────────────────────────────────

def classify_file_type(path: str) -> str:
    """
    Catégorise un fichier en : source | test | config | docs | assets | other.

    Ordre de priorité :
      1. Patterns de chemin (tests/, test/, spec/)
      2. Noms de fichiers connus (package.json, Makefile, …)
      3. Extensions
    """
    lower_path = path.lower()
    name = lower_path.split("/")[-1]

    # Tests — chemin ou nom de fichier
    if any(marker in lower_path for marker in ("/tests/", "/test/", "/spec/")):
        return "test"
    if name.startswith(("test_", "spec_")) or name.endswith((
        "_test.py", "_spec.py",
        ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx",
        ".test.ts", ".test.tsx", ".test.js", ".test.jsx",
        "test.swift",
    )):
        return "test"

    # Config — noms exacts
    if name in {
        "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
        "pyproject.toml", "requirements.txt", "poetry.lock", "pipfile", "pipfile.lock",
        "cargo.toml", "cargo.lock", "go.mod", "go.sum", "package.swift",
        "podfile", "podfile.lock", "gemfile", "gemfile.lock", "makefile",
        "dockerfile", "docker-compose.yml", "docker-compose.yaml", ".env",
        "tsconfig.json", "tsconfig.base.json",
        "vite.config.ts", "vite.config.js", "vite.config.mts",
        "vite.config.cjs", "vite.config.mjs",
        "jest.config.js", "jest.config.ts",
        "vitest.config.ts", "vitest.config.js",
        "playwright.config.ts", "playwright.config.js",
        ".editorconfig",
    }:
        return "config"

    # Config — extensions
    if name.endswith((
        ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".conf", ".properties", ".env.local", ".env.example",
    )):
        return "config"

    # Plists : seulement les fichiers de projet connus
    # Les plists systèmes (appPrivateData, syncstatus, metrics, etc.) génèrent
    # du bruit constant en arrière-plan — ils ne constituent pas un signal de travail.
    # Comparaison sur le nom original (case-sensitive) — name est en lowercase.
    original_name = path.split("/")[-1]
    if original_name.endswith(".plist") and original_name in {
        "Info.plist", "Entitlements.plist",
        "Debug.entitlements", "Release.entitlements",
    }:
        return "config"

    # Docs
    if name.endswith((".md", ".rst", ".txt", ".adoc")) or "/docs/" in lower_path:
        return "docs"

    # Assets
    if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")):
        return "assets"

    # Source
    if name.endswith((
        ".py", ".js", ".ts", ".tsx", ".jsx", ".swift", ".kt", ".java",
        ".go", ".rs", ".rb", ".php", ".c", ".h", ".cpp", ".hpp",
        ".m", ".mm", ".cs", ".sh", ".bash", ".zsh", ".sql",
    )):
        return "source"

    return "other"


# ── Significance ──────────────────────────────────────────────────────────────

def file_signal_significance(path: Optional[str]) -> str:
    """
    Évalue l'importance d'un chemin de fichier pour le scoring de signal.

    Retourne :
      "technical_noise" — à ignorer complètement
      "meaningful"      — influence active_file, probable_task, focus
      "neutral"         — trackable mais non prioritaire
    """
    if not path:
        return "technical_noise"
    if is_pulse_internal_path(path):
        return "technical_noise"

    name = path.split("/")[-1]
    lower_name = name.lower()
    lower_path = path.lower()

    # Bruit système
    if name.startswith("."):
        return "technical_noise"
    if "/.trash/" in lower_path:
        return "technical_noise"
    if name.endswith((".DS_Store", "~", ".xcuserstate")):
        return "technical_noise"
    if name == "COMMIT_EDITMSG":
        return "technical_noise"
    if name.endswith((
        ".sqlite", ".sqlite3", ".db", ".db-journal", ".db-wal", ".db-shm",
        ".log", ".jsonl", ".tmp", ".temp", ".swp", ".swo",
    )):
        return "technical_noise"
    # JSON de cache auto-générés : bruit technique récurrent qui ne doit pas
    # piloter le contexte courant ni la tâche probable.
    if lower_name == "models_cache.json":
        return "technical_noise"
    if lower_name.endswith(("_cache.json", "-cache.json", ".cache.json")):
        return "technical_noise"
    if _is_screenshot_capture(name):
        return "technical_noise"
    if name.endswith(("-journal", "-wal", "-shm")):
        return "technical_noise"
    if ".sb-" in name:
        return "technical_noise"
    if any(
        segment in path
        for segment in (
            # Outils de développement
            "/.git/", "/node_modules/", "/__pycache__/",
            "/xcuserdata/", "/DerivedData/",
            # Environnements Python
            "/site-packages/", "/dist-packages/", "/.venv/", "/venv/",
            # Librairies système macOS / Homebrew
            "/opt/homebrew/Cellar/", "/opt/homebrew/lib/",
            "/usr/local/lib/", "/usr/lib/", "/usr/share/",
            "/System/Library/", "/private/var/",
        )
    ):
        return "technical_noise"

    # Lockfiles — auto-générés, pas d'action utilisateur directe
    _LOCKFILE_NAMES = {
        "poetry.lock", "pipfile.lock", "cargo.lock",
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "podfile.lock", "gemfile.lock", "composer.lock",
    }
    if name.lower() in _LOCKFILE_NAMES:
        return "neutral"

    # Meaningful — type de fichier connu et utile
    file_type = classify_file_type(path)
    if file_type in {"source", "test", "config", "docs", "assets"}:
        return "meaningful"

    # Neutral — lockfiles, csv, etc.
    if lower_path.endswith((".lock", ".csv")):
        return "neutral"

    return "neutral"
