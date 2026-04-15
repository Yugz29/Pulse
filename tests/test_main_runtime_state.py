import os
import tempfile
import unittest
from unittest.mock import patch

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ["HOME"] = _TEST_HOME

import daemon.main as daemon_main
from daemon.core.decision_engine import Decision
from daemon.core.signal_scorer import Signals


class TestMainRuntimeState(unittest.TestCase):
    def setUp(self):
        daemon_main.runtime_state.reset_for_tests()
        daemon_main.runtime_orchestrator.reset_for_tests()
        daemon_main.bus.clear()
        self.client = daemon_main.app.test_client()

    def test_state_exposes_runtime_signals_and_decision(self):
        daemon_main.runtime_state.set_paused(True)
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
        )
        decision = Decision(
            action="notify",
            level=2,
            reason="high_friction",
            payload={"file": "PanelView.swift"},
        )
        daemon_main.runtime_state.set_analysis(signals=signals, decision=decision)

        with patch.object(
            daemon_main.store,
            "to_dict",
            return_value={"active_app": "Xcode", "session_duration_min": 96},
        ):
            response = self.client.get("/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["runtime_paused"])
        self.assertEqual(payload["active_app"], "Xcode")
        self.assertEqual(payload["signals"]["active_project"], "Pulse")
        self.assertEqual(payload["signals"]["probable_task"], "coding")
        self.assertEqual(payload["signals"]["edited_file_count_10m"], 4)
        self.assertEqual(payload["signals"]["file_type_mix_10m"]["source"], 2)
        self.assertEqual(payload["signals"]["dominant_file_mode"], "few_files")
        self.assertEqual(payload["signals"]["work_pattern_candidate"], "feature_candidate")
        self.assertEqual(payload["decision"]["action"], "notify")
        self.assertEqual(payload["decision"]["payload"]["file"], "PanelView.swift")

    def test_event_endpoint_ignores_events_while_runtime_is_paused(self):
        daemon_main.runtime_state.set_paused(True)

        with patch.object(daemon_main.bus, "publish") as publish:
            response = self.client.post(
                "/event",
                json={"type": "file_modified", "path": "/tmp/test.py"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["paused"])
        self.assertTrue(payload["ignored"])
        publish.assert_not_called()

    def test_insights_uses_default_limit_of_twenty_five(self):
        with patch.object(daemon_main.bus, "recent", return_value=[]) as recent:
            response = self.client.get("/insights")

        self.assertEqual(response.status_code, 200)
        recent.assert_called_once_with(25)

    def test_insights_falls_back_to_default_limit_on_invalid_value(self):
        with patch.object(daemon_main.bus, "recent", return_value=[]) as recent:
            response = self.client.get("/insights?limit=abc")

        self.assertEqual(response.status_code, 200)
        recent.assert_called_once_with(25)

    def test_insights_clamps_limit_to_one_hundred(self):
        with patch.object(daemon_main.bus, "recent", return_value=[]) as recent:
            response = self.client.get("/insights?limit=500")

        self.assertEqual(response.status_code, 200)
        recent.assert_called_once_with(100)

    def test_llm_models_reports_inactive_when_ollama_is_offline(self):
        class _Provider:
            is_operational = True

        with patch("daemon.main.get_available_llm_models", return_value=["mistral"]), \
             patch("daemon.main.get_selected_command_llm_model", return_value="mistral"), \
             patch("daemon.main.get_selected_summary_llm_model", return_value="mistral"), \
             patch("daemon.main._ollama_ping", return_value=False), \
             patch("daemon.main._llm_provider", return_value=_Provider()):
            response = self.client.get("/llm/models")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["ollama_online"])
        self.assertEqual(payload["selected_model"], "mistral")
        self.assertTrue(payload["model_selected"])
        self.assertFalse(payload["llm_ready"])
        self.assertFalse(payload["llm_active"])

    def test_llm_models_reports_inactive_when_online_without_model_or_provider(self):
        class _Provider:
            is_operational = False

        with patch("daemon.main.get_available_llm_models", return_value=[]), \
             patch("daemon.main.get_selected_command_llm_model", return_value=""), \
             patch("daemon.main.get_selected_summary_llm_model", return_value=""), \
             patch("daemon.main._ollama_ping", return_value=True), \
             patch("daemon.main._llm_provider", return_value=_Provider()):
            response = self.client.get("/llm/models")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ollama_online"])
        self.assertEqual(payload["selected_model"], "")
        self.assertFalse(payload["model_selected"])
        self.assertFalse(payload["llm_ready"])
        self.assertFalse(payload["llm_active"])


if __name__ == "__main__":
    unittest.main()
