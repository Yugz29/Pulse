import tempfile
import unittest
from pathlib import Path

from daemon.memory.extractor import load_memory_context, update_memories_from_session


class FakeLLM:

    def complete(self, prompt, max_tokens=200):
        return "Résumé court de la session."


class TestExtractor(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.memory_dir = Path(self.tmpdir.name)

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
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        self.assertIn("Résumé court de la session.", session_files[0].read_text())


if __name__ == "__main__":
    unittest.main()
