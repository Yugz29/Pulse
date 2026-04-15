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

        # Les signaux de debug dérivés du clipboard restent trop faibles
        # pour justifier une émission produit autonome.
        if (
            signals.clipboard_context == "stacktrace"
            and signals.probable_task == "debug"
        ):
            return Decision("silent", 0, "debug_signal_only")

        # Le churn sur un fichier est un signal de contexte, pas un déclencheur direct.
        if signals.friction_score > 0.7:
            return Decision("silent", 0, "friction_signal_only")

        # Longue session + idle reste insuffisant tant qu'il n'existe pas
        # de surface produit claire pour cette suggestion.
        if (
            signals.focus_level == "idle"
            and signals.session_duration_min > 45
        ):
            return Decision("silent", 0, "summary_signal_only")

        # Après un peu de contexte accumulé, Pulse peut proposer une injection,
        # mais seulement sur un vrai signal de travail local et suffisamment concret.
        if self._can_emit_context_proposal(signals, trigger_event):
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

    def _can_emit_context_proposal(
        self, signals: Signals, trigger_event: Optional[Event]
    ) -> bool:
        if not trigger_event or trigger_event.type not in {
            "file_created",
            "file_modified",
            "file_renamed",
        }:
            return False
        return bool(
            signals.active_project
            and signals.active_file
            and signals.session_duration_min > 10
            and signals.focus_level == "normal"
        )
