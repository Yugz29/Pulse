import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from daemon.core.contracts import Episode
from daemon.core.event_bus import Event
from daemon.core.signal_scorer import Signals
from daemon.memory.session import SessionMemory
from daemon.memory.session_snapshot_builder import (
    build_session_snapshot,
    session_snapshot_to_legacy_dict,
)


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

    def test_export_session_data_golden_legacy_contract_exact(self):
        main_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"
        helper_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/helper.py"
        deleted_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/old.py"

        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}))
        self.memory.record_event(Event("app_activated", {"app_name": "Terminal"}))
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}))
        self.memory.record_event(Event("file_modified", {"path": main_path}))
        self.memory.record_event(Event("file_modified", {"path": helper_path}))
        self.memory.record_event(Event("file_modified", {"path": main_path}))
        self.memory.record_event(Event("file_deleted", {"path": deleted_path}))
        self.memory.update_signals(
            Signals(
                active_project="Pulse",
                active_file=main_path,
                probable_task="coding",
                friction_score=0.8,
                focus_level="normal",
                session_duration_min=20,
                recent_apps=["Cursor", "Terminal"],
                clipboard_context=None,
            )
        )

        session = self.memory.get_session()
        expected = {
            "session_id": "test-session",
            "started_at": session["started_at"],
            "updated_at": session["updated_at"],
            "ended_at": session["ended_at"],
            "active_project": "Pulse",
            "active_file": main_path,
            "probable_task": "coding",
            "focus_level": "normal",
            "duration_min": 20,
            "recent_apps": ["Cursor", "Terminal"],
            "files_changed": 3,
            "top_files": ["main.py", "helper.py", "old.py"],
            "event_count": 7,
            "max_friction": 0.8,
        }

        data = self.memory.export_session_data()

        self.assertEqual(data, expected)

    def test_build_session_snapshot_plus_adaptateur_legacy_reproduit_le_contrat_exact(self):
        session = {
            "id": "session-42",
            "started_at": "2026-04-21T09:00:00",
            "updated_at": "2026-04-21T09:25:00",
            "ended_at": None,
            "active_project": "Pulse",
            "active_file": "/repo/daemon/main.py",
            "probable_task": "coding",
            "focus_level": "deep",
            "session_duration_min": 25,
            "friction_score": 0.6,
        }
        recent_events = [
            {"type": "app_activated", "payload": {"app_name": "Cursor"}, "timestamp": "2026-04-21T09:01:00"},
            {"type": "app_switch", "payload": {"app_name": "Terminal"}, "timestamp": "2026-04-21T09:02:00"},
            {"type": "app_activated", "payload": {"app_name": "Cursor"}, "timestamp": "2026-04-21T09:03:00"},
            {"type": "file_modified", "payload": {"path": "/repo/daemon/main.py"}, "timestamp": "2026-04-21T09:04:00"},
            {"type": "file_modified", "payload": {"path": "/repo/daemon/utils.py"}, "timestamp": "2026-04-21T09:05:00"},
            {"type": "file_modified", "payload": {"path": "/repo/daemon/main.py"}, "timestamp": "2026-04-21T09:06:00"},
            {"type": "file_deleted", "payload": {"path": "/repo/daemon/old.py"}, "timestamp": "2026-04-21T09:07:00"},
        ]
        expected = {
            "session_id": "session-42",
            "started_at": "2026-04-21T09:00:00",
            "updated_at": "2026-04-21T09:25:00",
            "ended_at": None,
            "active_project": "Pulse",
            "active_file": "/repo/daemon/main.py",
            "probable_task": "coding",
            "focus_level": "deep",
            "duration_min": 25,
            "recent_apps": ["Cursor", "Terminal"],
            "files_changed": 3,
            "top_files": ["main.py", "utils.py", "old.py"],
            "event_count": 7,
            "max_friction": 0.6,
        }

        snapshot = build_session_snapshot(
            session=session,
            recent_events=recent_events,
            duration_fallback_min=999,
        )
        legacy = session_snapshot_to_legacy_dict(snapshot)

        self.assertEqual(legacy, expected)

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

    def test_save_episode_persists_active_episode(self):
        episode = Episode(
            id="ep-1",
            session_id="test-session",
            started_at="2026-04-22T10:00:00",
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.82,
        )

        self.memory.save_episode(episode)

        current = self.memory.get_current_episode()
        self.assertIsNotNone(current)
        self.assertEqual(current["id"], "ep-1")
        self.assertEqual(current["ended_at"], None)
        self.assertEqual(current["probable_task"], "coding")
        self.assertEqual(current["activity_level"], "editing")
        self.assertEqual(current["task_confidence"], 0.82)

    def test_save_episode_updates_closed_episode(self):
        active = Episode(
            id="ep-1",
            session_id="test-session",
            started_at="2026-04-22T10:00:00",
        )
        closed = Episode(
            id="ep-1",
            session_id="test-session",
            started_at="2026-04-22T10:00:00",
            ended_at="2026-04-22T10:25:00",
            boundary_reason="commit",
            duration_sec=1500,
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.88,
        )

        self.memory.save_episode(active)
        self.memory.save_episode(closed)

        current = self.memory.get_current_episode()
        recent = self.memory.get_recent_episodes(limit=5)
        self.assertIsNone(current)
        self.assertEqual(recent[0]["boundary_reason"], "commit")
        self.assertEqual(recent[0]["duration_sec"], 1500)
        self.assertEqual(recent[0]["probable_task"], "coding")
        self.assertEqual(recent[0]["activity_level"], "editing")
        self.assertEqual(recent[0]["task_confidence"], 0.88)

    def test_get_recent_episodes_orders_latest_first(self):
        self.memory.save_episode(
            Episode(
                id="ep-older",
                session_id="test-session",
                started_at="2026-04-22T09:00:00",
                ended_at="2026-04-22T09:30:00",
                boundary_reason="idle_timeout",
                duration_sec=1800,
            )
        )
        self.memory.save_episode(
            Episode(
                id="ep-newer",
                session_id="test-session",
                started_at="2026-04-22T10:00:00",
            )
        )

        recent = self.memory.get_recent_episodes(limit=5)

        self.assertEqual([row["id"] for row in recent], ["ep-newer", "ep-older"])


    # ── I3 : update_signals — signals est la source de vérité pour la durée ───

    def test_i3_signals_duration_ecrase_pas_le_max_avec_memory_duration(self):
        """
        Cas problématique du max() :
        Si session_memory.started_at est ancien (grande _duration_min),
        mais que signals.session_duration_min est petit (post-reset du scorer),
        le max() aurait écrit la grande valeur. On doit écrire la petite.
        """
        from datetime import timedelta
        # Simule une session_memory dont started_at pointe loin dans le passé
        self.memory.started_at = datetime.now() - timedelta(minutes=90)

        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="coding",
            friction_score=0.1,
            focus_level="normal",
            session_duration_min=5,   # ← scorer vient de reseté
            recent_apps=["Xcode"],
            clipboard_context=None,
        )

        self.memory.update_signals(signals)

        session = self.memory.get_session()
        self.assertEqual(session["session_duration_min"], 5,
            "signals.session_duration_min doit primer sur _duration_min() "
            "même quand _duration_min() est plus grand")

    def test_i3_zero_signals_duration_ecrit_zero(self):
        """
        Quand le scorer vient de reseté (duration=0), on écrit 0.
        Avec l'ancien max(), si _duration_min() > 0, on aurait écrit
        la durée depuis le démarrage de SessionMemory.
        """
        from datetime import timedelta
        self.memory.started_at = datetime.now() - timedelta(minutes=60)

        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="general",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=0,   # ← scorer tout juste reseté
            recent_apps=[],
            clipboard_context=None,
        )

        self.memory.update_signals(signals)

        session = self.memory.get_session()
        self.assertEqual(session["session_duration_min"], 0,
            "session_duration_min=0 depuis signals doit être écrit tel quel")

    def test_i3_update_signals_valeur_normale_inchangee(self):
        """Régression : cas normal sans divergence reste correct."""
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.2,
            focus_level="deep",
            session_duration_min=45,
            recent_apps=["Xcode"],
            clipboard_context=None,
        )

        self.memory.update_signals(signals)

        session = self.memory.get_session()
        self.assertEqual(session["session_duration_min"], 45)
        self.assertEqual(session["probable_task"], "coding")
        self.assertEqual(session["focus_level"], "deep")


if __name__ == "__main__":
    unittest.main()
