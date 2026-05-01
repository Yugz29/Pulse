import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from pathlib import Path

from flask import Flask

from daemon.core.contracts import SessionContext
from daemon.core.event_bus import Event
from daemon.core.decision_engine import Decision
from daemon.core.signal_scorer import Signals
from daemon.routes.runtime import _FileEventCoalescer, register_runtime_routes
from daemon.runtime_state import RuntimeState


class _DummyThread:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False

    def start(self):
        self.started = True


class _ImmediateThread:
    def __init__(self, *args, **kwargs):
        self.target = kwargs.get("target")
        self.args = kwargs.get("args", ())
        self.kwargs = kwargs.get("kwargs", {})
        self.started = False

    def start(self):
        self.started = True
        if self.target is not None:
            self.target(*self.args, **self.kwargs)


class _ManualTimer:
    def __init__(self, interval, callback, args=None, kwargs=None):
        self.interval = interval
        self.callback = callback
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.daemon = False
        self.cancelled = False
        self.started = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.callback(*self.args, **self.kwargs)


class TestRuntimeRoutes(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.bus = MagicMock()
        self.store = MagicMock()
        self.runtime_state = RuntimeState()
        self.llm_unload_background = MagicMock()
        self.llm_warmup_background = MagicMock()
        self.shutdown_runtime = MagicMock()
        self.log = MagicMock()

        register_runtime_routes(
            self.app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        self.client = self.app.test_client()

    def test_daydreams_expose_etat_meme_sans_fichier(self):
        with patch("pathlib.Path.home", return_value=Path("/tmp/pulse-home")), \
             patch("daemon.memory.daydream.get_daydream_status", return_value={
                 "status": "skipped",
                 "pending": False,
                 "target_date": "2026-04-27",
                 "done_for_date": "2026-04-27",
                 "last_reason": "no_journal_entries",
                 "last_error": None,
                 "last_attempt_at": "2026-04-28T00:05:16",
                 "last_completed_at": "2026-04-28T00:05:16",
                 "last_output_path": None,
             }):
            response = self.client.get("/daydreams")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["daydreams"], [])
        self.assertEqual(payload["status"]["status"], "skipped")
        self.assertEqual(payload["status"]["last_reason"], "no_journal_entries")

    def test_today_summary_expose_un_aggregate_persiste(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_summary=lambda: {
                "date": "2026-04-28",
                "generated_at": "2026-04-28T12:50:00",
                "totals": {
                    "worked_min": 95,
                    "active_min": 72,
                    "commit_count": 3,
                    "window_count": 2,
                    "project_count": 1,
                },
                "projects": [
                    {
                        "name": "Pulse",
                        "worked_min": 95,
                        "active_min": 72,
                        "commit_count": 3,
                        "top_tasks": ["coding", "debug"],
                    }
                ],
                "timeline": {
                    "first_activity_at": "2026-04-28T11:10:00",
                    "last_activity_at": "2026-04-28T12:49:00",
                },
                "current_window": {
                    "id": "ww-1",
                    "started_at": "2026-04-28T12:36:00",
                    "updated_at": "2026-04-28T12:49:00",
                    "project": "Pulse",
                    "probable_task": "coding",
                    "activity_level": "executing",
                    "commit_count": 2,
                },
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/today_summary")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["totals"]["worked_min"], 95)
        self.assertEqual(payload["projects"][0]["name"], "Pulse")
        self.assertEqual(payload["current_window"]["id"], "ww-1")

    def test_state_golden_legacy_json_output_exact(self):
        self.runtime_state.set_paused(True)
        signals = Signals(
            active_project="Pulse",
            active_file="/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
            probable_task="coding",
            friction_score=0.42,
            focus_level="deep",
            session_duration_min=96,
            recent_apps=["Xcode", "Codex", "Safari"],
            clipboard_context="text",
            edited_file_count_10m=4,
            file_type_mix_10m={"source": 2, "test": 1, "docs": 1},
            rename_delete_ratio_10m=0.25,
            dominant_file_mode="few_files",
            work_pattern_candidate="feature_candidate",
            activity_level="editing",
            task_confidence=0.81,
        )
        decision = Decision(
            action="notify",
            level=2,
            reason="high_friction",
            payload={"file": "PanelView.swift"},
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
            updated_at=datetime(2026, 4, 23, 10, 0, 0),
        )
        self.runtime_state.set_analysis(
            signals=signals,
            decision=decision,
        )

        self.store.to_dict.return_value = {
            "active_app": "Xcode",
            "session_duration_min": 96,
        }
        self.runtime_state.set_latest_active_app("Xcode")

        expected = {
            "active_app": "Xcode",
            "active_file": "/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
            "active_project": "Pulse",
            "session_duration_min": 96,
            "last_event_type": None,
            "runtime_paused": True,
            "present": {
                "session_status": "active",
                "awake": True,
                "locked": False,
                "active_file": "/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
                "active_project": "Pulse",
                "probable_task": "coding",
                "activity_level": "editing",
                "focus_level": "deep",
                "friction_score": 0.42,
                "clipboard_context": "text",
                "session_duration_min": 96,
                "updated_at": "2026-04-23T10:00:00",
            },
            "signals": {
                "active_project": "Pulse",
                "active_file": "/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
                "probable_task": "coding",
                "activity_level": "editing",
                "task_confidence": 0.81,
                "friction_score": 0.42,
                "focus_level": "deep",
                "session_duration_min": 96,
                "recent_apps": ["Xcode", "Codex", "Safari"],
                "clipboard_context": "text",
                "edited_file_count_10m": 4,
                "file_type_mix_10m": {"source": 2, "test": 1, "docs": 1},
                "rename_delete_ratio_10m": 0.25,
                "dominant_file_mode": "few_files",
                "work_pattern_candidate": "feature_candidate",
                "last_session_context": "Dernière session Pulse : hier (développement, 45 min)",
            },
            "decision": {
                "action": "notify",
                "level": 2,
                "reason": "high_friction",
                "payload": {"file": "PanelView.swift"},
            },
            "debug": {
                "store": {
                    "active_app": "Xcode",
                    "session_duration_min": 96,
                },
                "runtime": {
                    "latest_active_app": "Xcode",
                    "lock_marker_active": False,
                    "last_screen_locked_at": None,
                    "memory_synced_at": None,
                },
                "signals": {
                    "active_project": "Pulse",
                    "active_file": "/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
                    "probable_task": "coding",
                    "activity_level": "editing",
                    "task_confidence": 0.81,
                    "friction_score": 0.42,
                    "focus_level": "deep",
                    "session_duration_min": 96,
                    "recent_apps": ["Xcode", "Codex", "Safari"],
                    "clipboard_context": "text",
                    "edited_file_count_10m": 4,
                    "file_type_mix_10m": {"source": 2, "test": 1, "docs": 1},
                    "rename_delete_ratio_10m": 0.25,
                    "dominant_file_mode": "few_files",
                    "work_pattern_candidate": "feature_candidate",
                    "last_session_context": "Dernière session Pulse : hier (développement, 45 min)",
                },
                "decision": {
                    "action": "notify",
                    "level": 2,
                    "reason": "high_friction",
                    "payload": {"file": "PanelView.swift"},
                },
            },
        }

        with patch("daemon.routes.runtime.last_session_context", return_value="Dernière session Pulse : hier (développement, 45 min)"):
            response = self.client.get("/state")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)

    def test_state_fallbacks_to_builder_when_current_context_absent(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=24,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.store.to_dict.return_value = {
            "active_project": None,
            "active_file": None,
            "active_app": "Xcode",
            "session_duration_min": 0,
        }

        with patch("daemon.routes.runtime.find_git_root", return_value=None), \
             patch("daemon.routes.runtime.find_workspace_root", return_value=None), \
             patch("daemon.routes.runtime.last_session_context", return_value="Dernière session Pulse : hier (développement, 45 min)"):
            response = self.client.get("/state")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["active_project"], "Pulse")
        self.assertEqual(payload["active_file"], "/tmp/main.py")
        self.assertEqual(payload["signals"]["active_project"], "Pulse")
        self.assertEqual(payload["signals"]["active_file"], "/tmp/main.py")
        self.assertEqual(payload["signals"]["session_duration_min"], 24)
        self.assertEqual(payload["debug"]["store"]["active_project"], None)

    def test_state_builder_ignores_store_active_file_and_project(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/current.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=24,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("RuntimeApp")
        self.store.to_dict.return_value = {
            "active_project": "OldProject",
            "active_file": "/tmp/stale.py",
            "active_app": "Xcode",
            "session_duration_min": 999,
        }

        with patch("daemon.routes.runtime.last_session_context", return_value=None):
            response = self.client.get("/state")

        payload = response.get_json()
        self.assertEqual(payload["active_project"], "Pulse")
        self.assertEqual(payload["active_file"], "/tmp/current.py")
        self.assertEqual(payload["active_app"], "RuntimeApp")
        self.assertEqual(payload["session_duration_min"], 24)
        self.assertEqual(payload["signals"]["active_project"], "Pulse")
        self.assertEqual(payload["signals"]["active_file"], "/tmp/current.py")
        self.assertEqual(payload["signals"]["session_duration_min"], 24)
        self.assertEqual(payload["debug"]["store"]["active_project"], "OldProject")
        self.assertEqual(payload["debug"]["store"]["active_file"], "/tmp/stale.py")
        self.assertEqual(payload["debug"]["store"]["active_app"], "Xcode")
        self.assertEqual(payload["debug"]["store"]["session_duration_min"], 999)

    def test_state_uses_atomic_runtime_snapshot_read_path(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/current.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=24,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )
        decision = Decision("silent", 0, "nothing_relevant")
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=decision)
        self.store.to_dict.return_value = {
            "active_app": "Xcode",
            "last_event_type": "file_modified",
        }

        with patch.object(self.runtime_state, "get_signal_snapshot", side_effect=AssertionError("legacy signal snapshot must not be used")), \
             patch.object(self.runtime_state, "get_present_snapshot", side_effect=AssertionError("legacy present snapshot must not be used")), \
             patch("daemon.routes.runtime.last_session_context", return_value=None):
            response = self.client.get("/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["present"]["active_project"], "Pulse")
        self.assertEqual(payload["signals"]["active_project"], "Pulse")

    def test_state_exposes_current_context_and_recent_sessions_when_getters_are_provided(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_current_context=lambda: SessionContext(
                id="ep-1",
                session_id="session-1",
                started_at="2026-04-22T10:00:00",
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.81,
            ),
            get_recent_sessions=lambda limit: [
                {
                    "id": "ep-1",
                    "session_id": "session-1",
                    "started_at": "2026-04-22T10:00:00",
                    "ended_at": None,
                    "boundary_reason": None,
                    "duration_sec": None,
                    "active_project": "Pulse",
                    "probable_task": "coding",
                    "activity_level": "editing",
                    "task_confidence": 0.81,
                }
            ],
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()
        self.store.to_dict.return_value = {}

        response = client.get("/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["current_context"]["id"], "ep-1")
        self.assertEqual(payload["current_context"]["active_project"], "Pulse")
        self.assertEqual(payload["current_context"]["probable_task"], "coding")
        self.assertEqual(payload["recent_sessions"][0]["id"], "ep-1")
        self.assertEqual(payload["recent_sessions"][0]["active_project"], "Pulse")
        self.assertEqual(payload["recent_sessions"][0]["activity_level"], "editing")
        self.assertNotIn("current_episode", payload)
        self.assertNotIn("recent_episodes", payload)

    def test_state_keeps_product_hierarchy_with_present_context_and_signals(self):
        signals = Signals(
            active_project="SignalsProject",
            active_file="/tmp/signals.py",
            probable_task="general",
            activity_level="reading",
            task_confidence=0.22,
            friction_score=0.61,
            focus_level="scattered",
            session_duration_min=12,
            recent_apps=["Chrome"],
            clipboard_context="text",
        )
        self.runtime_state.update_present(
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/live.py",
                probable_task="debug",
                activity_level="executing",
                task_confidence=0.88,
                friction_score=0.18,
                focus_level="deep",
                session_duration_min=33,
                recent_apps=["Terminal"],
                clipboard_context="code",
            ),
            session_status="active",
            awake=True,
            locked=False,
            updated_at=datetime(2026, 4, 23, 12, 0, 0),
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)

        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_current_context=lambda: SessionContext(
                id="ep-1",
                session_id="session-1",
                started_at="2026-04-23T11:50:00",
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.86,
            ),
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()
        self.store.to_dict.return_value = {"active_app": "Terminal"}

        with patch("daemon.routes.runtime.last_session_context", return_value=None):
            response = client.get("/state")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["current_context"]["active_project"], "Pulse")
        self.assertEqual(payload["current_context"]["probable_task"], "coding")
        self.assertEqual(payload["present"]["active_project"], "Pulse")
        self.assertEqual(payload["present"]["probable_task"], "debug")
        self.assertIn("signals", payload)
        self.assertEqual(payload["signals"]["probable_task"], "debug")
        self.assertEqual(payload["signals"]["focus_level"], "deep")
        self.assertEqual(payload["signals"]["friction_score"], 0.61)
        self.assertEqual(payload["active_project"], payload["present"]["active_project"])
        self.assertEqual(payload["active_file"], payload["present"]["active_file"])

    def test_ping_returns_status_and_pause_state(self):
        self.runtime_state.set_paused(True)
        response = self.client.get("/ping")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"status": "ok", "version": "0.1.0", "paused": True},
        )

    def test_event_endpoint_ignores_events_while_runtime_is_paused(self):
        self.runtime_state.set_paused(True)
        response = self.client.post("/event", json={"type": "file_modified", "path": "/tmp/test.py"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "paused": True, "ignored": True},
        )
        self.bus.publish.assert_not_called()

    def test_event_endpoint_normalizes_terminal_event_and_drops_raw_command(self):
        response = self.client.post(
            "/event",
            json={
                "type": "terminal_command_finished",
                "command": "git status",
                "cwd": "/Users/yugz/Projets/Pulse/Pulse",
                "shell": "zsh",
                "terminal_program": "Apple_Terminal",
                "exit_code": 0,
                "duration_ms": 1200,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        self.bus.publish.assert_called_once()
        event_type, payload = self.bus.publish.call_args.args
        self.assertEqual(event_type, "terminal_command_finished")
        self.assertEqual(payload["source"], "terminal")
        self.assertEqual(payload["kind"], "finished")
        self.assertEqual(payload["terminal_action_category"], "vcs")
        self.assertEqual(payload["terminal_project"], "Pulse")
        self.assertEqual(payload["terminal_cwd"], "/Users/yugz/Projets/Pulse/Pulse")
        self.assertEqual(payload["terminal_exit_code"], 0)
        self.assertEqual(payload["terminal_duration_ms"], 1200)
        self.assertNotIn("command", payload)

    def test_event_endpoint_transmet_le_timestamp_source_au_bus(self):
        source_ts = "2026-04-23T10:15:30"

        response = self.client.post(
            "/event",
            json={
                "type": "app_activated",
                "app_name": "Cursor",
                "timestamp": source_ts,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.bus.publish.assert_called_once()
        event_type, payload, observed_at = self.bus.publish.call_args.args
        self.assertEqual(event_type, "app_activated")
        self.assertEqual(payload, {"app_name": "Cursor"})
        self.assertEqual(observed_at.isoformat(), "2026-04-23T10:15:30")

    def test_insights_uses_default_limit_of_twenty_five(self):
        self.bus.recent.return_value = []
        response = self.client.get("/insights")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        self.bus.recent.assert_called_once_with(25)

    def test_insights_falls_back_to_default_limit_on_invalid_value(self):
        self.bus.recent.return_value = []
        response = self.client.get("/insights?limit=abc")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        self.bus.recent.assert_called_once_with(25)

    def test_insights_clamps_limit_to_one_hundred(self):
        self.bus.recent.return_value = []
        response = self.client.get("/insights?limit=500")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        self.bus.recent.assert_called_once_with(100)

    def test_events_debug_describes_recent_events_without_raw_payload_values(self):
        self.bus.recent.return_value = [
            Event(
                "file_modified",
                {"path": "/tmp/Pulse/daemon/main.py", "_actor": "user"},
                timestamp=datetime(2026, 5, 1, 16, 0, 0),
            ),
            Event(
                "clipboard_updated",
                {"clipboard_context": "text", "length": 42},
                timestamp=datetime(2026, 5, 1, 16, 1, 0),
            ),
        ]

        response = self.client.get("/events/debug")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["events"][0]["type"], "file_modified")
        self.assertEqual(payload["events"][0]["source"], "filesystem")
        self.assertEqual(payload["events"][0]["bucket"], "filesystem")
        self.assertEqual(payload["events"][0]["privacy"], "path_sensitive")
        self.assertEqual(payload["events"][0]["retention"], "session")
        self.assertEqual(payload["events"][0]["payload_keys"], ["_actor", "path"])
        self.assertNotIn("payload", payload["events"][0])
        self.assertNotIn("/tmp/Pulse/daemon/main.py", str(payload["events"][0]))

        self.assertEqual(payload["events"][1]["type"], "clipboard_updated")
        self.assertEqual(payload["events"][1]["source"], "clipboard")
        self.assertEqual(payload["events"][1]["bucket"], "clipboard_activity")
        self.assertEqual(payload["events"][1]["privacy"], "content_sensitive")
        self.assertEqual(payload["events"][1]["retention"], "ephemeral")
        self.assertEqual(payload["events"][1]["payload_keys"], ["clipboard_context", "length"])
        self.assertNotIn("payload", payload["events"][1])
        self.bus.recent.assert_called_once_with(50)

    def test_events_debug_clamps_limit_and_filters_since(self):
        self.bus.recent.return_value = [
            Event(
                "file_modified",
                {"path": "/tmp/old.py"},
                timestamp=datetime(2026, 5, 1, 15, 59, 0),
            ),
            Event(
                "app_activated",
                {"app_name": "Code"},
                timestamp=datetime(2026, 5, 1, 16, 1, 0),
            ),
        ]

        response = self.client.get("/events/debug?limit=500&since=2026-05-01T16:00:00")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["events"][0]["type"], "app_activated")
        self.assertEqual(payload["events"][0]["source"], "app")
        self.assertEqual(payload["events"][0]["privacy"], "public")
        self.bus.recent.assert_called_once_with(200)

    def test_events_debug_invalid_limit_uses_default(self):
        self.bus.recent.return_value = []

        response = self.client.get("/events/debug?limit=abc")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"events": [], "count": 0})
        self.bus.recent.assert_called_once_with(50)

    def test_events_debug_filters_by_event_metadata(self):
        self.bus.recent.return_value = [
            Event(
                "file_modified",
                {"path": "/tmp/Pulse/daemon/main.py"},
                timestamp=datetime(2026, 5, 1, 16, 0, 0),
            ),
            Event(
                "clipboard_updated",
                {"clipboard_context": "text", "length": 42},
                timestamp=datetime(2026, 5, 1, 16, 1, 0),
            ),
            Event(
                "app_activated",
                {"app_name": "Code"},
                timestamp=datetime(2026, 5, 1, 16, 2, 0),
            ),
        ]

        response = self.client.get(
            "/events/debug?source=clipboard&bucket=clipboard_activity&privacy=content_sensitive&retention=ephemeral"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["events"][0]["type"], "clipboard_updated")
        self.assertEqual(payload["events"][0]["source"], "clipboard")
        self.assertEqual(payload["events"][0]["bucket"], "clipboard_activity")
        self.assertEqual(payload["events"][0]["privacy"], "content_sensitive")
        self.assertEqual(payload["events"][0]["retention"], "ephemeral")
        self.bus.recent.assert_called_once_with(50)

    def test_events_schema_exposes_event_metadata_enums(self):
        response = self.client.get("/events/schema")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertIn("filesystem", payload["sources"])
        self.assertIn("terminal", payload["sources"])
        self.assertIn("unknown", payload["sources"])

        self.assertIn("filesystem", payload["buckets"])
        self.assertIn("terminal_activity", payload["buckets"])
        self.assertIn("unknown", payload["buckets"])

        self.assertIn("public", payload["privacy_classes"])
        self.assertIn("path_sensitive", payload["privacy_classes"])
        self.assertIn("content_sensitive", payload["privacy_classes"])
        self.assertIn("secret_sensitive", payload["privacy_classes"])
        self.assertIn("unknown", payload["privacy_classes"])

        self.assertIn("ephemeral", payload["retention_classes"])
        self.assertIn("session", payload["retention_classes"])
        self.assertIn("persistent", payload["retention_classes"])
        self.assertIn("debug_only", payload["retention_classes"])

    def test_timeline_preview_builds_span_from_current_context_when_signals_exist(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/Pulse/daemon/runtime.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=30,
            recent_apps=["Code"],
            clipboard_context="text",
            activity_level="editing",
            task_confidence=0.82,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Code")

        with patch("daemon.routes.runtime.find_git_root", return_value=None), \
             patch("daemon.routes.runtime.find_workspace_root", return_value=None):
            response = self.client.get("/timeline/preview")

        self.assertEqual(response.status_code, 200)
        span = response.get_json()["span"]
        self.assertEqual(span["kind"], "work")
        self.assertEqual(span["title"], "Pulse — coding")
        self.assertEqual(span["project"], "Pulse")
        self.assertEqual(span["activity_level"], "editing")
        self.assertEqual(span["probable_task"], "coding")
        self.assertEqual(span["confidence"], 0.82)
        self.assertEqual(span["buckets"], ["filesystem"])
        self.assertEqual(span["privacy"], "path_sensitive")
        self.assertEqual(span["retention"], "session")
        self.assertEqual(span["evidence_event_count"], 0)
        self.assertEqual(span["metadata"], {"source": "current_context"})
        self.assertEqual(span["duration_min"], 30)

    def test_timeline_preview_falls_back_to_present_when_no_signals_exist(self):
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="debug",
            friction_score=0.2,
            focus_level="normal",
            session_duration_min=5,
            recent_apps=["Terminal"],
            clipboard_context=None,
            activity_level="executing",
            task_confidence=0.91,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )

        response = self.client.get("/timeline/preview")

        self.assertEqual(response.status_code, 200)
        span = response.get_json()["span"]
        self.assertEqual(span["kind"], "debug")
        self.assertEqual(span["title"], "Pulse — debug")
        self.assertEqual(span["project"], "Pulse")
        self.assertEqual(span["activity_level"], "executing")
        self.assertEqual(span["probable_task"], "debug")
        self.assertEqual(span["confidence"], 0.0)
        self.assertEqual(span["buckets"], ["terminal_activity"])
        self.assertEqual(span["privacy"], "content_sensitive")
        self.assertEqual(span["duration_min"], 5)

    def test_daemon_pause_returns_legacy_payload(self):
        with patch("daemon.routes.runtime.threading.Thread", side_effect=lambda *a, **k: _DummyThread(*a, **k)):
            response = self.client.post("/daemon/pause")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "action": "pause", "paused": True},
        )
        self.assertTrue(self.runtime_state.is_paused())

    def test_daemon_resume_returns_legacy_payload(self):
        self.runtime_state.set_paused(True)
        with patch("daemon.routes.runtime.threading.Thread", side_effect=lambda *a, **k: _DummyThread(*a, **k)):
            response = self.client.post("/daemon/resume")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "action": "resume", "paused": False},
        )
        self.assertFalse(self.runtime_state.is_paused())

    def test_daemon_shutdown_returns_legacy_payload(self):
        with patch("daemon.routes.runtime.threading.Thread", side_effect=lambda *a, **k: _DummyThread(*a, **k)):
            response = self.client.post("/daemon/shutdown")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "action": "shutdown"},
        )
        self.shutdown_runtime.assert_called_once()

    def test_daemon_restart_returns_legacy_payload(self):
        with patch("daemon.routes.runtime.threading.Thread", side_effect=lambda *a, **k: _DummyThread(*a, **k)):
            response = self.client.post("/daemon/restart")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "action": "restart"},
        )
        self.shutdown_runtime.assert_called_once()


class TestFileEventCoalescer(unittest.TestCase):
    def setUp(self):
        self.emitted = []
        self.now = 100.0

        self.coalescer = _FileEventCoalescer(
            publisher=lambda event_type, payload, timestamp=None: self.emitted.append(
                (event_type, dict(payload), timestamp)
            ),
            time_fn=lambda: self.now,
            start_worker=False,
        )

    def _flush_last_pending(self):
        self.now += 2.0
        for emitted in self.coalescer._flush_due():
            self.emitted.append(emitted)

    def test_heterogeneous_burst_created_then_modified_emits_one_created(self):
        path = "/tmp/screenshot.png"

        self.coalescer.publish("file_created", {"path": path})
        self.coalescer.publish("file_modified", {"path": path})
        self._flush_last_pending()

        self.assertEqual(self.emitted, [("file_created", {"path": path}, None)])

    def test_heterogeneous_burst_renamed_then_modified_emits_one_renamed(self):
        path = "/tmp/screenshot.png"

        self.coalescer.publish("file_renamed", {"path": path})
        self.coalescer.publish("file_modified", {"path": path})
        self._flush_last_pending()

        self.assertEqual(self.emitted, [("file_renamed", {"path": path}, None)])

    def test_events_outside_window_remain_distinct(self):
        path = "/tmp/screenshot.png"

        self.coalescer.publish("file_created", {"path": path})
        self._flush_last_pending()

        self.now += 1.2
        self.coalescer.publish("file_modified", {"path": path})
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [
                ("file_created", {"path": path}, None),
                ("file_modified", {"path": path}, None),
            ],
        )

    def test_successive_modify_events_are_not_fused_by_new_rule(self):
        path = "/tmp/main.py"

        self.coalescer.publish("file_modified", {"path": path, "seq": 1})
        self.coalescer.publish("file_modified", {"path": path, "seq": 2})
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [
                ("file_modified", {"path": path, "seq": 1}, None),
                ("file_modified", {"path": path, "seq": 2}, None),
            ],
        )

    def test_coalescer_conserve_le_timestamp_source_retenu(self):
        path = "/tmp/main.py"
        created_at = datetime(2026, 4, 23, 9, 0, 0)
        modified_at = datetime(2026, 4, 23, 9, 0, 1)

        self.coalescer.publish("file_created", {"path": path}, created_at)
        self.coalescer.publish("file_modified", {"path": path}, modified_at)
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [("file_created", {"path": path}, created_at)],
        )

    def test_coalescer_reste_base_sur_fenetre_locale_pas_sur_ecart_source(self):
        path = "/tmp/main.py"
        created_at = datetime(2026, 4, 23, 9, 0, 0)
        modified_at = datetime(2026, 4, 23, 9, 15, 0)

        self.coalescer.publish("file_created", {"path": path}, created_at)
        self.coalescer.publish("file_modified", {"path": path}, modified_at)
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [("file_created", {"path": path}, created_at)],
        )


if __name__ == "__main__":
    unittest.main()