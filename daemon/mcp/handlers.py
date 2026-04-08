import queue
import threading
from daemon.interpreter.command_interpreter import CommandInterpreter

# Une queue par commande en attente — clé = tool_use_id
_pending: dict[str, queue.Queue] = {}
# Analyse en attente — exposée à /mcp/pending pour Swift
_pending_analysis: dict[str, dict] = {}
_lock = threading.Lock()

interpreter = CommandInterpreter()


def intercept_command(command: str, tool_use_id: str) -> dict:
    """
    Analyse une commande et attend la décision de l'utilisateur.
    Retourne le résultat de l'analyse + la décision (allow/deny).
    """
    # 1. Analyse la commande
    result = interpreter.interpret(command)

    # 2. Affiche dans le terminal
    _print_interception(command, result)

    # 3. Stocke l'analyse pour que Swift puisse la lire via /mcp/pending
    analysis = {
        "tool_use_id":  tool_use_id,
        "command":      result.original,
        "translated":   result.translated,
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


def get_pending_command() -> dict | None:
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


def _print_interception(command: str, result):
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
    print(f"  {icon} {result.translated}")
    print(f"  Risque : {result.risk_level} ({result.risk_score}/100)")
    if result.warning:
        print(f"  ⚠ {result.warning}")
    print(f"  Commande : {command}\n")
