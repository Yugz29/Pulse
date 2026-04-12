import queue
import threading
from typing import Optional
from daemon.interpreter.command_interpreter import CommandInterpreter
from daemon.llm.router import LLMRouter

# Une queue par commande en attente — clé = tool_use_id
_pending: dict[str, queue.Queue] = {}
# Analyse en attente — exposée à /mcp/pending pour Swift
_pending_analysis: dict[str, dict] = {}
_lock = threading.Lock()

interpreter = CommandInterpreter()
llm_router = LLMRouter()


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
    # 1. Analyse la commande
    result = interpreter.interpret(command)
    translated = result.translated
    if result.needs_llm:
        translated = _translate_with_llm(command, translated)

    # 2. Affiche dans le terminal
    _print_interception(command, translated, result)

    # 3. Stocke l'analyse pour que Swift puisse la lire via /mcp/pending
    analysis = {
        "tool_use_id":  tool_use_id,
        "command":      result.original,
        "translated":   translated,
        "risk_level":   result.risk_level,
        "risk_score":   result.risk_score,
        "is_read_only": result.is_read_only,
        "affects":      result.affects,
        "warning":      result.warning,
        "needs_llm":    result.needs_llm,
    }

    # 4. Crée une queue pour cette commande et attend la décision
    decision_queue: queue.Queue = queue.Queue()
    with _lock:
        _pending[tool_use_id] = decision_queue
        _pending_analysis[tool_use_id] = analysis

    try:
        # Attend la décision 60 secondes max
        decision = decision_queue.get(timeout=60)
    except queue.Empty:
        # Timeout → refuse par sécurité
        decision = "deny"
        print(f"[MCP] Timeout — commande refusée par défaut : {command}")
    finally:
        with _lock:
            _pending.pop(tool_use_id, None)
            _pending_analysis.pop(tool_use_id, None)

    return {**analysis, "decision": decision, "allowed": decision == "allow"}


def receive_decision(tool_use_id: str, decision: str) -> bool:
    """
    Reçoit la décision (allow/deny) pour une commande en attente.
    Retourne True si la commande était bien en attente, False sinon.
    """
    with _lock:
        pending_queue = _pending.get(tool_use_id)

    if pending_queue:
        pending_queue.put(decision)
        return True

    return False


def get_pending_command() -> Optional[dict]:
    """
    Retourne la première commande en attente de décision.
    Appelé par la route GET /mcp/pending — Swift poll cette route.
    """
    with _lock:
        if not _pending_analysis:
            return None
        # Retourne la plus ancienne commande en attente
        first_id = next(iter(_pending_analysis))
        return _pending_analysis[first_id]


def get_pending_count() -> int:
    """Retourne le nombre de commandes en attente de décision."""
    with _lock:
        return len(_pending)


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
