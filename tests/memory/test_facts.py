"""
test_facts.py — Tests du FactEngine (c2t3).

Couvre :
  - observe_session() : promotion à FACT_THRESHOLD
  - reinforce() : augmentation de confiance
  - contradict() : réduction + archivage si sous ARCHIVE_THRESHOLD
  - decay_all() : decay temporel + archivage automatique
  - render_for_context() : format pour le system prompt
  - stats() : compteurs cohérents
"""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from daemon.memory.facts import (
    ARCHIVE_THRESHOLD,
    CONFIDENCE_CONFIRM,
    CONFIDENCE_INIT,
    CONFIDENCE_MAX,
    FACT_THRESHOLD,
    FactEngine,
)


def _make_engine(tmp: Path) -> FactEngine:
    return FactEngine(
        db_path=tmp / "facts.db",
        md_path=tmp / "facts.md",
    )


def _session(task="coding", focus="normal", duration=30, friction=0.0, apps=None):
    return {
        "probable_task": task,
        "focus_level": focus,
        "duration_min": duration,
        "max_friction": friction,
        "recent_apps": apps or [],
        "active_project": "Pulse",
    }


class TestFactEnginePromotion(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(Path(self.tmpdir.name))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_observation_sous_threshold_ne_cree_pas_de_fait(self):
        for _ in range(FACT_THRESHOLD - 1):
            new_facts = self.engine.observe_session(_session())
            self.assertEqual(new_facts, [])

        stats = self.engine.stats()
        self.assertEqual(stats["active_facts"], 0)

    def test_observation_au_threshold_cree_un_fait(self):
        new_facts = []
        for _ in range(FACT_THRESHOLD):
            new_facts = self.engine.observe_session(_session())

        self.assertGreater(len(new_facts), 0)
        stats = self.engine.stats()
        self.assertGreater(stats["active_facts"], 0)

    def test_fait_cree_avec_confiance_initiale(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(_session())

        facts = self.engine.get_facts()
        self.assertTrue(all(f["confidence"] == CONFIDENCE_INIT for f in facts))

    def test_observation_supplementaire_renforce_le_fait(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(_session())

        conf_before = self.engine.get_facts()[0]["confidence"]

        self.engine.observe_session(_session())
        conf_after = self.engine.get_facts()[0]["confidence"]

        self.assertGreater(conf_after, conf_before)

    def test_confiance_ne_depasse_pas_confidence_max(self):
        for _ in range(FACT_THRESHOLD + 50):
            self.engine.observe_session(_session())

        facts = self.engine.get_facts()
        self.assertTrue(all(f["confidence"] <= CONFIDENCE_MAX for f in facts))

    def test_meme_key_ne_cree_pas_deux_faits(self):
        for _ in range(FACT_THRESHOLD * 2):
            self.engine.observe_session(_session())

        # Une même session génère une même key — un seul fait par key
        facts = self.engine.get_facts()
        keys = [f["key"] for f in facts]
        self.assertEqual(len(keys), len(set(keys)))

    def test_categorie_workflow_cree_des_faits_workflow(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(_session(task="coding"))

        facts = self.engine.get_facts(category="workflow")
        self.assertGreater(len(facts), 0)
        self.assertTrue(all(f["category"] == "workflow" for f in facts))

    def test_focus_deep_cree_faits_cognitive(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(_session(focus="deep"))

        facts = self.engine.get_facts(category="cognitive")
        self.assertGreater(len(facts), 0)


class TestFactEngineReinforceContradict(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(Path(self.tmpdir.name))
        # Crée un fait consolidé
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(_session())
        self.fact_id = self.engine.get_facts()[0]["id"]

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_reinforce_augmente_la_confiance(self):
        conf_before = self.engine.get_facts()[0]["confidence"]
        result = self.engine.reinforce(self.fact_id)

        self.assertTrue(result["ok"])
        self.assertAlmostEqual(
            result["confidence"],
            min(conf_before + CONFIDENCE_CONFIRM, CONFIDENCE_MAX),
            places=5,
        )

    def test_contradict_reduit_la_confiance(self):
        conf_before = self.engine.get_facts()[0]["confidence"]
        result = self.engine.contradict(self.fact_id)

        self.assertTrue(result["ok"])
        self.assertLess(result["confidence"], conf_before)

    def test_contradict_archive_si_confiance_sous_seuil(self):
        # On contredit suffisamment pour passer sous ARCHIVE_THRESHOLD
        result = None
        for _ in range(20):
            result = self.engine.contradict(self.fact_id)
            if result.get("archived"):
                break

        self.assertTrue(result["archived"])
        # Le fait est archivé — plus visible dans get_facts()
        facts = self.engine.get_facts()
        self.assertFalse(any(f["id"] == self.fact_id for f in facts))

    def test_reinforce_inconnu_retourne_erreur(self):
        result = self.engine.reinforce("id-qui-nexiste-pas")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_archive_directement(self):
        result = self.engine.archive(self.fact_id)
        self.assertTrue(result["ok"])
        self.assertTrue(result["archived"])

        facts = self.engine.get_facts()
        self.assertFalse(any(f["id"] == self.fact_id for f in facts))

        # Visible avec include_archived=True
        all_facts = self.engine.get_facts(include_archived=True)
        self.assertTrue(any(f["id"] == self.fact_id for f in all_facts))


class TestFactEngineDecay(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(Path(self.tmpdir.name))
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(_session())

    def tearDown(self):
        self.tmpdir.cleanup()

    def _set_last_seen_old(self, days: int) -> None:
        """Rétrodate last_seen pour simuler un fait inactif."""
        old_date = (datetime.now() - timedelta(days=days)).isoformat()
        with self.engine._connect() as conn:
            conn.execute("UPDATE facts SET last_seen = ?", (old_date,))
            conn.commit()

    def test_decay_ne_touche_pas_les_faits_recents(self):
        conf_before = self.engine.get_facts()[0]["confidence"]
        decayed = self.engine.decay_all()
        conf_after = self.engine.get_facts()[0]["confidence"]

        self.assertEqual(decayed, 0)
        self.assertEqual(conf_before, conf_after)

    def test_decay_reduit_confiance_apres_decay_start_days(self):
        self._set_last_seen_old(days=5)
        conf_before = self.engine.get_facts()[0]["confidence"]

        decayed = self.engine.decay_all()

        self.assertGreater(decayed, 0)
        conf_after = self.engine.get_facts()[0]["confidence"]
        self.assertLess(conf_after, conf_before)

    def test_decay_archive_si_confiance_sous_seuil(self):
        # Fait déjà proche du seuil d'archivage
        fact_id = self.engine.get_facts()[0]["id"]
        with self.engine._connect() as conn:
            conn.execute(
                "UPDATE facts SET confidence = ? WHERE id = ?",
                (ARCHIVE_THRESHOLD + 0.01, fact_id),
            )
            conn.commit()

        self._set_last_seen_old(days=10)
        self.engine.decay_all()

        facts = self.engine.get_facts()
        self.assertFalse(any(f["id"] == fact_id for f in facts))


class TestFactEngineRender(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(Path(self.tmpdir.name))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_render_vide_si_pas_de_faits(self):
        result = self.engine.render_for_context()
        self.assertEqual(result, "")

    def test_render_contient_header_et_faits(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(_session(task="coding"))

        result = self.engine.render_for_context()
        self.assertIn("── Profil utilisateur ──", result)
        self.assertIn("conf ", result)

    def test_render_exclut_faits_sous_seuil_confiance(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(_session(task="coding"))

        fact_id = self.engine.get_facts()[0]["id"]
        # Baisse la confiance sous 0.5
        with self.engine._connect() as conn:
            conn.execute("UPDATE facts SET confidence = 0.3 WHERE id = ?", (fact_id,))
            conn.commit()

        result = self.engine.render_for_context()
        # Pas de faits au-dessus du seuil → vide
        self.assertEqual(result, "")

    def test_stats_coherentes(self):
        for _ in range(FACT_THRESHOLD):
            self.engine.observe_session(_session(task="coding", focus="deep"))

        stats = self.engine.stats()
        self.assertGreater(stats["active_facts"], 0)
        self.assertGreater(stats["observations"], 0)
        self.assertEqual(stats["archived_facts"], 0)
        self.assertIn("workflow", stats["by_category"])

# ── loginwindow : filtre processus système ─────────────────────────────────────

    def test_loginwindow_absent_des_paires_dapps(self):
        """loginwindow dans recent_apps ne doit générer aucune paire."""
        session = _session(task="coding", focus="normal", apps=["Claude", "loginwindow", "Code"])
        from daemon.memory.facts import _extract_observations
        obs = _extract_observations(session)
        keys = [o[0] for o in obs]
        self.assertFalse(any("loginwindow" in k for k in keys),
            "loginwindow ne doit pas apparaitre dans les clés d'observation")

    def test_loginwindow_ne_prend_pas_un_slot_dans_le_top4(self):
        """Avec 5 apps dont loginwindow, les 4 vraies apps sont retenues pour les paires."""
        session = _session(task="coding", focus="normal",
                        apps=["Claude", "loginwindow", "Code", "Safari", "Xcode"])
        from daemon.memory.facts import _extract_observations
        obs = _extract_observations(session)
        pairs = [o for o in obs if o[0].startswith("apps:pair:")]
        pair_keys = " ".join(o[0] for o in pairs)
        self.assertNotIn("loginwindow", pair_keys)
        # Claude, Code, Safari, Xcode → 6 paires attendues
        self.assertEqual(len(pairs), 6)

    def test_liste_sans_processus_systeme_reste_inchangee(self):
        """Avec des apps normales, le filtre ne change rien."""
        session = _session(task="coding", focus="normal",
                        apps=["Claude", "Code", "Safari", "Xcode"])
        from daemon.memory.facts import _extract_observations
        obs = _extract_observations(session)
        pairs = [o for o in obs if o[0].startswith("apps:pair:")]
        self.assertEqual(len(pairs), 6)


if __name__ == "__main__":
    unittest.main()
