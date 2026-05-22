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

    def _interpretation(
        self,
        *,
        original="rm -rf build",
        translated="Supprime le dossier build",
        risk_level="critical",
        risk_score=100,
        is_read_only=False,
        affects=None,
        warning="Supprime définitivement des fichiers.",
        needs_llm=False,
    ):
        return CommandInterpretation(
            original=original,
            translated=translated,
            risk_level=risk_level,
            risk_score=risk_score,
            is_read_only=is_read_only,
            affects=list(affects or ["fichiers"]),
            warning=warning,
            needs_llm=needs_llm,
        )

    def _add_risky_command_proposal(self, *, tool_use_id="tool-1", interpretation=None):
        interpretation = interpretation or self._interpretation()
        candidate = handlers._build_risky_command_candidate(
            tool_use_id=tool_use_id,
            command=interpretation.original,
            interpretation=interpretation,
            translated=interpretation.translated,
        )
        proposal = handlers.proposal_candidate_to_proposal(candidate, proposal_id=tool_use_id)
        handlers.proposal_store.add(proposal)
        return proposal

    def test_get_pending_command_exposes_legacy_fields_and_proposal_metadata(self):
        self._add_risky_command_proposal()

        pending = handlers.get_pending_command()

        self.assertIsNotNone(pending)
        self.assertEqual(pending["tool_use_id"], "tool-1")
        self.assertEqual(pending["type"], "risky_command")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(pending["translated"], "Supprime le dossier build")
        self.assertEqual(pending["risk_level"], "critical")
        self.assertIn("evidence", pending)

    def test_receive_decision_resolves_pending_proposal(self):
        self._add_risky_command_proposal()

        ok = handlers.receive_decision("tool-1", "deny")

        self.assertTrue(ok)
        resolved = handlers.proposal_store.get("tool-1")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "refused")
        self.assertIsNone(handlers.get_pending_command())

    def test_receive_decision_allow_resolves_to_accepted(self):
        self._add_risky_command_proposal()

        ok = handlers.receive_decision("tool-1", "allow")

        self.assertTrue(ok)
        resolved = handlers.proposal_store.get("tool-1")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "accepted")
        self.assertEqual(
            [event["status"] for event in resolved.lifecycle],
            ["created", "pending", "accepted"],
        )

    def test_get_proposal_history_returns_resolved_proposals_with_lifecycle(self):
        self._add_risky_command_proposal()
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
        interpretation = self._interpretation()
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

    def test_intercept_command_ne_retourne_allowed_true_que_si_status_accepted(self):
        interpretation = self._interpretation()
        statuses = ["refused", "expired", "executed"]

        for status in statuses:
            with self.subTest(status=status):
                handlers.reset_proposals_for_tests()

                def resolve_with_status(proposal_id, timeout):
                    proposal = handlers.proposal_store.get(proposal_id)
                    proposal.set_status(status)
                    return proposal

                with patch.object(handlers.interpreter, "interpret", return_value=interpretation), \
                     patch.object(handlers.proposal_store, "wait_for_resolution", side_effect=resolve_with_status), \
                     patch("daemon.mcp.handlers._log_interception"):
                    result = handlers.intercept_command("rm -rf build", f"tool-{status}")

                self.assertFalse(result["allowed"])
                self.assertEqual(result["decision"], "deny")
                self.assertEqual(result["status"], status)

    def test_intercept_command_timeout_expire_refuse_par_defaut(self):
        interpretation = self._interpretation()

        def expire_immediately(proposal_id, timeout):
            proposal = handlers.proposal_store.get(proposal_id)
            proposal.set_status("expired")
            return proposal

        with patch.object(handlers.interpreter, "interpret", return_value=interpretation), \
             patch.object(handlers.proposal_store, "wait_for_resolution", side_effect=expire_immediately), \
             patch("daemon.mcp.handlers._log_interception"), \
             patch("daemon.mcp.handlers.log") as log:
            result = handlers.intercept_command("rm -rf build", "tool-timeout")

        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "deny")
        self.assertEqual(result["status"], "expired")
        self.assertEqual(handlers.proposal_store.get("tool-timeout").status, "expired")
        log.warning.assert_called_once()

    def test_intercept_command_deny_via_decision(self):
        interpretation = self._interpretation(
            original="rm -rf /",
            translated="Supprime tout le système",
            risk_level="critical",
            risk_score=100,
            is_read_only=False,
            affects=["système"],
            warning=None,
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
        interpretation = self._interpretation(
            original="ls",
            translated="Liste les fichiers",
            risk_level="safe",
            risk_score=0,
            is_read_only=True,
            affects=[],
            warning=None,
        )
        self._add_risky_command_proposal(tool_use_id="tool-3", interpretation=interpretation)
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
        candidate = handlers._build_risky_command_candidate(
            tool_use_id="tool-swift",
            command="rm -rf build",
            interpretation=interpretation,
            translated="Supprime le dossier build",
        )
        proposal = handlers.proposal_candidate_to_proposal(candidate, proposal_id="tool-swift")
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

    def test_build_risky_command_candidate_preserves_business_and_transport_data(self):
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

        candidate = handlers._build_risky_command_candidate(
            tool_use_id="tool-meta",
            command="rm -rf build",
            interpretation=interpretation,
            translated="Supprime le dossier build",
        )

        self.assertEqual(candidate.type, "risky_command")
        self.assertEqual(candidate.trigger, "mcp_intercept")
        self.assertEqual(candidate.decision_action, "allow_shell_command")
        self.assertEqual(candidate.decision_reason, "mcp_interception")
        self.assertEqual(candidate.details["translated"], "Supprime le dossier build")
        self.assertEqual(candidate.details["rationale"], "Action irréversible.")
        self.assertEqual(candidate.transport["tool_use_id"], "tool-meta")
        self.assertEqual(candidate.transport["risk_level"], "high")
        self.assertEqual(candidate.transport["warning"], "Action irréversible.")

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
