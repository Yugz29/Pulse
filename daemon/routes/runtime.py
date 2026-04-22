from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.current_context_adapters import current_context_to_legacy_signals_payload
from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.event_actor import EventActorClassifier
from daemon.core.file_classifier import file_signal_significance
from daemon.core.workspace_context import find_workspace_root
from daemon.memory.extractor import last_session_context
from daemon.memory.extractor import find_git_root

_actor_classifier = EventActorClassifier()
_current_context_builder = CurrentContextBuilder()

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


@dataclass
class _PendingFileEvent:
    path: str
    event_type: str
    payload: dict[str, Any]
    started_at: float
    token: int
    timer: Any


class _FileEventCoalescer:
    """
    Regroupe un burst heterogene create/modify/rename sur un meme path
    avant injection dans l'EventBus.

    Le premier event eligible est retenu pendant une courte fenetre.
    - meme type (modify + modify) : pas de fusion, les events restent distincts
    - types heterogenes : l'event de priorite la plus forte gagne
      (renamed > created > modified)
    """

    def __init__(
        self,
        *,
        publisher: Callable[[str, dict[str, Any]], None],
        window_sec: float = _FILE_EVENT_COHERENCE_WINDOW_SEC,
        timer_factory: Callable[..., Any] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._publisher = publisher
        self._window_sec = window_sec
        self._timer_factory = timer_factory or threading.Timer
        self._time_fn = time_fn or time.monotonic
        self._lock = threading.Lock()
        self._pending_by_path: dict[str, _PendingFileEvent] = {}
        self._next_token = 0

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        path = payload.get("path")
        if not self._is_coalescible(event_type, path):
            self._publisher(event_type, payload)
            return

        emit_now: tuple[str, dict[str, Any]] | None = None
        now = self._time_fn()

        with self._lock:
            pending = self._pending_by_path.get(path)
            if pending is None:
                self._pending_by_path[path] = self._new_pending(
                    path=path,
                    event_type=event_type,
                    payload=dict(payload),
                    started_at=now,
                )
                return

            expired = (now - pending.started_at) > self._window_sec
            same_type = pending.event_type == event_type

            if expired or same_type:
                pending.timer.cancel()
                emit_now = (pending.event_type, pending.payload)
                self._pending_by_path[path] = self._new_pending(
                    path=path,
                    event_type=event_type,
                    payload=dict(payload),
                    started_at=now,
                )
            else:
                if self._priority(event_type) > self._priority(pending.event_type):
                    pending.event_type = event_type
                    pending.payload = dict(payload)

        if emit_now is not None:
            self._publisher(*emit_now)

    def _new_pending(
        self,
        *,
        path: str,
        event_type: str,
        payload: dict[str, Any],
        started_at: float,
    ) -> _PendingFileEvent:
        token = self._next_token
        self._next_token += 1
        timer = self._timer_factory(
            self._window_sec,
            self._flush_pending,
            args=(path, token),
        )
        timer.daemon = True
        pending = _PendingFileEvent(
            path=path,
            event_type=event_type,
            payload=payload,
            started_at=started_at,
            token=token,
            timer=timer,
        )
        timer.start()
        return pending

    def _flush_pending(self, path: str, token: int) -> None:
        emit: tuple[str, dict[str, Any]] | None = None
        with self._lock:
            pending = self._pending_by_path.get(path)
            if pending is None or pending.token != token:
                return
            emit = (pending.event_type, pending.payload)
            self._pending_by_path.pop(path, None)

        if emit is not None:
            self._publisher(*emit)

    def _is_coalescible(self, event_type: str, path: Any) -> bool:
        return bool(path) and event_type in _COALESCIBLE_FILE_EVENT_TYPES

    def _priority(self, event_type: str) -> int:
        return _FILE_EVENT_PRIORITY.get(event_type, -1)


def register_runtime_routes(
    app: Flask,
    *,
    bus: Any,
    store: Any,
    runtime_state: Any,
    get_session_fsm: Callable[[], Any] | None = None,
    get_current_episode: Callable[[], Any] | None = None,
    get_recent_episodes: Callable[[int], Any] | None = None,
    llm_unload_background: Callable[[], None],
    llm_warmup_background: Callable[[], None],
    shutdown_runtime: Callable[[], None],
    log: Any,
) -> None:
    file_event_coalescer = _FileEventCoalescer(
        publisher=lambda event_type, payload: threading.Thread(
            target=bus.publish,
            args=(event_type, payload),
            daemon=True,
        ).start()
    )

    @app.route("/ping")
    def ping():
        paused = runtime_state.touch_ping()
        return jsonify({"status": "ok", "version": "0.1.0", "paused": paused})

    @app.route("/event", methods=["POST"])
    def receive_event():
        data = request.get_json() or {}
        event_type = data.get("type", "unknown")
        payload = {key: value for key, value in data.items() if key != "type"}
        if runtime_state.is_paused():
            return jsonify({"ok": True, "paused": True, "ignored": True})

        # Mise à jour de l'app active avant le filtre — la classification d'actor
        # en a besoin pour les events fichiers qui suivent.
        if event_type in {"app_activated", "app_switch"}:
            app_name = payload.get("app_name")
            if app_name:
                runtime_state.set_latest_active_app(app_name)

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
        file_event_coalescer.publish(event_type, payload)
        return jsonify({"ok": True})

    @app.route("/state")
    def get_state():
        state = store.to_dict()
        signals, decision, paused = runtime_state.get_signal_snapshot()
        state["runtime_paused"] = paused
        if signals:
            current_context = runtime_state.get_current_context()
            if current_context is None:
                current_context = _current_context_builder.build(
                    state=state,
                    signals=signals,
                    find_git_root_fn=find_git_root,
                    find_workspace_root_fn=find_workspace_root,
                )
            state["signals"] = current_context_to_legacy_signals_payload(
                current_context,
                signals=signals,
                last_session_line=(
                    last_session_context(current_context.active_project)
                    if current_context.active_project
                    else None
                ),
            )
        if decision:
            state["decision"] = {
                "action": decision.action,
                "level": decision.level,
                "reason": decision.reason,
                "payload": decision.payload,
            }
        if get_session_fsm is not None:
            fsm = get_session_fsm()
            state["session_fsm"] = {
                "state": fsm.state,
                "session_started_at": fsm.session_started_at.isoformat() if fsm.session_started_at else None,
                "last_meaningful_activity_at": fsm.last_meaningful_activity_at.isoformat() if fsm.last_meaningful_activity_at else None,
                "last_screen_locked_at": fsm.last_screen_locked_at.isoformat() if fsm.last_screen_locked_at else None,
            }
        if get_current_episode is not None:
            episode = get_current_episode()
            if episode is not None:
                state["current_episode"] = {
                    "id": episode.id,
                    "session_id": episode.session_id,
                    "started_at": episode.started_at,
                    "ended_at": episode.ended_at,
                    "boundary_reason": episode.boundary_reason,
                    "duration_sec": episode.duration_sec,
                    "probable_task": episode.probable_task,
                    "activity_level": episode.activity_level,
                    "task_confidence": episode.task_confidence,
                }
        if get_recent_episodes is not None:
            episodes = get_recent_episodes(8)
            if episodes:
                state["recent_episodes"] = episodes
        return jsonify(state)

    @app.route("/insights")
    def get_insights():
        try:
            limit = int(request.args.get("limit", 25))
        except (TypeError, ValueError):
            limit = 25
        limit = min(max(limit, 1), 100)
        # Le bus ne contient que des events meaningful depuis le filtrage
        # à l'entrée dans _should_publish_to_bus(). Pas de filtre supplémentaire.
        recent = bus.recent(limit)
        return jsonify([
            {"type": event.type, "payload": event.payload, "timestamp": event.timestamp.isoformat()}
            for event in recent
        ])

    @app.route("/daemon/shutdown", methods=["POST"])
    def daemon_shutdown():
        log.info("Shutdown demandé via HTTP")
        shutdown_runtime()

        def _exit():
            time.sleep(0.3)
            os._exit(0)

        threading.Thread(target=_exit, daemon=True).start()
        return jsonify({"ok": True, "action": "shutdown"})

    @app.route("/daemon/pause", methods=["POST"])
    def daemon_pause():
        runtime_state.set_paused(True)
        threading.Thread(target=llm_unload_background, daemon=True).start()
        return jsonify({"ok": True, "action": "pause", "paused": True})

    @app.route("/daemon/resume", methods=["POST"])
    def daemon_resume():
        runtime_state.set_paused(False)
        threading.Thread(target=llm_warmup_background, daemon=True).start()
        return jsonify({"ok": True, "action": "resume", "paused": False})

    @app.route("/daemon/restart", methods=["POST"])
    def daemon_restart():
        log.info("Restart demandé via HTTP")
        shutdown_runtime()

        def _exit():
            time.sleep(0.3)
            os._exit(1)

        threading.Thread(target=_exit, daemon=True).start()
        return jsonify({"ok": True, "action": "restart"})


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
    - Pour clipboard_updated, le champ 'content' est retiré du payload avant
      publication : seul content_kind est utilisé par le scorer. Défense en
      profondeur au cas où un ancien client Swift enverrait encore le contenu brut.
    """
    _LOCK_PASSTHROUGH = {"screen_locked", "screen_unlocked"}

    # Pendant le verrou : seuls les events de transition verrouillage passent.
    if runtime_state is not None and runtime_state.is_screen_locked():
        if event_type not in _LOCK_PASSTHROUGH:
            return False

    if event_type not in _BUS_FILE_EVENT_TYPES:
        # Défense en profondeur : retirer le contenu brut clipboard avant publication.
        if event_type == "clipboard_updated" and "content" in payload:
            payload.pop("content")
        return True

    path = payload.get("path", "")

    # Exception critique : COMMIT_EDITMSG déclenche la détection de commit.
    if "COMMIT_EDITMSG" in path:
        return True

    return file_signal_significance(path) == "meaningful"
