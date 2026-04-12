import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta

from daemon.memory.extractor import load_memory_context, update_memories_from_session
import daemon.memory.extractor as extractor_module


class FakeLLM:

    def complete(self, prompt, max_tokens=200):
        return "Résumé court de la session."


class FailingLLM:

    def complete(self, prompt, max_tokens=200):
        raise RuntimeError("offline")


class TestExtractor(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.memory_dir = Path(self.tmpdir.name)
        # Réinitialise le curseur entre chaque test
        extractor_module._last_report_at.clear()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_update_memories_cree_projects_habits_et_index(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 25,
                "probable_task": "coding",
                "recent_apps": ["Cursor", "Terminal"],
                "files_changed": 3,
                "max_friction": 0.4,
            },
            memory_dir=self.memory_dir,
        )

        projects = (self.memory_dir / "projects.md").read_text()
        habits = (self.memory_dir / "habits.md").read_text()
        index = (self.memory_dir / "MEMORY.md").read_text()

        self.assertIn("## Pulse", projects)
        self.assertIn("Type de travail détecté : coding", projects)
        self.assertIn("Session", habits)
        self.assertIn("[projects](projects.md)", index)
        self.assertIn("[habits](habits.md)", index)

    def test_update_projects_met_a_jour_un_projet_existant(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 12,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
            },
            memory_dir=self.memory_dir,
        )
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 40,
                "probable_task": "debug",
                "recent_apps": ["Terminal"],
            },
            memory_dir=self.memory_dir,
        )

        projects = (self.memory_dir / "projects.md").read_text()

        self.assertEqual(projects.count("## Pulse"), 1)
        self.assertIn("Type de travail détecté : debug", projects)
        self.assertIn("(40 min, debug)", projects)

    def test_load_memory_context_concatene_les_fichiers(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 18,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
            },
            memory_dir=self.memory_dir,
        )
        (self.memory_dir / "preferences.md").write_text("# Préférences\n\n- Réponses courtes\n")
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 19,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
            },
            memory_dir=self.memory_dir,
        )

        context = load_memory_context(memory_dir=self.memory_dir)

        self.assertIn("# Index mémoire Pulse", context)
        self.assertIn("# Projets", context)
        self.assertIn("# Habitudes", context)
        self.assertIn("# Préférences", context)

    def test_resume_llm_ecrit_une_session_si_duree_suffisante(self):
        # trigger='commit' pour que le LLM soit effectivement appelé
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 45,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 5,
                "max_friction": 0.7,
            },
            llm=FakeLLM(),
            memory_dir=self.memory_dir,
            trigger="commit",
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        self.assertIn("Résumé court de la session.", session_files[0].read_text())

    def test_llm_desactive_pour_screen_lock(self):
        """Le LLM ne doit PAS être appelé pour screen_lock — fallback déterministe uniquement."""
        call_count = {"n": 0}

        class CountingLLM:
            def complete(self, prompt, max_tokens=200):
                call_count["n"] += 1
                return "Ne devrait pas apparaître."

        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 45,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 3,
                "max_friction": 0.2,
            },
            llm=CountingLLM(),
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        self.assertEqual(call_count["n"], 0, "LLM ne doit pas être appelé pour screen_lock")
        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        # Le rapport déterministe doit quand même exister
        self.assertIn("45 min", session_files[0].read_text())

    def test_curseur_empeche_doublon_dans_cooldown(self):
        """Deux appels en moins de REPORT_COOLDOWN_MIN ne produisent qu'un seul rapport."""
        session = {
            "active_project": "Pulse",
            "duration_min": 30,
            "probable_task": "coding",
            "recent_apps": ["Xcode"],
            "files_changed": 5,
            "max_friction": 0.3,
        }
        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")
        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1, "Le curseur doit bloquer le deuxième rapport")

    def test_commit_ignore_le_cooldown(self):
        """Un trigger commit bypasse toujours le cooldown."""
        session = {
            "active_project": "Pulse",
            "duration_min": 30,
            "probable_task": "coding",
            "recent_apps": ["Xcode"],
            "files_changed": 5,
            "max_friction": 0.3,
        }
        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")
        update_memories_from_session(
            session, memory_dir=self.memory_dir,
            trigger="commit", commit_message="fix: correction critique"
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 2, "Le commit doit bypasser le cooldown")

    def test_curseur_expire_apres_cooldown(self):
        """Après REPORT_COOLDOWN_MIN, un nouveau rapport peut être généré."""
        session = {
            "active_project": "Pulse",
            "duration_min": 30,
            "probable_task": "coding",
            "recent_apps": ["Xcode"],
            "files_changed": 5,
            "max_friction": 0.3,
        }
        # Simule un curseur vieux de 31 minutes
        past = datetime.now() - timedelta(minutes=31)
        extractor_module._last_report_at["Pulse"] = past

        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1, "Le curseur expiré doit autoriser un nouveau rapport")

    def test_habits_najoute_pas_de_doublon_consecutif(self):
        session = {
            "active_project": "Pulse",
            "duration_min": 25,
            "probable_task": "coding",
            "recent_apps": ["Cursor", "Terminal"],
        }

        update_memories_from_session(session, memory_dir=self.memory_dir)
        update_memories_from_session(session, memory_dir=self.memory_dir)

        habits_lines = [
            line.strip()
            for line in (self.memory_dir / "habits.md").read_text().splitlines()
            if line.strip().startswith("- ")
        ]

        self.assertEqual(len(habits_lines), 1)

    def test_resume_llm_ecrit_un_fallback_si_ollama_echoue(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 45,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 5,
                "max_friction": 0.7,
            },
            llm=FailingLLM(),
            memory_dir=self.memory_dir,
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        content = session_files[0].read_text()

        # Vérifie les invariants stables plutôt que la phrase exacte
        # (_deterministic_summary() peut évoluer en formulation)
        self.assertIn("45 min", content)
        self.assertIn("Pulse", content)
        self.assertIn("5 fichier", content)


if __name__ == "__main__":
    unittest.main()
