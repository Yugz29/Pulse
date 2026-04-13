"""
pulse_tools.py — Outils exposés au LLM via tool calling natif Ollama.

Chaque outil est défini par :
  - Un JSON schema (pour Ollama /api/chat)
  - Une fonction Python qui l'exécute et retourne une string lisible

Outils disponibles :
  - score_file       : scoring de risque Cortex sur un fichier
  - git_diff_stat    : git diff HEAD --stat sur un projet
  - git_log_recent   : derniers commits git
  - list_scoreable_files : liste des fichiers scorables dans un projet
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


# ── Définitions JSON schema (format Ollama) ───────────────────────────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "score_file",
            "description": (
                "Évalue le risque d'un fichier source avec le scoring Cortex. "
                "Retourne un score global (0-100), un label (safe/low/medium/high/critical), "
                "et les métriques détaillées : complexité cyclomatique, churn git, "
                "taille des fonctions, profondeur d'imbrication, fan-in. "
                "Utilise cet outil quand l'utilisateur pose des questions sur la qualité "
                "ou le risque d'un fichier spécifique. Accepte aussi un nom de fichier "
                "ou un chemin relatif: l'outil essaie de résoudre le fichier automatiquement."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Chemin absolu du fichier à évaluer.",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff_stat",
            "description": (
                "Retourne le résultat de `git diff HEAD --stat` : la liste des fichiers "
                "modifiés depuis le dernier commit, avec le nombre de lignes ajoutées/supprimées. "
                "Utilise cet outil quand l'utilisateur veut savoir ce qui a changé dans le projet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Chemin absolu de la racine du projet git.",
                    }
                },
                "required": ["project_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log_recent",
            "description": (
                "Retourne les N derniers commits du projet au format condensé (hash + message). "
                "Utilise cet outil pour répondre aux questions sur l'historique récent du code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Chemin absolu de la racine du projet git.",
                    },
                    "n": {
                        "type": "integer",
                        "description": "Nombre de commits à récupérer (défaut: 10, max: 30).",
                    },
                },
                "required": ["project_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_project",
            "description": (
                "Score tous les fichiers source d'un projet et retourne un classement par risque. "
                "C'est l'outil à utiliser pour trouver les fichiers les plus risqués d'un projet entier. "
                "Retourne le top N fichiers triés par score global décroissant avec leurs métriques."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": (
                            "Chemin absolu de la racine du projet (valeur de 'Racine projet' dans le contexte), "
                            "ou simplement le nom du projet (ex: 'Pulse') si le chemin absolu n'est pas connu. "
                            "L'outil résout automatiquement les noms de projets."
                        ),
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Nombre de fichiers à retourner dans le classement (défaut: 5, max: 10).",
                    },
                },
                "required": ["project_path"],
            },
        },
    },
]


# ── Implémentations ────────────────────────────────────────────────────────────

def _stability_summary(label: str) -> str:
    return {
        "safe": "Conclusion : fichier stable, risque faible.",
        "low": "Conclusion : fichier plutot stable, avec un faible niveau de vigilance.",
        "medium": "Conclusion : fichier correct mais a surveiller si tu ajoutes de la logique critique.",
        "high": "Conclusion : zone sensible du code. Une modification merite une revue attentive.",
        "critical": "Conclusion : zone tres sensible du code. Toute modification demande une revue approfondie.",
    }.get(label, "Conclusion : niveau de risque non determine.")


def _project_risk_summary(top: list[Any], total_count: int) -> str:
    if not top:
        return f"Aucun fichier risque trouve sur {total_count} fichier(s) analyse(s)."

    highest = top[0].label
    if highest in {"safe", "low"}:
        return (
            "Lecture : classement relatif uniquement. Ce sont les fichiers les plus risques du projet, "
            "mais le projet reste globalement peu risque."
        )
    if highest == "medium":
        return (
            "Lecture : classement relatif uniquement. Le projet parait globalement correct, "
            "avec quelques zones a surveiller."
        )
    return (
        "Lecture : classement relatif + scores absolus eleves. Les premiers fichiers listes sont de vraies "
        "zones sensibles, pas seulement les moins bons d'un projet sain."
    )


def _resolve_file_path(file_path: str) -> str | None:
    raw = (file_path or "").strip()
    if not raw:
        return None

    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())

    cwd_candidate = (Path.cwd() / raw).resolve()
    if cwd_candidate.is_file():
        return str(cwd_candidate)

    basename = candidate.name or raw.strip("/").split("/")[-1]
    if not basename:
        return None

    preferred_roots = [
        Path.cwd(),
        Path.cwd().parent,
        Path.home() / "Projets",
        Path.home() / "Projects",
        Path.home() / "Developer",
        Path.home() / "src",
    ]
    skip_dirs = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", "out", "DerivedData", ".build", "xcuserdata",
    }

    matches: list[Path] = []
    suffix_parts = [part for part in raw.strip("/").split("/") if part]
    for root in preferred_roots:
        if not root.is_dir():
            continue
        for current_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            if basename not in files:
                continue
            found = Path(current_root) / basename
            if suffix_parts:
                found_parts = found.parts
                if len(found_parts) >= len(suffix_parts) and list(found_parts[-len(suffix_parts):]) == suffix_parts:
                    return str(found.resolve())
            matches.append(found)
            if len(matches) >= 20:
                break
        if matches:
            break

    if len(matches) == 1:
        return str(matches[0].resolve())
    return None


def score_file(file_path: str) -> str:
    """Scoring Cortex sur un fichier — retourne un résumé lisible."""
    resolved = _resolve_file_path(file_path)
    if resolved is None:
        return f"Fichier introuvable : {file_path!r}. Utilise un chemin exact ou un nom de fichier resolvable depuis le projet."

    try:
        from daemon.scoring.engine import score_file as _score
        result = _score(resolved)
    except Exception as exc:
        return f"Erreur lors du scoring de {file_path}: {exc}"

    r = result.raw
    d = result.details
    lines = [
        f"Fichier : {Path(resolved).name}",
        f"Score global : {result.global_score}/100 ({result.label})",
        _stability_summary(result.label),
        f"Parser : {result.parser} | Langage : {result.language}",
        "",
        "Métriques brutes :",
        f"  - Complexité cyclomatique (max) : {r.complexity:.0f}",
        f"  - Complexité cognitive (max)    : {r.cognitive_complexity:.0f}",
        f"  - Taille des fonctions (max)    : {r.function_size:.0f} lignes",
        f"  - Profondeur d'imbrication      : {r.depth:.0f}",
        f"  - Churn git (30 jours)          : {r.churn:.0f} commits",
        f"  - Fan-in                        : {r.fan_in:.0f} importeurs",
        "",
        "Scores par dimension (0-100) :",
        f"  - Complexité    : {d.complexity_score:.0f}",
        f"  - Cog. complexité : {d.cognitive_complexity_score:.0f}",
        f"  - Taille fonctions : {d.function_size_score:.0f}",
        f"  - Churn         : {d.churn_score:.0f}",
        f"  - Profondeur    : {d.depth_score:.0f}",
    ]
    if result.hotspot_score > 0:
        lines.append(f"Hotspot score : {result.hotspot_score:.1f} (complexité × churn)")
    return "\n".join(lines)


def git_diff_stat(project_path: str) -> str:
    """git diff HEAD --stat — retourne les fichiers modifiés avec stats."""
    resolved = _resolve_project_path(project_path)
    if resolved is None:
        return f"Chemin introuvable : {project_path!r}. Utilise la valeur de 'Racine projet' du contexte."
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            cwd=resolved,
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            # Essaie sans HEAD (dépôt sans commits)
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=resolved,
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return f"Impossible d'exécuter git diff dans {project_path}"
        output = result.stdout.strip()
        return output if output else "Aucune modification depuis le dernier commit."
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return f"Erreur git: {exc}"


def git_log_recent(project_path: str, n: int = 10) -> str:
    """git log --oneline — retourne les N derniers commits."""
    resolved = _resolve_project_path(project_path)
    if resolved is None:
        return f"Chemin introuvable : {project_path!r}. Utilise la valeur de 'Racine projet' du contexte."
    n = min(max(int(n), 1), 30)
    try:
        result = subprocess.run(
            ["git", "log", f"-{n}", "--oneline"],
            cwd=resolved,
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return f"Impossible de lire l'historique git dans {project_path}"
        output = result.stdout.strip()
        return output if output else "Aucun commit dans ce dépôt."
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return f"Erreur git: {exc}"


def score_project(project_path: str, top_n: int = 5) -> str:
    """
    Score tous les fichiers source du projet en une passe et retourne
    le classement par risque décroissant. Remplace la combinaison
    list_scoreable_files + score_file en boucle.
    """
    import os
    top_n = min(max(int(top_n), 1), 10)

    resolved = _resolve_project_path(project_path)
    if resolved is None:
        return f"Chemin introuvable : {project_path!r}. Utilise la valeur de 'Racine projet' du contexte."

    extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".swift"}
    skip_dirs = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", "out", "DerivedData", ".build", "xcuserdata",
    }

    # Collecte des fichiers
    file_paths: list[str] = []
    for root, dirs, filenames in os.walk(resolved):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in filenames:
            if Path(fname).suffix.lower() in extensions:
                file_paths.append(os.path.join(root, fname))

    if not file_paths:
        return f"Aucun fichier source trouvé dans {resolved}."

    # Scoring de chaque fichier
    from daemon.scoring.engine import score_file as _score
    results = []
    errors = []
    for fp in file_paths:
        try:
            r = _score(fp)
            results.append(r)
        except Exception as exc:
            errors.append(f"{Path(fp).name}: {exc}")

    if not results:
        return f"Impossible de scorer les fichiers ({len(errors)} erreur(s))."

    # Tri par score décroissant
    results.sort(key=lambda r: r.global_score, reverse=True)
    top = results[:top_n]

    lines = [
        f"Classement des {len(top)} fichiers les plus risqués sur {len(results)} analysés",
        f"(Projet : {Path(resolved).name})",
        _project_risk_summary(top, len(results)),
        "",
    ]
    for i, r in enumerate(top, 1):
        rel = os.path.relpath(r.file_path, resolved)
        lines.append(f"{i}. {rel}")
        lines.append(f"   Score : {r.global_score}/100 ({r.label}) | Hotspot : {r.hotspot_score:.0f}")
        lines.append(f"   Complexité : {r.raw.complexity:.0f} | Churn : {r.raw.churn:.0f} commits/30j | Fan-in : {r.raw.fan_in:.0f}")
        lines.append("")

    if errors:
        lines.append(f"({len(errors)} fichier(s) non analysable(s) ignoré(s))")

    return "\n".join(lines)


def _resolve_project_path(project_path: str) -> str | None:
    """
    Résout un chemin de projet en chemin absolu existant.
    Essaie dans l'ordre :
      1. Le chemin tel quel (absolu ou relatif au cwd)
      2. La racine git déduite depuis le chemin si c'est un fichier
      3. Recherche dans ~/Projets, ~/Projects, ~/Developer, ~/src
    """
    import os
    # 1. Tel quel
    if os.path.isdir(project_path):
        return project_path

    # 2. Si c'est un fichier, remonte à la racine git
    if os.path.isfile(project_path):
        root = find_git_root(project_path)
        if root:
            return str(root)

    # 3. Recherche par nom dans les dossiers communs
    name = Path(project_path).name  # ex. "Pulse"
    search_roots = [
        Path.home() / "Projets",
        Path.home() / "Projects",
        Path.home() / "Developer",
        Path.home() / "src",
        Path.home(),
    ]
    for search_root in search_roots:
        candidate = search_root / name
        if candidate.is_dir():
            return str(candidate)
        # Cherche un niveau plus profond (ex. ~/Projets/Pulse/Pulse)
        for child in search_root.glob(f"*/{name}"):
            if child.is_dir():
                return str(child)

    return None


# ── Registre des outils ────────────────────────────────────────────────────────

TOOL_MAP: dict[str, Any] = {
    "score_file":    score_file,
    "score_project": score_project,
    "git_diff_stat": git_diff_stat,
    "git_log_recent": git_log_recent,
}
