"""Observation and feed routes — read-only bus and memory inspection. No side effects."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from flask import Flask, jsonify, request


def register_feed_routes(
    app: Flask,
    *,
    bus: Any,
    parse_timestamp_fn: Callable[[Any], datetime | None],
    get_today_summary: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """Register observation and feed inspection routes onto *app*."""

    @app.route("/observation")
    def get_observation():
        """Retourne les titres de fenêtres et commandes récents capturs par Pulse."""
        recent = bus.recent(200)
        now = datetime.now()

        window_titles = []
        terminal_commands = []
        seen_titles: set[str] = set()

        for event in reversed(recent):
            payload = event.payload or {}
            elapsed = (now - event.timestamp).total_seconds()

            # Titres de fenêtres — depuis app_activated et window_title_poll
            if event.type in {"app_activated", "window_title_poll"}:
                title = payload.get("window_title") or payload.get("title")
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    window_titles.append({
                        "title": title,
                        "app": payload.get("app_name", ""),
                        "timestamp": event.timestamp.isoformat(),
                        "elapsed_sec": int(elapsed),
                    })
                    if len(window_titles) >= 50:
                        break

            # Commandes terminal récentes — filtrer les triviales
            _TRIVIAL_COMMANDS = {"clear", "ls", "cd", "pwd", "echo", "cat", "man", "which", "history"}
            if event.type == "terminal_command_finished":
                cmd = payload.get("terminal_command", "")
                base = payload.get("terminal_command_base", "")
                if cmd and base not in _TRIVIAL_COMMANDS:
                    terminal_commands.append({
                        "command": cmd,
                        "summary": payload.get("terminal_summary", ""),
                        "success": payload.get("terminal_success"),
                        "duration_ms": payload.get("terminal_duration_ms"),
                        "project": payload.get("terminal_project", ""),
                        "timestamp": event.timestamp.isoformat(),
                    })
                    if len(terminal_commands) >= 20:
                        break

        return jsonify({
            "window_titles": window_titles[:50],
            "terminal_commands": terminal_commands[:20],
        })

    @app.route("/daydreams")
    def get_daydreams():
        """Liste les fichiers DayDream disponibles."""
        from pathlib import Path
        from daemon.memory.daydream import get_daydream_status
        daydream_dir = Path.home() / ".pulse" / "memory" / "daydreams"
        if not daydream_dir.exists():
            return jsonify({"daydreams": [], "status": get_daydream_status()})

        files = sorted(daydream_dir.glob("*.md"), reverse=True)[:7]
        result = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
                result.append({
                    "date": f.stem,
                    "content": content,
                })
            except Exception:
                pass
        return jsonify({"daydreams": result, "status": get_daydream_status()})

    @app.route("/today_summary")
    def get_today_summary_route():
        if get_today_summary is None:
            now = datetime.now()
            return jsonify({
                "date": now.date().isoformat(),
                "generated_at": now.isoformat(),
                "totals": {
                    "worked_min": 0,
                    "active_min": 0,
                    "commit_count": 0,
                    "window_count": 0,
                    "project_count": 0,
                },
                "projects": [],
                "timeline": {
                    "first_activity_at": None,
                    "last_activity_at": None,
                },
                "current_window": None,
            })
        return jsonify(get_today_summary())

    @app.route("/feed")
    def get_feed():
        """Events notables depuis un timestamp — pour les notifications UI."""
        since_raw = request.args.get("since")
        since_dt = parse_timestamp_fn(since_raw) if since_raw else None

        recent = bus.recent(200)

        _GENERIC_LABELS = {
            "Commande terminal", "Inspection terminal",
            "Exécution de tests", "Commande de build",
            "Commande de setup", "Commande de contrôle de version",
        }

        notable: list[dict] = []
        for event in recent:
            if since_dt is not None and event.timestamp <= since_dt:
                continue
            payload = event.payload or {}

            if (
                event.type == "terminal_command_finished"
                and payload.get("terminal_success") is not None
            ):
                success = payload["terminal_success"]
                base_cmd = payload.get("terminal_command_base", "")
                summary = payload.get("terminal_summary", "")

                if base_cmd == "pytest" or (
                    base_cmd in {"python", "python3"}
                    and "-m" in payload.get("terminal_command", "")
                    and "pytest" in payload.get("terminal_command", "")
                ):
                    cmd_parts = payload.get("terminal_command", "").split()
                    test_target = next(
                        (
                            p for p in cmd_parts[1:]
                            if not p.startswith("-")
                            and p != "-m"
                            and p != "pytest"
                            and (".py" in p or "/" in p or p == "tests")
                        ),
                        None,
                    )
                    label = f"pytest {test_target.split('/')[-1].replace('.py', '')}" if test_target else "pytest"
                elif base_cmd in {"xcodebuild", "make", "ninja", "cmake"}:
                    label = f"Build {base_cmd}"
                elif base_cmd == "git":
                    parts = payload.get("terminal_command", "").split()
                    subcmd = parts[1] if len(parts) > 1 else ""
                    label = f"git {subcmd}" if subcmd else summary
                elif summary:
                    label = summary
                else:
                    label = base_cmd

                if label and label not in _GENERIC_LABELS:
                    notable.append({
                        "kind": "terminal",
                        "success": success,
                        "label": label,
                        "command": payload.get("terminal_command", ""),
                        "timestamp": event.timestamp.isoformat(),
                    })

            elif event.type == "llm_loading":
                notable.append({
                    "kind": "llm_loading",
                    "success": None,
                    "label": "Chargement du modèle…",
                    "command": None,
                    "timestamp": event.timestamp.isoformat(),
                })
            elif event.type == "llm_ready":
                notable.append({
                    "kind": "llm_ready",
                    "success": True,
                    "label": "Modèle chargé",
                    "command": None,
                    "timestamp": event.timestamp.isoformat(),
                })
            elif event.type == "resume_card":
                notable.append({
                    "kind": "resume_card",
                    "success": True,
                    "label": payload.get("title") or "Reprise de contexte",
                    "command": None,
                    "timestamp": event.timestamp.isoformat(),
                    "resume_card": payload,
                })

        return jsonify(notable)
