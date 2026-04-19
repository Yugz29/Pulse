from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.file_classifier import file_signal_significance
from daemon.memory.extractor import last_session_context


def register_runtime_routes(
    app: Flask,
    *,
    bus: Any,
    store: Any,
    runtime_state: Any,
    llm_unload_background: Callable[[], None],
    llm_warmup_background: Callable[[], None],
    shutdown_runtime: Callable[[], None],
    log: Any,
) -> None:
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
        if not _should_publish_to_bus(event_type, payload, runtime_state):
            return jsonify({"ok": True, "filtered": True})
        # Répond immédiatement — Swift ne doit jamais attendre le pipeline SQLite.
        threading.Thread(target=bus.publish, args=(event_type, payload), daemon=True).start()
        return jsonify({"ok": True})

    @app.route("/state")
    def get_state():
        state = store.to_dict()
        signals, decision, paused = runtime_state.get_signal_snapshot()
        state["runtime_paused"] = paused
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
                "edited_file_count_10m": signals.edited_file_count_10m,
                "file_type_mix_10m": signals.file_type_mix_10m,
                "rename_delete_ratio_10m": signals.rename_delete_ratio_10m,
                "dominant_file_mode": signals.dominant_file_mode,
                "work_pattern_candidate": signals.work_pattern_candidate,
                "last_session_context": last_session_context(signals.active_project) if signals.active_project else None,
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
