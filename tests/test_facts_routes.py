"""
tests/test_facts_routes.py — Tests des routes API /facts.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from daemon.memory.facts import FactEngine, FACT_THRESHOLD
from daemon.routes.facts import register_facts_routes


def _make_app(engine: FactEngine) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_facts_routes(app, get_fact_engine=lambda: engine)
    return app


def _make_engine() -> tuple[FactEngine, Path]:
    tmp = tempfile.mkdtemp()
    engine = FactEngine(
        db_path=Path(tmp) / "facts.db",
        md_path=Path(tmp) / "facts.md",
    )
    return engine, Path(tmp)


def _promote_facts(engine: FactEngine) -> None:
    """Fait remonter des faits au-dessus du seuil de promotion."""
    session = {
        "probable_task": "coding",
        "focus_level": "deep",
        "duration_min": 60,
        "max_friction": 0.0,
        "recent_apps": ["Xcode", "Claude"],
        "active_project": "Pulse",
    }
    for _ in range(FACT_THRESHOLD):
        engine.observe_session(session)


class TestFactsRoutes(unittest.TestCase):

    def setUp(self):
        self.engine, self.tmp = _make_engine()
        self.app = _make_app(self.engine)
        self.client = self.app.test_client()

    def test_get_facts_vide(self):
        resp = self.client.get("/facts")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["facts"], [])

    def test_get_facts_apres_promotion(self):
        _promote_facts(self.engine)
        resp = self.client.get("/facts")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertGreater(data["count"], 0)

    def test_get_facts_filtre_category(self):
        _promote_facts(self.engine)
        resp = self.client.get("/facts?category=workflow")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        for fact in data["facts"]:
            self.assertEqual(fact["category"], "workflow")

    def test_get_facts_filtre_min_confidence(self):
        _promote_facts(self.engine)
        resp = self.client.get("/facts?min_confidence=0.9")
        data = resp.get_json()
        for fact in data["facts"]:
            self.assertGreaterEqual(fact["confidence"], 0.9)

    def test_stats(self):
        _promote_facts(self.engine)
        resp = self.client.get("/facts/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("active_facts", data)
        self.assertIn("observations", data)
        self.assertGreater(data["active_facts"], 0)

    def test_profile(self):
        _promote_facts(self.engine)
        resp = self.client.get("/facts/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("profile", data)
        self.assertIsInstance(data["profile"], str)

    def test_reinforce(self):
        _promote_facts(self.engine)
        fact_id = self.engine.get_facts()[0]["id"]
        conf_before = self.engine.get_facts()[0]["confidence"]

        resp = self.client.post(f"/facts/{fact_id}/reinforce")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertGreater(data["confidence"], conf_before)

    def test_contradict(self):
        _promote_facts(self.engine)
        fact_id = self.engine.get_facts()[0]["id"]
        conf_before = self.engine.get_facts()[0]["confidence"]

        resp = self.client.post(f"/facts/{fact_id}/contradict")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertLess(data["confidence"], conf_before)

    def test_reinforce_id_inconnu(self):
        resp = self.client.post("/facts/inexistant/reinforce")
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertFalse(data["ok"])

    def test_stats_observations_somme_faits(self):
        """stats() doit retourner la somme des observations des faits, pas le COUNT des lignes brutes."""
        _promote_facts(self.engine)
        stats = self.engine.stats()
        facts = self.engine.get_facts()
        expected = sum(f["observations"] for f in facts)
        self.assertEqual(stats["observations"], expected)
        self.assertGreater(stats["observations"], stats["active_facts"])

    def test_archive_direct(self):
        _promote_facts(self.engine)
        fact_id = self.engine.get_facts()[0]["id"]
        result = self.engine.archive(fact_id)
        self.assertTrue(result["ok"])
        ids_actifs = [f["id"] for f in self.engine.get_facts()]
        self.assertNotIn(fact_id, ids_actifs)

    def test_archive_route(self):
        _promote_facts(self.engine)
        fact_id = self.engine.get_facts()[0]["id"]
        resp = self.client.post(f"/facts/{fact_id}/archive")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_archive_id_inconnu(self):
        resp = self.client.post("/facts/inexistant/archive")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
