import atexit
import time
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify
from daemon.core.event_bus import EventBus
from daemon.core.state_store import StateStore
from daemon.core.signal_scorer import SignalScorer
from daemon.core.decision_engine import DecisionEngine
from daemon.llm.router import LLMRouter
from daemon.memory.session import SessionMemory
from daemon.memory.extractor import update_memories_from_session, load_memory_context
from daemon.settings import load_runtime_settings, save_runtime_settings
from daemon.mcp.server import start_mcp_server
from daemon.mcp.handlers import (
    receive_decision,
    get_pending_command,
    intercept_command,
    get_available_llm_models,
    get_selected_command_llm_model,
    set_selected_command_llm_model,
)

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
summary_llm = LLMRouter()
session_memory = SessionMemory()
runtime_lock = threading.Lock()
last_signals = None
last_decision = None
last_memory_sync_at = None
recent_file_events = {}
settings_path = Path.home() / ".pulse" / "settings.json"


def _handle_event(event):
    global last_signals, last_decision, last_memory_sync_at, recent_file_events

    if _should_ignore_event(event):
        return

    session_memory.record_event(event)
    signals = scorer.compute()
    session_memory.update_signals(signals)
    decision = decision_engine.evaluate(signals, trigger_event=event)

    should_sync = _should_sync_memory(event.type, signals, last_memory_sync_at)
    snapshot = None
    if should_sync:
        snapshot = session_memory.export_session_data()
        update_memories_from_session(
            snapshot,
            llm=_summary_llm_for(event.type, signals),
        )

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


def _should_ignore_event(event):
    global recent_file_events

    if not event.type.startswith("file_"):
        return False

    path = (event.payload or {}).get("path", "")
    if not _is_meaningful_file_path(path):
        return True

    dedupe_key = "{0}:{1}".format(event.type, path)
    now = datetime.now()
    with runtime_lock:
        last_seen = recent_file_events.get(dedupe_key)
        recent_file_events = {
            key: ts for key, ts in recent_file_events.items()
            if now - ts < timedelta(seconds=5)
        }
        if last_seen and now - last_seen < timedelta(seconds=1):
            return True
        recent_file_events[dedupe_key] = now

    return False


def _is_meaningful_file_path(path):
    if not path:
        return False

    name = path.split("/")[-1]
    if name.startswith("."):
        return False
    if name.endswith((".DS_Store", "~", ".xcuserstate")):
        return False
    if ".sb-" in name:
        return False
    if any(part in path for part in ("/.git/", "/node_modules/", "/__pycache__/", "/xcuserdata/", "/DerivedData/")):
        return False
    return True


def _should_sync_memory(event_type, signals, previous_sync_at):
    if signals.session_duration_min < 20:
        return False
    if event_type in {"screen_locked", "user_idle", "screen_unlocked"}:
        return True
    if previous_sync_at is None:
        return True
    return datetime.now() - previous_sync_at >= timedelta(minutes=10)


def _summary_llm_for(event_type, signals):
    if signals.session_duration_min < 20:
        return None

    if event_type in {"screen_locked", "user_idle"}:
        return summary_llm

    if signals.focus_level == "idle":
        return summary_llm

    return None


def get_selected_summary_llm_model():
    return summary_llm.get_model()


def set_selected_summary_llm_model(model: str) -> bool:
    available = get_available_llm_models()
    if available and model not in available:
        return False
    summary_llm.set_model(model)
    return True


def _load_persisted_models():
    settings = load_runtime_settings(settings_path)

    command_model = (settings.get("command_model") or "").strip()
    if command_model:
        set_selected_command_llm_model(command_model)

    summary_model = (settings.get("summary_model") or "").strip()
    if summary_model:
        set_selected_summary_llm_model(summary_model)


def _persist_selected_models():
    save_runtime_settings(
        {
            "command_model": get_selected_command_llm_model(),
            "summary_model": get_selected_summary_llm_model(),
        },
        settings_path=settings_path,
    )


def _shutdown_runtime():
    try:
        snapshot = session_memory.export_session_data()
        if snapshot.get("duration_min", 0) > 0:
            update_memories_from_session(snapshot)
        session_memory.close()
    except Exception as exc:
        log.warning("shutdown sync failed: %s", exc)


def build_context_snapshot() -> str:
    state = store.to_dict()
    session_data = session_memory.export_session_data()
    recent_events = session_memory.get_recent_events(limit=8)
    memory_context = load_memory_context()

    with runtime_lock:
        signals = last_signals
        decision = last_decision

    sections = [
        "# Pulse Context Snapshot",
        "",
        "## Current State",
        "- Project: {0}".format(state.get("active_project") or "not detected"),
        "- Active file: {0}".format(state.get("active_file") or "unknown"),
        "- Active app: {0}".format(state.get("active_app") or "unknown"),
        "- Session duration: {0} min".format(state.get("session_duration_min", 0)),
        "- Last event: {0}".format(state.get("last_event_type") or "unknown"),
    ]

    if signals:
        sections.extend(
            [
                "",
                "## Signals",
                "- Probable task: {0}".format(signals.probable_task),
                "- Focus level: {0}".format(signals.focus_level),
                "- Friction score: {0:.2f}".format(signals.friction_score),
                "- Clipboard context: {0}".format(signals.clipboard_context or "none"),
                "- Recent apps: {0}".format(", ".join(signals.recent_apps) or "none"),
            ]
        )

    if decision:
        sections.extend(
            [
                "",
                "## Latest Decision",
                "- Action: {0}".format(decision.action),
                "- Level: {0}".format(decision.level),
                "- Reason: {0}".format(decision.reason),
            ]
        )
        if decision.payload:
            payload_parts = [
                "{0}={1}".format(key, value)
                for key, value in sorted(decision.payload.items())
            ]
            sections.append("- Payload: {0}".format(", ".join(payload_parts)))

    sections.extend(
        [
            "",
            "## Session Memory",
            "- Session ID: {0}".format(session_data.get("session_id") or "unknown"),
            "- Files changed: {0}".format(session_data.get("files_changed", 0)),
            "- Event count: {0}".format(session_data.get("event_count", 0)),
            "- Max friction: {0:.2f}".format(float(session_data.get("max_friction", 0.0))),
        ]
    )

    if recent_events:
        sections.extend(["", "## Recent Events"])
        for event in recent_events:
            payload = event.get("payload") or {}
            summary_keys = (
                payload.get("app_name")
                or payload.get("path")
                or payload.get("content_kind")
                or payload.get("tool_use_id")
                or payload.get("decision")
            )
            suffix = " ({0})".format(summary_keys) if summary_keys else ""
            sections.append(
                "- {0}: {1}{2}".format(
                    event.get("timestamp", "unknown"),
                    event.get("type", "unknown"),
                    suffix,
                )
            )

    if memory_context:
        sections.extend(
            [
                "",
                "## Persistent Memory",
                memory_context.strip(),
            ]
        )

    return "\n".join(sections).strip() + "\n"


bus.subscribe(store.update)
bus.subscribe(_handle_event)
atexit.register(_shutdown_runtime)
_load_persisted_models()


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
    return jsonify({"context": build_context_snapshot()})


@app.route("/llm/models")
def get_llm_models():
    return jsonify({
        "provider": "ollama",
        "available_models": get_available_llm_models(),
        "selected_command_model": get_selected_command_llm_model(),
        "selected_summary_model": get_selected_summary_llm_model(),
    })


@app.route("/llm/model", methods=["POST"])
def set_llm_model():
    data = request.get_json() or {}
    kind = (data.get("kind") or "command").strip()
    model = (data.get("model") or "").strip()
    if not model:
        return jsonify({"ok": False, "error": "missing_model"}), 400

    if kind == "summary":
        ok = set_selected_summary_llm_model(model)
        selected = get_selected_summary_llm_model()
    elif kind == "command":
        ok = set_selected_command_llm_model(model)
        selected = get_selected_command_llm_model()
    else:
        return jsonify({"ok": False, "error": "unknown_kind"}), 400

    if not ok:
        return jsonify({"ok": False, "error": "unknown_model"}), 400

    _persist_selected_models()

    return jsonify({
        "ok": True,
        "kind": kind,
        "selected_model": selected,
        "selected_command_model": get_selected_command_llm_model(),
        "selected_summary_model": get_selected_summary_llm_model(),
    })


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
