"""
routes/facts.py — Routes API pour le moteur de faits utilisateur.

GET  /facts              — liste des faits actifs
GET  /facts/stats        — statistiques globales
POST /facts/<id>/reinforce  — valider un fait (hausse la confiance)
POST /facts/<id>/contradict — corriger un fait (baisse la confiance)
"""

from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, request


def register_facts_routes(
    app: Flask,
    *,
    get_fact_engine: Callable[[], Any],
) -> None:

    @app.route("/facts")
    def facts_list():
        engine   = get_fact_engine()
        category = request.args.get("category")
        min_conf = float(request.args.get("min_confidence", 0.0))
        archived = request.args.get("archived", "false").lower() == "true"
        limit    = min(int(request.args.get("limit", 20)), 100)

        facts = engine.get_facts(
            category=category,
            min_confidence=min_conf,
            include_archived=archived,
            limit=limit,
        )
        return jsonify({
            "count": len(facts),
            "facts": facts,
        })

    @app.route("/facts/stats")
    def facts_stats():
        engine = get_fact_engine()
        return jsonify(engine.stats())

    @app.route("/facts/profile")
    def facts_profile():
        """Retourne le profil utilisateur formaté tel qu'injecté dans le prompt."""
        engine = get_fact_engine()
        return jsonify({
            "profile": engine.render_for_context(limit=8),
        })

    @app.route("/facts/<fact_id>/reinforce", methods=["POST"])
    def facts_reinforce(fact_id: str):
        engine = get_fact_engine()
        result = engine.reinforce(fact_id)
        return jsonify(result), (200 if result["ok"] else 404)

    @app.route("/facts/<fact_id>/contradict", methods=["POST"])
    def facts_contradict(fact_id: str):
        engine = get_fact_engine()
        result = engine.contradict(fact_id)
        return jsonify(result), (200 if result["ok"] else 404)

    @app.route("/facts/<fact_id>/archive", methods=["POST"])
    def facts_archive(fact_id: str):
        """Archive un fait directement — utile pour corriger des faits erronés."""
        engine = get_fact_engine()
        result = engine.archive(fact_id)
        return jsonify(result), (200 if result["ok"] else 404)
