from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class SignalSummary:
    """
    Vue synthétique des métriques détaillées du runtime.

    Ce contrat reste passif : aucune logique métier, aucun accès externe.
    """

    recent_apps: list[str] = field(default_factory=list)
    edited_file_count_10m: int = 0
    file_type_mix_10m: dict[str, int] = field(default_factory=dict)
    rename_delete_ratio_10m: float = 0.0
    dominant_file_mode: str = "none"
    work_pattern_candidate: Optional[str] = None
    active_app_duration_sec: Optional[int] = None
    active_window_title_duration_sec: Optional[int] = None
    app_switch_count_10m: int = 0
    ai_app_switch_count_10m: int = 0


@dataclass(frozen=True)
class CurrentContext:
    """
    Contrat métier synthétique du runtime courant.

    Il ne remplace pas encore tous les usages de Signals en Phase 1, mais pose
    la forme cible pour le runtime sans exposer un dump plat de métriques.
    """

    active_project: Optional[str]
    project_root: Optional[str]
    active_file: Optional[str]
    active_app: Optional[str]
    session_duration_min: int
    activity_level: str
    probable_task: str
    task_confidence: float
    focus_level: str
    clipboard_context: Optional[str]
    user_presence_state: Optional[str] = None
    user_idle_seconds: Optional[int] = None
    mcp_action_category: Optional[str] = None
    mcp_is_read_only: Optional[bool] = None
    mcp_decision: Optional[str] = None
    mcp_summary: Optional[str] = None
    terminal_action_category: Optional[str] = None
    terminal_project: Optional[str] = None
    terminal_cwd: Optional[str] = None
    terminal_command: Optional[str] = None
    terminal_success: Optional[bool] = None
    terminal_exit_code: Optional[int] = None
    terminal_duration_ms: Optional[int] = None
    terminal_summary: Optional[str] = None
    signal_summary: SignalSummary = field(default_factory=SignalSummary)


@dataclass(frozen=True)
class SessionSnapshot:
    """
    Projection structurée d'une session pour la couche mémoire/rétrospective.

    Le contrat reste strictement aligné avec l'export legacy actuel afin de
    permettre des adaptateurs sans changement de comportement.
    """

    session_id: Optional[str]
    started_at: Optional[str]
    updated_at: Optional[str]
    ended_at: Optional[str]
    active_project: Optional[str]
    active_file: Optional[str]
    probable_task: Optional[str]
    focus_level: Optional[str]
    duration_min: int
    recent_apps: list[str] = field(default_factory=list)
    files_changed: int = 0
    top_files: list[str] = field(default_factory=list)
    event_count: int = 0
    max_friction: float = 0.0


@dataclass(frozen=True)
class SessionContext:
    """
    Projection déterministe du contexte de session courant.

    Ce contrat décrit le cycle de session courant, sans remplacer CurrentContext.
    """

    id: str
    session_id: str
    started_at: str
    ended_at: Optional[str] = None
    boundary_reason: Optional[str] = None
    duration_sec: Optional[int] = None
    active_project: Optional[str] = None
    probable_task: Optional[str] = None
    activity_level: Optional[str] = None
    task_confidence: Optional[float] = None


@dataclass(frozen=True)
class ProposalCandidate:
    """
    Contrat métier passif d'une proposition avant conversion vers le transport
    legacy Proposal.

    `details` porte les informations métier stables.
    `transport` permet de conserver des métadonnées techniques nécessaires
    au flux d'entrée sans imposer leur présence à tous les producteurs.
    """

    type: str
    trigger: str
    decision_action: str
    decision_reason: str
    confidence: float = 1.0
    proposed_action: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    transport: dict[str, Any] = field(default_factory=dict)
