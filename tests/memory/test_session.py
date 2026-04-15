import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from daemon.core.event_bus import Event
from daemon.core.signal_scorer import Signals
from daemon.memory.session import SessionMemory


class TestSessionMemory(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "session.db")
        self.memory = SessionMemory(db_path=self.db_path, session_id="test-session")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_init_cree_la_session(self):
        session = self.memory.get_session()
        self.assertEqual(session["id"], "test-session")
        self.assertIsNotNone(session["started_at"])

    def test_record_event_persiste_et_met_a_jour_fichier_actif(self):
        event = Event(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"},
            timestamp=datetime.now(),
        )

        self.memory.record_event(event)

        session = self.memory.get_session()
        events = self.memory.get_recent_events()

        self.assertEqual(session["active_project"], "Pulse")
        self.assertEqual(session["active_file"], event.payload["path"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "file_modified")

    def test_update_signals_met_a_jour_les_colonnes_de_session(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/Users/yugz/Projets/Pulse/Pulse/daemon/main.py",
            probable_task="coding",
            friction_score=0.4,
            focus_level="normal",
            session_duration_min=12,
            recent_apps=["Cursor", "Terminal"],
            clipboard_context="code",
        )

        self.memory.update_signals(signals)

        session = self.memory.get_session()
        self.assertEqual(session["active_project"], "Pulse")
        self.assertEqual(session["probable_task"], "coding")
        self.assertEqual(session["focus_level"], "normal")
        self.assertEqual(session["session_duration_min"], 12)

    def test_export_session_data_resume_la_session(self):
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}))
        self.memory.record_event(
            Event("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})
        )
        self.memory.update_signals(
            Signals(
                active_project="Pulse",
                active_file="/Users/yugz/Projets/Pulse/Pulse/daemon/main.py",
                probable_task="coding",
                friction_score=0.8,
                focus_level="normal",
                session_duration_min=20,
                recent_apps=["Cursor"],
                clipboard_context=None,
            )
        )

        data = self.memory.export_session_data()

        self.assertEqual(data["active_project"], "Pulse")
        self.assertEqual(data["probable_task"], "coding")
        self.assertEqual(data["files_changed"], 1)
        self.assertIn("Cursor", data["recent_apps"])
        self.assertEqual(data["max_friction"], 0.8)

    def test_file_deleted_ne_remplace_pas_le_fichier_actif_de_session(self):
        active_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"
        deleted_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/old.py"

        self.memory.record_event(Event("file_modified", {"path": active_path}))
        self.memory.record_event(Event("file_deleted", {"path": deleted_path}))

        session = self.memory.get_session()

        self.assertEqual(session["active_file"], active_path)
        self.assertEqual(session["active_project"], "Pulse")

    def test_close_termine_la_session(self):
        self.memory.close()
        session = self.memory.get_session()
        self.assertIsNotNone(session["ended_at"])


if __name__ == "__main__":
    unittest.main()
