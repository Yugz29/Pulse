"""
context_formatter.py — Mise en forme des signaux de session pour le LLM.

Fonctions pures qui traduisent un objet Signals en texte lisible.
Pas d'état, pas de dépendances sur l'orchestrateur.

Exporté par :
  - runtime_orchestrator.py  (build_context_snapshot, _build_context_injection_proposal)
"""

from __future__ import annotations

from typing import Optional

from daemon.core.signal_scorer import Signals


# ── API publique ──────────────────────────────────────────────────────────────

def has_informative_file_reading(signals: Signals) -> bool:
    """
    Retourne True si les signaux contiennent assez d'information pour
    produire une 'lecture de session' utile.
    """
    if signals.work_pattern_candidate:
        return True
    if signals.rename_delete_ratio_10m >= 0.2:
        return True
    if signals.edited_file_count_10m >= 2 and signals.dominant_file_mode != "single_file":
        return True
    return False


def format_file_activity_summary(signals: Signals) -> str:
    """
    Résumé compact de l'activité fichiers sur 10 min.
    Exemple : "5 fichier(s) touché(s) sur 10 min, surtout code source (3), tests (1)"
    """
    if not signals.edited_file_count_10m:
        return ""

    parts = [f"{signals.edited_file_count_10m} fichier(s) touché(s) sur 10 min"]
    if signals.edited_file_count_10m < 2:
        return parts[0]

    mix = _format_file_type_mix(signals.file_type_mix_10m)
    if mix:
        parts.append(f"surtout {mix}")
    return ", ".join(parts)


def format_file_work_reading(signals: Signals) -> str:
    """
    Lecture qualitative de la session : mode de travail, pattern, changements structurels.
    Exemple : "petit lot cohérent de 4 fichiers, ça ressemble à un refactor"
    """
    if not has_informative_file_reading(signals):
        return ""

    parts = []
    mode = _file_mode_label(signals.dominant_file_mode, signals.edited_file_count_10m)
    if mode:
        parts.append(mode)
    pattern = _work_pattern_label(signals.work_pattern_candidate)
    if pattern:
        parts.append(pattern)
    structural = _format_structural_changes(signals.rename_delete_ratio_10m)
    if structural:
        parts.append(structural)
    return ", ".join(parts)


# ── Helpers privés ────────────────────────────────────────────────────────────

def _format_file_type_mix(file_type_mix: dict) -> str:
    if not file_type_mix:
        return ""
    meaningful_items = [
        (kind, count)
        for kind, count in file_type_mix.items()
        if kind != "other" and count > 0
    ]
    ordered = sorted(meaningful_items, key=lambda item: (-item[1], item[0]))
    labels = [
        f"{_file_type_label(kind)} ({count})"
        for kind, count in ordered[:3]
        if count > 0
    ]
    return ", ".join(labels)


def _format_structural_changes(rename_delete_ratio: float) -> str:
    if rename_delete_ratio >= 0.4:
        return "avec changements de structure marqués"
    if rename_delete_ratio >= 0.2:
        return "avec quelques changements de structure"
    return ""


def _file_mode_label(mode: str, edited_file_count: int) -> str:
    if mode == "single_file":
        return "travail concentré sur un seul fichier"
    if mode == "few_files":
        return f"petit lot cohérent de {edited_file_count} fichiers"
    if mode == "multi_file":
        return "travail réparti sur plusieurs fichiers"
    return ""


def _work_pattern_label(pattern: Optional[str]) -> str:
    if pattern == "feature_candidate":
        return "ça ressemble à une évolution de fonctionnalité"
    if pattern == "refactor_candidate":
        return "ça ressemble à un refactor"
    if pattern == "setup_candidate":
        return "ça ressemble à une phase de configuration"
    if pattern == "debug_loop_candidate":
        return "ça ressemble à une boucle de correction"
    return ""


def _file_type_label(file_type: str) -> str:
    return {
        "source": "code source",
        "test":   "tests",
        "config": "configuration",
        "docs":   "documentation",
        "assets": "assets",
        "other":  "autres fichiers",
    }.get(file_type, file_type)
