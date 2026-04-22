from __future__ import annotations

from typing import Any
from dataclasses import dataclass, field
from typing import Optional


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
class Episode:
    """
    Projection déterministe d'un épisode.

    Les champs sémantiques restent des snapshots du runtime live :
    ils sont attachés à l'épisode sans recalcul rétrospectif.
    """

    id: str
    session_id: str
    started_at: str
    ended_at: Optional[str] = None
    boundary_reason: Optional[str] = None
    duration_sec: Optional[int] = None
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
