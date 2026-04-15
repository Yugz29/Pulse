import threading
import time
import unittest
from unittest.mock import patch

from daemon.core.proposals import Proposal
from daemon.interpreter.command_interpreter import CommandInterpretation
from daemon.mcp import handlers


class TestHandlersProposals(unittest.TestCase):
    def setUp(self):
        handlers.reset_proposals_for_tests()

    def test_get_pending_command_exposes_legacy_fields_and_proposal_metadata(self):
        interpretation = CommandInterpretation(
            original="rm -rf build",
            translated="Supprime le dossier build",
            risk_level="critical",
            risk_score=100,
            is_read_only=False,
            affects=["fichiers"],
            warning="Supprime définitivement des fichiers.",
            needs_llm=False,
        )
        proposal = handlers._build_risky_command_proposal(
            tool_use_id="tool-1",
            command="rm -rf build",
            interpretation=interpretation,
            translated="Supprime le dossier build",
        )
        handlers.proposal_store.add(proposal)

        pending = handlers.get_pending_command()

        self.assertIsNotNone(pending)
        self.assertEqual(pending["tool_use_id"], "tool-1")
        self.assertEqual(pending["type"], "risky_command")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(pending["translated"], "Supprime le dossier build")
        self.assertEqual(pending["risk_level"], "critical")
        self.assertIn("evidence", pending)

    def test_receive_decision_resolves_pending_proposal(self):
        interpretation = CommandInterpretation(
            original="rm -rf build",
            translated="Supprime le dossier build",
            risk_level="critical",
            risk_score=100,
            is_read_only=False,
            affects=["fichiers"],
            warning="Supprime définitivement des fichiers.",
            needs_llm=False,
        )
        proposal = handlers._build_risky_command_proposal(
            tool_use_id="tool-1",
            command="rm -rf build",
            interpretation=interpretation,
            translated="Supprime le dossier build",
        )
        handlers.proposal_store.add(proposal)

        ok = handlers.receive_decision("tool-1", "deny")

        self.assertTrue(ok)
        resolved = handlers.proposal_store.get("tool-1")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "refused")
        self.assertIsNone(handlers.get_pending_command())

    def test_get_proposal_history_returns_resolved_proposals_with_lifecycle(self):
        interpretation = CommandInterpretation(
            original="rm -rf build",
            translated="Supprime le dossier build",
            risk_level="critical",
            risk_score=100,
            is_read_only=False,
            affects=["fichiers"],
            warning="Supprime définitivement des fichiers.",
            needs_llm=False,
        )
        proposal = handlers._build_risky_command_proposal(
            tool_use_id="tool-1",
            command="rm -rf build",
            interpretation=interpretation,
            translated="Supprime le dossier build",
        )
        handlers.proposal_store.add(proposal)
        handlers.receive_decision("tool-1", "allow")

        history = handlers.get_proposal_history(limit=10)

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["tool_use_id"], "tool-1")
        self.assertEqual(history[0]["status"], "accepted")
        self.assertEqual(
            [event["status"] for event in history[0]["lifecycle"]],
            ["created", "pending", "accepted"],
        )

    def test_get_pending_command_ignores_non_command_proposals(self):
        handlers.proposal_store.add(
            Proposal(
                id="proposal-1",
                type="context_injection",
                trigger="file_modified",
                title="Contexte prêt",
                summary="Contexte prêt",
                rationale="Test",
                proposed_action="inject_current_context",
            )
        )

        self.assertIsNone(handlers.get_pending_command())
        self.assertEqual(handlers.get_pending_count(), 0)

    def test_intercept_command_uses_proposal_pipeline_and_preserves_response_contract(self):
        interpretation = CommandInterpretation(
            original="rm -rf build",
            translated="Supprime le dossier build",
            risk_level="critical",
            risk_score=100,
            is_read_only=False,
            affects=["fichiers"],
            warning="Supprime définitivement des fichiers.",
            needs_llm=False,
        )
        result_box = {}

        def run_intercept():
            result_box["result"] = handlers.intercept_command("rm -rf build", "tool-1")

        with patch.object(handlers.interpreter, "interpret", return_value=interpretation), \
             patch("daemon.mcp.handlers._print_interception"):
            thread = threading.Thread(target=run_intercept, daemon=True)
            thread.start()

            deadline = time.time() + 1.0
            while handlers.get_pending_command() is None and time.time() < deadline:
                time.sleep(0.01)

            pending = handlers.get_pending_command()
            self.assertIsNotNone(pending)
            self.assertEqual(pending["tool_use_id"], "tool-1")
            self.assertEqual(pending["status"], "pending")

            self.assertTrue(handlers.receive_decision("tool-1", "allow"))
            thread.join(timeout=1.0)

        result = result_box.get("result")
        self.assertIsNotNone(result)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["tool_use_id"], "tool-1")


if __name__ == "__main__":
    unittest.main()
