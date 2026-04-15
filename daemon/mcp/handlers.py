from typing import Optional

from daemon.core.proposals import Proposal, proposal_store
from daemon.interpreter.command_interpreter import CommandInterpreter
from daemon.llm.router import LLMRouter

interpreter = CommandInterpreter()
llm_router = LLMRouter()


def configure_llm_router(router) -> None:
    global llm_router
    llm_router = router


def get_available_llm_models() -> list:
    try:
        return llm_router.list_models()
    except Exception:
        return []


def get_selected_command_llm_model() -> str:
    return llm_router.get_model()


def set_selected_command_llm_model(model: str) -> bool:
    available = get_available_llm_models()
    if available and model not in available:
        return False
    llm_router.set_model(model)
    return True


# Alias unifié — command et summary utilisent le même modèle
def get_selected_llm_model() -> str:
    return get_selected_command_llm_model()


def set_selected_llm_model(model: str) -> bool:
    return set_selected_command_llm_model(model)


def intercept_command(command: str, tool_use_id: str) -> dict:
    """
    Analyse une commande et attend la décision de l'utilisateur.
    Retourne le résultat de l'analyse + la décision (allow/deny).
    """
    # 1. Détection / interprétation déterministe
    result = interpreter.interpret(command)
    translated = result.translated
    if result.needs_llm:
        translated = _translate_with_llm(command, translated)

    # 2. Affiche dans le terminal
    _print_interception(command, translated, result)

    # 3. Construit la proposition réutilisable et la place dans la file
    proposal = _build_risky_command_proposal(
        tool_use_id=tool_use_id,
        command=command,
        interpretation=result,
        translated=translated,
    )
    proposal_store.add(proposal)

    # 4. Attend la résolution de la proposition
    resolved = proposal_store.wait_for_resolution(proposal.id, timeout=60)
    if resolved is None:
        decision = "deny"
        status = "expired"
    else:
        decision, status = _decision_from_proposal_status(resolved.status)

    if status == "expired":
        print(f"[MCP] Timeout — commande refusée par défaut : {command}")

    return {
        **_proposal_to_api_payload(proposal_store.get(proposal.id) or proposal),
        "decision": decision,
        "allowed": decision == "allow",
    }


def receive_decision(tool_use_id: str, decision: str) -> bool:
    """
    Reçoit la décision (allow/deny) pour une commande en attente.
    Retourne True si la commande était bien en attente, False sinon.
    """
    status = _status_from_decision(decision)
    if status is None:
        return False
    return proposal_store.resolve(tool_use_id, status) is not None


def get_pending_command() -> Optional[dict]:
    """
    Retourne la première proposition de commande risquée en attente de décision.
    Appelé par la route GET /mcp/pending — Swift poll cette route.
    """
    proposal = proposal_store.get_pending(proposal_type="risky_command")
    if proposal is None:
        return None
    return _proposal_to_api_payload(proposal)


def get_pending_count() -> int:
    """Retourne le nombre de propositions de commande risquée en attente."""
    return len(proposal_store.list_pending(proposal_type="risky_command"))


def get_proposal_history(limit: int = 20) -> list[dict]:
    """Retourne l'historique récent des propositions, pending incluses."""
    if limit <= 0:
        return []
    return [
        _proposal_to_api_payload(proposal)
        for proposal in proposal_store.list_history(limit=limit)
    ]


def reset_proposals_for_tests() -> None:
    proposal_store.clear()


def _translate_with_llm(command: str, fallback: str) -> str:
    prompt = (
        "Explain this shell command in concise French for a human approval UI.\n"
        "Keep it to one short sentence.\n"
        "Focus on what it does, not how it is written.\n"
        "Do not add warnings unless obvious from the command itself.\n\n"
        "Command: {0}"
    ).format(command)
    system = "You translate shell commands into short, plain French."

    try:
        translated = llm_router.complete(prompt=prompt, system=system, max_tokens=80)
        return translated.strip() or fallback
    except Exception:
        return fallback


def _build_risky_command_proposal(tool_use_id: str, command: str, interpretation, translated: str) -> Proposal:
    confidence = 0.78 if interpretation.needs_llm else 0.96
    warning = interpretation.warning
    rationale = warning or "Commande shell demandée via MCP et soumise à validation utilisateur."

    evidence = [
        {"kind": "command", "label": "Commande", "value": command},
        {
            "kind": "risk",
            "label": "Risque",
            "value": f"{interpretation.risk_level} ({interpretation.risk_score}/100)",
        },
    ]
    if interpretation.affects:
        evidence.append({
            "kind": "impact",
            "label": "Impacts",
            "value": ", ".join(interpretation.affects),
        })
    if warning:
        evidence.append({"kind": "warning", "label": "Avertissement", "value": warning})

    return Proposal(
        id=tool_use_id,
        type="risky_command",
        trigger="mcp_intercept",
        title=translated,
        summary=translated,
        rationale=rationale,
        evidence=evidence,
        confidence=confidence,
        proposed_action="allow_shell_command",
        metadata={
            "transport": {
                "tool_use_id": tool_use_id,
                "command": interpretation.original,
                "translated": translated,
                "risk_level": interpretation.risk_level,
                "risk_score": interpretation.risk_score,
                "is_read_only": interpretation.is_read_only,
                "affects": list(interpretation.affects),
                "warning": interpretation.warning,
                "needs_llm": interpretation.needs_llm,
            },
        },
    )


def _proposal_to_api_payload(proposal: Proposal) -> dict:
    payload = proposal.to_dict()
    metadata = payload.pop("metadata", {})
    transport = metadata.get("transport", {})
    return {
        "tool_use_id": transport.get("tool_use_id", proposal.id),
        "command": transport.get("command", ""),
        "translated": transport.get("translated", proposal.summary),
        "risk_level": transport.get("risk_level", "low"),
        "risk_score": transport.get("risk_score", 0),
        "is_read_only": transport.get("is_read_only", False),
        "affects": transport.get("affects"),
        "warning": transport.get("warning"),
        "needs_llm": transport.get("needs_llm", False),
        **payload,
    }


def _status_from_decision(decision: str | None) -> str | None:
    if decision == "allow":
        return "accepted"
    if decision == "deny":
        return "refused"
    return None


def _decision_from_proposal_status(status: str) -> tuple[str, str]:
    if status == "accepted":
        return "allow", status
    if status == "refused":
        return "deny", status
    if status == "expired":
        return "deny", status
    return "deny", status


def _print_interception(command: str, translated: str, result):
    """Affiche l'interception dans le terminal."""
    risk_icons = {
        "safe":     "✅",
        "low":      "🟡",
        "medium":   "🟠",
        "high":     "🔴",
        "critical": "💀",
    }
    icon = risk_icons.get(result.risk_level, "❓")
    print(f"\n[MCP] Commande interceptée")
    print(f"  {icon} {translated}")
    print(f"  Risque : {result.risk_level} ({result.risk_score}/100)")
    if result.warning:
        print(f"  ⚠ {result.warning}")
    print(f"  Commande : {command}\n")
