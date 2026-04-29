"""
restart_manager.py — Persistance et reprise d'état au redémarrage de Pulse.

Responsabilité unique : sauvegarder l'état courant au shutdown et le restaurer
au prochain démarrage si le redémarrage est récent.

Trois comportements selon l'ancienneté du redémarrage :
  < 5 min  → reprise transparente : session_started_at restauré
  5-30 min → reprise partielle : contexte conservé, timer non restauré
  > 30 min → ignoré, nouvelle session propre

Détecte aussi les commits effectués pendant l'absence de Pulse
et déclenche le pipeline de journalisation pour ne pas les perdre.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("pulse")

_STATE_PATH = Path.home() / ".pulse" / "restart_state.json"
_CONTINUE_MAX_MIN = 5    # reprise transparente
_RESUME_MAX_MIN   = 30   # reprise partielle


class RestartManager:
    """
    Gère la persistance et la reprise d'état entre redémarrages.

    Utilisé par RuntimeOrchestrator — pas de dépendance directe vers lui.
    Reçoit les collaborateurs dont il a besoin au moment de apply() et recover().
    """

    def save(self, snapshot: dict, *, session_fsm) -> None:
        """
        Persiste l'état courant au shutdown.
        Sauvegarde aussi le HEAD SHA du projet actif pour détecter les commits manqués.
        """
        try:
            state: dict[str, Any] = {
                "shutdown_at": datetime.now().isoformat(),
                "active_project": snapshot.get("active_project"),
                "probable_task":  snapshot.get("probable_task"),
                "activity_level": snapshot.get("activity_level"),
                "started_at": (
                    session_fsm.session_started_at.isoformat()
                    if session_fsm.session_started_at else None
                ),
            }

            project = snapshot.get("active_project")
            if project:
                sha = _read_project_head_sha(project)
                if sha:
                    state["last_head_sha"] = sha
                    state["last_sha_project"] = project

            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False))
            log.info("restart state sauvegardé : projet=%s", project)
        except Exception as exc:
            log.warning("restart state save échoué : %s", exc)

    def load(self) -> Optional[dict]:
        """Charge le dernier état persisté. Retourne None si absent ou corrompu."""
        try:
            if not _STATE_PATH.exists():
                return None
            state = json.loads(_STATE_PATH.read_text())
            shutdown_at = datetime.fromisoformat(state["shutdown_at"])
            state["elapsed_min"] = (datetime.now() - shutdown_at).total_seconds() / 60
            return state
        except Exception as exc:
            log.warning("restart state load échoué : %s", exc)
            return None

    def apply(self, state: dict, *, session_fsm, session_memory) -> None:
        """
        Applique l'état chargé pour restaurer la continuité de session.

        < 5 min  : reprise transparente — started_at restauré
        5-30 min : reprise partielle — contexte conservé, timer non restauré
        > 30 min : ignoré
        """
        elapsed_min = state.get("elapsed_min", 999)
        project = state.get("active_project")
        task    = state.get("probable_task", "general")

        if elapsed_min > _RESUME_MAX_MIN:
            log.info("restart state ignoré (%.0f min > %d min)", elapsed_min, _RESUME_MAX_MIN)
            return

        if elapsed_min <= _CONTINUE_MAX_MIN:
            started_at_raw = state.get("started_at")
            if started_at_raw:
                try:
                    original_started_at = datetime.fromisoformat(started_at_raw)
                    session_fsm.restore_session_start(original_started_at)
                    session_memory.resume_session(started_at=original_started_at)
                    log.info(
                        "reprise transparente (%.0f min) depuis %s",
                        elapsed_min, original_started_at.strftime("%H:%M"),
                    )
                except ValueError:
                    pass
        else:
            log.info("reprise partielle (%.0f min) — contexte conservé sans timer", elapsed_min)

        log.info("contexte restauré : projet=%s tâche=%s", project, task)

    def recover_missed_commits(self, state: dict, *, summary_llm) -> None:
        """
        Détecte les commits effectués pendant l'absence de Pulse et les journalise.
        Ne fait rien si aucun commit manqué n'est détecté.
        """
        last_sha = state.get("last_head_sha")
        project  = state.get("last_sha_project") or state.get("active_project")
        if not last_sha or not project:
            return

        try:
            from daemon.core.workspace_context import find_workspace_root
            from daemon.core.git_diff import read_commit_diff_summary
            from daemon.memory.extractor import (
                find_git_root,
                read_head_sha,
                read_commit_message,
                read_commit_file_names,
                update_memories_from_session,
            )

            workspace = find_workspace_root(project) or ""
            if not workspace:
                return
            git_root = find_git_root(workspace)
            if not git_root:
                return

            current_sha = read_head_sha(git_root)
            if not current_sha or current_sha == last_sha:
                return

            commit_message    = read_commit_message(git_root) or ""
            diff_summary      = read_commit_diff_summary(git_root) or ""
            commit_scope_files = read_commit_file_names(git_root)
            log.info("Commit manqué détecté sur %s : %s", project, commit_message[:60])

            shutdown_at = state.get("shutdown_at")
            started_at  = state.get("started_at") or shutdown_at
            snapshot = {
                "active_project":      project,
                "probable_task":       state.get("probable_task", "coding"),
                "activity_level":      "executing",
                "duration_min":        5,
                "top_files":           [],
                "files_changed":       0,
                "recent_apps":         [],
                "max_friction":        0.0,
                "focus_level":         "normal",
                "started_at":          started_at,
                "ended_at":            shutdown_at,
                "commit_scope_files":  commit_scope_files,
            }
            update_memories_from_session(
                snapshot,
                llm=summary_llm,
                commit_message=commit_message,
                trigger="commit",
                diff_summary=diff_summary,
            )
            log.info("Journal de secours écrit pour commit manqué : %s", commit_message[:60])

        except Exception as exc:
            log.warning("recover_missed_commits échoué : %s", exc)


# ── Helpers internes ──────────────────────────────────────────────────────────

def _read_project_head_sha(project: str) -> Optional[str]:
    """Lit le HEAD SHA du projet via son workspace git."""
    try:
        from daemon.core.workspace_context import find_workspace_root
        from daemon.memory.extractor import find_git_root, read_head_sha

        workspace = find_workspace_root(project) or ""
        if not workspace:
            return None
        git_root = find_git_root(workspace)
        if not git_root:
            return None
        return read_head_sha(git_root)
    except Exception:
        return None
