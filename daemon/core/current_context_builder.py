from __future__ import annotations

import logging
from typing import Any, Optional

from daemon.core.contracts import CurrentContext, SignalSummary
from daemon.runtime_state import PresentState

log = logging.getLogger("pulse")


class CurrentContextBuilder:
    """
    Construit un CurrentContext structuré à partir des sources runtime actuelles.

    Cette classe reste purement transformatrice : aucune persistance, aucun rendu.
    `present` porte le contexte canonique; `signals` ne sert plus qu'aux détails
    secondaires non encore remontés dans PresentState.
    """

    def build(
        self,
        *,
        present: PresentState,
        active_app: str | None,
        signals: Any | None,
        find_git_root_fn,
        find_workspace_root_fn,
    ) -> CurrentContext:
        terminal_cwd = self._signal_attr(signals, "terminal_cwd")

        ctx = CurrentContext(
            active_project=present.active_project,
            project_root=self._resolve_project_root(
                present.active_file or terminal_cwd,
                find_git_root_fn=find_git_root_fn,
                find_workspace_root_fn=find_workspace_root_fn,
            ),
            active_file=present.active_file,
            active_app=active_app,
            session_duration_min=present.session_duration_min,
            activity_level=present.activity_level,
            probable_task=present.probable_task,
            task_confidence=self._signal_attr(signals, "task_confidence", 0.5),
            focus_level=present.focus_level,
            clipboard_context=present.clipboard_context,
            user_presence_state=present.user_presence_state,
            user_idle_seconds=present.user_idle_seconds,
            mcp_action_category=self._signal_attr(signals, "mcp_action_category"),
            mcp_is_read_only=self._signal_attr(signals, "mcp_is_read_only"),
            mcp_decision=self._signal_attr(signals, "mcp_decision"),
            mcp_summary=self._signal_attr(signals, "mcp_summary"),
            terminal_action_category=self._signal_attr(signals, "terminal_action_category"),
            terminal_project=self._signal_attr(signals, "terminal_project"),
            terminal_command=self._signal_attr(signals, "terminal_command"),
            terminal_success=self._signal_attr(signals, "terminal_success"),
            terminal_cwd=terminal_cwd,
            terminal_exit_code=self._signal_attr(signals, "terminal_exit_code"),
            terminal_duration_ms=self._signal_attr(signals, "terminal_duration_ms"),
            terminal_summary=self._signal_attr(signals, "terminal_summary"),
            signal_summary=self._build_signal_summary(signals),
        )
        log.debug(
            "context: task=%s conf=%.2f activity=%s project=%s",
            ctx.probable_task,
            ctx.task_confidence,
            ctx.activity_level,
            ctx.active_project,
        )
        return ctx

    def _build_signal_summary(self, signals: Any | None) -> SignalSummary:
        return SignalSummary(
            recent_apps=list(self._signal_attr(signals, "recent_apps", []) or []),
            edited_file_count_10m=self._signal_attr(signals, "edited_file_count_10m", 0),
            file_type_mix_10m=dict(self._signal_attr(signals, "file_type_mix_10m", {}) or {}),
            rename_delete_ratio_10m=self._signal_attr(signals, "rename_delete_ratio_10m", 0.0),
            dominant_file_mode=self._signal_attr(signals, "dominant_file_mode", "none"),
            work_pattern_candidate=self._signal_attr(signals, "work_pattern_candidate"),
            active_app_duration_sec=self._signal_attr(signals, "active_app_duration_sec"),
            active_window_title_duration_sec=self._signal_attr(signals, "active_window_title_duration_sec"),
            app_switch_count_10m=self._signal_attr(signals, "app_switch_count_10m", 0),
            ai_app_switch_count_10m=self._signal_attr(signals, "ai_app_switch_count_10m", 0),
        )

    @staticmethod
    def _signal_attr(signals: Any | None, name: str, default: Any = None) -> Any:
        if signals is None:
            return default
        return getattr(signals, name, default)

    def _resolve_project_root(
        self,
        active_file: Optional[str],
        *,
        find_git_root_fn,
        find_workspace_root_fn,
    ) -> Optional[str]:
        if not active_file:
            return None
        try:
            git_root = find_git_root_fn(active_file)
            if git_root:
                return str(git_root)
            workspace_root = find_workspace_root_fn(active_file)
            if workspace_root:
                return str(workspace_root)
        except Exception:
            try:
                workspace_root = find_workspace_root_fn(active_file)
                if workspace_root:
                    return str(workspace_root)
            except Exception:
                return None
        return None
