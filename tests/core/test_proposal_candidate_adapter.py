import unittest

from daemon.core.contracts import ProposalCandidate
from daemon.core.proposal_candidate_adapter import proposal_candidate_to_proposal


class TestProposalCandidateAdapter(unittest.TestCase):
    def test_context_injection_adapter_golden_output_exact(self):
        candidate = ProposalCandidate(
            type="context_injection",
            trigger="file_modified",
            decision_action="inject_context",
            decision_reason="context_ready",
            confidence=0.66,
            proposed_action="inject_current_context",
            evidence=[
                {"kind": "project", "label": "Projet", "value": "Pulse"},
                {"kind": "task", "label": "Tâche", "value": "coding"},
                {"kind": "focus", "label": "Focus", "value": "normal"},
            ],
            details={
                "decision_action": "inject_context",
                "decision_reason": "context_ready",
                "project": "Pulse",
                "task": "coding",
                "focus_level": "normal",
                "session_duration_min": 25,
                "active_file": "/tmp/main.py",
                "edited_file_count_10m": 4,
                "file_type_mix_10m": {"source": 2, "test": 1, "docs": 1},
                "rename_delete_ratio_10m": 0.0,
                "dominant_file_mode": "few_files",
                "work_pattern_candidate": "feature_candidate",
                "decision_payload": {"project": "Pulse", "task": "coding"},
            },
        )

        proposal = proposal_candidate_to_proposal(
            candidate,
            proposal_id="proposal-123",
            created_at="2026-04-21T10:00:00",
            updated_at="2026-04-21T10:00:00",
        )

        expected = {
            "id": "proposal-123",
            "type": "context_injection",
            "trigger": "file_modified",
            "title": "Contexte de session prêt à être injecté",
            "summary": "Le contexte local est jugé assez riche pour une réponse assistée.",
            "rationale": "La session a accumulé assez de contexte local pour justifier une injection de contexte existante.",
            "evidence": [
                {"kind": "project", "label": "Projet", "value": "Pulse"},
                {"kind": "task", "label": "Tâche", "value": "coding"},
                {"kind": "focus", "label": "Focus", "value": "normal"},
            ],
            "confidence": 0.66,
            "proposed_action": "inject_current_context",
            "status": "pending",
            "created_at": "2026-04-21T10:00:00",
            "updated_at": "2026-04-21T10:00:00",
            "decided_at": None,
            "lifecycle": [
                {"status": "created", "at": "2026-04-21T10:00:00"},
                {"status": "pending", "at": "2026-04-21T10:00:00"},
            ],
            "metadata": {
                "details": {
                    "decision_action": "inject_context",
                    "decision_reason": "context_ready",
                    "project": "Pulse",
                    "task": "coding",
                    "focus_level": "normal",
                    "session_duration_min": 25,
                    "active_file": "/tmp/main.py",
                    "edited_file_count_10m": 4,
                    "file_type_mix_10m": {"source": 2, "test": 1, "docs": 1},
                    "rename_delete_ratio_10m": 0.0,
                    "dominant_file_mode": "few_files",
                    "work_pattern_candidate": "feature_candidate",
                    "decision_payload": {"project": "Pulse", "task": "coding"},
                }
            },
        }

        self.assertEqual(proposal.to_dict(), expected)

    def test_risky_command_adapter_preserves_transport_and_legacy_payload(self):
        candidate = ProposalCandidate(
            type="risky_command",
            trigger="mcp_intercept",
            decision_action="allow_shell_command",
            decision_reason="mcp_interception",
            confidence=0.96,
            proposed_action="allow_shell_command",
            evidence=[
                {"kind": "command", "label": "Commande", "value": "rm -rf build"},
                {"kind": "risk", "label": "Risque", "value": "critical (100/100)"},
            ],
            details={
                "decision_action": "allow_shell_command",
                "decision_reason": "mcp_interception",
                "translated": "Supprime le dossier build",
                "rationale": "Supprime définitivement des fichiers.",
            },
            transport={
                "tool_use_id": "tool-1",
                "command": "rm -rf build",
                "translated": "Supprime le dossier build",
                "risk_level": "critical",
                "risk_score": 100,
                "is_read_only": False,
                "affects": ["fichiers"],
                "warning": "Supprime définitivement des fichiers.",
                "needs_llm": False,
            },
        )

        proposal = proposal_candidate_to_proposal(
            candidate,
            proposal_id="tool-1",
            created_at="2026-04-21T10:00:00",
            updated_at="2026-04-21T10:00:00",
        )

        expected = {
            "id": "tool-1",
            "type": "risky_command",
            "trigger": "mcp_intercept",
            "title": "Supprime le dossier build",
            "summary": "Supprime le dossier build",
            "rationale": "Supprime définitivement des fichiers.",
            "evidence": [
                {"kind": "command", "label": "Commande", "value": "rm -rf build"},
                {"kind": "risk", "label": "Risque", "value": "critical (100/100)"},
            ],
            "confidence": 0.96,
            "proposed_action": "allow_shell_command",
            "status": "pending",
            "created_at": "2026-04-21T10:00:00",
            "updated_at": "2026-04-21T10:00:00",
            "decided_at": None,
            "lifecycle": [
                {"status": "created", "at": "2026-04-21T10:00:00"},
                {"status": "pending", "at": "2026-04-21T10:00:00"},
            ],
            "metadata": {
                "details": {
                    "decision_action": "allow_shell_command",
                    "decision_reason": "mcp_interception",
                    "translated": "Supprime le dossier build",
                    "rationale": "Supprime définitivement des fichiers.",
                },
                "transport": {
                    "tool_use_id": "tool-1",
                    "command": "rm -rf build",
                    "translated": "Supprime le dossier build",
                    "risk_level": "critical",
                    "risk_score": 100,
                    "is_read_only": False,
                    "affects": ["fichiers"],
                    "warning": "Supprime définitivement des fichiers.",
                    "needs_llm": False,
                },
            },
        }

        self.assertEqual(proposal.to_dict(), expected)


if __name__ == "__main__":
    unittest.main()
