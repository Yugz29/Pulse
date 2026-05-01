from __future__ import annotations

import os
import shlex
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.current_context_adapters import current_context_to_legacy_signals_payload
from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.context_probe_policy import (
    ContextProbeConsent,
    ContextProbeKind,
    policy_for_probe,
)
from daemon.core.context_probe_debug import describe_context_probe_request_for_debug
from daemon.core.context_probe_request import (
    approve_context_probe_request,
    create_context_probe_request,
    execute_context_probe_request,
    refuse_context_probe_request,
)
from daemon.core.context_probe_store import ContextProbeRequestStore, requests_to_dicts
from daemon.core.context_probe_runner import run_app_context_probe, run_window_title_probe
from daemon.core.event_actor import EventActorClassifier
from daemon.core.event_debug import describe_event_for_debug
from daemon.core.event_envelope import (
    PulseEventBucket,
    PulseEventSource,
    PulsePrivacyClass,
    PulseRetention,
)
from daemon.core.file_classifier import file_signal_significance
from daemon.core.timeline_builder import span_from_current_context
from daemon.core.timeline_debug import describe_timeline_span_for_debug
from daemon.core.timeline_span import TimelineSpanKind
from daemon.core.workspace_context import extract_project_name, find_workspace_root
from daemon.interpreter.command_interpreter import CommandInterpreter
from daemon.memory.extractor import last_session_context
from daemon.memory.extractor import find_git_root

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
        if not self._is_coalescible(event_type, path):
            self._publisher(event_type, payload, timestamp)
            return

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

            if expired or same_type:
                emit_now = (pending.event_type, pending.payload, pending.timestamp)
                self._pending_by_path[path] = self._new_pending(
                    path=path,
                    event_type=event_type,
                    payload=dict(payload),
                    timestamp=timestamp,
                    started_at=now,
                )
            else:
                if self._priority(event_type) > self._priority(pending.event_type):
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
    get_current_context: Callable[[], Any] | None = None,
    get_recent_sessions: Callable[[int], Any] | None = None,
    get_today_summary: Callable[[], dict[str, Any]] | None = None,
    context_probe_store: ContextProbeRequestStore | None = None,
    llm_unload_background: Callable[[], None],
    llm_warmup_background: Callable[[], None],
    shutdown_runtime: Callable[[], None],
    log: Any,
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
        store_state = store.to_dict()
        runtime_snapshot = runtime_state.get_runtime_snapshot()
        present = runtime_snapshot.present
        state = {
            "active_app": runtime_snapshot.latest_active_app,
            "active_file": present.active_file,
            "active_project": present.active_project,
            "session_duration_min": present.session_duration_min,
            "last_event_type": store_state.get("last_event_type"),
            "runtime_paused": runtime_snapshot.paused,
            "present": present.to_dict(),
        }

        debug: dict[str, Any] = {
            "store": store_state,
            "runtime": {
                "latest_active_app": runtime_snapshot.latest_active_app,
                "lock_marker_active": runtime_snapshot.lock_marker_active,
                "last_screen_locked_at": (
                    runtime_snapshot.last_screen_locked_at.isoformat()
                    if runtime_snapshot.last_screen_locked_at
                    else None
                ),
                "memory_synced_at": (
                    runtime_snapshot.memory_synced_at.isoformat()
                    if runtime_snapshot.memory_synced_at
                    else None
                ),
            },
        }

        if runtime_snapshot.decision:
            decision_payload = {
                "action": runtime_snapshot.decision.action,
                "level": runtime_snapshot.decision.level,
                "reason": runtime_snapshot.decision.reason,
                "payload": runtime_snapshot.decision.payload,
            }
            state["decision"] = decision_payload
            debug["decision"] = decision_payload
        if get_session_fsm is not None:
            fsm = get_session_fsm()
            session_fsm_payload = {
                "state": fsm.state,
                "session_started_at": fsm.session_started_at.isoformat() if fsm.session_started_at else None,
                "last_meaningful_activity_at": fsm.last_meaningful_activity_at.isoformat() if fsm.last_meaningful_activity_at else None,
                "last_screen_locked_at": fsm.last_screen_locked_at.isoformat() if fsm.last_screen_locked_at else None,
            }
            state["session_fsm"] = session_fsm_payload
            debug["session_fsm"] = session_fsm_payload
        if get_current_context is not None:
            current_context = get_current_context()
            if current_context is not None:
                context_payload = {
                    "id": current_context.id,
                    "session_id": current_context.session_id,
                    "started_at": current_context.started_at,
                    "ended_at": current_context.ended_at,
                    "boundary_reason": current_context.boundary_reason,
                    "duration_sec": current_context.duration_sec,
                    "active_project": current_context.active_project,
                    "probable_task": current_context.probable_task,
                    "activity_level": current_context.activity_level,
                    "task_confidence": current_context.task_confidence,
                }
                state["current_context"] = context_payload
                debug["current_context"] = context_payload
        if runtime_snapshot.signals:
            current_context = _current_context_builder.build(
                present=present,
                active_app=state.get("active_app"),
                signals=runtime_snapshot.signals,
                find_git_root_fn=find_git_root,
                find_workspace_root_fn=find_workspace_root,
            )
            legacy_signals = current_context_to_legacy_signals_payload(
                current_context,
                signals=runtime_snapshot.signals,
                last_session_line=(
                    last_session_context(current_context.active_project)
                    if current_context.active_project
                    else None
                ),
            )
            # Compat / debug : la lecture produit passe par current_context
            # puis present. Les signaux restent exposés pour instrumentation.
            state["signals"] = legacy_signals
            debug["signals"] = legacy_signals
        if get_recent_sessions is not None:
            sessions = get_recent_sessions(8)
            if sessions:
                state["recent_sessions"] = sessions
                debug["recent_sessions"] = sessions
        state["debug"] = debug
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


    @app.route("/events/debug")
    def get_events_debug():
        """Developer-only raw event browser preview without raw payload values."""
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        limit = min(max(limit, 1), 200)

        since_raw = request.args.get("since")
        since_dt = _parse_event_timestamp(since_raw) if since_raw else None

        source_filter = request.args.get("source")
        bucket_filter = request.args.get("bucket")
        privacy_filter = request.args.get("privacy")
        retention_filter = request.args.get("retention")

        recent = bus.recent(limit)
        events = []
        for event in recent:
            if since_dt is not None and event.timestamp <= since_dt:
                continue
            description = describe_event_for_debug(event)
            if source_filter and description["source"] != source_filter:
                continue
            if bucket_filter and description["bucket"] != bucket_filter:
                continue
            if privacy_filter and description["privacy"] != privacy_filter:
                continue
            if retention_filter and description["retention"] != retention_filter:
                continue
            events.append(description)
        return jsonify({"events": events, "count": len(events)})

    @app.route("/events/schema")
    def get_events_schema():
        """Expose event metadata enums for debug UI / raw event browser filters."""
        return jsonify({
            "sources": [source.value for source in PulseEventSource],
            "buckets": [bucket.value for bucket in PulseEventBucket],
            "privacy_classes": [privacy.value for privacy in PulsePrivacyClass],
            "retention_classes": [retention.value for retention in PulseRetention],
        })

    @app.route("/timeline/preview")
    def get_timeline_preview():
        """Preview a passive timeline span from the current runtime context."""
        runtime_snapshot = runtime_state.get_runtime_snapshot()
        present = runtime_snapshot.present
        now = datetime.now()
        duration_min = max(int(present.session_duration_min or 0), 0)
        started_at = now - timedelta(minutes=duration_min)

        if runtime_snapshot.signals:
            context = _current_context_builder.build(
                present=present,
                active_app=runtime_snapshot.latest_active_app,
                signals=runtime_snapshot.signals,
                find_git_root_fn=find_git_root,
                find_workspace_root_fn=find_workspace_root,
            )
        else:
            context = present

        span = span_from_current_context(
            context,
            started_at=started_at,
            ended_at=now,
        )
        return jsonify({
            "span": span.to_dict(),
            "debug": describe_timeline_span_for_debug(span),
        })

    @app.route("/timeline/schema")
    def get_timeline_schema():
        """Expose timeline metadata enums for debug UI / timeline filters."""
        return jsonify({
            "span_kinds": [kind.value for kind in TimelineSpanKind],
        })

    @app.route("/context-probes/schema")
    def get_context_probes_schema():
        """Expose context probe safety policies for debug UI / consent screens."""
        probe_kinds = [kind for kind in ContextProbeKind if kind is not ContextProbeKind.UNKNOWN]
        return jsonify({
            "probe_kinds": [kind.value for kind in ContextProbeKind],
            "consent_levels": [consent.value for consent in ContextProbeConsent],
            "default_policies": {
                kind.value: policy_for_probe(kind).to_dict()
                for kind in probe_kinds
            },
            "unknown_policy": policy_for_probe(ContextProbeKind.UNKNOWN).to_dict(),
        })

    @app.route("/context-probes/request-preview", methods=["POST"])
    def create_context_probe_request_preview():
        """Create a non-persistent context probe request preview for consent UI."""
        data = request.get_json() or {}
        kind = data.get("kind", ContextProbeKind.UNKNOWN.value)
        reason = str(data.get("reason", "") or "")
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

        try:
            ttl_sec = int(data.get("ttl_sec", 300))
        except (TypeError, ValueError):
            ttl_sec = 300
        ttl_sec = min(max(ttl_sec, 0), 3600)

        probe_request = create_context_probe_request(
            kind,
            reason=reason,
            ttl_sec=ttl_sec,
            metadata=metadata,
        )
        return jsonify({
            "request": probe_request.to_dict(),
            "debug": describe_context_probe_request_for_debug(probe_request),
        })

    @app.route("/context-probes/requests", methods=["POST"])
    def create_context_probe_request_route():
        """Create and store a pending context probe request without executing it."""
        data = request.get_json() or {}
        kind = data.get("kind", ContextProbeKind.UNKNOWN.value)
        reason = str(data.get("reason", "") or "")
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

        try:
            ttl_sec = int(data.get("ttl_sec", 300))
        except (TypeError, ValueError):
            ttl_sec = 300
        ttl_sec = min(max(ttl_sec, 0), 3600)

        probe_request = create_context_probe_request(
            kind,
            reason=reason,
            ttl_sec=ttl_sec,
            metadata=metadata,
        )
        probe_store.add(probe_request)
        return jsonify({
            "request": probe_request.to_dict(),
            "debug": describe_context_probe_request_for_debug(probe_request),
        })

    @app.route("/context-probes/requests")
    def list_context_probe_requests_route():
        """List stored context probe requests without exposing metadata values."""
        probe_store.expire_due()
        status = request.args.get("status")
        include_terminal = request.args.get("include_terminal", "true").lower() not in {"0", "false", "no"}
        try:
            requests_list = probe_store.list(
                status=status,
                include_terminal=include_terminal,
            )
        except ValueError:
            return jsonify({"error": "invalid_status"}), 400
        return jsonify({
            "requests": requests_to_dicts(requests_list),
            "debug": [describe_context_probe_request_for_debug(item) for item in requests_list],
            "count": len(requests_list),
        })

    @app.route("/context-probes/requests/<request_id>/approve", methods=["POST"])
    def approve_context_probe_request_route(request_id: str):
        """Approve a stored context probe request without executing it."""
        data = request.get_json(silent=True) or {}
        probe_request = probe_store.get(request_id)
        if probe_request is None:
            return jsonify({"error": "not_found"}), 404
        try:
            approved = approve_context_probe_request(
                probe_request,
                decision_reason=data.get("reason"),
            )
        except ValueError as exc:
            return jsonify({"error": "invalid_transition", "message": str(exc)}), 409
        probe_store.update(approved)
        return jsonify({
            "request": approved.to_dict(),
            "debug": describe_context_probe_request_for_debug(approved),
        })

    @app.route("/context-probes/requests/<request_id>/refuse", methods=["POST"])
    def refuse_context_probe_request_route(request_id: str):
        """Refuse a stored context probe request."""
        data = request.get_json(silent=True) or {}
        probe_request = probe_store.get(request_id)
        if probe_request is None:
            return jsonify({"error": "not_found"}), 404
        try:
            refused = refuse_context_probe_request(
                probe_request,
                decision_reason=data.get("reason"),
            )
        except ValueError as exc:
            return jsonify({"error": "invalid_transition", "message": str(exc)}), 409
        probe_store.update(refused)
        return jsonify({
            "request": refused.to_dict(),
            "debug": describe_context_probe_request_for_debug(refused),
        })

    @app.route("/context-probes/requests/<request_id>/execute", methods=["POST"])
    def execute_context_probe_request_route(request_id: str):
        """Execute an approved context probe and mark the request executed."""
        probe_request = probe_store.get(request_id)
        if probe_request is None:
            return jsonify({"error": "not_found"}), 404

        runtime_snapshot = runtime_state.get_runtime_snapshot()
        present = runtime_snapshot.present

        if runtime_snapshot.signals:
            current_context = _current_context_builder.build(
                present=present,
                active_app=runtime_snapshot.latest_active_app,
                signals=runtime_snapshot.signals,
                find_git_root_fn=find_git_root,
                find_workspace_root_fn=find_workspace_root,
            )
            probe_context = SimpleNamespace(
                active_app=runtime_snapshot.latest_active_app,
                active_project=current_context.active_project,
                activity_level=current_context.activity_level,
                probable_task=current_context.probable_task,
                window_title=runtime_snapshot.signals.window_title,
            )
        else:
            probe_context = SimpleNamespace(
                active_app=runtime_snapshot.latest_active_app,
                active_project=present.active_project,
                activity_level=present.activity_level,
                probable_task=present.probable_task,
                window_title=None,
            )

        if probe_request.kind is ContextProbeKind.WINDOW_TITLE:
            result = run_window_title_probe(probe_request, probe_context)
        else:
            result = run_app_context_probe(probe_request, probe_context)
        if not result.captured:
            return jsonify({
                "error": "probe_blocked",
                "blocked_reason": result.blocked_reason,
                "result": result.to_dict(),
                "request": probe_request.to_dict(),
                "debug": describe_context_probe_request_for_debug(probe_request),
            }), 409

        try:
            executed = execute_context_probe_request(probe_request)
        except ValueError as exc:
            return jsonify({"error": "invalid_transition", "message": str(exc)}), 409
        probe_store.update(executed)
        bus.publish("context_probe_executed", {
            "request_id": executed.request_id,
            "kind": result.kind,
            "captured": result.captured,
            "privacy": result.privacy,
            "retention": result.retention,
            "data_keys": sorted(result.data.keys()),
        })
        return jsonify({
            "result": result.to_dict(),
            "request": executed.to_dict(),
            "debug": describe_context_probe_request_for_debug(executed),
        })

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
            return jsonify(
                {
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
                }
            )
        return jsonify(get_today_summary())

    @app.route("/feed")
    def get_feed():
        """Events notables depuis un timestamp — pour les notifications UI."""
        since_raw = request.args.get("since")
        since_dt = _parse_event_timestamp(since_raw) if since_raw else None

        recent = bus.recent(200)

        notable: list[dict] = []
        for event in recent:
            if since_dt is not None and event.timestamp <= since_dt:
                continue
            payload = event.payload or {}

            # Terminal fini avec résultat
            if (
                event.type == "terminal_command_finished"
                and payload.get("terminal_success") is not None
            ):
                success = payload["terminal_success"]
                base_cmd = payload.get("terminal_command_base", "")
                summary = payload.get("terminal_summary", "")
                duration_ms = payload.get("terminal_duration_ms")
                tick = ""

                if base_cmd == "pytest" or (base_cmd in {"python", "python3"} and "-m" in payload.get("terminal_command", "") and "pytest" in payload.get("terminal_command", "")):
                    cmd_parts = payload.get("terminal_command", "").split()
                    test_target = next(
                        (p for p in cmd_parts[1:] if not p.startswith("-") and p != "-m" and p != "pytest" and (".py" in p or "/" in p or p == "tests")),
                        None
                    )
                    if test_target:
                        short = test_target.split("/")[-1].replace(".py", "")
                        label = f"pytest {short}"
                    else:
                        label = "pytest"
                elif base_cmd in {"xcodebuild", "make", "ninja", "cmake"}:
                    label = f"Build {base_cmd}"
                elif base_cmd == "git":
                    cmd = payload.get("terminal_command", "")
                    parts = cmd.split()
                    subcmd = parts[1] if len(parts) > 1 else ""
                    label = f"git {subcmd}" if subcmd else summary
                elif summary:
                    label = summary
                else:
                    label = base_cmd

                if duration_ms and duration_ms > 2000:
                    pass  # durée retirée de la notification

                # Ne notifier que si le label est spécifique et utile.
                # Les labels génériques comme "Commande terminal" n'apportent rien.
                _GENERIC_LABELS = {
                    "Commande terminal", "Inspection terminal",
                    "Exécution de tests", "Commande de build",
                    "Commande de setup", "Commande de contrôle de version",
                }
                if label and label not in _GENERIC_LABELS:
                    notable.append({
                        "kind": "terminal",
                        "success": success,
                        "label": label,
                        "command": payload.get("terminal_command", ""),
                        "timestamp": event.timestamp.isoformat(),
                    })

            # Commit capturé — retiré du feed (peu d'info pour une notification)

            # LLM loading / ready
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

        def _warmup_with_events():
            bus.publish("llm_loading", {"model": ""})
            llm_warmup_background()
            bus.publish("llm_ready", {"model": ""})

        threading.Thread(target=_warmup_with_events, daemon=True).start()
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
      "observe_only" entre dans le bus pour le contexte brut, mais ne doit
      pas piloter le runtime live.
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
        if event_type in _TERMINAL_EVENT_TYPES:
            payload.pop("command", None)
            payload.pop("raw", None)
        return True

    path = payload.get("path", "")

    # Exception critique : COMMIT_EDITMSG déclenche la détection de commit.
    if "COMMIT_EDITMSG" in path:
        return True

    return file_signal_significance(path) in {"meaningful", "observe_only"}


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
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _terminal_action_category(command: str, interpretation) -> str:
    base_cmd, tokens = _split_command(command)
    subcommands = set(tokens[1:])

    if base_cmd == "git":
        return "vcs"

    if base_cmd in _TERMINAL_TEST_COMMANDS or "test" in subcommands:
        return "testing"

    if base_cmd in _TERMINAL_BUILD_COMMANDS:
        return "build"

    if base_cmd in _TERMINAL_SETUP_COMMANDS:
        if subcommands & {"install", "add", "init", "bootstrap", "update"}:
            return "setup"
        if subcommands & {"build", "compile", "run"}:
            return "build"

    if interpretation.is_read_only:
        return "inspection"

    return "execution"


def _terminal_category_summary(category: str) -> str:
    return {
        "inspection": "Inspection terminal",
        "testing": "Exécution de tests",
        "vcs": "Commande de contrôle de version",
        "build": "Commande de build",
        "setup": "Commande de setup",
        "execution": "Commande terminal",
    }.get(category, "Commande terminal")


def _split_command(command: str) -> tuple[str, list[str]]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    return (tokens[0] if tokens else "", tokens)


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
