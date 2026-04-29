import tempfile
import sqlite3
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from daemon.core.contracts import Episode
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
        event = Event(
            "app_activated",
            {"app_name": "Cursor"},
            timestamp=source_ts,
        )

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

    def test_find_file_activity_window_retient_le_dernier_cluster_des_fichiers_du_commit(self):
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

    def test_resume_session_realigne_started_at_sur_la_session_courante(self):
        restarted_from = datetime(2026, 4, 23, 16, 0, 0)

        self.memory.resume_session(started_at=restarted_from)
        self.memory.record_event(
            Event("app_activated", {"app_name": "Cursor"}, timestamp=datetime(2026, 4, 23, 16, 12, 0))
        )

        session = self.memory.get_session()
        self.assertEqual(session["started_at"], restarted_from.isoformat())
        self.assertEqual(session["session_duration_min"], 12)

    def test_get_recent_events_reste_ordre_par_timestamp_meme_hors_ordre_arrivee(self):
        older = datetime(2026, 4, 23, 16, 0, 0)
        newer = datetime(2026, 4, 23, 16, 5, 0)

        self.memory.record_event(Event("app_activated", {"app_name": "Chrome"}, timestamp=newer))
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=older))

        events = self.memory.get_recent_events()

        self.assertEqual([event["timestamp"] for event in events], [older.isoformat(), newer.isoformat()])

    def test_update_present_snapshot_met_a_jour_les_colonnes_de_session(self):
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
        signals = Signals(
            active_project="Pulse",
            active_file=main_path,
            probable_task="coding",
            friction_score=0.8,
            focus_level="normal",
            session_duration_min=20,
            recent_apps=["Cursor", "Terminal"],
            clipboard_context=None,
        )
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                active_file=main_path,
                probable_task="coding",
                activity_level="editing",
                focus_level="normal",
                session_duration_min=20,
            ),
            signals=signals,
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

    def test_file_deleted_ne_remplace_pas_le_fichier_actif_de_session_sans_snapshot(self):
        active_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"
        deleted_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/old.py"

        self.memory.record_event(Event("file_modified", {"path": active_path}))
        self.memory.record_event(Event("file_deleted", {"path": deleted_path}))

        session = self.memory.get_session()

        self.assertIsNone(session["active_file"])
        self.assertIsNone(session["active_project"])

    def test_close_termine_la_session(self):
        observed_end = datetime(2026, 4, 23, 16, 5, 0)
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=observed_end))
        self.memory.close()
        session = self.memory.get_session()
        self.assertEqual(session["ended_at"], observed_end.isoformat())

    def test_reouverture_repare_les_sessions_episodes_et_work_windows_ouverts(self):
        db_path = str(Path(self.tmpdir.name) / "repair.db")
        stale = SessionMemory(db_path=db_path, session_id="stale-session")
        start = datetime(2026, 4, 28, 9, 0, 0)
        stale.started_at = start
        stale.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=start))
        stale.save_episode(
            Episode(
                id="ep-open",
                session_id="stale-session",
                started_at=start.isoformat(),
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.91,
            )
        )
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

        reopened = SessionMemory(db_path=db_path, session_id="fresh-session")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            session_row = conn.execute(
                "SELECT ended_at, updated_at, session_duration_min FROM sessions WHERE id = ?",
                ("stale-session",),
            ).fetchone()
            episode_row = conn.execute(
                "SELECT ended_at, boundary_reason, duration_sec FROM episodes WHERE id = ?",
                ("ep-open",),
            ).fetchone()
            work_window_row = conn.execute(
                """
                SELECT status, ended_at, close_reason, active_sec, active_min
                FROM work_windows
                WHERE session_id = ?
                """,
                ("stale-session",),
            ).fetchone()
            fresh_row = conn.execute(
                "SELECT ended_at FROM sessions WHERE id = ?",
                ("fresh-session",),
            ).fetchone()

        self.assertIsNotNone(session_row)
        self.assertEqual(session_row["ended_at"], session_row["updated_at"])
        self.assertEqual(session_row["session_duration_min"], 25)
        self.assertIsNotNone(episode_row)
        self.assertEqual(episode_row["boundary_reason"], "restart_repair")
        self.assertEqual(episode_row["duration_sec"], 1500)
        self.assertIsNotNone(work_window_row)
        self.assertEqual(work_window_row["status"], "closed")
        self.assertEqual(work_window_row["close_reason"], "restart_repair")
        self.assertEqual(work_window_row["active_sec"], 1500)
        self.assertEqual(work_window_row["active_min"], 25)
        self.assertIsNotNone(fresh_row)
        self.assertIsNone(fresh_row["ended_at"])
        self.assertEqual(reopened.session_id, "fresh-session")

    def test_save_episode_persists_active_episode(self):
        episode = Episode(
            id="ep-1",
            session_id="test-session",
            started_at="2026-04-22T10:00:00",
            active_project="Pulse",
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.82,
        )

        self.memory.save_episode(episode)

        current = self.memory.get_current_episode()
        self.assertIsNotNone(current)
        self.assertEqual(current["id"], "ep-1")
        self.assertEqual(current["ended_at"], None)
        self.assertEqual(current["active_project"], "Pulse")
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
            active_project="Pulse",
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
        self.assertEqual(recent[0]["active_project"], "Pulse")
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

    def test_get_recent_closed_episodes_returns_minimal_consolidated_rows(self):
        self.memory.save_episode(
            Episode(
                id="ep-open",
                session_id="test-session",
                started_at="2026-04-22T11:00:00",
                active_project="Pulse",
                probable_task="coding",
            )
        )
        self.memory.save_episode(
            Episode(
                id="ep-closed",
                session_id="test-session",
                started_at="2026-04-22T10:00:00",
                ended_at="2026-04-22T10:25:00",
                boundary_reason="commit",
                duration_sec=1500,
                active_project="Pulse",
                probable_task="debug",
                activity_level="executing",
                task_confidence=0.87,
            )
        )

        episodes = self.memory.get_recent_closed_episodes(limit=5)

        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].episode_id, "ep-closed")
        self.assertEqual(episodes[0].session_id, "test-session")
        self.assertEqual(episodes[0].active_project, "Pulse")
        self.assertEqual(episodes[0].probable_task, "debug")
        self.assertEqual(episodes[0].activity_level, "executing")
        self.assertEqual(episodes[0].task_confidence, 0.87)
        self.assertEqual(episodes[0].ended_at, "2026-04-22T10:25:00")
        self.assertEqual(episodes[0].duration_sec, 1500)
        self.assertEqual(episodes[0].boundary_reason, "commit")

    def test_export_memory_payload_adds_closed_episodes_without_changing_legacy_export(self):
        self.memory.save_episode(
            Episode(
                id="ep-closed",
                session_id="test-session",
                started_at="2026-04-22T10:00:00",
                ended_at="2026-04-22T10:15:00",
                boundary_reason="idle_timeout",
                duration_sec=900,
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.78,
            )
        )

        legacy = self.memory.export_session_data()
        payload = self.memory.export_memory_payload()

        self.assertNotIn("closed_episodes", legacy)
        self.assertIn("closed_episodes", payload)
        self.assertEqual(payload["session_id"], legacy["session_id"])
        self.assertEqual(payload["closed_episodes"][0]["episode_id"], "ep-closed")
        self.assertEqual(payload["closed_episodes"][0]["active_project"], "Pulse")
        self.assertEqual(payload["closed_episodes"][0]["probable_task"], "coding")

    def test_export_memory_payload_ancre_la_derniere_work_window_persisted(self):
        start = datetime(2026, 4, 28, 11, 46, 1)
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
                session_duration_min=18,
                updated_at=start + timedelta(minutes=18),
            ),
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/daydream.py",
                probable_task="coding",
                activity_level="editing",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=18,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        )
        self.memory.rollover_work_window(
            ended_at=start + timedelta(minutes=18),
            next_started_at=start + timedelta(minutes=18),
            close_reason="project_change",
            session_id="test-session",
            active_project="plugins",
            probable_task="debug",
            activity_level="executing",
            task_confidence=0.81,
        )
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="plugins",
                probable_task="debug",
                activity_level="executing",
                focus_level="normal",
                session_duration_min=22,
                updated_at=start + timedelta(minutes=22),
            ),
            signals=Signals(
                active_project="plugins",
                active_file="/tmp/plugin.py",
                probable_task="debug",
                activity_level="executing",
                friction_score=0.2,
                focus_level="normal",
                session_duration_min=22,
                recent_apps=["Cursor"],
                clipboard_context=None,
                task_confidence=0.81,
            ),
        )

        payload = self.memory.export_memory_payload()

        self.assertEqual(payload["started_at"], start.isoformat())
        self.assertEqual(payload["work_window_started_at"], (start + timedelta(minutes=18)).isoformat())
        self.assertEqual(payload["work_window_ended_at"], (start + timedelta(minutes=22)).isoformat())
        self.assertEqual(payload["work_window_status"], "open")

    def test_active_min_accumule_les_updates_sub_minute_en_secondes(self):
        start = datetime(2026, 4, 28, 18, 42, 52)
        self.memory.started_at = start
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=start))

        for observed_at in (
            start + timedelta(seconds=20),
            start + timedelta(seconds=45),
            start + timedelta(seconds=75),
        ):
            self.memory.update_present_snapshot(
                PresentState(
                    session_status="active",
                    awake=True,
                    locked=False,
                    active_project="Pulse",
                    probable_task="coding",
                    activity_level="editing",
                    focus_level="normal",
                    session_duration_min=max(int((observed_at - start).total_seconds() / 60), 0),
                    updated_at=observed_at,
                ),
                signals=Signals(
                    active_project="Pulse",
                    active_file="/tmp/dashboard.py",
                    probable_task="coding",
                    activity_level="editing",
                    friction_score=0.1,
                    focus_level="normal",
                    session_duration_min=max(int((observed_at - start).total_seconds() / 60), 0),
                    recent_apps=["Cursor"],
                    clipboard_context=None,
                ),
            )

        summary = self.memory.get_today_summary(now=start + timedelta(seconds=75))

        self.assertEqual(summary["totals"]["worked_min"], 1)
        self.assertEqual(summary["totals"]["active_min"], 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT active_sec, active_min FROM work_windows WHERE session_id = ?", ("test-session",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["active_sec"], 75)
        self.assertEqual(row["active_min"], 1)


    # ── I3 : update_present_snapshot — present est la source de vérité du présent ───

    def test_i3_present_duration_ecrase_pas_le_max_avec_memory_duration(self):
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
        self.assertEqual(session["session_duration_min"], 5,
            "signals.session_duration_min doit primer sur _duration_min() "
            "même quand _duration_min() est plus grand")

    def test_i3_zero_present_duration_ecrit_zero(self):
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
        self.assertEqual(session["session_duration_min"], 0,
            "session_duration_min=0 depuis signals doit être écrit tel quel")

    def test_i3_update_present_snapshot_valeur_normale_inchangee(self):
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

        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                activity_level="editing",
                focus_level="deep",
                session_duration_min=45,
            ),
            signals=signals,
        )

        session = self.memory.get_session()
        self.assertEqual(session["session_duration_min"], 45)
        self.assertEqual(session["probable_task"], "coding")
        self.assertEqual(session["focus_level"], "deep")

    def test_today_summary_aggregate_les_work_windows_persistes_du_jour(self):
        start = datetime(2026, 4, 28, 9, 0, 0)
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
                session_duration_min=45,
                updated_at=start + timedelta(minutes=45),
            ),
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                activity_level="editing",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=45,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        )
        self.memory.note_commit_for_current_work_window(when=start + timedelta(minutes=45))
        self.memory.new_session(
            started_at=start + timedelta(hours=2),
            ended_at=start + timedelta(hours=1),
            close_reason="screen_lock",
        )

        self.memory.record_event(
            Event("app_activated", {"app_name": "Cursor"}, timestamp=start + timedelta(hours=2))
        )
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                probable_task="debug",
                activity_level="executing",
                focus_level="deep",
                session_duration_min=30,
                updated_at=start + timedelta(hours=2, minutes=30),
            ),
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/runtime.py",
                probable_task="debug",
                activity_level="executing",
                friction_score=0.2,
                focus_level="deep",
                session_duration_min=30,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        )

        summary = self.memory.get_today_summary(now=start + timedelta(hours=2, minutes=30))

        self.assertEqual(summary["totals"]["worked_min"], 90)
        self.assertEqual(summary["totals"]["commit_count"], 1)
        self.assertEqual(summary["totals"]["window_count"], 2)
        self.assertEqual(summary["projects"][0]["name"], "Pulse")
        self.assertEqual(summary["projects"][0]["worked_min"], 90)

    def test_today_summary_plafonne_une_fenetre_ouverte_qui_traverse_la_nuit(self):
        start = datetime(2026, 4, 28, 23, 30, 0)
        now = datetime(2026, 4, 29, 10, 30, 0)
        self.memory.started_at = start
        self.memory.record_event(Event("app_activated", {"app_name": "Xcode"}, timestamp=start))
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                probable_task="coding",
                activity_level="idle",
                focus_level="normal",
                session_duration_min=660,
                updated_at=now,
            ),
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/SystemObserver.swift",
                probable_task="coding",
                activity_level="idle",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=660,
                recent_apps=["Xcode"],
                clipboard_context=None,
            ),
        )

        summary = self.memory.get_today_summary(now=now)

        self.assertLess(summary["totals"]["worked_min"], 660)
        self.assertEqual(
            summary["totals"]["worked_min"],
            summary["totals"]["active_min"] + 15,
        )

    def test_rollover_work_window_scinde_les_projets_dans_today_summary(self):
        start = datetime(2026, 4, 28, 14, 0, 0)
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
                session_duration_min=20,
                updated_at=start + timedelta(minutes=20),
            ),
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                activity_level="editing",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=20,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        )
        self.memory.rollover_work_window(
            ended_at=start + timedelta(minutes=20),
            next_started_at=start + timedelta(minutes=20),
            close_reason="project_change",
            session_id="test-session",
            active_project="plugins",
            probable_task="debug",
            activity_level="executing",
            task_confidence=0.82,
        )
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="plugins",
                probable_task="debug",
                activity_level="executing",
                focus_level="normal",
                session_duration_min=35,
                updated_at=start + timedelta(minutes=35),
            ),
            signals=Signals(
                active_project="plugins",
                active_file="/tmp/plugin.py",
                probable_task="debug",
                activity_level="executing",
                friction_score=0.2,
                focus_level="normal",
                session_duration_min=35,
                recent_apps=["Cursor"],
                clipboard_context=None,
                task_confidence=0.82,
            ),
        )

        summary = self.memory.get_today_summary(now=start + timedelta(minutes=35))

        self.assertEqual(summary["totals"]["worked_min"], 35)
        self.assertEqual([item["name"] for item in summary["projects"]], ["Pulse", "plugins"])
        self.assertEqual(summary["projects"][0]["worked_min"], 20)
        self.assertEqual(summary["projects"][1]["worked_min"], 15)

    def test_reouverture_reconstruit_work_windows_depuis_sessions_et_episodes_existants(self):
        start = datetime(2026, 4, 28, 10, 0, 0)
        self.memory.started_at = start
        self.memory.record_event(Event("app_activated", {"app_name": "Cursor"}, timestamp=start))
        self.memory.save_episode(
            Episode(
                id="ep-1",
                session_id="test-session",
                started_at=start.isoformat(),
                ended_at=(start + timedelta(minutes=25)).isoformat(),
                boundary_reason="commit",
                duration_sec=1500,
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.91,
            )
        )
        self.memory.save_episode(
            Episode(
                id="ep-2",
                session_id="test-session",
                started_at=(start + timedelta(minutes=25)).isoformat(),
                ended_at=(start + timedelta(minutes=40)).isoformat(),
                boundary_reason="screen_lock",
                duration_sec=900,
                active_project="Pulse",
                probable_task="debug",
                activity_level="executing",
                task_confidence=0.88,
            )
        )
        self.memory.update_present_snapshot(
            PresentState(
                session_status="active",
                awake=True,
                locked=False,
                active_project="Pulse",
                probable_task="debug",
                activity_level="executing",
                focus_level="normal",
                session_duration_min=40,
                updated_at=start + timedelta(minutes=40),
            ),
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/runtime.py",
                probable_task="debug",
                activity_level="executing",
                friction_score=0.2,
                focus_level="normal",
                session_duration_min=40,
                recent_apps=["Cursor"],
                clipboard_context=None,
                task_confidence=0.88,
            ),
        )
        self.memory.close(ended_at=start + timedelta(minutes=40), close_reason="screen_lock")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM work_windows")
            conn.commit()

        reopened = SessionMemory(db_path=self.db_path, session_id="test-session-reopened")
        summary = reopened.get_today_summary(now=start + timedelta(minutes=45))

        self.assertEqual(summary["totals"]["worked_min"], 40)
        self.assertEqual(summary["totals"]["commit_count"], 1)
        self.assertEqual(summary["projects"][0]["name"], "Pulse")


if __name__ == "__main__":
    unittest.main()
