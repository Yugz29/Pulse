import unittest
import os
import tempfile
from unittest.mock import patch

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ["HOME"] = _TEST_HOME

import daemon.main as daemon_main
from daemon.llm.unavailable import UnavailableLLMRouter


class TestMainLLMModels(unittest.TestCase):
    def setUp(self):
        daemon_main.runtime_state.reset_for_tests()
        daemon_main.runtime_orchestrator.reset_for_tests()
        self.client = daemon_main.app.test_client()

    def test_llm_models_reports_ready_when_online_and_model_is_selected(self):
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
        self.assertEqual(payload["selected_model"], "qwen2.5-coder:1.5b")
        self.assertTrue(payload["ollama_online"])
        self.assertTrue(payload["model_selected"])
        self.assertTrue(payload["llm_ready"])
        self.assertTrue(payload["llm_active"])

    def test_llm_models_reports_ready_without_declaring_active_when_provider_is_not_operational(self):
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
        self.assertEqual(payload["selected_model"], "qwen2.5-coder:1.5b")
        self.assertTrue(payload["ollama_online"])
        self.assertTrue(payload["model_selected"])
        self.assertTrue(payload["llm_ready"])
        self.assertFalse(payload["llm_active"])

    def test_llm_models_available_models_is_inventory_only(self):
        class _Provider:
            is_operational = False

        with patch("daemon.main.get_available_llm_models", return_value=["mistral"]), \
             patch("daemon.main.get_selected_command_llm_model", return_value=""), \
             patch("daemon.main.get_selected_summary_llm_model", return_value=""), \
             patch("daemon.main._ollama_ping", return_value=True), \
             patch("daemon.main._llm_provider", return_value=_Provider()):
            response = self.client.get("/llm/models")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["available_models"], ["mistral"])
        self.assertEqual(payload["selected_model"], "")
        self.assertTrue(payload["ollama_online"])
        self.assertFalse(payload["model_selected"])
        self.assertFalse(payload["llm_ready"])
        self.assertFalse(payload["llm_active"])

    def test_set_llm_model_returns_selected_model_as_primary_public_field(self):
        with patch("daemon.main.set_unified_model", return_value=True) as set_model, \
             patch("daemon.main._persist_selected_models") as persist, \
             patch("daemon.main.get_selected_command_llm_model", return_value="mistral"):
            response = self.client.post("/llm/model", json={"model": "mistral", "kind": "summary"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["selected_model"], "mistral")
        self.assertEqual(payload["selected_command_model"], "mistral")
        self.assertEqual(payload["selected_summary_model"], "mistral")
        set_model.assert_called_once_with("mistral")
        persist.assert_called_once()

    def test_set_llm_model_ignores_kind_for_unified_selection(self):
        with patch("daemon.main.set_unified_model", return_value=True), \
             patch("daemon.main._persist_selected_models"), \
             patch("daemon.main.get_selected_command_llm_model", return_value="mistral"):
            response = self.client.post("/llm/model", json={"model": "mistral", "kind": "command"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["selected_model"], "mistral")

    def test_ping_reflects_paused_runtime(self):
        daemon_main.runtime_state.set_paused(True)
        response = self.client.get("/ping")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["paused"])

    def test_ask_returns_400_when_message_is_missing(self):
        with patch("daemon.main.cognitive_ask") as cognitive_ask:
            response = self.client.post("/ask", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"ok": False, "error": "message requis"})
        cognitive_ask.assert_not_called()

    def test_pause_and_resume_routes_toggle_runtime(self):
        pause = self.client.post("/daemon/pause")
        self.assertEqual(pause.status_code, 200)
        self.assertTrue(pause.get_json()["paused"])
        self.assertTrue(daemon_main.runtime_state.is_paused())

        resume = self.client.post("/daemon/resume")
        self.assertEqual(resume.status_code, 200)
        self.assertFalse(resume.get_json()["paused"])
        self.assertFalse(daemon_main.runtime_state.is_paused())

    def test_build_summary_llm_returns_fallback_when_import_fails(self):
        with patch("daemon.main.importlib.import_module", side_effect=ModuleNotFoundError("no llm")):
            router = daemon_main._build_summary_llm()

        self.assertIsInstance(router, UnavailableLLMRouter)
        self.assertEqual(router.list_models(), [])


if __name__ == "__main__":
    unittest.main()
