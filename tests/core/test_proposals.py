import threading
import time
import unittest

from daemon.core.proposals import Proposal, ProposalStore


class TestProposalStore(unittest.TestCase):
    def setUp(self):
        self.store = ProposalStore()

    def _proposal(self, proposal_id="proposal-1", proposal_type="risky_command"):
        return Proposal(
            id=proposal_id,
            type=proposal_type,
            trigger="mcp_intercept" if proposal_type == "risky_command" else "file_modified",
            title="Commande",
            summary="Commande",
            rationale="Test",
            proposed_action="allow_shell_command" if proposal_type == "risky_command" else "inject_current_context",
        )

    def test_add_and_get_pending(self):
        proposal = self._proposal()
        self.store.add(proposal)

        pending = self.store.get_pending()

        self.assertIsNotNone(pending)
        self.assertEqual(pending.id, "proposal-1")
        self.assertEqual(pending.status, "pending")
        self.assertEqual(
            [event["status"] for event in pending.lifecycle],
            ["created", "pending"],
        )

    def test_add_refuses_non_pending_proposal(self):
        proposal = self._proposal()
        proposal.set_status("accepted")

        with self.assertRaises(ValueError):
            self.store.add(proposal)

    def test_resolve_updates_status_and_timestamps(self):
        proposal = self._proposal()
        self.store.add(proposal)

        resolved = self.store.resolve("proposal-1", "accepted")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "accepted")
        self.assertIsNotNone(resolved.decided_at)
        self.assertIsNone(self.store.get_pending())
        self.assertEqual(
            [event["status"] for event in resolved.lifecycle],
            ["created", "pending", "accepted"],
        )

    def test_pending_to_refused_updates_lifecycle(self):
        proposal = self._proposal()
        self.store.add(proposal)

        resolved = self.store.resolve("proposal-1", "refused")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "refused")
        self.assertIsNotNone(resolved.decided_at)
        self.assertEqual(
            [event["status"] for event in resolved.lifecycle],
            ["created", "pending", "refused"],
        )

    def test_wait_for_resolution_returns_resolved_proposal(self):
        proposal = self._proposal()
        self.store.add(proposal)

        def resolve_later():
            time.sleep(0.02)
            self.store.resolve("proposal-1", "refused")

        threading.Thread(target=resolve_later, daemon=True).start()
        resolved = self.store.wait_for_resolution("proposal-1", timeout=0.5)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "refused")

    def test_wait_for_resolution_expires_after_timeout(self):
        proposal = Proposal(
            id="proposal-1",
            type="risky_command",
            trigger="mcp_intercept",
            title="Supprime des fichiers",
            summary="Supprime des fichiers",
            rationale="Commande destructive détectée",
            proposed_action="allow_shell_command",
        )
        self.store.add(proposal)

        resolved = self.store.wait_for_resolution("proposal-1", timeout=0.01)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "expired")
        self.assertIsNotNone(resolved.decided_at)
        self.assertEqual(
            [event["status"] for event in resolved.lifecycle],
            ["created", "pending", "expired"],
        )

    def test_resolve_returns_none_for_unknown_or_already_terminal_proposal(self):
        proposal = self._proposal()
        self.store.add(proposal)

        first = self.store.resolve("proposal-1", "accepted")
        unknown = self.store.resolve("missing", "accepted")
        second = self.store.resolve("proposal-1", "refused")

        self.assertIsNotNone(first)
        self.assertIsNone(unknown)
        self.assertIsNone(second)
        self.assertEqual(proposal.status, "accepted")
        self.assertEqual(
            [event["status"] for event in proposal.lifecycle],
            ["created", "pending", "accepted"],
        )

    def test_pending_to_executed_is_possible_but_dangerous_outside_core_r6(self):
        proposal = self._proposal(proposal_type="context_injection")
        self.store.add(proposal)

        resolved = self.store.resolve("proposal-1", "executed")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "executed")
        self.assertIsNotNone(resolved.decided_at)
        self.assertEqual(
            [event["status"] for event in resolved.lifecycle],
            ["created", "pending", "executed"],
        )

    def test_list_history_keeps_resolved_proposals_in_reverse_creation_order(self):
        proposal_1 = self._proposal("proposal-1")
        proposal_2 = self._proposal("proposal-2")
        self.store.add(proposal_1)
        self.store.add(proposal_2)
        self.store.resolve("proposal-1", "accepted")

        history = self.store.list_history()

        self.assertEqual([proposal.id for proposal in history], ["proposal-2", "proposal-1"])
        self.assertEqual(history[1].status, "accepted")

    def test_proposal_validation_rejects_invalid_conventions(self):
        with self.assertRaises(ValueError):
            Proposal(
                id="proposal-1",
                type="RiskyCommand",
                trigger="mcp_intercept",
                title="Commande",
                summary="Commande",
                rationale="Test",
                proposed_action="allow_shell_command",
            )

    def test_proposal_validation_rejects_non_pending_initial_status(self):
        with self.assertRaises(ValueError):
            Proposal(
                id="proposal-1",
                type="risky_command",
                trigger="mcp_intercept",
                title="Commande",
                summary="Commande",
                rationale="Test",
                proposed_action="allow_shell_command",
                status="accepted",
            )

    def test_proposal_validation_rejects_unknown_metadata_namespace(self):
        with self.assertRaises(ValueError):
            Proposal(
                id="proposal-1",
                type="risky_command",
                trigger="mcp_intercept",
                title="Commande",
                summary="Commande",
                rationale="Test",
                proposed_action="allow_shell_command",
                metadata={"foo": {"bar": 1}},
            )

    def test_add_rejects_duplicate_ids(self):
        proposal = self._proposal()
        self.store.add(proposal)

        with self.assertRaises(ValueError):
            self.store.add(proposal)

    def test_resolve_rejects_non_terminal_status(self):
        proposal = self._proposal()
        self.store.add(proposal)

        with self.assertRaises(ValueError):
            self.store.resolve("proposal-1", "pending")

    def test_set_status_rejects_terminal_to_terminal_transition(self):
        proposal = self._proposal()

        proposal.set_status("accepted")

        with self.assertRaises(ValueError):
            proposal.set_status("refused")

    def test_list_pending_can_filter_by_type(self):
        risky = self._proposal("proposal-1")
        context = self._proposal("proposal-2", proposal_type="context_injection")
        self.store.add(risky)
        self.store.add(context)

        pending = self.store.list_pending(proposal_type="risky_command")

        self.assertEqual([proposal.id for proposal in pending], ["proposal-1"])

    def test_list_pending_without_filter_returns_only_pending_proposals(self):
        accepted = self._proposal("proposal-1")
        refused = self._proposal("proposal-2")
        pending = self._proposal("proposal-3", proposal_type="context_injection")
        self.store.add(accepted)
        self.store.add(refused)
        self.store.add(pending)
        self.store.resolve("proposal-1", "accepted")
        self.store.resolve("proposal-2", "refused")

        pending_items = self.store.list_pending()

        self.assertEqual([proposal.id for proposal in pending_items], ["proposal-3"])


if __name__ == "__main__":
    unittest.main()
