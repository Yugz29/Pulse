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
             patch("daemon.mcp.handlers._log_interception"):
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

    def test_intercept_command_deny_via_decision(self):
        interpretation = CommandInterpretation(
            original="rm -rf /",
            translated="Supprime tout le système",
            risk_level="critical",
            risk_score=100,
            is_read_only=False,
            affects=["système"],
            warning=None,
            needs_llm=False,
        )
        result_box = {}

        def run_intercept():
            result_box["result"] = handlers.intercept_command("rm -rf /", "tool-2")

        with patch.object(handlers.interpreter, "interpret", return_value=interpretation), \
             patch("daemon.mcp.handlers._log_interception"):
            thread = threading.Thread(target=run_intercept, daemon=True)
            thread.start()

            deadline = time.time() + 1.0
            while handlers.get_pending_command() is None and time.time() < deadline:
                time.sleep(0.01)

            handlers.receive_decision("tool-2", "deny")
            thread.join(timeout=1.0)

        result = result_box.get("result")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "deny")
        self.assertEqual(result["status"], "refused")

    def test_receive_decision_returns_false_for_unknown_tool_use_id(self):
        ok = handlers.receive_decision("unknown-id", "allow")
        self.assertFalse(ok)

    def test_receive_decision_returns_false_for_invalid_decision_string(self):
        interpretation = CommandInterpretation(
            original="ls", translated="Liste les fichiers",
            risk_level="safe", risk_score=0,
            is_read_only=True, affects=[], warning=None, needs_llm=False,
        )
        proposal = handlers._build_risky_command_proposal(
            tool_use_id="tool-3", command="ls",
            interpretation=interpretation, translated="Liste les fichiers",
        )
        handlers.proposal_store.add(proposal)
        ok = handlers.receive_decision("tool-3", "maybe")
        self.assertFalse(ok)
        self.assertEqual(handlers.proposal_store.get("tool-3").status, "pending")

    def test_get_pending_command_returns_none_when_empty(self):
        self.assertIsNone(handlers.get_pending_command())

    def test_proposal_to_api_payload_contient_tous_les_champs_swift(self):
        """Tous les champs décodés par CommandAnalysis.swift doivent être présents."""
        interpretation = CommandInterpretation(
            original="rm -rf build",
            translated="Supprime le dossier build",
            risk_level="high",
            risk_score=80,
            is_read_only=False,
            affects=["fichiers"],
            warning="Action irréversible.",
            needs_llm=False,
        )
        proposal = handlers._build_risky_command_proposal(
            tool_use_id="tool-swift",
            command="rm -rf build",
            interpretation=interpretation,
            translated="Supprime le dossier build",
        )
        handlers.proposal_store.add(proposal)
        payload = handlers._proposal_to_api_payload(proposal)

        # Champs attendus par CommandAnalysis.swift (CodingKeys)
        required_swift_fields = [
            "tool_use_id", "command", "translated",
            "risk_level", "risk_score", "is_read_only",
            "affects", "warning", "needs_llm",
        ]
        for field in required_swift_fields:
            self.assertIn(field, payload, f"Champ manquant pour Swift : {field!r}")

        self.assertEqual(payload["tool_use_id"], "tool-swift")
        self.assertEqual(payload["risk_level"], "high")
        self.assertEqual(payload["risk_score"], 80)
        self.assertFalse(payload["is_read_only"])
        self.assertEqual(payload["warning"], "Action irréversible.")

    def test_get_proposal_history_limit_zero_retourne_liste_vide(self):
        self.assertEqual(handlers.get_proposal_history(limit=0), [])

    def test_translate_with_llm_logs_warning_on_failure(self):
        """_translate_with_llm doit logger un warning si le LLM échoue."""
        with patch.object(handlers.llm_router, "complete", side_effect=RuntimeError("offline")), \
             patch("daemon.mcp.handlers.log") as mock_log:
            result = handlers._translate_with_llm("unknowncmd", "fallback")

        self.assertEqual(result, "fallback")
        mock_log.warning.assert_called_once()
        warning_msg = mock_log.warning.call_args[0][0]
        self.assertIn("LLM", warning_msg)


if __name__ == "__main__":
    unittest.main()
