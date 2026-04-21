"""
test_last_session_context.py — Tests de last_session_context().

La fonction lit projects.md et retourne une ligne de contexte sur
la dernière session connue pour un projet donné.
Le paramètre `today` permet de tester sans mock de datetime.now().
"""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from daemon.memory.extractor import last_session_context, update_memories_from_session
import daemon.memory.extractor as extractor_module


def _write_projects_md(memory_dir: Path, content: str) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "projects.md").write_text(content)


class TestLastSessionContext(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.memory_dir = Path(self.tmpdir.name) / "memory"
        self.today = date(2026, 4, 18)  # date fixe pour tous les tests

    def tearDown(self):
        self.tmpdir.cleanup()

    # ── Cas nominaux ──────────────────────────────────────────────────────────

    def test_retourne_hier_si_session_hier(self):
        yesterday = self.today - timedelta(days=1)
        _write_projects_md(self.memory_dir, f"""# Projets

## Pulse

- Première session : 2026-01-01
- Dernière session : {yesterday.strftime('%Y-%m-%d')} (45 min, coding)
- Type de travail détecté : coding
""")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNotNone(result)
        self.assertIn("hier", result)
        self.assertIn("développement", result)
        self.assertIn("45", result)

    def test_retourne_aujourd_hui_si_session_today(self):
        _write_projects_md(self.memory_dir, f"""# Projets

## Pulse

- Première session : 2026-01-01
- Dernière session : {self.today.strftime('%Y-%m-%d')} (30 min, debug)
- Type de travail détecté : debug
""")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNotNone(result)
        self.assertIn("aujourd'hui", result)
        self.assertIn("débogage", result)

    def test_retourne_il_y_a_n_jours_pour_delta_entre_2_et_6(self):
        three_days_ago = self.today - timedelta(days=3)
        _write_projects_md(self.memory_dir, f"""# Projets

## Pulse

- Première session : 2026-01-01
- Dernière session : {three_days_ago.strftime('%Y-%m-%d')} (20 min, writing)
- Type de travail détecté : writing
""")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNotNone(result)
        self.assertIn("il y a 3 jours", result)
        self.assertIn("rédaction", result)

    def test_retourne_la_semaine_derniere_pour_delta_7_a_13(self):
        eight_days_ago = self.today - timedelta(days=8)
        _write_projects_md(self.memory_dir, f"""# Projets

## Pulse

- Première session : 2026-01-01
- Dernière session : {eight_days_ago.strftime('%Y-%m-%d')} (60 min, coding)
- Type de travail détecté : coding
""")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNotNone(result)
        self.assertIn("la semaine dernière", result)

    def test_retourne_il_y_a_n_semaines_pour_delta_superieur_14(self):
        three_weeks_ago = self.today - timedelta(days=21)
        _write_projects_md(self.memory_dir, f"""# Projets

## Pulse

- Première session : 2026-01-01
- Dernière session : {three_weeks_ago.strftime('%Y-%m-%d')} (15 min, general)
- Type de travail détecté : general
""")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNotNone(result)
        self.assertIn("il y a 3 semaine(s)", result)

    def test_tache_inconnue_passee_telle_quelle(self):
        yesterday = self.today - timedelta(days=1)
        _write_projects_md(self.memory_dir, f"""# Projets

## Pulse

- Première session : 2026-01-01
- Dernière session : {yesterday.strftime('%Y-%m-%d')} (10 min, refactor)
- Type de travail détecté : refactor
""")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNotNone(result)
        self.assertIn("refactor", result)

    def test_browsing_legacy_est_rendu_comme_exploration(self):
        yesterday = self.today - timedelta(days=1)
        _write_projects_md(self.memory_dir, f"""# Projets

## Pulse

- Première session : 2026-01-01
- Dernière session : {yesterday.strftime('%Y-%m-%d')} (25 min, browsing)
- Type de travail détecté : browsing
""")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNotNone(result)
        self.assertIn("exploration", result)

    # ── Robustesse ────────────────────────────────────────────────────────────

    def test_retourne_none_si_projet_inconnu(self):
        _write_projects_md(self.memory_dir, "# Projets\n\n## AutreProjet\n\n- Première session : 2026-01-01\n")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNone(result)

    def test_retourne_none_si_projects_md_absent(self):
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNone(result)

    def test_retourne_none_si_date_future(self):
        future = self.today + timedelta(days=5)
        _write_projects_md(self.memory_dir, f"""# Projets

## Pulse

- Première session : 2026-01-01
- Dernière session : {future.strftime('%Y-%m-%d')} (30 min, coding)
- Type de travail détecté : coding
""")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNone(result)

    def test_retourne_none_si_date_malformee(self):
        _write_projects_md(self.memory_dir, """# Projets

## Pulse

- Première session : 2026-01-01
- Dernière session : pas-une-date (30 min, coding)
- Type de travail détecté : coding
""")
        result = last_session_context("Pulse", memory_dir=self.memory_dir, today=self.today)
        self.assertIsNone(result)

    def test_ne_leve_pas_d_exception_en_cas_d_erreur(self):
        """last_session_context() ne doit jamais lever d'exception."""
        try:
            result = last_session_context(
                "Pulse",
                memory_dir=Path("/chemin/qui/nexiste/pas"),
                today=self.today,
            )
            self.assertIsNone(result)
        except Exception as exc:
            self.fail(f"last_session_context() a levé une exception : {exc}")

    # ── Intégration avec update_memories_from_session ─────────────────────────

    def test_apres_update_memories_last_session_context_retourne_un_resultat(self):
        """
        Après une session réelle écrite par update_memories_from_session,
        last_session_context() doit pouvoir lire les données et retourner
        une ligne de contexte valide.
        """
        extractor_module.reset_cooldown_for_tests()
        extractor_module.reset_fact_engine_for_tests()
        orig_cooldown = extractor_module._COOLDOWN_FILE
        extractor_module._COOLDOWN_FILE = Path(self.tmpdir.name) / "cooldown.json"

        try:
            update_memories_from_session(
                {
                    "active_project": "Pulse",
                    "duration_min": 30,
                    "probable_task": "coding",
                    "recent_apps": ["Cursor"],
                    "files_changed": 3,
                    "top_files": ["main.py"],
                },
                memory_dir=self.memory_dir,
                trigger="screen_lock",
            )
        finally:
            extractor_module._COOLDOWN_FILE = orig_cooldown
            extractor_module.reset_cooldown_for_tests()

        # last_session_context avec today = aujourd'hui (la session vient d'être écrite)
        result = last_session_context(
            "Pulse",
            memory_dir=self.memory_dir,
            today=date.today(),
        )
        self.assertIsNotNone(result)
        self.assertIn("Pulse", result)
        self.assertIn("aujourd'hui", result)


if __name__ == "__main__":
    unittest.main()
