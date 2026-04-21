from __future__ import annotations

from typing import Optional

from daemon.core.contracts import ProposalCandidate
from daemon.core.proposals import Proposal


def proposal_candidate_to_proposal(
    candidate: ProposalCandidate,
    *,
    proposal_id: str,
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> Proposal:
    """
    Convertit un ProposalCandidate métier vers le transport legacy Proposal.

    L'adaptateur ne décide rien : il ne fait que reproduire le format historique.
    """

    kwargs = {}
    if created_at is not None:
        kwargs["created_at"] = created_at
    if updated_at is not None:
        kwargs["updated_at"] = updated_at

    return Proposal(
        id=proposal_id,
        type=candidate.type,
        trigger=candidate.trigger,
        title=_legacy_title(candidate),
        summary=_legacy_summary(candidate),
        rationale=_legacy_rationale(candidate),
        evidence=[dict(item) for item in candidate.evidence],
        confidence=candidate.confidence,
        proposed_action=candidate.proposed_action,
        metadata=_legacy_metadata(candidate),
        **kwargs,
    )


def _legacy_title(candidate: ProposalCandidate) -> str:
    if candidate.type == "context_injection":
        return "Contexte de session prêt à être injecté"
    if candidate.type == "risky_command":
        return _risky_command_translated(candidate)
    raise ValueError(f"Unsupported proposal candidate type: {candidate.type}")


def _legacy_summary(candidate: ProposalCandidate) -> str:
    if candidate.type == "context_injection":
        return "Le contexte local est jugé assez riche pour une réponse assistée."
    if candidate.type == "risky_command":
        return _risky_command_translated(candidate)
    raise ValueError(f"Unsupported proposal candidate type: {candidate.type}")


def _legacy_rationale(candidate: ProposalCandidate) -> str:
    if candidate.type == "context_injection":
        return "La session a accumulé assez de contexte local pour justifier une injection de contexte existante."
    if candidate.type == "risky_command":
        return candidate.details.get(
            "rationale",
            "Commande shell demandée via MCP et soumise à validation utilisateur.",
        )
    raise ValueError(f"Unsupported proposal candidate type: {candidate.type}")


def _legacy_metadata(candidate: ProposalCandidate) -> dict:
    metadata = {}
    if candidate.details:
        metadata["details"] = dict(candidate.details)
    if candidate.transport:
        metadata["transport"] = dict(candidate.transport)
    return metadata


def _risky_command_translated(candidate: ProposalCandidate) -> str:
    translated = candidate.details.get("translated", "")
    if isinstance(translated, str) and translated.strip():
        return translated
    command = candidate.transport.get("command", "")
    if isinstance(command, str) and command.strip():
        return command
    return "Commande shell à valider"
