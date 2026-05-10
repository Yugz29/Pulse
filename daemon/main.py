import atexit
import importlib
import logging
import os
import threading
import time
from dataclasses import dataclass
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
from daemon.platform.idle_heartbeat import create_idle_presence_heartbeat
from daemon.routes.assistant import register_assistant_routes
from daemon.routes.facts import register_facts_routes
from daemon.routes.mcp import register_mcp_routes
from daemon.routes.memory import register_memory_routes
from daemon.routes.runtime import register_runtime_routes
from daemon.routes.runtime_daemon_routes import DAEMON_EXIT_GRACE_SEC
from daemon.runtime_orchestrator import RuntimeOrchestrator
from daemon.runtime_state import RuntimeState

logging.basicConfig(
    level=logging.DEBUG,
    format="[Daemon %(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pulse")


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
        from daemon.settings import load_runtime_settings
        settings = load_runtime_settings(Path.home() / ".pulse" / "settings.json")
        model = (settings.get("model") or settings.get("command_model") or "").strip()
        config = {"llm": {"model": model}} if model else {}
        router_module = importlib.import_module("daemon.llm.router")
        return router_module.LLMRouter(config=config)
    except Exception as exc:
        log.warning("LLM router indisponible au démarrage: %s", exc)
        return UnavailableLLMRouter(reason=exc)


@dataclass(frozen=True)
class RuntimeBundle:
    bus: EventBus
    store: StateStore
    scorer: SignalScorer
    decision_engine: DecisionEngine
    summary_llm: object
    session_memory: SessionMemory
    memory_store: MemoryStore
    runtime_state: RuntimeState
    llm_runtime: LLMRuntime
    runtime_orchestrator: RuntimeOrchestrator


def create_runtime() -> RuntimeBundle:
    runtime_bus = EventBus()
    runtime_store = StateStore()
    runtime_scorer = SignalScorer(runtime_bus)
    runtime_decision_engine = DecisionEngine()
    runtime_summary_llm = _build_summary_llm()
    configure_llm_router(runtime_summary_llm)
    runtime_session_memory = SessionMemory()
    runtime_memory_store = MemoryStore()
    runtime_state_obj = RuntimeState()
    runtime_settings_path = Path.home() / ".pulse" / "settings.json"
    runtime_llm = LLMRuntime(
        summary_llm=runtime_summary_llm,
        settings_path=runtime_settings_path,
        get_available_models=get_available_llm_models,
        get_selected_command_model=get_selected_command_llm_model,
        set_selected_command_model=set_selected_command_llm_model,
    )
    orchestrator = RuntimeOrchestrator(
        store=runtime_store,
        scorer=runtime_scorer,
        decision_engine=runtime_decision_engine,
        summary_llm=runtime_summary_llm,
        session_memory=runtime_session_memory,
        memory_store=runtime_memory_store,
        runtime_state=runtime_state_obj,
        llm_runtime=runtime_llm,
        log=log,
    )
    return RuntimeBundle(
        bus=runtime_bus,
        store=runtime_store,
        scorer=runtime_scorer,
        decision_engine=runtime_decision_engine,
        summary_llm=runtime_summary_llm,
        session_memory=runtime_session_memory,
        memory_store=runtime_memory_store,
        runtime_state=runtime_state_obj,
        llm_runtime=runtime_llm,
        runtime_orchestrator=orchestrator,
    )


runtime = create_runtime()
bus = runtime.bus
store = runtime.store
scorer = runtime.scorer
decision_engine = runtime.decision_engine
summary_llm = runtime.summary_llm
session_memory = runtime.session_memory
memory_store = runtime.memory_store
runtime_state = runtime.runtime_state
llm_runtime = runtime.llm_runtime
runtime_orchestrator = runtime.runtime_orchestrator
idle_presence_heartbeat = create_idle_presence_heartbeat(
    bus,
    is_locked=runtime_state.is_screen_locked,
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


def start_runtime_services() -> None:
    runtime_orchestrator.start()
    idle_presence_heartbeat.start()


def _shutdown_runtime() -> None:
    try:
        idle_presence_heartbeat.stop()
    except Exception as exc:
        log.warning("shutdown idle heartbeat failed: %s", exc)
    try:
        runtime_event_coalescer.close()
    except Exception as exc:
        log.warning("shutdown coalescer failed: %s", exc)
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
            time.sleep(DAEMON_EXIT_GRACE_SEC)
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


def create_app(runtime: RuntimeBundle) -> Flask:
    flask_app = Flask(__name__)

    coalescer = register_runtime_routes(
        flask_app,
        bus=runtime.bus,
        store=runtime.store,
        runtime_state=runtime.runtime_state,
        get_session_fsm=lambda: runtime.runtime_orchestrator.session_fsm,
        get_current_context=lambda: runtime.runtime_orchestrator.current_context,
        get_recent_sessions=lambda limit: runtime.session_memory.get_recent_sessions(limit=limit),
        get_today_summary=lambda: runtime.session_memory.get_today_summary(),
        get_today_work_episodes=lambda date=None: runtime.session_memory.get_today_work_episodes(date=date),
        get_today_journal_candidates=lambda date=None: runtime.session_memory.get_today_journal_candidates(date=date),
        get_today_journal_comparison=lambda date=None: runtime.session_memory.get_today_journal_comparison(date=date),
        get_today_commit_episode_links=lambda date=None: runtime.session_memory.get_today_commit_episode_links(date=date),
        llm_unload_background=_llm_unload_background,
        llm_warmup_background=_llm_warmup_background,
        shutdown_runtime=_shutdown_runtime,
        resume_card_llm=runtime.summary_llm,
        log=log,
    )
    setattr(flask_app, "runtime_event_coalescer", coalescer)

    register_assistant_routes(
        flask_app,
        cognitive_ask=cognitive_ask,
        cognitive_ask_stream=cognitive_ask_stream,
        cognitive_ask_stream_with_tools=cognitive_ask_stream_with_tools,
        llm=runtime.summary_llm,
        build_context_snapshot=build_context_snapshot,
        get_frozen_memory=lambda: runtime.runtime_orchestrator.get_frozen_memory(),
        get_available_models=lambda: get_available_llm_models(),
        get_selected_command_model=lambda: get_selected_command_llm_model(),
        get_selected_summary_model=lambda: get_selected_summary_llm_model(),
        set_unified_model=lambda model: set_unified_model(model),
        persist_selected_models=lambda: _persist_selected_models(),
        ollama_ping=lambda: _ollama_ping(),
        llm_provider=lambda: _llm_provider(),
    )

    register_memory_routes(
        flask_app,
        memory_store=runtime.memory_store,
        session_memory=runtime.session_memory,
        get_frozen_memory_at=lambda: runtime.runtime_orchestrator.get_frozen_memory_at(),
    )

    register_mcp_routes(
        flask_app,
        bus=runtime.bus,
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
        flask_app,
        get_fact_engine=lambda: runtime.runtime_orchestrator.fact_engine,
    )

    return flask_app


bus.subscribe(store.update)
bus.subscribe(_handle_event)

app = create_app(runtime)
runtime_event_coalescer = app.runtime_event_coalescer


if __name__ == "__main__":
    start_runtime_services()
    atexit.register(_shutdown_runtime)
    start_mcp_server(host="127.0.0.1", port=8766)
    threading.Thread(target=_watchdog_loop, daemon=True, name="pulse-watchdog").start()
    threading.Thread(target=_deferred_startup, daemon=True, name="pulse-startup").start()
    log.info("✓ Pulse daemon démarré sur http://127.0.0.1:8765 (threaded=True)")
    app.run(host="127.0.0.1", port=8765, debug=False, threaded=True)
