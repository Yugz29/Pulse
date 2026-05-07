"""Runtime route aggregator — wires all sub-routers onto the Flask app."""
from __future__ import annotations

from typing import Any, Callable

from flask import Flask

from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.context_probe_store import ContextProbeRequestStore
from daemon.routes.debug_memory import register_debug_memory_routes
from daemon.routes.runtime_debug_routes import register_debug_routes
from daemon.routes.runtime_feed_routes import register_feed_routes
from daemon.routes.runtime_ingestion import register_ingestion_routes, _parse_event_timestamp
from daemon.routes.runtime_probe_routes import register_probe_routes
from daemon.routes.runtime_daemon_routes import register_daemon_routes
from daemon.routes.runtime_resume_card_routes import register_resume_card_routes
from daemon.routes.runtime_status_routes import register_status_routes




def register_runtime_routes(
    app: Flask,
    *,
    bus: Any,
    store: Any,
    runtime_state: Any,
    get_session_fsm: Callable[[], Any] | None = None,
    get_current_context: Callable[[], Any] | None = None,
    get_recent_sessions: Callable[[int], Any] | None = None,
    get_today_summary: Callable[[], dict[str, Any]] | None = None,
    get_today_work_episodes: Callable[[], dict[str, Any]] | None = None,
    get_today_journal_candidates: Callable[[], dict[str, Any]] | None = None,
    get_today_journal_comparison: Callable[[], dict[str, Any]] | None = None,
    get_today_commit_episode_links: Callable[[], dict[str, Any]] | None = None,
    context_probe_store: ContextProbeRequestStore | None = None,
    llm_unload_background: Callable[[], None],
    llm_warmup_background: Callable[[], None],
    shutdown_runtime: Callable[[], None],
    log: Any,
    resume_card_llm: Any = None,
) -> None:
    probe_store = context_probe_store or ContextProbeRequestStore()

    current_context_builder = CurrentContextBuilder()

    register_ingestion_routes(app, bus=bus, runtime_state=runtime_state)

    register_debug_memory_routes(
        app,
        get_work_episodes=get_today_work_episodes,
        get_journal_candidates=get_today_journal_candidates,
        get_journal_comparison=get_today_journal_comparison,
        get_commit_episode_links=get_today_commit_episode_links,
    )

    register_debug_routes(
        app,
        bus=bus,
        runtime_state=runtime_state,
        current_context_builder=current_context_builder,
        parse_timestamp_fn=_parse_event_timestamp,
    )

    register_feed_routes(
        app,
        bus=bus,
        parse_timestamp_fn=_parse_event_timestamp,
        get_today_summary=get_today_summary,
    )

    register_probe_routes(
        app,
        bus=bus,
        runtime_state=runtime_state,
        probe_store=probe_store,
        current_context_builder=current_context_builder,
    )

    register_daemon_routes(
        app,
        bus=bus,
        runtime_state=runtime_state,
        shutdown_runtime=shutdown_runtime,
        llm_unload_background=llm_unload_background,
        llm_warmup_background=llm_warmup_background,
        log=log,
    )

    register_resume_card_routes(
        app,
        bus=bus,
        runtime_state=runtime_state,
        get_recent_sessions=get_recent_sessions,
        get_today_summary=get_today_summary,
        resume_card_llm=resume_card_llm,
    )


    register_status_routes(
        app,
        bus=bus,
        store=store,
        runtime_state=runtime_state,
        current_context_builder=current_context_builder,
        get_session_fsm=get_session_fsm,
        get_current_context=get_current_context,
        get_recent_sessions=get_recent_sessions,
    )
