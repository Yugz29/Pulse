from dataclasses import dataclass
from typing import Any, Dict, Optional

from .event_bus import Event
from .signal_scorer import Signals


@dataclass
class Decision:
    action: str
    level: int
    reason: str
    payload: Optional[Dict[str, Any]] = None


class DecisionEngine:
    """
    Règles déterministes du daemon.

    Le moteur ne produit qu'une décision pure à partir des signaux
    et d'un éventuel event déclencheur.
    """

    def evaluate(
        self, signals: Signals, trigger_event: Optional[Event] = None
    ) -> Decision:
        # Deep focus -> ne rien faire, sauf si une commande MCP demande attention.
        if (
            signals.focus_level == "deep"
            and not self._is_mcp_trigger(trigger_event)
        ):
            return Decision("silent", 0, "deep_focus")

        # Une commande MCP doit toujours être traduite et présentée.
        if self._is_mcp_trigger(trigger_event):
            return Decision(
                "translate",
                3,
                "mcp_interception",
                payload=trigger_event.payload if trigger_event else None,
            )

        # Copier une stacktrace pendant une phase de debug mérite une suggestion.
        if (
            signals.clipboard_context == "stacktrace"
            and signals.probable_task == "debug"
        ):
            return Decision(
                "notify",
                2,
                "debug_context_detected",
                payload={"suggestion": "explain_error"},
            )

        # Beaucoup de churn récent sur le même fichier.
        if signals.friction_score > 0.7:
            return Decision(
                "notify",
                2,
                "high_friction",
                payload={
                    "file": signals.active_file,
                    "task": signals.probable_task,
                },
            )

        # Session longue puis idle -> opportunité de résumé.
        if (
            signals.focus_level == "idle"
            and signals.session_duration_min > 45
        ):
            return Decision("llm", 1, "session_summary_opportunity")

        # Après un peu de contexte accumulé, Pulse peut proposer une injection.
        if (
            signals.active_project
            and signals.session_duration_min > 10
            and signals.focus_level in {"normal", "deep"}
        ):
            return Decision(
                "inject_context",
                1,
                "context_ready",
                payload={
                    "project": signals.active_project,
                    "task": signals.probable_task,
                },
            )

        return Decision("silent", 0, "nothing_relevant")

    def _is_mcp_trigger(self, trigger_event: Optional[Event]) -> bool:
        return bool(
            trigger_event
            and trigger_event.type in {
                "mcp_command",
                "mcp_command_received",
                "mcp_command_requested",
            }
        )
