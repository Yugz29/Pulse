from __future__ import annotations

from typing import Any, Mapping, Optional

from daemon.core.contracts import CurrentContext, SignalSummary
class CurrentContextBuilder:
    """
    Construit un CurrentContext structuré à partir des sources runtime actuelles.

    Cette classe reste purement transformatrice : aucune persistance, aucun rendu.
    """

    def build(
        self,
        *,
        state: Mapping[str, Any],
        signals: Any | None,
        find_git_root_fn,
        find_workspace_root_fn,
    ) -> CurrentContext:
        active_project = (signals.active_project if signals else None) or state.get("active_project")
        active_file = (signals.active_file if signals else None) or state.get("active_file")
        active_app = state.get("active_app")

        if signals and signals.session_duration_min > 0:
            session_duration_min = signals.session_duration_min
        else:
            session_duration_min = 0

        return CurrentContext(
            active_project=active_project,
            project_root=self._resolve_project_root(
                active_file,
                find_git_root_fn=find_git_root_fn,
                find_workspace_root_fn=find_workspace_root_fn,
            ),
            active_file=active_file,
            active_app=active_app,
            session_duration_min=session_duration_min,
            activity_level=getattr(signals, "activity_level", "idle") if signals else "idle",
            probable_task=getattr(signals, "probable_task", "general") if signals else "general",
            task_confidence=getattr(signals, "task_confidence", 0.5) if signals else 0.5,
            focus_level=getattr(signals, "focus_level", "normal") if signals else "normal",
            clipboard_context=getattr(signals, "clipboard_context", None) if signals else None,
            signal_summary=self._build_signal_summary(signals),
        )

    def _build_signal_summary(self, signals: Any | None) -> SignalSummary:
        if signals is None:
            return SignalSummary()
        return SignalSummary(
            recent_apps=list(getattr(signals, "recent_apps", []) or []),
            edited_file_count_10m=getattr(signals, "edited_file_count_10m", 0),
            file_type_mix_10m=dict(getattr(signals, "file_type_mix_10m", {}) or {}),
            rename_delete_ratio_10m=getattr(signals, "rename_delete_ratio_10m", 0.0),
            dominant_file_mode=getattr(signals, "dominant_file_mode", "none"),
            work_pattern_candidate=getattr(signals, "work_pattern_candidate", None),
        )

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
