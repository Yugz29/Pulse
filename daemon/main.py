import atexit
import time
import logging
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from daemon.core.event_bus import EventBus
from daemon.core.state_store import StateStore
from daemon.core.signal_scorer import SignalScorer
from daemon.core.decision_engine import DecisionEngine
from daemon.memory.session import SessionMemory
from daemon.memory.extractor import update_memories_from_session
from daemon.mcp.server import start_mcp_server
from daemon.mcp.handlers import receive_decision, get_pending_command, intercept_command

logging.basicConfig(
    level=logging.DEBUG,
    format="[Daemon %(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pulse")

app = Flask(__name__)

bus   = EventBus()
store = StateStore()
scorer = SignalScorer(bus)
decision_engine = DecisionEngine()
session_memory = SessionMemory()
runtime_lock = threading.Lock()
last_signals = None
last_decision = None
last_memory_sync_at = None


def _handle_event(event):
    global last_signals, last_decision, last_memory_sync_at

    session_memory.record_event(event)
    signals = scorer.compute()
    session_memory.update_signals(signals)
    decision = decision_engine.evaluate(signals, trigger_event=event)

    should_sync = _should_sync_memory(event.type, signals, last_memory_sync_at)
    snapshot = None
    if should_sync:
        snapshot = session_memory.export_session_data()
        update_memories_from_session(snapshot)

    with runtime_lock:
        last_signals = signals
        last_decision = decision
        if should_sync:
            last_memory_sync_at = datetime.now()

    if decision.action != "silent":
        log.info(
            "decision=%s level=%s reason=%s",
            decision.action,
            decision.level,
            decision.reason,
        )
    if should_sync:
        log.info(
            "memory sync complete project=%s duration=%smin",
            snapshot.get("active_project"),
            snapshot.get("duration_min"),
        )


def _should_sync_memory(event_type, signals, previous_sync_at):
    if signals.session_duration_min < 20:
        return False
    if event_type in {"screen_locked", "user_idle", "screen_unlocked"}:
        return True
    if previous_sync_at is None:
        return True
    return datetime.now() - previous_sync_at >= timedelta(minutes=10)


def _shutdown_runtime():
    try:
        snapshot = session_memory.export_session_data()
        if snapshot.get("duration_min", 0) > 0:
            update_memories_from_session(snapshot)
        session_memory.close()
    except Exception as exc:
        log.warning("shutdown sync failed: %s", exc)


bus.subscribe(store.update)
bus.subscribe(_handle_event)
atexit.register(_shutdown_runtime)


@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "version": "0.1.0"})


@app.route("/event", methods=["POST"])
def receive_event():
    data       = request.get_json()
    event_type = data.get("type", "unknown")
    payload    = {k: v for k, v in data.items() if k != "type"}
    bus.publish(event_type, payload)
    return jsonify({"ok": True})


@app.route("/state")
def get_state():
    state = store.to_dict()
    with runtime_lock:
        signals = last_signals
        decision = last_decision

    if signals:
        state["signals"] = {
            "active_project": signals.active_project,
            "active_file": signals.active_file,
            "probable_task": signals.probable_task,
            "friction_score": signals.friction_score,
            "focus_level": signals.focus_level,
            "session_duration_min": signals.session_duration_min,
            "recent_apps": signals.recent_apps,
            "clipboard_context": signals.clipboard_context,
        }
    if decision:
        state["decision"] = {
            "action": decision.action,
            "level": decision.level,
            "reason": decision.reason,
            "payload": decision.payload,
        }

    return jsonify(state)


@app.route("/insights")
def get_insights():
    recent = bus.recent(10)
    return jsonify([
        {"type": e.type, "payload": e.payload, "timestamp": e.timestamp.isoformat()}
        for e in recent
    ])


@app.route("/ask", methods=["POST"])
def ask():
    data    = request.get_json()
    message = data.get("message", "")
    return jsonify({"response": f"(LLM not connected yet) : {message}"})


@app.route("/context")
def get_context():
    state = store.to_dict()
    context = (
        f"# Pulse Context\n\n"
        f"- Project : {state['active_project'] or 'not detected'}\n"
        f"- Active app : {state['active_app'] or 'unknown'}\n"
        f"- Session : {state['session_duration_min']} min\n"
    )
    return jsonify({"context": context})


@app.route("/mcp/pending")
def mcp_pending():
    """Swift poll cette route toutes les 500ms."""
    cmd = get_pending_command()
    if cmd is None:
        return "", 204
    log.debug(f"/mcp/pending → commande en attente : tool_use_id={cmd.get('tool_use_id')} command={cmd.get('command')!r}")
    return jsonify(cmd)


@app.route("/mcp/intercept", methods=["POST"])
def mcp_intercept():
    """
    Point d'entrée principal pour stdio_server.py.
    BLOQUE jusqu'à ce que l'utilisateur clique Autoriser ou Refuser dans l'encoche.
    Flask gère cette requête dans son propre thread — les autres routes restent accessibles.
    """
    data        = request.get_json()
    command     = data.get("command", "")
    tool_use_id = data.get("tool_use_id", "unknown")

    log.info(f"/mcp/intercept reçu : tool_use_id={tool_use_id} command={command!r}")

    # Publie l'event immédiatement (pour les logs)
    bus.publish("mcp_command_received", {"command": command, "tool_use_id": tool_use_id})

    t0 = time.monotonic()
    log.info(f"intercept_command : attente décision Swift (max 60s)...")

    # Bloque jusqu'à la décision (max 60s) — Swift voit la commande via /mcp/pending
    result = intercept_command(command, tool_use_id)

    elapsed = time.monotonic() - t0
    log.info(f"intercept_command terminé en {elapsed:.2f}s : decision={result.get('decision')} allowed={result.get('allowed')}")

    bus.publish("mcp_decision", {
        "tool_use_id": tool_use_id,
        "decision":    result.get("decision"),
        "allowed":     result.get("allowed"),
    })

    return jsonify(result)


@app.route("/mcp/decision", methods=["POST"])
def mcp_decision():
    """Reçoit la décision depuis Swift."""
    data        = request.get_json()
    tool_use_id = data.get("tool_use_id")
    decision    = data.get("decision")

    log.info(f"/mcp/decision reçu : tool_use_id={tool_use_id} decision={decision}")
    ok = receive_decision(tool_use_id, decision)
    log.info(f"receive_decision → {'✓ commande trouvée' if ok else '✗ commande introuvable (timeout?)'}")
    bus.publish("mcp_decision", {"tool_use_id": tool_use_id, "decision": decision})
    return jsonify({"ok": ok})


if __name__ == "__main__":
    start_mcp_server(host="127.0.0.1", port=8766)
    log.info("✓ Pulse daemon démarré sur http://localhost:8765 (threaded=True)")
    # threaded=True — indispensable : /mcp/pending doit répondre pendant
    # que /mcp/intercept bloque dans un thread séparé.
    app.run(host="127.0.0.1", port=8765, debug=False, threaded=True)
