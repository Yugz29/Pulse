"""Context probe lifecycle routes — create, list, approve, refuse, execute. No side effects beyond probe state."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from flask import Flask, jsonify, request

from daemon.core.context_probe_policy import (
    ContextProbeConsent,
    ContextProbeKind,
    policy_for_probe,
)
from daemon.core.context_probe_debug import describe_context_probe_request_for_debug
from daemon.core.context_probe_request import (
    abort_context_probe_request,
    approve_context_probe_request,
    create_context_probe_request,
    execute_context_probe_request,
    refuse_context_probe_request,
)
from daemon.core.context_probe_store import ContextProbeRequestStore, requests_to_dicts
from daemon.core.context_probe_runner import (
    run_app_context_probe,
    run_window_title_probe,
    submit_context_probe_result,
)
from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.memory.extractor import find_git_root
from daemon.core.workspace_context import find_workspace_root


def register_probe_routes(
    app: Flask,
    *,
    bus: Any,
    runtime_state: Any,
    probe_store: ContextProbeRequestStore,
    work_intent_candidate_store: Any | None = None,
    current_context_builder: CurrentContextBuilder,
) -> None:
    """Register context probe lifecycle routes onto *app*."""

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
            limit = int(request.args.get("limit", 100))
        except (TypeError, ValueError):
            limit = 100
        limit = min(max(limit, 1), 100)
        try:
            requests_list = probe_store.list(
                status=status,
                include_terminal=include_terminal,
            )
        except ValueError:
            return jsonify({"error": "invalid_status"}), 400
        requests_list = requests_list[:limit]
        return jsonify({
            "requests": requests_to_dicts(requests_list),
            "debug": [describe_context_probe_request_for_debug(item) for item in requests_list],
            "count": len(requests_list),
        })

    @app.route("/context-probes/requests/<request_id>", methods=["GET"])
    def get_context_probe_request_route(request_id: str):
        """Return one context probe request and its stored redacted result, if any."""
        probe_store.expire_due()
        probe_request = probe_store.get(request_id)
        if probe_request is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify({
            "request": probe_request.to_dict(),
            "debug": describe_context_probe_request_for_debug(probe_request),
            "result": probe_store.get_result(request_id),
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

    @app.route("/context-probes/requests/<request_id>/abort", methods=["POST"])
    def abort_context_probe_request_route(request_id: str):
        """Abort an approved context probe request before execution."""
        data = request.get_json(silent=True) or {}
        probe_request = probe_store.get(request_id)
        if probe_request is None:
            return jsonify({"error": "not_found"}), 404
        try:
            aborted = abort_context_probe_request(
                probe_request,
                decision_reason=data.get("reason"),
            )
        except ValueError as exc:
            return jsonify({"error": "invalid_transition", "message": str(exc)}), 409
        probe_store.update(aborted)
        return jsonify({
            "request": aborted.to_dict(),
            "debug": describe_context_probe_request_for_debug(aborted),
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
            current_context = current_context_builder.build(
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
        probe_store.store_result(executed.request_id, result.to_dict())
        _maybe_create_work_intent_candidate(
            runtime_state=runtime_state,
            candidate_store=work_intent_candidate_store,
            probe_request=executed,
            result=result.to_dict(),
        )
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

    @app.route("/context-probes/requests/<request_id>/result", methods=["POST"])
    def submit_context_probe_result_route(request_id: str):
        """Accept a bounded Swift AX text result for an approved content probe."""
        probe_request = probe_store.get(request_id)
        if probe_request is None:
            return jsonify({"error": "not_found"}), 404

        result = submit_context_probe_result(
            probe_request,
            request.get_json(silent=True) or {},
        )
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
        probe_store.store_result(executed.request_id, result.to_dict())
        _maybe_create_work_intent_candidate(
            runtime_state=runtime_state,
            candidate_store=work_intent_candidate_store,
            probe_request=executed,
            result=result.to_dict(),
        )
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


def _maybe_create_work_intent_candidate(
    *,
    runtime_state: Any,
    candidate_store: Any | None,
    probe_request: Any,
    result: dict[str, Any],
) -> None:
    if candidate_store is None:
        return
    present = runtime_state.get_present()
    candidate_store.maybe_create_from_probe_result(
        probe_request=probe_request,
        result=result,
        project=present.active_project,
        active_work_intent=present.work_intent,
    )
