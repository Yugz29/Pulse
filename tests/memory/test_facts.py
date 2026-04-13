"""
tests/memory/test_facts.py — Tests du moteur de faits utilisateur.

Couvre :
  - Pipeline observation → signal → fait (déterministe)
  - Renforcement et contradiction d'un fait
  - Decay temporel
  - Export Markdown
  - render_for_context()
  - _extract_observations() : cas nominaux et cas limites
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from daemon.memory.facts import (
    FACT_THRESHOLD,
    SIGNAL_THRESHOLD,
    FactEngine,
    _extract_observations,
    _time_slot,
)


def _make_session(
    task: str = "coding",
    focus: str = "normal",
    duration: int = 45,
    friction: float = 0.0,
    apps: list | None = None,
    project: str = "Pulse",
    hour: int | None = None,
) -> dict:
    """Construit un session_data minimal pour les tests."""
    return {
        "probable_task":  task,
        "focus_level":    focus,
        "duration_min":   duration,
        "max_friction":   friction,
        "recent_apps":    apps or ["Xcode", "Claude", "Safari"],
        "active_project": project,
    }


class TestExtractObservations(unittest.TestCase):
    """Tests unitaires sur _extract_observations — pas de DB."""

    def test_coding_session_produces_workflow_obs(self):
        obs = _extract_observations(_make_session(task="coding"))
        keys = [o[0] for o in obs]
        self.assertTrue(any("task:coding" in k for k in keys))

    def test_general_task_skipped(self):
        obs = _extract_observations(_make_session(task="general"))
        keys = [o[0] for o in obs]
        self.assertFalse(any("task:general" in k for k in keys))

    def test_deep_focus_produces_cognitive_obs(self):
        obs = _extract_observations(_make_session(focus="deep"))
        cats = [o[1] for o in obs]
        self.assertIn("cognitive", cats)

    def test_long_session_produces_obs(self):
        obs = _extract_observations(_make_session(duration=90))
        keys = [o[0] for o in obs]
        self.assertTrue(any("session:long" in k for k in keys))

    def test_short_session_no_long_obs(self):
        obs = _extract_observations(_make_session(duration=30))
        keys = [o[0] for o in obs]
        self.assertFalse(any("session:long" in k for k in keys))

    def test_high_friction_produces_obs(self):
        obs = _extract_observations(_make_session(friction=0.8, project="Pulse"))
        keys = [o[0] for o in obs]
        self.assertTrue(any("friction:high" in k for k in keys))

    def test_low_friction_no_obs(self):
        obs = _extract_observations(_make_session(friction=0.3))
        keys = [o[0] for o in obs]
        self.assertFalse(any("friction:high" in k for k in keys))

    def test_app_pairs_generated(self):
        obs = _extract_observations(_make_session(apps=["Xcode", "Claude", "Safari"]))
        keys = [o[0] for o in obs]
        pair_keys = [k for k in keys if "apps:pair" in k]
        # 3 apps → 3 paires max
        self.assertGreaterEqual(len(pair_keys), 1)

    def test_no_duplicate_keys_from_single_session(self):
        obs = _extract_observations(_make_session())
        keys = [o[0] for o in obs]
        self.assertEqual(len(keys), len(set(keys)))


class TestFactEnginePromotion(unittest.TestCase):
    """Tests d'intégration du pipeline observation → fait."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "facts.db"
        md_path = Path(self.tmp.name) / "facts.md"
        self.engine = FactEngine(db_path=db_path, md_path=md_path)
        self.session = _make_session(task="coding", focus="deep")

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_observation_no_fact(self):
        self.engine.observe_session(self.session)
        facts = self.engine.get_facts()
        self.assertEqual(len(facts), 0)

    def test_promotion_after_threshold(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(self.session)
        facts = self.engine.get_facts()
        self.assertGreater(len(facts), 0)

    def test_promoted_fact_has_correct_category(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(self.session)
        facts = self.engine.get_facts()
        categories = {f["category"] for f in facts}
        # coding + deep focus → workflow et/ou cognitive
        self.assertTrue(categories & {"workflow", "cognitive"})

    def test_promoted_fact_initial_confidence(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(self.session)
        facts = self.engine.get_facts()
        for f in facts:
            self.assertAlmostEqual(f["confidence"], 0.5, delta=0.1)

    def test_repeated_observation_increases_confidence(self):
        # D'abord promotion
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(self.session)
        facts_after_promo = self.engine.get_facts()
        conf_after_promo = facts_after_promo[0]["confidence"]

        # Puis observations supplémentaires
        for _ in range(5):
            self.engine.observe_session(self.session)
        facts_after_more = self.engine.get_facts()
        conf_after_more = facts_after_more[0]["confidence"]

        self.assertGreater(conf_after_more, conf_after_promo)

    def test_no_duplicate_fact_for_same_key(self):
        for _ in range(FACT_THRESHOLD * 2):
            self.engine.observe_session(self.session)
        facts = self.engine.get_facts()
        keys = [f["key"] for f in facts]
        self.assertEqual(len(keys), len(set(keys)))


class TestFactEngineReinforceContradict(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = FactEngine(
            db_path=Path(self.tmp.name) / "facts.db",
            md_path=Path(self.tmp.name) / "facts.md",
        )
        session = _make_session(task="coding", focus="deep")
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(session)
        self.fact_id = self.engine.get_facts()[0]["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_reinforce_increases_confidence(self):
        before = self.engine.get_facts()[0]["confidence"]
        self.engine.reinforce(self.fact_id)
        after = self.engine.get_facts()[0]["confidence"]
        self.assertGreater(after, before)

    def test_contradict_decreases_confidence(self):
        before = self.engine.get_facts()[0]["confidence"]
        self.engine.contradict(self.fact_id)
        after_facts = self.engine.get_facts(include_archived=True)
        fact = next(f for f in after_facts if f["id"] == self.fact_id)
        self.assertLess(fact["confidence"], before)

    def test_contradict_unknown_id_returns_error(self):
        result = self.engine.contradict("nonexistent-id")
        self.assertFalse(result["ok"])

    def test_reinforce_unknown_id_returns_error(self):
        result = self.engine.reinforce("nonexistent-id")
        self.assertFalse(result["ok"])

    def test_heavy_contradiction_archives_fact(self):
        # Contredire suffisamment pour tomber sous ARCHIVE_THRESHOLD
        for _ in range(20):
            self.engine.contradict(self.fact_id)
        facts_active = self.engine.get_facts(include_archived=False)
        ids_active = [f["id"] for f in facts_active]
        self.assertNotIn(self.fact_id, ids_active)

    def test_autonomy_level_increases_after_5_reinforcements(self):
        initial_level = self.engine.get_facts()[0]["autonomy_level"]
        for _ in range(5):
            self.engine.reinforce(self.fact_id)
        after_level = self.engine.get_facts()[0]["autonomy_level"]
        self.assertGreater(after_level, initial_level)


class TestFactEngineDecay(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "facts.db"
        self.engine = FactEngine(
            db_path=self.db_path,
            md_path=Path(self.tmp.name) / "facts.md",
        )
        session = _make_session(task="coding")
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(session)

    def tearDown(self):
        self.tmp.cleanup()

    def test_decay_on_stale_fact(self):
        facts = self.engine.get_facts()
        self.assertGreater(len(facts), 0)
        fact_id = facts[0]["id"]
        conf_before = facts[0]["confidence"]

        # Forcer last_seen dans le passé (10 jours) sur ce fait spécifique
        import sqlite3
        stale_date = (datetime.now() - timedelta(days=10)).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE facts SET last_seen = ? WHERE id = ?",
                (stale_date, fact_id),
            )
            conn.commit()

        decayed = self.engine.decay_all()
        self.assertGreater(decayed, 0)

        # Chercher le fait par son ID, pas par position (d'autres faits peuvent
        # avoir la même confidence et changer l'ordre de tri)
        all_facts = self.engine.get_facts(include_archived=True)
        updated = next((f for f in all_facts if f["id"] == fact_id), None)
        self.assertIsNotNone(updated, "Le fait devrait toujours exister après decay")
        self.assertLess(updated["confidence"], conf_before)

    def test_decay_does_not_affect_recent_facts(self):
        facts = self.engine.get_facts()
        conf_before = facts[0]["confidence"]
        decayed = self.engine.decay_all()
        # Aucun decay car last_seen est récent
        self.assertEqual(decayed, 0)
        conf_after = self.engine.get_facts()[0]["confidence"]
        self.assertEqual(conf_after, conf_before)


class TestFactEngineRender(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = FactEngine(
            db_path=Path(self.tmp.name) / "facts.db",
            md_path=Path(self.tmp.name) / "facts.md",
        )
        session = _make_session(task="coding", focus="deep")
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(session)

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_not_empty_when_facts_exist(self):
        output = self.engine.render_for_context()
        self.assertIn("Profil utilisateur", output)

    def test_render_empty_when_no_facts(self):
        engine = FactEngine(
            db_path=Path(self.tmp.name) / "empty.db",
            md_path=Path(self.tmp.name) / "empty.md",
        )
        self.assertEqual(engine.render_for_context(), "")

    def test_markdown_export_creates_file(self):
        md_path = Path(self.tmp.name) / "facts.md"
        self.assertTrue(md_path.exists())
        content = md_path.read_text()
        self.assertIn("Faits utilisateur Pulse", content)

    def test_stats_returns_correct_counts(self):
        stats = self.engine.stats()
        self.assertGreater(stats["observations"], 0)
        self.assertGreater(stats["active_facts"], 0)
        self.assertEqual(stats["archived_facts"], 0)


class TestTimeSlot(unittest.TestCase):

    def test_morning(self):
        self.assertEqual(_time_slot(8), "matin")

    def test_afternoon(self):
        self.assertEqual(_time_slot(15), "après-midi")

    def test_evening(self):
        self.assertEqual(_time_slot(21), "soir")

    def test_midnight(self):
        self.assertEqual(_time_slot(0), "soir")

    def test_noon_is_afternoon(self):
        self.assertEqual(_time_slot(12), "après-midi")


if __name__ == "__main__":
    unittest.main()
