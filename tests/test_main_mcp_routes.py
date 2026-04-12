import os
import tempfile
import unittest
from unittest.mock import patch

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ["HOME"] = _TEST_HOME

import daemon.main as daemon_main


class TestMainMcpRoutes(unittest.TestCase):
    def setUp(self):
        daemon_main.runtime_state.reset_for_tests()
        daemon_main.runtime_orchestrator.reset_for_tests()
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
