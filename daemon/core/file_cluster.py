"""
file_cluster.py — Regroupement sémantique de fichiers pour le journal.

Transforme une liste de noms de fichiers en description lisible groupée par langage.

Exemples :
  ["extractor.py", "session.py"]
  → "extractor.py, session.py"

  ["extractor.py", "session.py", "file_classifier.py", "NotchWindow.swift"]
  → "Python (extractor.py, session.py +1) · Swift (NotchWindow.swift)"

  ["runtime.py", "extractor.py", "session.py", "episode_fsm.py", "NotchWindow.swift", "PanelView.swift"]
  → "Python (runtime.py, extractor.py +2) · Swift (NotchWindow.swift, PanelView.swift)"
"""

from __future__ import annotations

from typing import Dict, List

# Mappage extension → étiquette lisible.
# Les extensions non listées tombent dans "autre".
_EXT_TO_LANG: Dict[str, str] = {
    ".py":   "Python",
    ".swift": "Swift",
    ".ts":   "TypeScript",
    ".tsx":  "TypeScript",
    ".js":   "JavaScript",
    ".jsx":  "JavaScript",
    ".go":   "Go",
    ".rs":   "Rust",
    ".rb":   "Ruby",
    ".java": "Java",
    ".kt":   "Kotlin",
    ".cs":   "C#",
    ".c":    "C",
    ".cpp":  "C++",
    ".h":    "C/C++",
    ".hpp":  "C++",
    ".m":    "Objective-C",
    ".mm":   "Objective-C++",
    ".sh":   "Shell",
    ".bash": "Shell",
    ".zsh":  "Shell",
    ".sql":  "SQL",
    ".md":   "docs",
    ".rst":  "docs",
    ".txt":  "docs",
    ".adoc": "docs",
    ".yaml": "config",
    ".yml":  "config",
    ".toml": "config",
    ".json": "config",
    ".jsonc": "config",
    ".ini":  "config",
    ".cfg":  "config",
    ".conf": "config",
}


def _file_language(filename: str) -> str:
    """Retourne l'étiquette de langage d'un nom de fichier."""
    if "." not in filename:
        return "autre"
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    return _EXT_TO_LANG.get(ext, "autre")


def cluster_files_for_display(files: List[str], threshold: int = 3) -> str:
    """
    Retourne une description lisible et groupée d'une liste de fichiers.

    - Si ≤ threshold fichiers : liste directe séparée par des virgules.
    - Si > threshold fichiers : regroupement par langage avec comptage.

    Le threshold par défaut est 3 — au-delà, le regroupement apporte
    plus de lisibilité qu'une liste plate.

    Args:
        files     : liste de noms de fichiers (sans chemin complet)
        threshold : nombre de fichiers à partir duquel on regroupe

    Returns:
        Chaîne lisible, ex.
        "extractor.py, session.py"
        "Python (extractor.py, session.py +1) · Swift (NotchWindow.swift)"
    """
    if not files:
        return "non déterminée"

    if len(files) <= threshold:
        return ", ".join(files)

    # Regroupement par langage — ordre d'insertion conservé pour chaque groupe.
    groups: Dict[str, List[str]] = {}
    for f in files:
        lang = _file_language(f)
        groups.setdefault(lang, []).append(f)

    # Un seul langage : liste les deux premiers + comptage du reste.
    if len(groups) == 1:
        lang = next(iter(groups))
        shown = files[:2]
        rest = len(files) - 2
        suffix = f" +{rest}" if rest > 0 else ""
        return f"{', '.join(shown)}{suffix} {lang}"

    # Multi-langage : un fragment par groupe, groupes triés par taille décroissante.
    parts: List[str] = []
    for lang, filenames in sorted(groups.items(), key=lambda item: -len(item[1])):
        if len(filenames) == 1:
            parts.append(filenames[0])
        elif len(filenames) == 2:
            parts.append(f"{filenames[0]}, {filenames[1]} ({lang})")
        else:
            rest = len(filenames) - 1
            parts.append(f"{filenames[0]} +{rest} {lang}")

    # Limite à 3 groupes pour ne pas dépasser une ligne.
    return " · ".join(parts[:3])
