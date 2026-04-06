from flask import Flask, request, jsonify
from daemon.interpreter.command_interpreter import CommandInterpreter
from daemon.core.event_bus import EventBus
from daemon.core.state_store import StateStore

app = Flask(__name__)

# Instances globales — partagées entre toutes les routes
interpreter = CommandInterpreter()
bus = EventBus()
store = StateStore()

# Le StateStore s'abonne au bus — mis à jour automatiquement à chaque event
bus.subscribe(store.update)


@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "version": "0.1.0"})


@app.route("/event", methods=["POST"])
def receive_event():
    """Reçoit un event depuis Swift et le publie dans le bus."""
    data = request.get_json()
    event_type = data.get("type", "unknown")
    payload = data.get("payload", {})

    bus.publish(event_type, payload)

    return jsonify({"ok": True})


@app.route("/state")
def get_state():
    """Retourne l'état courant du daemon."""
    return jsonify(store.to_dict())


@app.route("/insights")
def get_insights():
    """Retourne les derniers events — insights bruts pour l'instant."""
    recent = bus.recent(10)
    return jsonify([
        {
            "type":      e.type,
            "payload":   e.payload,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in recent
    ])


@app.route("/ask", methods=["POST"])
def ask():
    """Reçoit une question de l'utilisateur — LLM pas encore branché."""
    data = request.get_json()
    message = data.get("message", "")
    return jsonify({"response": f"(LLM pas encore branché) : {message}"})


@app.route("/context")
def get_context():
    """Retourne un snapshot de contexte structuré."""
    state = store.to_dict()
    context = f"""# Contexte Pulse

## Session courante
- Projet : {state['active_project'] or 'non détecté'}
- App active : {state['active_app'] or 'inconnue'}
- Fichier actif : {state['active_file'] or 'aucun'}
- Durée session : {state['session_duration_min']} minutes
"""
    return jsonify({"context": context})


@app.route("/mcp/intercept", methods=["POST"])
def mcp_intercept():
    """Intercepte une commande Claude Code et retourne son analyse."""
    data = request.get_json()
    command = data.get("command", "")
    tool_use_id = data.get("tool_use_id", "unknown")

    result = interpreter.interpret(command)

    # Publie l'event dans le bus pour que l'état soit mis à jour
    bus.publish("mcp_command", {
        "command":    command,
        "risk_level": result.risk_level,
        "tool_use_id": tool_use_id,
    })

    return jsonify({
        "tool_use_id":  tool_use_id,
        "command":      result.original,
        "translated":   result.translated,
        "risk_level":   result.risk_level,
        "risk_score":   result.risk_score,
        "is_read_only": result.is_read_only,
        "affects":      result.affects,
        "warning":      result.warning,
        "needs_llm":    result.needs_llm,
    })


@app.route("/mcp/decision", methods=["POST"])
def mcp_decision():
    """Reçoit la décision Autoriser/Refuser depuis Swift."""
    data = request.get_json()
    tool_use_id = data.get("tool_use_id")
    decision = data.get("decision")  # "allow" ou "deny"

    print(f"[MCP] Décision : {decision} pour {tool_use_id}")
    bus.publish("mcp_decision", {"tool_use_id": tool_use_id, "decision": decision})

    return jsonify({"ok": True})


if __name__ == "__main__":
    print("✓ Pulse daemon démarré sur http://localhost:8765")
    app.run(host="127.0.0.1", port=8765, debug=False)
