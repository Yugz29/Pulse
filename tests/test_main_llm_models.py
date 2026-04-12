import unittest
import os
import tempfile
from unittest.mock import patch

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ["HOME"] = _TEST_HOME

import daemon.main as daemon_main


class TestMainLLMModels(unittest.TestCase):
    def setUp(self):
        daemon_main.runtime_state.reset_for_tests()
        daemon_main.runtime_orchestrator.reset_for_tests()
        self.client = daemon_main.app.test_client()

    def test_llm_models_reports_active_when_provider_is_operational(self):
        class _Provider:
            is_operational = True

        with patch("daemon.main.get_available_llm_models", return_value=[]), \
             patch("daemon.main.get_selected_command_llm_model", return_value="qwen2.5-coder:1.5b"), \
             patch("daemon.main.get_selected_summary_llm_model", return_value="qwen2.5-coder:1.5b"), \
             patch("daemon.main._ollama_ping", return_value=True), \
             patch("daemon.main._llm_provider", return_value=_Provider()):
            response = self.client.get("/llm/models")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["available_models"], [])
        self.assertTrue(payload["ollama_online"])
        self.assertTrue(payload["llm_active"])

    def test_llm_models_reports_active_when_online_and_model_is_configured(self):
        class _Provider:
            is_operational = False

        with patch("daemon.main.get_available_llm_models", return_value=[]), \
             patch("daemon.main.get_selected_command_llm_model", return_value=""), \
             patch("daemon.main.get_selected_summary_llm_model", return_value="qwen2.5-coder:1.5b"), \
             patch("daemon.main._ollama_ping", return_value=True), \
             patch("daemon.main._llm_provider", return_value=_Provider()):
            response = self.client.get("/llm/models")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ollama_online"])
        self.assertTrue(payload["llm_active"])

    def test_ping_reflects_paused_runtime(self):
        daemon_main.runtime_state.set_paused(True)
        response = self.client.get("/ping")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["paused"])

    def test_pause_and_resume_routes_toggle_runtime(self):
        pause = self.client.post("/daemon/pause")
        self.assertEqual(pause.status_code, 200)
        self.assertTrue(pause.get_json()["paused"])
        self.assertTrue(daemon_main.runtime_state.is_paused())

        resume = self.client.post("/daemon/resume")
        self.assertEqual(resume.status_code, 200)
        self.assertFalse(resume.get_json()["paused"])
        self.assertFalse(daemon_main.runtime_state.is_paused())


if __name__ == "__main__":
    unittest.main()
