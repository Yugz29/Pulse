"""Daemon lifecycle control routes — shutdown, pause, resume, restart."""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

from flask import Flask, jsonify


DAEMON_EXIT_GRACE_SEC = 1.0


def register_daemon_routes(
    app: Flask,
    *,
    bus: Any,
    runtime_state: Any,
    shutdown_runtime: Callable[[], None],
    llm_unload_background: Callable[[], None],
    llm_warmup_background: Callable[[], None],
    log: Any,
) -> None:
    """Register daemon lifecycle control routes onto *app*."""

    @app.route("/daemon/shutdown", methods=["POST"])
    def daemon_shutdown():
        log.info("Shutdown demandé via HTTP")
        shutdown_runtime()

        def _exit():
            time.sleep(DAEMON_EXIT_GRACE_SEC)
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
        import time as _time
        runtime_state.set_paused(False)

        def _warmup_with_events():
            bus.publish("llm_loading", {"model": ""})
            t0 = _time.monotonic()
            llm_warmup_background()
            load_time_sec = round(_time.monotonic() - t0, 2)
            bus.publish("llm_ready", {"model": "", "load_time_sec": load_time_sec})

        threading.Thread(target=_warmup_with_events, daemon=True).start()
        return jsonify({"ok": True, "action": "resume", "paused": False})

    @app.route("/daemon/restart", methods=["POST"])
    def daemon_restart():
        log.info("Restart demandé via HTTP")
        shutdown_runtime()

        def _exit():
            time.sleep(DAEMON_EXIT_GRACE_SEC)
            os._exit(1)

        threading.Thread(target=_exit, daemon=True).start()
        return jsonify({"ok": True, "action": "restart"})
