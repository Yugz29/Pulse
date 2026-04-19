"""
test_stdio_server.py — Tests du fallback MCP quand le daemon est injoignable.

Couvre uniquement le comportement de handle_request() lorsque _post_daemon()
retourne None (daemon arrêté, crash, réseau coupé).

Cas testés :
  - Commande risquée (rm -rf) → refusée, warning présent
  - Commande read-only (ls) → autorisée, pas de warning daemon
  - Commande git write (git push) → refusée
  - Commande git read (git log) → autorisée
"""

import unittest
from unittest.mock import patch

from daemon.mcp.stdio_server import handle_request


def _make_tool_call(command: str, tool_use_id: str = "test-id") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "analyze_command",
            "arguments": {
                "command": command,
                "tool_use_id": tool_use_id,
            },
        },
    }


def _call_with_daemon_down(command: str) -> dict:
    """Simule un appel avec le daemon injoignable."""
    with patch("daemon.mcp.stdio_server._post_daemon", return_value=None):
        resp = handle_request(_make_tool_call(command))
    return resp


class TestStdioServerFallback(unittest.TestCase):

    # ── Commandes risquées : toujours refusées sans daemon ────────────────────

    def test_rm_rf_refuse_si_daemon_injoignable(self):
        resp = _call_with_daemon_down("rm -rf /tmp/test")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Refusé", text, "rm -rf doit être refusé quand le daemon est down")
        self.assertIn("Ne pas l'exécuter", text)

    def test_rm_rf_warning_daemon_injoignable_present(self):
        resp = _call_with_daemon_down("rm -rf /tmp/test")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Daemon Pulse injoignable", text,
            "Le warning doit expliquer pourquoi la commande est refusée")

    def test_git_push_force_refuse_si_daemon_injoignable(self):
        resp = _call_with_daemon_down("git push --force")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Refusé", text)
        self.assertIn("Ne pas l'exécuter", text)

    def test_pip_install_refuse_si_daemon_injoignable(self):
        resp = _call_with_daemon_down("pip install requests")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Refusé", text)

    # ── Commandes read-only : autorisées sans daemon ──────────────────────────

    def test_ls_autorise_si_daemon_injoignable(self):
        resp = _call_with_daemon_down("ls -la")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Autorisé", text, "ls est read-only et doit passer même sans daemon")
        self.assertNotIn("Ne pas l'exécuter", text)

    def test_cat_autorise_si_daemon_injoignable(self):
        resp = _call_with_daemon_down("cat README.md")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Autorisé", text)

    def test_git_log_autorise_si_daemon_injoignable(self):
        resp = _call_with_daemon_down("git log --oneline -10")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Autorisé", text, "git log est read-only et doit passer")

    def test_git_status_autorise_si_daemon_injoignable(self):
        resp = _call_with_daemon_down("git status")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Autorisé", text)

    def test_git_diff_autorise_si_daemon_injoignable(self):
        resp = _call_with_daemon_down("git diff")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Autorisé", text)

    # ── Pas de faux warning daemon sur commandes autorisées ───────────────────

    def test_pas_de_warning_daemon_sur_commande_safe(self):
        resp = _call_with_daemon_down("ls")
        text = resp["result"]["content"][0]["text"]
        self.assertNotIn("Daemon Pulse injoignable", text,
            "Le warning daemon ne doit pas apparaître pour une commande autorisée")

    # ── Format de réponse intact ──────────────────────────────────────────────

    def test_reponse_est_jsonrpc_valide(self):
        resp = _call_with_daemon_down("rm -rf /")
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        self.assertIn("result", resp)
        self.assertIn("content", resp["result"])

    def test_risk_level_present_dans_reponse(self):
        resp = _call_with_daemon_down("rm -rf /tmp/test")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Risque", text, "Le niveau de risque doit être visible dans la réponse")


if __name__ == "__main__":
    unittest.main()
