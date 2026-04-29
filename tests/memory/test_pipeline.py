"""
test_pipeline.py — Test d'intégration du pipeline mémoire Pulse.

Vérifie le flux complet :
  SessionMemory.record_event()
    → export_session_data()
      → update_memories_from_session()
        → journal + projects.md

Pas de mock sur les modules mémoire — on teste les vraies interactions.
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import daemon.memory.extractor as extractor_module
from daemon.core.event_bus import Event
from daemon.memory.session import SessionMemory
from daemon.memory.extractor import update_memories_from_session, reset_cooldown_for_tests


class TestMemoryPipeline(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self.tmpdir.name)
        self.memory_dir = tmp / "memory"
        self.memory_dir.mkdir()
        self.db_path = str(tmp / "session.db")

        reset_cooldown_for_tests()
        extractor_module.reset_fact_engine_for_tests()

        # Redirige le cooldown vers un fichier temporaire isolé
        self._orig_cooldown = extractor_module._COOLDOWN_FILE
        extractor_module._COOLDOWN_FILE = tmp / "cooldown.json"

    def tearDown(self):
        extractor_module._COOLDOWN_FILE = self._orig_cooldown
        extractor_module.reset_fact_engine_for_tests()
        reset_cooldown_for_tests()
        self.tmpdir.cleanup()

    def _make_session(self) -> SessionMemory:
        return SessionMemory(db_path=self.db_path)

    # ── SessionMemory ─────────────────────────────────────────────────────────

    def test_record_event_persiste_dans_sqlite(self):
        session = self._make_session()
        event = Event("file_modified", {"path": "/Users/yugz/Projets/Pulse/daemon/main.py"})
        session.record_event(event)

        events = session.get_recent_events(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "file_modified")
        self.assertEqual(events[0]["payload"]["path"], "/Users/yugz/Projets/Pulse/daemon/main.py")

    def test_export_session_data_top_files_reflect_most_edited(self):
        session = self._make_session()

        # main.py touché 3 fois, cognitive.py 1 fois
        for _ in range(3):
            session.record_event(Event("file_modified", {"path": "/proj/daemon/main.py"}))
        session.record_event(Event("file_modified", {"path": "/proj/daemon/cognitive.py"}))

        data = session.export_session_data()

        self.assertIn("main.py", data["top_files"])
        self.assertIn("cognitive.py", data["top_files"])
        # main.py doit être premier (plus touché)
        self.assertEqual(data["top_files"][0], "main.py")
        self.assertEqual(data["files_changed"], 2)  # 2 paths distincts

    def test_export_session_data_recent_apps_dedupliques(self):
        session = self._make_session()
        session.record_event(Event("app_activated", {"app_name": "Xcode"}))
        session.record_event(Event("app_activated", {"app_name": "Terminal"}))
        session.record_event(Event("app_activated", {"app_name": "Xcode"}))  # doublon

        data = session.export_session_data()

        # Xcode apparaît une seule fois malgré 2 events
        apps = data["recent_apps"]
        self.assertEqual(apps.count("Xcode"), 1)
        self.assertIn("Terminal", apps)

    def test_export_session_data_contient_tous_les_champs_extractor(self):
        session = self._make_session()
        data = session.export_session_data()

        required_fields = [
            "session_id", "active_project", "active_file",
            "probable_task", "focus_level", "duration_min",
            "recent_apps", "files_changed", "top_files",
            "event_count", "max_friction",
        ]
        for field in required_fields:
            self.assertIn(field, data, f"Champ manquant : {field!r}")

    # ── Pipeline complet ──────────────────────────────────────────────────────

    def test_pipeline_session_vers_journal(self):
        """record_event → export → update_memories écrit le journal."""
        session = self._make_session()

        for _ in range(5):
            session.record_event(Event("file_modified", {
                "path": "/Users/yugz/Projets/Pulse/daemon/main.py"
            }))
        session.record_event(Event("app_activated", {"app_name": "Cursor"}))

        data = session.export_session_data()
        data["duration_min"] = 20
        data["active_project"] = "Pulse"
        data["probable_task"] = "coding"

        update_memories_from_session(data, memory_dir=self.memory_dir, trigger="screen_lock")

        # projects.md créé
        projects = (self.memory_dir / "projects.md").read_text()
        self.assertIn("## Pulse", projects)
        self.assertIn("coding", projects)

        # Journal créé dans sessions/
        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        content = session_files[0].read_text()
        self.assertIn("# Journal Pulse —", content)
        self.assertIn("## Pulse", content)
        self.assertIn("### ", content)
        self.assertIn("développement (20 min)", content)

    def test_pipeline_top_files_dans_journal(self):
        """Les fichiers les plus édités apparaissent dans le résumé de session."""
        session = self._make_session()

        for _ in range(4):
            session.record_event(Event("file_modified", {
                "path": "/proj/daemon/cognitive.py"
            }))
        session.record_event(Event("file_modified", {
            "path": "/proj/daemon/main.py"
        }))

        data = session.export_session_data()
        data["duration_min"] = 25
        data["active_project"] = "Pulse"
        data["probable_task"] = "coding"

        update_memories_from_session(data, memory_dir=self.memory_dir, trigger="screen_lock")

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        content = session_files[0].read_text()
        # cognitive.py est le plus touché — doit apparaître dans la portée
        self.assertIn("cognitive.py", content)

    def test_pipeline_commit_trigger_bypass_cooldown(self):
        """Un commit écrit un rapport même si le cooldown est actif."""
        session = self._make_session()
        data = {
            "active_project": "Pulse",
            "duration_min": 30,
            "probable_task": "coding",
            "recent_apps": ["Xcode"],
            "files_changed": 3,
            "top_files": ["main.py", "cognitive.py", "handlers.py"],
            "max_friction": 0.2,
        }

        # Premier rapport via screen_lock
        update_memories_from_session(data, memory_dir=self.memory_dir, trigger="screen_lock")

        # Deuxième rapport via commit — doit passer malgré le cooldown
        update_memories_from_session(
            data, memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: ajout du pipeline mémoire",
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)  # un seul fichier jour
        content = session_files[0].read_text()
        self.assertEqual(content.count("### "), 1)
        self.assertIn("développement (30 min)", content)
        self.assertIn("ajout du pipeline m\u00e9moire", content)

    def test_pipeline_session_sans_projet_ne_plante_pas(self):
        """Un session_data sans active_project ne doit pas lever d'exception."""
        data = {
            "active_project": None,
            "duration_min": 20,
            "probable_task": "general",
            "recent_apps": [],
            "files_changed": 0,
            "top_files": [],
            "max_friction": 0.0,
        }
        try:
            update_memories_from_session(data, memory_dir=self.memory_dir, trigger="screen_lock")
        except Exception as exc:
            self.fail(f"update_memories_from_session a levé une exception : {exc}")

    def test_pipeline_llm_fallback_si_erreur(self):
        """Si le LLM échoue, le fallback déterministe est utilisé sans exception."""
        class FailingLLM:
            def complete(self, prompt, **kwargs):
                raise RuntimeError("Ollama offline")

        data = {
            "active_project": "Pulse",
            "duration_min": 40,
            "probable_task": "coding",
            "recent_apps": ["Cursor"],
            "files_changed": 5,
            "top_files": ["main.py", "cognitive.py"],
            "max_friction": 0.3,
        }

        update_memories_from_session(
            data,
            llm=FailingLLM(),
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="fix: correction critique",
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        content = session_files[0].read_text()
        # Le fallback déterministe mentionne le commit
        self.assertIn("correction critique", content)


if __name__ == "__main__":
    unittest.main()
