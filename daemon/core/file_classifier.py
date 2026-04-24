"""
file_classifier.py — Classification des chemins de fichiers.

Source de vérité unique pour la distinction technique_noise / meaningful / neutral
et pour la classification par type (source, test, config, docs, assets, other).

Importé par :
  - signal_scorer.py  (filtrage des events avant scoring)
  - state_store.py    (filtrage avant mise à jour de active_file)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# ── Bruit récurrent à faible valeur produit ──────────────────────────────────

_SCREENSHOT_MARKERS = (
    "capture d\u2019\u00e9cran",  # apostrophe curly macOS (U+2019)
    "capture d'ecran",
    "capture d'\u00e9cran",
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

# Regex UUID standard (8-4-4-4-12 hex).
# Tout fichier dont le nom contient un UUID est du bruit système
# (télémétrie, events, cache applicatif) — jamais du code utilisateur.
# Ex : 1p_failed_events.bd63bb8f-c123-4dbe-8641-619c47b09fa0.json
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _is_screenshot_capture(name: str) -> bool:
    lower_name = name.lower()
    return (
        lower_name.endswith(_SCREENSHOT_EXTENSIONS)
        and any(marker in lower_name for marker in _SCREENSHOT_MARKERS)
    )


def _is_git_hash_filename(name: str) -> bool:
    """
    Retourne True si le nom de fichier est un hash git
    (40 caractères hexadécimaux, avec ou sans extension).
    Ex : b0ea68e2170702581ea23134b2f69d16a2bfd5ab.json
    """
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return len(stem) == 40 and all(c in "0123456789abcdef" for c in stem.lower())


def _contains_uuid(name: str) -> bool:
    """
    Retourne True si le nom de fichier contient un UUID.
    Ex : 1p_failed_events.bd63bb8f-c123-4dbe-8641-619c47b09fa0.9f22...json
    """
    return bool(_UUID_RE.search(name))


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

    # Hashes git (ex. b0ea68e2170702581ea23134b2f69d16a2bfd5ab.json)
    if _is_git_hash_filename(name):
        return "technical_noise"

    # Fichiers contenant un UUID — télémétrie, events, cache applicatif
    if _contains_uuid(name):
        return "technical_noise"

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
            "/.git/", "/node_modules/", "/__pycache__/",
            "/xcuserdata/", "/DerivedData/",
            "/site-packages/", "/dist-packages/", "/.venv/", "/venv/",
            "/opt/homebrew/Cellar/", "/opt/homebrew/lib/",
            "/usr/local/lib/", "/usr/lib/", "/usr/share/",
            "/System/Library/", "/private/var/",
        )
    ):
        return "technical_noise"

    # Téléchargements
    if "/Downloads/" in path:
        return "neutral"

    # Lockfiles
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

    # Neutral
    if lower_path.endswith((".lock", ".csv")):
        return "neutral"

    return "neutral"
