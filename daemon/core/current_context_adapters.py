from __future__ import annotations

from typing import Any, Optional

from daemon.core.context_formatter import (
    format_file_activity_summary,
    format_file_work_reading,
    has_informative_file_reading,
)
from daemon.core.contracts import CurrentContext


def current_context_to_markdown(
    context: CurrentContext,
    *,
    signals: Any | None = None,
    diff_summary: Optional[str] = None,
    last_session_line: Optional[str] = None,
) -> str:
    """
    Adaptateur legacy vers le texte Markdown attendu par build_context_snapshot().

    Le rendu doit rester strictement identique à l'implémentation historique.
    `signals` n'est utilisé que pour les lectures dérivées secondaires encore
    non portées par CurrentContext.
    """

    lines = [
        "# Contexte session",
        f"- Projet : {context.active_project or 'non détecté'}",
        f"- Racine projet : {context.project_root or 'inconnue'}",
        f"- Fichier actif : {context.active_file or 'aucun'}",
        f"- App active : {context.active_app or 'inconnue'}",
        f"- Durée session : {context.session_duration_min or 0} min",
    ]

    lines += [
        f"- Tâche probable : {context.probable_task}",
        f"- Focus : {context.focus_level}",
    ]

    if signals:
        file_activity = format_file_activity_summary(signals)
        if file_activity:
            lines.append(f"- Activité fichiers : {file_activity}")
        if has_informative_file_reading(signals):
            file_reading = format_file_work_reading(signals)
            if file_reading:
                lines.append(f"- Lecture de la session : {file_reading}")
        recent_apps = list(context.signal_summary.recent_apps)
        if recent_apps:
            lines.append(f"- Apps récentes : {', '.join(recent_apps[:4])}")

    if diff_summary:
        lines.append(f"- {diff_summary.replace(chr(10), chr(10) + '  ')}")

    if last_session_line:
        lines.append(f"- {last_session_line}")

    return "\n".join(lines)


def current_context_to_legacy_signals_payload(
    context: CurrentContext,
    *,
    signals: Any,
    last_session_line: Optional[str] = None,
) -> dict[str, Any]:
    """
    Adaptateur legacy pour le bloc `signals` exposé par /state.

    Le JSON retourné doit rester strictement identique au contrat existant.
    """

    return {
        "active_project": context.active_project,
        "active_file": context.active_file,
        "probable_task": context.probable_task,
        "activity_level": context.activity_level,
        "task_confidence": signals.task_confidence,
        "friction_score": signals.friction_score,
        "focus_level": context.focus_level,
        "session_duration_min": context.session_duration_min,
        "recent_apps": list(context.signal_summary.recent_apps),
        "clipboard_context": context.clipboard_context,
        "user_presence_state": getattr(signals, "user_presence_state", None),
        "user_idle_seconds": getattr(signals, "user_idle_seconds", None),
        "active_app_duration_sec": getattr(signals, "active_app_duration_sec", None),
        "active_window_title_duration_sec": getattr(signals, "active_window_title_duration_sec", None),
        "app_switch_count_10m": getattr(signals, "app_switch_count_10m", 0),
        "ai_app_switch_count_10m": getattr(signals, "ai_app_switch_count_10m", 0),
        "terminal_action_category": getattr(signals, "terminal_action_category", None),
        "terminal_project": getattr(signals, "terminal_project", None),
        "terminal_cwd": getattr(signals, "terminal_cwd", None),
        "terminal_command": getattr(signals, "terminal_command", None),
        "terminal_success": getattr(signals, "terminal_success", None),
        "terminal_exit_code": getattr(signals, "terminal_exit_code", None),
        "terminal_duration_ms": getattr(signals, "terminal_duration_ms", None),
        "terminal_summary": getattr(signals, "terminal_summary", None),
        "edited_file_count_10m": context.signal_summary.edited_file_count_10m,
        "file_type_mix_10m": dict(context.signal_summary.file_type_mix_10m),
        "rename_delete_ratio_10m": context.signal_summary.rename_delete_ratio_10m,
        "dominant_file_mode": context.signal_summary.dominant_file_mode,
        "work_pattern_candidate": context.signal_summary.work_pattern_candidate,
        "last_session_context": last_session_line,
    }
