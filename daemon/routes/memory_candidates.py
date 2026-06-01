from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, request

from daemon.memory.candidates import MemoryCandidateError

log = logging.getLogger(__name__)

_PUBLIC_MEMORY_CANDIDATE_ERRORS = {
    "claim_required",
    "claim_too_long",
    "evidence_required",
    "forbidden_memory_type",
    "invalid_claim",
    "invalid_confidence",
    "invalid_evidence",
    "invalid_evidence_item",
    "invalid_memory_type",
    "invalid_payload",
    "invalid_sensitivity",
    "invalid_status",
    "memory_type_required",
    "sensitive_candidate_refused",
    "sensitive_claim_refused",
    "sensitivity_required",
}


def register_memory_candidate_routes(
    app: Flask,
    *,
    candidate_store: Any,
) -> None:
    """Register the dedicated memory candidates review surface."""

    @app.route("/memory/candidates/manual", methods=["POST"])
    def memory_candidates_manual_create():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _bad_request("invalid_payload")

        error = _manual_candidate_payload_error(data)
        if error:
            return _bad_request(error)

        try:
            candidate = candidate_store.create_manual_candidate(
                memory_type=data["memory_type"],
                claim=data["claim"],
                evidence=data["evidence"],
                sensitivity=data["sensitivity"],
            )
        except MemoryCandidateError as exc:
            return _bad_request(_public_memory_candidate_error(exc))

        return jsonify({
            "ok": True,
            "surface": "memory_candidates",
            "canonical_memory_created": False,
            "llm_injected": False,
            "candidate": candidate,
        })

    @app.route("/memory/candidates", methods=["GET"])
    def memory_candidates_list():
        status = request.args.get("status")
        limit = _query_limit()
        try:
            candidates = candidate_store.list_candidates(status=status, limit=limit)
        except MemoryCandidateError as exc:
            return _bad_request(_public_memory_candidate_error(exc))
        return jsonify({
            "surface": "memory_candidates",
            "canonical_memory": False,
            "count": len(candidates),
            "candidates": candidates,
        })

    @app.route("/memory/candidates/<candidate_id>", methods=["GET"])
    def memory_candidates_get(candidate_id: str):
        candidate = candidate_store.get_candidate(candidate_id)
        if candidate is None:
            return jsonify({"ok": False, "error": "not_found", "surface": "memory_candidates"}), 404
        return jsonify({
            "surface": "memory_candidates",
            "canonical_memory": False,
            "candidate": candidate,
        })

    @app.route("/memory/candidates/<candidate_id>/accept", methods=["POST"])
    def memory_candidates_accept(candidate_id: str):
        candidate = candidate_store.accept(candidate_id, reviewer=_reviewer())
        if candidate is None:
            return jsonify({"ok": False, "error": "not_found", "surface": "memory_candidates"}), 404
        return jsonify({
            "ok": True,
            "surface": "memory_candidates",
            "canonical_memory_created": False,
            "llm_injected": False,
            "candidate": candidate,
        })

    @app.route("/memory/candidates/<candidate_id>/edit", methods=["POST"])
    def memory_candidates_edit(candidate_id: str):
        data = _json_object()
        try:
            candidate = candidate_store.edit(
                candidate_id,
                claim=data.get("claim", ""),
                reviewer=_reviewer(data),
            )
        except MemoryCandidateError as exc:
            return _bad_request(_public_memory_candidate_error(exc))
        if candidate is None:
            return jsonify({"ok": False, "error": "not_found", "surface": "memory_candidates"}), 404
        return jsonify({
            "ok": True,
            "surface": "memory_candidates",
            "canonical_memory_created": False,
            "llm_injected": False,
            "candidate": candidate,
        })

    @app.route("/memory/candidates/<candidate_id>/reject", methods=["POST"])
    def memory_candidates_reject(candidate_id: str):
        data = _json_object()
        candidate = candidate_store.reject(
            candidate_id,
            reviewer=_reviewer(data),
            reason=data.get("reason"),
        )
        if candidate is None:
            return jsonify({"ok": False, "error": "not_found", "surface": "memory_candidates"}), 404
        return jsonify({
            "ok": True,
            "surface": "memory_candidates",
            "canonical_memory_created": False,
            "llm_injected": False,
            "candidate": candidate,
        })

    @app.route("/memory/candidates/<candidate_id>/archive", methods=["POST"])
    def memory_candidates_archive(candidate_id: str):
        candidate = candidate_store.archive(candidate_id, reviewer=_reviewer())
        if candidate is None:
            return jsonify({"ok": False, "error": "not_found", "surface": "memory_candidates"}), 404
        return jsonify({
            "ok": True,
            "surface": "memory_candidates",
            "canonical_memory_created": False,
            "llm_injected": False,
            "candidate": candidate,
        })

    @app.route("/memory/candidates/<candidate_id>", methods=["DELETE"])
    def memory_candidates_delete(candidate_id: str):
        deleted = candidate_store.delete(candidate_id)
        if not deleted:
            return jsonify({"ok": False, "error": "not_found", "surface": "memory_candidates"}), 404
        return jsonify({
            "ok": True,
            "surface": "memory_candidates",
            "deleted": True,
        })


def _bad_request(error: str):
    return jsonify({"ok": False, "error": error, "surface": "memory_candidates"}), 400


def _public_memory_candidate_error(exc: MemoryCandidateError) -> str:
    code = exc.args[0].strip() if exc.args and isinstance(exc.args[0], str) else ""
    if code in _PUBLIC_MEMORY_CANDIDATE_ERRORS:
        return code
    log.exception("Memory candidate request failed")
    return "invalid_request"


def _manual_candidate_payload_error(data: dict[str, Any]) -> str | None:
    if "memory_type" not in data:
        return "memory_type_required"
    if "claim" not in data:
        return "claim_required"
    if not isinstance(data.get("claim"), str):
        return "invalid_claim"
    if not str(data.get("claim") or "").strip():
        return "claim_required"
    if _looks_sensitive_claim(str(data.get("claim") or "")):
        return "sensitive_claim_refused"
    if "evidence" not in data:
        return "evidence_required"
    evidence = data["evidence"]
    if not isinstance(evidence, list):
        return "invalid_evidence"
    if not evidence:
        return "evidence_required"
    if any(not isinstance(item, dict) for item in evidence):
        return "invalid_evidence_item"
    if "sensitivity" not in data:
        return "sensitivity_required"
    if not isinstance(data["sensitivity"], dict):
        return "invalid_sensitivity"
    return None


def _looks_sensitive_claim(claim: str) -> bool:
    lowered = claim.lower()
    sensitive_markers = {
        "api key",
        "apikey",
        "bearer ",
        "credential",
        "mot de passe",
        "password",
        "secret",
        "token",
    }
    return any(marker in lowered for marker in sensitive_markers)


def _json_object() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _query_limit(default: int = 50) -> int:
    try:
        return int(request.args.get("limit", default))
    except (TypeError, ValueError):
        return default


def _reviewer(data: dict[str, Any] | None = None) -> str:
    payload = data if isinstance(data, dict) else _json_object()
    reviewer = str(payload.get("reviewer") or "human").strip()
    return reviewer or "human"
