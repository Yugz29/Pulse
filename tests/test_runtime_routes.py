import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from daemon.core.contracts import CurrentContext, SignalSummary
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
        self.runtime_state.set_analysis(
            signals=signals,
            decision=decision,
            current_context=CurrentContext(
                active_project="Pulse",
                project_root="/Users/yugz/Projets/Pulse/Pulse",
                active_file="/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
                active_app="Xcode",
                session_duration_min=96,
                activity_level="editing",
                probable_task="coding",
                task_confidence=0.81,
                focus_level="deep",
                clipboard_context="text",
                signal_summary=SignalSummary(
                    recent_apps=["Xcode", "Codex", "Safari"],
                    edited_file_count_10m=4,
                    file_type_mix_10m={"source": 2, "test": 1, "docs": 1},
                    rename_delete_ratio_10m=0.25,
                    dominant_file_mode="few_files",
                    work_pattern_candidate="feature_candidate",
                ),
            ),
        )

        self.store.to_dict.return_value = {
            "active_app": "Xcode",
            "session_duration_min": 96,
        }

        expected = {
            "active_app": "Xcode",
            "session_duration_min": 96,
            "runtime_paused": True,
            "signals": {
                "active_project": "Pulse",
                "active_file": "/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
                "probable_task": "coding",
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
        self.assertEqual(payload["signals"]["active_project"], "Pulse")
        self.assertEqual(payload["signals"]["active_file"], "/tmp/main.py")
        self.assertEqual(payload["signals"]["session_duration_min"], 24)

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
        self.timers = []

        def timer_factory(interval, callback, args=None, kwargs=None):
            timer = _ManualTimer(interval, callback, args=args, kwargs=kwargs)
            self.timers.append(timer)
            return timer

        self.coalescer = _FileEventCoalescer(
            publisher=lambda event_type, payload: self.emitted.append((event_type, dict(payload))),
            timer_factory=timer_factory,
            time_fn=lambda: self.now,
        )

    def _flush_last_pending(self):
        self.timers[-1].fire()

    def test_heterogeneous_burst_created_then_modified_emits_one_created(self):
        path = "/tmp/screenshot.png"

        self.coalescer.publish("file_created", {"path": path})
        self.coalescer.publish("file_modified", {"path": path})
        self._flush_last_pending()

        self.assertEqual(self.emitted, [("file_created", {"path": path})])

    def test_heterogeneous_burst_renamed_then_modified_emits_one_renamed(self):
        path = "/tmp/screenshot.png"

        self.coalescer.publish("file_renamed", {"path": path})
        self.coalescer.publish("file_modified", {"path": path})
        self._flush_last_pending()

        self.assertEqual(self.emitted, [("file_renamed", {"path": path})])

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
                ("file_created", {"path": path}),
                ("file_modified", {"path": path}),
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
                ("file_modified", {"path": path, "seq": 1}),
                ("file_modified", {"path": path, "seq": 2}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
