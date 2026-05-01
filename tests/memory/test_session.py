import tempfile
import sqlite3
import subprocess
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from daemon.core.event_bus import Event
from daemon.core.signal_scorer import Signals
from daemon.memory.session import SessionMemory
from daemon.memory.session_snapshot_builder import (
    build_session_snapshot,
    session_snapshot_to_legacy_dict,
)
from daemon.runtime_state import PresentState


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

    def test_record_event_persiste_sans_mettre_a_jour_le_present(self):
        event = Event(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"},
            timestamp=datetime.now(),
        )
        self.memory.record_event(event)

        session = self.memory.get_session()
        events = self.memory.get_recent_events()

        self.assertIsNone(session["active_project"])
        self.assertIsNone(session["active_file"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "file_modified")

    def test_record_event_persiste_le_timestamp_source(self):
        source_ts = datetime(2026, 4, 23, 16, 5, 0)
        event = Event("app_activated", {"app_name": "Cursor"}, timestamp=source_ts)
        self.memory.record_event(event)

        events = self.memory.get_recent_events()
        self.assertEqual(events[0]["timestamp"], source_ts.isoformat())

    def test_record_event_aligne_started_at_updated_at_et_duree_sur_temps_observe(self):
        older = datetime(2026, 4, 23, 16, 0, 0)
        newer = datetime(2026, 4, 23, 16, 10, 0)

        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=newer))
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=older))

        session = self.memory.get_session()
        self.assertEqual(session["started_at"], older.isoformat())
        self.assertEqual(session["updated_at"], newer.isoformat())
        self.assertEqual(session["session_duration_min"], 10)

    def test_screen_events_sont_persistes_sans_demarrer_une_activite(self):
        initial = self.memory.get_session()
        unlock_at = datetime(2026, 4, 23, 10, 0, 0)

        self.memory.record_event(Event("screen_unlocked", {}, timestamp=unlock_at))

        session = self.memory.get_session()
        events = self.memory.get_recent_events()
        self.assertEqual(events[0]["type"], "screen_unlocked")
        self.assertEqual(session["started_at"], initial["started_at"])
        self.assertEqual(session["updated_at"], initial["updated_at"])
        self.assertEqual(session["session_duration_min"], initial["session_duration_min"])

    def test_premiere_activite_apres_unlock_devient_le_vrai_debut(self):
        unlock_at = datetime(2026, 4, 23, 10, 0, 0)
        work_at = datetime(2026, 4, 23, 10, 8, 0)

        self.memory.record_event(Event("screen_unlocked", {}, timestamp=unlock_at))
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=work_at))

        session = self.memory.get_session()
        self.assertEqual(session["started_at"], work_at.isoformat())
        self.assertEqual(session["updated_at"], work_at.isoformat())
        self.assertEqual(session["session_duration_min"], 0)

    def test_find_file_activity_window_retient_le_dernier_cluster(self):
        repo = "/Users/yugz/Projets/Pulse/Pulse"
        old_start = datetime(2026, 4, 29, 9, 0, 0)
        old_end = datetime(2026, 4, 29, 9, 10, 0)
        recent_start = datetime(2026, 4, 29, 10, 30, 0)
        recent_end = datetime(2026, 4, 29, 10, 42, 0)
        commit_at = datetime(2026, 4, 29, 11, 30, 0)

        for observed_at in (old_start, old_end, recent_start, recent_end):
            self.memory.record_event(Event(
                "file_modified",
                {"path": f"{repo}/App/App/DashboardContentView.swift"},
                timestamp=observed_at,
            ))
        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/runtime_orchestrator.py"},
            timestamp=recent_start + timedelta(minutes=3),
        ))
        self.memory.record_event(Event(
            "file_modified",
            {"path": "/Users/yugz/.codex/plugins/cache/openai.yaml"},
            timestamp=recent_start + timedelta(minutes=4),
        ))

        window = self.memory.find_file_activity_window(
            ["DashboardContentView.swift", "runtime_orchestrator.py", "openai.yaml"],
            before=commit_at,
            repo_root=repo,
        )

        self.assertIsNotNone(window)
        self.assertEqual(window["started_at"], recent_start.isoformat())
        self.assertEqual(window["ended_at"], recent_end.isoformat())
        self.assertEqual(window["duration_min"], 12)
        self.assertEqual(window["event_count"], 3)

    def test_resume_session_realigne_started_at(self):
        restarted_from = datetime(2026, 4, 23, 16, 0, 0)
        self.memory.resume_session(started_at=restarted_from)
        self.memory.record_event(
            Event("app_activated", {"app_name": "Cursor"}, timestamp=datetime(2026, 4, 23, 16, 12, 0))
        )

        session = self.memory.get_session()
        self.assertEqual(session["started_at"], restarted_from.isoformat())
        self.assertEqual(session["session_duration_min"], 12)

    def test_get_recent_events_ordonne_par_timestamp(self):
        older = datetime(2026, 4, 23, 16, 0, 0)
        newer = datetime(2026, 4, 23, 16, 5, 0)

        self.memory.record_event(Event("app_activated", {"app_name": "Chrome"}, timestamp=newer))
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=older))

        events = self.memory.get_recent_events()
        self.assertEqual([e["timestamp"] for e in events], [older.isoformat(), newer.isoformat()])

    def test_update_present_snapshot_met_a_jour_les_colonnes(self):
        present = PresentState(
            session_status="active",
            awake=True,
            locked=False,
            active_project="Pulse",
            active_file="/Users/yugz/Projets/Pulse/Pulse/daemon/main.py",
            probable_task="coding",
            activity_level="editing",
            focus_level="normal",
            session_duration_min=12,
        )
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

        self.memory.update_present_snapshot(present, signals=signals)

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
        signals = Signals(
            active_project="Pulse",
            active_file="/Users/yugz/Projets/Pulse/Pulse/daemon/main.py",
            probable_task="coding",
            friction_score=0.8,
            focus_level="normal",
            session_duration_min=20,
            recent_apps=["Cursor"],
            clipboard_context=None,
        )
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                active_file="/Users/yugz/Projets/Pulse/Pulse/daemon/main.py",
                probable_task="coding",
                activity_level="idle",
                focus_level="normal",
                session_duration_min=20,
            ),
            signals=signals,
        )

        data = self.memory.export_session_data()

        self.assertEqual(data["active_project"], "Pulse")
        self.assertEqual(data["probable_task"], "coding")
        self.assertEqual(data["files_changed"], 1)
        self.assertIn("Cursor", data["recent_apps"])
        self.assertEqual(data["max_friction"], 0.8)

    def test_export_memory_payload_contient_les_champs_essentiels(self):
        start = datetime(2026, 4, 28, 11, 0, 0)
        self.memory.started_at = start
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=start))
        self.memory.record_event(
            Event("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"}, timestamp=start)
        )
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                focus_level="normal",
                session_duration_min=20,
                updated_at=start + timedelta(minutes=20),
            ),
            signals=Signals(
                active_project="Pulse",
                active_file="/Users/yugz/Projets/Pulse/Pulse/daemon/main.py",
                probable_task="coding",
                friction_score=0.2,
                focus_level="normal",
                session_duration_min=20,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        )

        payload = self.memory.export_memory_payload()

        self.assertEqual(payload["active_project"], "Pulse")
        self.assertEqual(payload["probable_task"], "coding")
        self.assertEqual(payload["duration_min"], 20)
        self.assertEqual(payload["files_changed"], 1)
        self.assertIn("Cursor", payload["recent_apps"])
        self.assertIn("work_block_started_at", payload)
        self.assertIn("work_block_commit_count", payload)
        self.assertIn("recent_sessions", payload)
        self.assertEqual(payload["work_block_started_at"], payload["started_at"])
        self.assertEqual(payload["work_block_commit_count"], payload["commit_count"])

        # Legacy aliases stay available only for older memory consumers.
        self.assertIn("work_window_started_at", payload)
        self.assertIn("work_window_commit_count", payload)
        self.assertIn("closed_episodes", payload)
        self.assertEqual(payload["work_window_started_at"], payload["work_block_started_at"])
        self.assertEqual(payload["work_window_commit_count"], payload["work_block_commit_count"])
        self.assertEqual(payload["closed_episodes"], payload["recent_sessions"])

    def test_export_memory_payload_compte_les_commits(self):
        """Les events COMMIT_EDITMSG sont comptés comme commits."""
        start = datetime(2026, 4, 28, 11, 0, 0)
        self.memory.started_at = start
        self.memory.record_event(Event(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/.git/COMMIT_EDITMSG"},
            timestamp=start,
        ))
        self.memory.record_event(Event(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/.git/COMMIT_EDITMSG"},
            timestamp=start + timedelta(minutes=10),
        ))

        payload = self.memory.export_memory_payload()
        self.assertEqual(payload["commit_count"], 2)
        self.assertEqual(payload["work_block_commit_count"], 2)
        self.assertEqual(payload["work_window_commit_count"], payload["work_block_commit_count"])

    def test_get_today_summary_derive_le_temps_depuis_les_evenements(self):
        today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        repo = "/Users/yugz/Projets/Pulse/Pulse"

        self.memory.record_event(Event("screen_unlocked", {}, timestamp=today))
        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/main.py"},
            timestamp=today + timedelta(minutes=1),
        ))
        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/session.py"},
            timestamp=today + timedelta(minutes=11),
        ))
        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/runtime_orchestrator.py"},
            timestamp=today + timedelta(minutes=90),
        ))
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                focus_level="normal",
                session_duration_min=120,
            ),
            signals=Signals(
                active_project="Pulse",
                active_file=f"{repo}/daemon/runtime_orchestrator.py",
                probable_task="coding",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=120,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        )

        summary = self.memory.get_today_summary()

        self.assertEqual(summary["totals"]["window_count"], 2)
        self.assertEqual(summary["totals"]["worked_min"], 11)
        self.assertEqual(summary["totals"]["project_count"], 1)
        self.assertEqual(summary["projects"][0]["name"], "Pulse")
        self.assertEqual(summary["current_window"]["probable_task"], "coding")
        self.assertEqual(len(summary["work_blocks"]), 2)
        self.assertEqual(summary["work_blocks"][0]["duration_min"], 10)
        self.assertEqual(summary["work_blocks"][1]["duration_min"], 1)
        self.assertEqual(summary["work_blocks"][1]["project"], "Pulse")

    def test_get_today_summary_compte_les_commits_du_depot(self):
        repo = Path(self.tmpdir.name) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "pulse@example.test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Pulse Test"], cwd=repo, check=True)
        source = repo / "main.py"
        source.write_text("print('pulse')\n", encoding="utf-8")
        subprocess.run(["git", "add", "main.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "test commit"], cwd=repo, check=True, capture_output=True, text=True)

        self.memory.record_event(Event(
            "file_modified",
            {"path": str(source)},
            timestamp=datetime.now().replace(hour=10, minute=0, second=0, microsecond=0),
        ))
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="repo",
                probable_task="coding",
                activity_level="editing",
                focus_level="normal",
                session_duration_min=10,
            ),
            signals=Signals(
                active_project="repo",
                active_file=str(source),
                probable_task="coding",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=10,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        )

        summary = self.memory.get_today_summary()

        self.assertGreaterEqual(summary["totals"]["commit_count"], 1)
        self.assertGreaterEqual(summary["projects"][0]["commit_count"], 1)

    def test_get_recent_sessions_projette_les_sessions_closes(self):
        start = datetime(2026, 4, 28, 9, 0, 0)
        end = start + timedelta(minutes=25)
        self.memory.started_at = start
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=start))
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                focus_level="normal",
                session_duration_min=25,
                updated_at=end,
            ),
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                activity_level="editing",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=25,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        )
        self.memory.close(ended_at=end)

        episodes = self.memory.get_recent_sessions()

        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["session_id"], "test-session")
        self.assertEqual(episodes[0]["active_project"], "Pulse")
        self.assertEqual(episodes[0]["probable_task"], "coding")
        self.assertEqual(episodes[0]["duration_sec"], 25 * 60)

    def test_build_session_snapshot_plus_adaptateur_legacy(self):
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

    def test_reouverture_repare_les_sessions_restees_ouvertes(self):
        db_path = str(Path(self.tmpdir.name) / "repair.db")
        stale = SessionMemory(db_path=db_path, session_id="stale-session")
        start = datetime(2026, 4, 28, 9, 0, 0)
        stale.started_at = start
        stale.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=start))
        stale.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                focus_level="normal",
                session_duration_min=25,
                updated_at=start + timedelta(minutes=25),
            ),
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                activity_level="editing",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=25,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        )

        # On rouvre sans fermer proprement
        reopened = SessionMemory(db_path=db_path, session_id="fresh-session")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            session_row = conn.execute(
                "SELECT ended_at, updated_at, session_duration_min FROM sessions WHERE id = ?",
                ("stale-session",),
            ).fetchone()
            fresh_row = conn.execute(
                "SELECT ended_at FROM sessions WHERE id = ?",
                ("fresh-session",),
            ).fetchone()

        self.assertIsNotNone(session_row)
        self.assertIsNotNone(session_row["ended_at"])
        self.assertEqual(session_row["session_duration_min"], 25)
        self.assertIsNotNone(fresh_row)
        self.assertIsNone(fresh_row["ended_at"])
        self.assertEqual(reopened.session_id, "fresh-session")

    def test_close_termine_la_session(self):
        observed_end = datetime(2026, 4, 23, 16, 5, 0)
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=observed_end))
        self.memory.close()
        session = self.memory.get_session()
        self.assertEqual(session["ended_at"], observed_end.isoformat())

    def test_file_deleted_ne_remplace_pas_le_fichier_actif_sans_snapshot(self):
        active_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"
        deleted_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/old.py"

        self.memory.record_event(Event("file_modified", {"path": active_path}))
        self.memory.record_event(Event("file_deleted", {"path": deleted_path}))

        session = self.memory.get_session()
        self.assertIsNone(session["active_file"])
        self.assertIsNone(session["active_project"])

    # ── I3 : present est la source de vérité du présent ──────────────────────

    def test_i3_present_duration_prime_sur_memory_duration(self):
        self.memory.started_at = datetime.now() - timedelta(minutes=90)
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="coding",
            friction_score=0.1,
            focus_level="normal",
            session_duration_min=5,
            recent_apps=["Xcode"],
            clipboard_context=None,
        )
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                probable_task="coding",
                focus_level="normal",
                session_duration_min=5,
            ),
            signals=signals,
        )

        session = self.memory.get_session()
        self.assertEqual(session["session_duration_min"], 5)

    def test_i3_zero_present_duration_ecrit_zero(self):
        self.memory.started_at = datetime.now() - timedelta(minutes=60)
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="general",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=0,
            recent_apps=[],
            clipboard_context=None,
        )
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                probable_task="general",
                focus_level="normal",
                session_duration_min=0,
            ),
            signals=signals,
        )

        session = self.memory.get_session()
        self.assertEqual(session["session_duration_min"], 0)


if __name__ == "__main__":
    unittest.main()
