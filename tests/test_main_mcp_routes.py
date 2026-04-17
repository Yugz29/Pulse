import os
import tempfile
import unittest
from unittest.mock import patch

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ["HOME"] = _TEST_HOME

import daemon.main as daemon_main
from daemon.mcp import handlers as mcp_handlers


class TestMainMcpRoutes(unittest.TestCase):
    def setUp(self):
        daemon_main.runtime_state.reset_for_tests()
        daemon_main.runtime_orchestrator.reset_for_tests()
        mcp_handlers.reset_proposals_for_tests()
        daemon_main.bus.clear()
        self.client = daemon_main.app.test_client()

    def test_mcp_pending_returns_204_when_empty(self):
        with patch("daemon.main.get_pending_command", return_value=None):
            response = self.client.get("/mcp/pending")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.data, b"")

    def test_mcp_pending_returns_payload_when_present(self):
        pending = {"tool_use_id": "abc", "command": "ls"}
        with patch("daemon.main.get_pending_command", return_value=pending):
            response = self.client.get("/mcp/pending")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["tool_use_id"], "abc")

    def test_mcp_proposals_returns_history_payload(self):
        history = [{"tool_use_id": "tool-1", "status": "accepted"}]
        with patch("daemon.main.get_proposal_history", return_value=history):
            response = self.client.get("/mcp/proposals?limit=5")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["items"][0]["tool_use_id"], "tool-1")
        self.assertEqual(payload["items"][0]["status"], "accepted")

    def test_mcp_intercept_publishes_and_returns_result(self):
        result = {"decision": "allow", "allowed": True}
        with patch.object(daemon_main.bus, "publish") as publish, \
             patch("daemon.main.intercept_command", return_value=result) as intercept:
            response = self.client.post(
                "/mcp/intercept",
                json={"command": "ls -la", "tool_use_id": "tool-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["allowed"])
        intercept.assert_called_once_with("ls -la", "tool-1")
        self.assertEqual(publish.call_count, 2)

    def test_mcp_decision_delegates_and_publishes(self):
        with patch.object(daemon_main.bus, "publish") as publish, \
             patch("daemon.main.receive_decision", return_value=True) as receive:
            response = self.client.post(
                "/mcp/decision",
                json={"tool_use_id": "tool-1", "decision": "deny"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        receive.assert_called_once_with("tool-1", "deny")
        publish.assert_called_once()

    def test_e2e_intercept_pending_decision_flux(self):
        """
        Flux complet sans mock sur les handlers :
          1. POST /mcp/intercept lance l'interception en thread
          2. GET /mcp/pending retourne la commande en attente
          3. POST /mcp/decision résout la proposition
          4. La réponse d'intercept contient allowed=True
        """
        import threading, time
        from daemon.interpreter.command_interpreter import CommandInterpretation

        safe_interpretation = CommandInterpretation(
            original="ls -la",
            translated="Liste les fichiers du répertoire",
            risk_level="safe",
            risk_score=0,
            is_read_only=True,
            affects=[],
            warning=None,
            needs_llm=False,
        )

        result_box = {}

        def run_intercept():
            with patch.object(mcp_handlers.interpreter, "interpret", return_value=safe_interpretation), \
                 patch("daemon.mcp.handlers._log_interception"):
                result_box["result"] = mcp_handlers.intercept_command("ls -la", "e2e-tool-1")

        thread = threading.Thread(target=run_intercept, daemon=True)
        thread.start()

        # Attend que la proposition soit visible
        deadline = time.time() + 2.0
        pending_payload = None
        while time.time() < deadline:
            response = self.client.get("/mcp/pending")
            if response.status_code == 200:
                pending_payload = response.get_json()
                break
            time.sleep(0.02)

        self.assertIsNotNone(pending_payload, "La commande n'est pas apparue dans /mcp/pending")
        self.assertEqual(pending_payload["tool_use_id"], "e2e-tool-1")
        self.assertEqual(pending_payload["status"], "pending")
        self.assertEqual(pending_payload["risk_level"], "safe")

        # Résout via /mcp/decision
        decision_response = self.client.post(
            "/mcp/decision",
            json={"tool_use_id": "e2e-tool-1", "decision": "allow"},
        )
        self.assertEqual(decision_response.status_code, 200)
        self.assertTrue(decision_response.get_json()["ok"])

        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive(), "Le thread intercept n'a pas terminé")

        result = result_box.get("result")
        self.assertIsNotNone(result)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["status"], "accepted")

        # La file est vide après résolution
        self.assertEqual(self.client.get("/mcp/pending").status_code, 204)

    def test_scoring_status_returns_runtime_capabilities(self):
        with patch("daemon.main.get_scoring_status", return_value={
            "treesitter_core": True,
            "python_ast": True,
            "languages": {"swift": {"available": True, "parser": "treesitter"}},
        }):
            response = self.client.get("/scoring/status")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["treesitter_core"])
        self.assertTrue(payload["languages"]["swift"]["available"])


if __name__ == "__main__":
    unittest.main()
