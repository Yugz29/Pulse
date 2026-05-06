from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.context_probe_store import ContextProbeRequestStore
from daemon.core.event_actor import EventActorClassifier
from daemon.core.workspace_context import extract_project_name, find_workspace_root
from daemon.interpreter.command_interpreter import CommandInterpreter
from daemon.memory.extractor import last_session_context
from daemon.routes.debug_memory import register_debug_memory_routes
from daemon.routes.runtime_debug_routes import register_debug_routes
from daemon.routes.runtime_feed_routes import register_feed_routes
from daemon.routes.runtime_probe_routes import register_probe_routes
from daemon.routes.runtime_daemon_routes import register_daemon_routes
from daemon.routes.runtime_resume_card_routes import register_resume_card_routes

_actor_classifier = EventActorClassifier()
_current_context_builder = CurrentContextBuilder()
_terminal_interpreter = CommandInterpreter()

_TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({
    "terminal_command_started",
    "terminal_command_finished",
})
_TERMINAL_TEST_COMMANDS: frozenset[str] = frozenset({
    "pytest", "tox", "nosetests", "nose2", "unittest",
})
_TERMINAL_BUILD_COMMANDS: frozenset[str] = frozenset({
    "xcodebuild", "make", "cmake", "ninja",
})
_TERMINAL_SETUP_COMMANDS: frozenset[str] = frozenset({
    "brew", "pip", "pip3", "npm", "pnpm", "yarn", "uv", "poetry", "cargo",
})

_FILE_EVENT_COHERENCE_WINDOW_SEC = 1.0
_COALESCIBLE_FILE_EVENT_TYPES: frozenset[str] = frozenset({
    "file_created",
    "file_modified",
    "file_renamed",
})
_FILE_EVENT_PRIORITY: dict[str, int] = {
    "file_modified": 0,
    "file_created": 1,
    "file_renamed": 2,
}

_SCREENSHOT_FILE_EVENT_PRIORITY: dict[str, int] = {
    "file_modified": 0,
    "file_renamed": 1,
    "file_created": 2,
}
_SCREENSHOT_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".heic", ".tiff"})
_SCREENSHOT_NAME_PREFIXES: tuple[str, ...] = (
    "capture d’écran",
    "capture d'ecran",
    "capture d’écran",
    "screenshot",
    "screen shot",
)


@dataclass
class _PendingFileEvent:
    path: str
    event_type: str
    payload: dict[str, Any]
    timestamp: datetime | None
    started_at: float
    due_at: float


class _FileEventCoalescer:
    """
    Regroupe un burst heterogene create/modify/rename sur un meme path
    avant injection dans l'EventBus.

    Le premier event eligible est retenu pendant une courte fenetre.
    - meme type (modify + modify) : pas de fusion, les events restent distincts
    - types heterogenes : l'event de priorite la plus forte gagne
      (renamed > created > modified)

    Important : cette fenetre est volontairement basee sur le temps local
    d'ingestion daemon (monotonic), pas sur le timestamp source. Le but est
    purement technique : absorber un burst HTTP/FSEvents local sans laisser
    l'ordre ou l'age source reconfigurer la logique de transport.
    """

    def __init__(
        self,
        *,
        publisher: Callable[[str, dict[str, Any], datetime | None], None],
        window_sec: float = _FILE_EVENT_COHERENCE_WINDOW_SEC,
        time_fn: Callable[[], float] | None = None,
        start_worker: bool = True,
    ) -> None:
        self._publisher = publisher
        self._window_sec = window_sec
        self._time_fn = time_fn or time.monotonic
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._pending_by_path: dict[str, _PendingFileEvent] = {}
        self._stopped = False
        self._worker: threading.Thread | None = None
        if start_worker:
            self._worker = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="pulse-file-coalescer",
            )
            self._worker.start()

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> None:
        path = payload.get("path")
        if not self._is_coalescible(event_type, payload):
            self._publisher(event_type, payload, timestamp)
            return

        screenshot_event = _is_screenshot_path(str(path))
        emit_now: tuple[str, dict[str, Any], datetime | None] | None = None
        now = self._time_fn()

        with self._condition:
            pending = self._pending_by_path.get(path)
            if pending is None:
                self._pending_by_path[path] = self._new_pending(
                    path=path,
                    event_type=event_type,
                    payload=dict(payload),
                    timestamp=timestamp,
                    started_at=now,
                )
                self._condition.notify_all()
                return

            expired = (now - pending.started_at) > self._window_sec
            same_type = pending.event_type == event_type

            if expired:
                emit_now = (pending.event_type, pending.payload, pending.timestamp)
                self._pending_by_path[path] = self._new_pending(
                    path=path,
                    event_type=event_type,
                    payload=dict(payload),
                    timestamp=timestamp,
                    started_at=now,
                )
            elif screenshot_event:
                if self._priority(event_type, payload) > self._priority(pending.event_type, pending.payload):
                    pending.event_type = event_type
                    pending.payload = dict(payload)
                    pending.timestamp = timestamp
            elif same_type:
                emit_now = (pending.event_type, pending.payload, pending.timestamp)
                self._pending_by_path[path] = self._new_pending(
                    path=path,
                    event_type=event_type,
                    payload=dict(payload),
                    timestamp=timestamp,
                    started_at=now,
                )
            else:
                if self._priority(event_type, payload) > self._priority(pending.event_type, pending.payload):
                    pending.event_type = event_type
                    pending.payload = dict(payload)
                    pending.timestamp = timestamp
            self._condition.notify_all()

        if emit_now is not None:
            self._publisher(*emit_now)

    def _new_pending(
        self,
        *,
        path: str,
        event_type: str,
        payload: dict[str, Any],
        timestamp: datetime | None,
        started_at: float,
    ) -> _PendingFileEvent:
        return _PendingFileEvent(
            path=path,
            event_type=event_type,
            payload=payload,
            timestamp=timestamp,
            started_at=started_at,
            due_at=started_at + self._window_sec,
        )

    def _flush_due(self) -> list[tuple[str, dict[str, Any], datetime | None]]:
        now = self._time_fn()
        due_paths = [
            path
            for path, pending in self._pending_by_path.items()
            if pending.due_at <= now
        ]
        emits: list[tuple[str, dict[str, Any], datetime | None]] = []
        for path in due_paths:
            pending = self._pending_by_path.pop(path, None)
            if pending is None:
                continue
            emits.append((pending.event_type, pending.payload, pending.timestamp))
        return emits

    def _run_loop(self) -> None:
        while True:
            with self._condition:
                while not self._stopped and not self._pending_by_path:
                    self._condition.wait()
                if self._stopped:
                    return
                next_due = min(pending.due_at for pending in self._pending_by_path.values())
                wait_sec = max(next_due - self._time_fn(), 0.0)
                if wait_sec > 0:
                    self._condition.wait(timeout=wait_sec)
                    continue
                emits = self._flush_due()

            for emit in emits:
                self._publisher(*emit)

    def close(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()

    def _is_coalescible(self, event_type: str, payload: dict[str, Any]) -> bool:
        from daemon.core.event_meaning import _default_policy
        return _default_policy.classify(event_type, payload).coalescible

    def _priority(self, event_type: str, payload: dict[str, Any]) -> int:
        from daemon.core.event_meaning import _default_policy
        return _default_policy.classify(event_type, payload).coalescing_priority


def _is_screenshot_path(path: str) -> bool:
    name = os.path.basename(path).strip().lower()
    if not name:
        return False
    _, ext = os.path.splitext(name)
    if ext not in _SCREENSHOT_EXTENSIONS:
        return False
    return any(name.startswith(prefix) for prefix in _SCREENSHOT_NAME_PREFIXES)


# Helper to serialize current_context for /state route
def _serialize_current_context(current_context: Any) -> dict[str, Any]:
    from daemon.routes.runtime_state_payloads import serialize_current_context
    return serialize_current_context(current_context)


def _build_state_payload(
    *,
    store_state: dict[str, Any],
    runtime_snapshot: Any,
    get_session_fsm: Callable[[], Any] | None = None,
    get_current_context: Callable[[], Any] | None = None,
    get_recent_sessions: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    from daemon.routes.runtime_state_payloads import build_state_payload
    return build_state_payload(
        store_state=store_state,
        runtime_snapshot=runtime_snapshot,
        get_session_fsm=get_session_fsm,
        get_current_context=get_current_context,
        get_recent_sessions=get_recent_sessions,
        current_context_builder=_current_context_builder,
        last_session_context_fn=last_session_context,
    )


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
    
    def _publish_to_bus(
        event_type: str,
        payload: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> None:
        if timestamp is None:
            bus.publish(event_type, payload)
        else:
            bus.publish(event_type, payload, timestamp)

    file_event_coalescer = _FileEventCoalescer(
        publisher=_publish_to_bus,
    )

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
        current_context_builder=_current_context_builder,
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
        current_context_builder=_current_context_builder,
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

    @app.route("/ping")
    def ping():
        paused = runtime_state.touch_ping()
        return jsonify({"status": "ok", "version": "0.1.0", "paused": paused})

    @app.route("/event", methods=["POST"])
    def receive_event():
        data = request.get_json() or {}
        event_type = data.get("type", "unknown")
        observed_at = _parse_event_timestamp(data.get("timestamp"))
        payload = {
            key: value
            for key, value in data.items()
            if key not in {"type", "timestamp"}
        }
        if runtime_state.is_paused():
            return jsonify({"ok": True, "paused": True, "ignored": True})

        # Mise à jour de l'app active avant le filtre — la classification d'actor
        # en a besoin pour les events fichiers qui suivent.
        if event_type in {"app_activated", "app_switch"}:
            app_name = payload.get("app_name")
            if app_name:
                runtime_state.set_latest_active_app(app_name)

        if event_type in _TERMINAL_EVENT_TYPES:
            payload = _normalize_terminal_event_payload(event_type, payload)

        if not _should_publish_to_bus(event_type, payload, runtime_state):
            return jsonify({"ok": True, "filtered": True})

        # Attribution de l'auteur pour les events fichiers.
        # On lit le bus avant la publication de l'event courant pour la détection
        # de burst et de repeat — l'event courant n'est pas encore dans le bus.
        if event_type in {"file_modified", "file_created", "file_renamed", "file_deleted"}:
            recent = bus.recent(60)
            attribution = _actor_classifier.classify(
                event_type,
                payload,
                latest_app=runtime_state.get_latest_active_app(),
                recent_events=recent,
            )
            payload["_actor"]            = attribution.actor
            payload["_actor_confidence"] = attribution.confidence
            payload["_automation_score"] = attribution.automation_score
            payload["_noise_policy"]     = attribution.noise_policy

        # Répond immédiatement — Swift ne doit jamais attendre le pipeline SQLite.
        # Les bursts heterogenes create/modify/rename sont coalesces ici,
        # juste avant l'injection dans l'EventBus.
        file_event_coalescer.publish(event_type, payload, observed_at)
        return jsonify({"ok": True})

    @app.route("/state")
    def get_state():
        # Legacy surface payload: still used for last_event_type / last_activity
        # and debug visibility only. Runtime-facing active_app comes from RuntimeState.
        state = _build_state_payload(
            store_state=store.to_dict(),
            runtime_snapshot=runtime_state.get_runtime_snapshot(),
            get_session_fsm=get_session_fsm,
            get_current_context=get_current_context,
            get_recent_sessions=get_recent_sessions,
        )
        return jsonify(state)

    @app.route("/insights")
    def get_insights():
        try:
            limit = int(request.args.get("limit", 25))
        except (TypeError, ValueError):
            limit = 25
        limit = min(max(limit, 1), 100)

        # Filtre optionnel par timestamp — Swift envoie son dernier ts connu.
        # Permet un polling différentiel : seuls les nouveaux events sont retournés.
        since_raw = request.args.get("since")
        since_dt = _parse_event_timestamp(since_raw) if since_raw else None

        recent = bus.recent(limit)

        # Filtre les events notables pour le feed UI :
        # terminal fini, commit capté, mémoire écrite.
        notable_types = {
            "terminal_command_finished",
            "memory_written",
        }

        events = [
            {
                "type": event.type,
                "payload": event.payload,
                "timestamp": event.timestamp.isoformat()
            }
            for event in recent
            if (since_dt is None or event.timestamp > since_dt)
        ]
        return jsonify(events)




# ── Bus entry filter ──────────────────────────────────────────────────────────

_BUS_FILE_EVENT_TYPES: frozenset[str] = frozenset({
    "file_created", "file_modified", "file_renamed",
    "file_deleted", "file_change",
})


def _should_publish_to_bus(event_type: str, payload: dict, runtime_state: Any = None) -> bool:
    """
    Décide si un event doit entrer dans l'EventBus.

    Règles :
    - Les events non-fichier (app, screen, clipboard) passent toujours,
      sauf les events app_* pendant le verrou écran.
    - COMMIT_EDITMSG passe toujours.
    - Pendant le verrou, seuls screen_locked/screen_unlocked entrent dans le bus.
      Les écritures système en arrière-plan ne doivent pas contaminer le scorer.
    - Les autres events fichier sont filtrés par file_signal_significance.
      "observe_only" entre dans le bus pour le contexte brut, mais ne doit
      pas piloter le runtime live.
    - Pour clipboard_updated, le champ 'content' est retiré du payload avant
      publication : seul content_kind est utilisé par le scorer. Défense en
      profondeur au cas où un ancien client Swift enverrait encore le contenu brut.
    """
    from daemon.core.event_meaning import _default_policy

    if runtime_state is not None and runtime_state.is_screen_locked():
        if event_type not in {"screen_locked", "screen_unlocked"}:
            return False

    decision = _default_policy.classify(event_type, payload)
    if decision.sanitized_payload is not None:
        payload.clear()
        payload.update(decision.sanitized_payload)
    return decision.publish_to_bus


def _normalize_terminal_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    command = str(payload.pop("command", "") or payload.pop("raw", "")).strip()
    cwd = str(payload.get("cwd", "")).strip() or None
    shell = str(payload.get("shell", "")).strip() or None
    terminal_program = str(payload.get("terminal_program", "")).strip() or None
    exit_code = _coerce_int(payload.get("exit_code"))
    duration_ms = _coerce_int(payload.get("duration_ms"))

    normalized: dict[str, Any] = {
        "source": "terminal",
        "kind": "finished" if event_type == "terminal_command_finished" else "started",
    }

    if shell:
        normalized["terminal_shell"] = shell
    if terminal_program:
        normalized["terminal_program"] = terminal_program
    if cwd:
        normalized["terminal_cwd"] = cwd
        normalized["terminal_project"] = extract_project_name(cwd)
        workspace_root = find_workspace_root(cwd)
        if workspace_root:
            normalized["terminal_workspace_root"] = str(workspace_root)

    if exit_code is not None:
        normalized["terminal_exit_code"] = exit_code
    if duration_ms is not None:
        normalized["terminal_duration_ms"] = duration_ms

    if not command:
        return normalized

    interpretation = _terminal_interpreter.interpret(command)
    action_category = _terminal_action_category(command, interpretation)
    base_cmd = _split_command(command)[0]

    # Résumé enrichi : statut de sortie + description humaine de la commande.
    # Si exit_code est disponible (terminal_command_finished), on préfixe
    # le résumé avec ✓/✗ pour indiquer succès ou échec.
    if interpretation.needs_llm:
        raw_summary = _terminal_category_summary(action_category)
    else:
        raw_summary = interpretation.translated

    if exit_code is not None:
        status_prefix = "\u2713" if exit_code == 0 else "\u2717"
        summary = f"{status_prefix} {raw_summary}"
    else:
        summary = raw_summary

    normalized.update(
        {
            "terminal_command": command,
            "terminal_command_base": base_cmd,
            "terminal_action_category": action_category,
            "terminal_is_read_only": interpretation.is_read_only,
            "terminal_affects": list(interpretation.affects),
            "terminal_success": (exit_code == 0) if exit_code is not None else None,
            "terminal_summary": summary,
        }
    )
    return normalized


def _parse_event_timestamp(raw: Any) -> datetime | None:
    from daemon.core.terminal_event_normalizer import parse_event_timestamp
    return parse_event_timestamp(raw)


def _terminal_action_category(command: str, interpretation) -> str:
    from daemon.core.terminal_event_normalizer import terminal_action_category
    return terminal_action_category(command, interpretation)


def _terminal_category_summary(category: str) -> str:
    from daemon.core.terminal_event_normalizer import terminal_category_summary
    return terminal_category_summary(category)


def _split_command(command: str) -> tuple[str, list[str]]:
    from daemon.core.terminal_event_normalizer import split_command
    return split_command(command)


def _coerce_int(value: Any) -> int | None:
    from daemon.core.terminal_event_normalizer import coerce_int
    return coerce_int(value)
