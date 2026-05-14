from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from daemon.core.work_intent_candidate import WorkIntentCandidateStore, candidates_to_dicts


def register_work_intent_routes(
    app: Flask,
    *,
    runtime_state: Any,
    candidate_store: WorkIntentCandidateStore,
) -> None:
    @app.route("/work-intent/candidates")
    def list_work_intent_candidates():
        candidates = candidate_store.list()
        return jsonify({
            "candidates": candidates_to_dicts(candidates),
            "count": len(candidates),
        })

    @app.route("/work-intent/candidates/<candidate_id>/accept", methods=["POST"])
    def accept_work_intent_candidate(candidate_id: str):
        try:
            candidate = candidate_store.accept(candidate_id)
        except KeyError:
            return jsonify({"error": "not_found"}), 404
        except ValueError as exc:
            return jsonify({"error": "invalid_transition", "message": str(exc)}), 409
        runtime_state.set_work_intent(candidate.to_work_intent())
        return jsonify({
            "candidate": candidate.to_dict(),
            "work_intent": candidate.to_work_intent().to_dict(),
        })

    @app.route("/work-intent/candidates/<candidate_id>/refuse", methods=["POST"])
    def refuse_work_intent_candidate(candidate_id: str):
        try:
            candidate = candidate_store.refuse(candidate_id)
        except KeyError:
            return jsonify({"error": "not_found"}), 404
        except ValueError as exc:
            return jsonify({"error": "invalid_transition", "message": str(exc)}), 409
        return jsonify({"candidate": candidate.to_dict()})
