"""Passive observation qualification contracts.

This module describes what a legacy Pulse event is allowed to influence. It is
not wired into runtime consumers yet; existing scorers and memory builders stay
the behavior source of truth until they are migrated deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from daemon.core.event_meaning import EventMeaningPolicy


EvidenceStrength = Literal["strong", "contextual", "noise"]
ObservationActor = Literal["user", "tool_assisted", "system", "unknown"]
ObservationSensitivity = Literal["low", "medium", "high"]

_FILE_EVENT_TYPES = {"file_created", "file_modified", "file_renamed", "file_deleted", "file_change"}
_APP_EVENT_TYPES = {"app_activated", "app_switch", "window_title_poll"}
_TERMINAL_EVENT_TYPES = {"terminal_command_started", "terminal_command_finished"}
_MCP_EVENT_TYPES = {"mcp_command_received", "mcp_decision"}
_PRESENCE_EVENT_TYPES = {"user_presence", "user_idle", "user_active"}
_SCREEN_EVENT_TYPES = {"screen_locked", "screen_unlocked"}
_INTERNAL_DAEMON_EVENTS = {"context_probe_executed", "llm_loading", "llm_ready", "resume_card"}
_STRONG_TERMINAL_CATEGORIES = {"testing", "test", "debug", "debugging", "build", "vcs", "git", "execution"}


@dataclass(frozen=True)
class ObservationQualification:
    evidence_strength: EvidenceStrength
    actor: ObservationActor = "unknown"
    sensitivity: ObservationSensitivity = "medium"
    can_persist: bool = True
    requires_redaction: bool = False
    can_anchor_project: bool = False
    can_anchor_file: bool = False
    can_start_work_block: bool = False
    can_influence_activity: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_strength": self.evidence_strength,
            "actor": self.actor,
            "sensitivity": self.sensitivity,
            "can_persist": self.can_persist,
            "requires_redaction": self.requires_redaction,
            "can_anchor_project": self.can_anchor_project,
            "can_anchor_file": self.can_anchor_file,
            "can_start_work_block": self.can_start_work_block,
            "can_influence_activity": self.can_influence_activity,
            "reasons": list(self.reasons),
        }


def qualify_observation(
    event_type: str,
    payload: Mapping[str, Any] | None = None,
) -> ObservationQualification:
    """Return a passive qualification for a legacy Pulse event."""
    event_payload = dict(payload or {})

    if event_type in _FILE_EVENT_TYPES:
        return _qualify_file_event(event_type, event_payload)
    if event_type in _APP_EVENT_TYPES:
        return _qualify_app_event(event_type, event_payload)
    if event_type in _TERMINAL_EVENT_TYPES:
        return _qualify_terminal_event(event_type, event_payload)
    if event_type in _MCP_EVENT_TYPES:
        return _qualify_mcp_event(event_type, event_payload)
    if event_type == "clipboard_updated":
        return ObservationQualification(
            evidence_strength="contextual",
            actor="unknown",
            sensitivity="high",
            can_persist=True,
            requires_redaction=True,
            can_influence_activity=False,
            reasons=("clipboard_metadata_only",),
        )
    if event_type in _PRESENCE_EVENT_TYPES:
        return ObservationQualification(
            evidence_strength="contextual",
            actor="unknown",
            sensitivity="low",
            can_persist=True,
            can_influence_activity=True,
            reasons=("presence_support_signal",),
        )
    if event_type in _SCREEN_EVENT_TYPES:
        return ObservationQualification(
            evidence_strength="strong",
            actor="system",
            sensitivity="low",
            can_persist=True,
            can_influence_activity=True,
            reasons=("lifecycle_signal",),
        )
    if event_type in _INTERNAL_DAEMON_EVENTS:
        return ObservationQualification(
            evidence_strength="contextual",
            actor="system",
            sensitivity="low",
            can_persist=event_type == "resume_card",
            can_influence_activity=False,
            reasons=("internal_daemon_event",),
        )

    return ObservationQualification(
        evidence_strength="contextual",
        actor="unknown",
        sensitivity="medium",
        can_persist=True,
        reasons=("unknown_event_family",),
    )


def _qualify_file_event(event_type: str, payload: dict[str, Any]) -> ObservationQualification:
    policy = EventMeaningPolicy().classify(event_type, payload)
    actor = _actor_from_payload(payload)
    reasons = [f"file_significance:{policy.file_significance}", f"noise_policy:{policy.noise_policy}"]
    if actor != "unknown":
        reasons.append(f"actor:{actor}")

    if actor == "system" or policy.file_significance == "technical_noise" or policy.noise_policy == "ignore":
        return ObservationQualification(
            evidence_strength="noise",
            actor=actor,
            sensitivity="medium",
            can_persist=False,
            reasons=tuple(reasons),
        )

    if policy.file_significance == "meaningful":
        return ObservationQualification(
            evidence_strength="strong",
            actor=actor,
            sensitivity="medium",
            can_persist=True,
            can_anchor_project=True,
            can_anchor_file=True,
            can_start_work_block=True,
            can_influence_activity=True,
            reasons=tuple(reasons),
        )

    return ObservationQualification(
        evidence_strength="contextual",
        actor=actor,
        sensitivity="medium",
        can_persist=policy.publish_to_bus,
        can_influence_activity=policy.scoring_relevant and policy.file_significance != "observe_only",
        reasons=tuple(reasons),
    )


def _qualify_app_event(event_type: str, payload: dict[str, Any]) -> ObservationQualification:
    has_window_title = bool(str(payload.get("window_title") or payload.get("title") or "").strip())
    reasons = ["app_context"]
    if has_window_title:
        reasons.append("window_title_present")
    return ObservationQualification(
        evidence_strength="contextual",
        actor="unknown",
        sensitivity="high" if has_window_title else "low",
        can_persist=True,
        requires_redaction=has_window_title,
        can_anchor_file=has_window_title,
        can_influence_activity=True,
        reasons=tuple(reasons),
    )


def _qualify_terminal_event(event_type: str, payload: dict[str, Any]) -> ObservationQualification:
    category = str(payload.get("terminal_action_category") or "").strip().lower()
    is_strong = event_type == "terminal_command_finished" and category in _STRONG_TERMINAL_CATEGORIES
    reasons = ["terminal_event"]
    if category:
        reasons.append(f"terminal_action_category:{category}")
    if payload.get("test_result"):
        reasons.append("test_result")
    if payload.get("terminal_cwd") or payload.get("terminal_project"):
        reasons.append("terminal_project_context")

    return ObservationQualification(
        evidence_strength="strong" if is_strong else "contextual",
        actor="unknown",
        sensitivity="high",
        can_persist=True,
        requires_redaction=bool(payload.get("terminal_command") or payload.get("command") or payload.get("raw")),
        can_anchor_project=bool(payload.get("terminal_cwd") or payload.get("terminal_project")),
        can_start_work_block=is_strong,
        can_influence_activity=True,
        reasons=tuple(reasons),
    )


def _qualify_mcp_event(event_type: str, payload: dict[str, Any]) -> ObservationQualification:
    reasons = ["mcp_event"]
    category = str(payload.get("mcp_action_category") or "").strip().lower()
    decision = str(payload.get("mcp_decision") or payload.get("decision") or "").strip().lower()
    if category:
        reasons.append(f"mcp_action_category:{category}")
    if decision:
        reasons.append(f"mcp_decision:{decision}")
    return ObservationQualification(
        evidence_strength="contextual",
        actor="tool_assisted",
        sensitivity="high",
        can_persist=True,
        requires_redaction=bool(payload.get("command")),
        can_anchor_project=False,
        can_anchor_file=False,
        can_start_work_block=False,
        can_influence_activity=category in {"testing", "build", "execution", "inspection"} or event_type == "mcp_command_received",
        reasons=tuple(reasons),
    )


def _actor_from_payload(payload: Mapping[str, Any]) -> ObservationActor:
    value = str(payload.get("_actor") or "").strip()
    if value in {"user", "tool_assisted", "system", "unknown"}:
        return value  # type: ignore[return-value]
    return "unknown"
