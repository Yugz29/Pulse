"""
git_diff.py — Lecture compacte du diff git pour le contexte LLM.

Produit un résumé compact (< 400 car.) de ce qui a réellement changé
dans le projet depuis le dernier commit. Injecté dans build_context_snapshot()
pour que Pulse sache ce que le développeur est en train de modifier.

Format de sortie :
  Diff en cours : facts.py (+18 -3), test_extractor.py (+12 -8)
  Fonctions touchées : _deterministic_summary, _write_session_report

Stratégie :
  1. git diff HEAD  — tout ce qui a changé (staged + unstaged)
  2. Si vide, git diff --cached — staged seulement
  3. Si toujours vide, pas de diff actif

Limites :
  - Max 6 fichiers affichés
  - Max 4 noms de fonctions/méthodes
  - Timeout 2s sur le subprocess — non bloquant
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

_MAX_DIFF_LINES = 200
_TIMEOUT_SEC    = 2


def read_diff_summary(project_root: str | Path) -> str:
    """
    Retourne un résumé compact du diff git courant (changements non commités).
    Retourne '' si aucun diff actif ou si git indisponible.
    """
    root = Path(project_root)
    if not root.exists():
        return ""

    raw = _run_git_diff(root, ["diff", "HEAD"])
    if not raw:
        raw = _run_git_diff(root, ["diff", "--cached"])
    if not raw:
        return ""

    return _parse_diff(raw)


def read_commit_diff_summary(project_root: str | Path) -> str:
    """
    Retourne un résumé compact du dernier commit (HEAD).
    Utilisé pour enrichir le prompt LLM lors d'un rapport de commit.
    Retourne '' si git indisponible ou si HEAD n'existe pas.
    """
    root = Path(project_root)
    if not root.exists():
        return ""

    # git show HEAD avec stat complet et diff
    raw = _run_git_diff(root, ["show", "HEAD", "--format=format:", "-U2"])
    if not raw:
        return ""

    return _parse_diff(raw)


def _run_git_diff(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
        )
        if result.returncode != 0:
            return ""
        lines = result.stdout.splitlines()
        return "\n".join(lines[:_MAX_DIFF_LINES])
    except Exception:
        return ""


def _parse_diff(raw: str) -> str:
    files: dict[str, dict] = {}
    functions: list[str]   = []
    current_file: str | None = None

    for line in raw.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" b/")
            if len(parts) == 2:
                current_file = Path(parts[1]).name
                if current_file not in files:
                    files[current_file] = {"added": 0, "removed": 0}
        elif line.startswith("+") and not line.startswith("+++") and current_file:
            files[current_file]["added"] += 1
        elif line.startswith("-") and not line.startswith("---") and current_file:
            files[current_file]["removed"] += 1
        elif line.startswith("@@") and len(functions) < 4:
            func = _extract_function_name(line)
            if func and func not in functions:
                functions.append(func)

    if not files:
        return ""

    sorted_files = sorted(
        files.items(),
        key=lambda x: x[1]["added"] + x[1]["removed"],
        reverse=True,
    )[:6]

    file_parts = []
    for name, stats in sorted_files:
        added   = stats["added"]
        removed = stats["removed"]
        if added or removed:
            file_parts.append(f"{name} (+{added} -{removed})")
        else:
            file_parts.append(name)

    lines = [f"Diff en cours : {', '.join(file_parts)}"]
    if functions:
        lines.append(f"Fonctions touchées : {', '.join(functions)}")

    return "\n".join(lines)


def _extract_function_name(hunk_header: str) -> Optional[str]:
    """
    Extrait le nom de la fonction depuis une ligne de hunk git.
    Ex: '@@ -45,12 +45,18 @@ def _write_session_report(' -> '_write_session_report'
    """
    parts = hunk_header.split("@@")
    if len(parts) < 3:
        return None
    context = parts[2].strip()
    if not context:
        return None
    for keyword in ("def ", "func ", "class ", "fn ", "function "):
        if keyword in context:
            after = context.split(keyword, 1)[1]
            name = after.split("(")[0].split(":")[0].split(" ")[0].strip()
            if name and name.isidentifier():
                return name
    return None
