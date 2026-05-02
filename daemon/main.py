import atexit
import importlib
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask

from daemon.cognitive import ask as cognitive_ask, ask_stream as cognitive_ask_stream, ask_stream_with_tools as cognitive_ask_stream_with_tools
from daemon.core.decision_engine import DecisionEngine
from daemon.core.event_bus import EventBus
from daemon.core.signal_scorer import SignalScorer
from daemon.core.state_store import StateStore
from daemon.llm.runtime import LLMRuntime
from daemon.llm.unavailable import UnavailableLLMRouter
from daemon.mcp.handlers import (
    build_runtime_signal,
    configure_llm_router,
    get_available_llm_models,
    get_pending_command,
    get_proposal_history,
    get_selected_command_llm_model,
    intercept_command,
    receive_decision,
    set_selected_command_llm_model,
)
from daemon.mcp.server import start_mcp_server
from daemon.memory.session import SessionMemory
from daemon.memory.store import MemoryStore
from daemon.routes.assistant import register_assistant_routes
from daemon.routes.facts import register_facts_routes
from daemon.routes.mcp import register_mcp_routes
from daemon.routes.memory import register_memory_routes
from daemon.routes.runtime import register_runtime_routes
from daemon.runtime_orchestrator import RuntimeOrchestrator
from daemon.runtime_state import RuntimeState

logging.basicConfig(
    level=logging.DEBUG,
    format="[Daemon %(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pulse")

app = Flask(__name__)


class _RoutineGetLogFilter(logging.Filter):
    """Masque les GET de polling normaux pour garder daemon.error.log exploitable."""

    _ROUTINE_GET_PATHS = {
        "/ping",
        "/state",
        "/feed",
        "/today_summary",
        "/observation",
        "/daydreams",
        "/mcp/pending",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        message = record.getMessage()
        if "\"GET " not in message:
            return True
        return not any(f"\"GET {path} " in message for path in self._ROUTINE_GET_PATHS)


logging.getLogger("werkzeug").addFilter(_RoutineGetLogFilter())


def _build_summary_llm():
    try:
        router_module = importlib.import_module("daemon.llm.router")
        return router_module.LLMRouter()
    except Exception as exc:
        log.warning("LLM router indisponible au démarrage: %s", exc)
        return UnavailableLLMRouter(reason=exc)

bus = EventBus()
store = StateStore()
scorer = SignalScorer(bus)
decision_engine = DecisionEngine()
summary_llm = _build_summary_llm()
configure_llm_router(summary_llm)
session_memory = SessionMemory()
memory_store = MemoryStore()
runtime_state = RuntimeState()
settings_path = Path.home() / ".pulse" / "settings.json"
llm_runtime = LLMRuntime(
    summary_llm=summary_llm,
    settings_path=settings_path,
    get_available_models=get_available_llm_models,
    get_selected_command_model=get_selected_command_llm_model,
    set_selected_command_model=set_selected_command_llm_model,
)
runtime_orchestrator = RuntimeOrchestrator(
    store=store,
    scorer=scorer,
    decision_engine=decision_engine,
    summary_llm=summary_llm,
    session_memory=session_memory,
    memory_store=memory_store,
    runtime_state=runtime_state,
    llm_runtime=llm_runtime,
    log=log,
)

WATCHDOG_TIMEOUT_SEC = 30
WATCHDOG_GRACE_SEC = 15


def _ollama_ping() -> bool:
    return llm_runtime.ollama_ping()


def _llm_provider():
    return llm_runtime.provider()


def _llm_unload_background() -> None:
    runtime_orchestrator.llm_unload_background()


def _llm_warmup_background() -> None:
    runtime_orchestrator.llm_warmup_background()


def _handle_event(event) -> None:
    runtime_orchestrator.handle_event(event)


def get_selected_summary_llm_model():
    return llm_runtime.get_selected_summary_model()


def set_selected_summary_llm_model(model: str) -> bool:
    return llm_runtime.set_selected_summary_model(model)


def set_unified_model(model: str) -> bool:
    return llm_runtime.set_unified_model(model)


def _persist_selected_models() -> None:
    llm_runtime.persist_selected_models()


def _shutdown_runtime() -> None:
    runtime_orchestrator.shutdown_runtime()


def build_context_snapshot() -> str:
    return runtime_orchestrator.build_context_snapshot()


def _deferred_startup() -> None:
    runtime_orchestrator.deferred_startup()


def _is_launchd_child() -> bool:
    try:
        return os.getppid() == 1
    except Exception:
        return False


def _watchdog_loop() -> None:
    if _is_launchd_child():
        log.info("Watchdog désactivé (mode LaunchAgent)")
        return

    log.info("Watchdog activé (mode dev) — timeout %ds", WATCHDOG_TIMEOUT_SEC)
    time.sleep(WATCHDOG_GRACE_SEC)

    while True:
        time.sleep(10)
        last = runtime_state.get_last_ping_at()
        if last is None:
            continue
        silence = (datetime.now() - last).total_seconds()
        if silence > WATCHDOG_TIMEOUT_SEC:
            log.info("Client Swift absent depuis %.0fs → arrêt daemon (mode dev)", silence)
            _shutdown_runtime()
            os._exit(0)


def get_scoring_status():
    from daemon.scoring import parser_treesitter

    ts_available = parser_treesitter.is_available()
    languages = parser_treesitter.available_languages() if ts_available else {}
    return {
        "treesitter_core": ts_available,
        "python_ast": True,
        "languages": {
            lang: {"available": ok, "parser": "treesitter" if ok else "regex_fallback"}
            for lang, ok in languages.items()
        },
    }


bus.subscribe(store.update)
bus.subscribe(_handle_event)

register_runtime_routes(
    app,
    bus=bus,
    store=store,
    runtime_state=runtime_state,
    get_session_fsm=lambda: runtime_orchestrator.session_fsm,
    get_current_context=lambda: runtime_orchestrator.current_context,
    get_recent_sessions=lambda limit: session_memory.get_recent_sessions(limit=limit),
    get_today_summary=lambda: session_memory.get_today_summary(),
    llm_unload_background=_llm_unload_background,
    llm_warmup_background=_llm_warmup_background,
    shutdown_runtime=_shutdown_runtime,
    resume_card_llm=summary_llm,
    log=log,
)

register_assistant_routes(
    app,
    cognitive_ask=cognitive_ask,
    cognitive_ask_stream=cognitive_ask_stream,
    cognitive_ask_stream_with_tools=cognitive_ask_stream_with_tools,
    llm=summary_llm,
    build_context_snapshot=build_context_snapshot,
    get_frozen_memory=lambda: runtime_orchestrator.get_frozen_memory(),
    get_available_models=lambda: get_available_llm_models(),
    get_selected_command_model=lambda: get_selected_command_llm_model(),
    get_selected_summary_model=lambda: get_selected_summary_llm_model(),
    set_unified_model=lambda model: set_unified_model(model),
    persist_selected_models=lambda: _persist_selected_models(),
    ollama_ping=lambda: _ollama_ping(),
    llm_provider=lambda: _llm_provider(),
)

register_memory_routes(
    app,
    memory_store=memory_store,
    session_memory=session_memory,
    get_frozen_memory_at=lambda: runtime_orchestrator.get_frozen_memory_at(),
)

register_mcp_routes(
    app,
    bus=bus,
    get_pending_command=lambda: get_pending_command(),
    get_proposal_history=lambda limit: get_proposal_history(limit),
    intercept_command=lambda command, tool_use_id: intercept_command(command, tool_use_id),
    build_runtime_signal=lambda command, tool_use_id, **kwargs: build_runtime_signal(
        command,
        tool_use_id,
        **kwargs,
    ),
    receive_decision=lambda tool_use_id, decision: receive_decision(tool_use_id, decision),
    get_scoring_status=lambda: get_scoring_status(),
    log=log,
)

register_facts_routes(
    app,
    get_fact_engine=lambda: runtime_orchestrator.fact_engine,
)


if __name__ == "__main__":
    atexit.register(_shutdown_runtime)
    start_mcp_server(host="127.0.0.1", port=8766)
    threading.Thread(target=_watchdog_loop, daemon=True, name="pulse-watchdog").start()
    threading.Thread(target=_deferred_startup, daemon=True, name="pulse-startup").start()
    log.info("✓ Pulse daemon démarré sur http://127.0.0.1:8765 (threaded=True)")
    app.run(host="127.0.0.1", port=8765, debug=False, threaded=True)
