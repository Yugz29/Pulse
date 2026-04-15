import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from daemon.core.event_bus import Event
from daemon.core.decision_engine import Decision
from daemon.core.proposals import proposal_store
from daemon.core.signal_scorer import Signals
from daemon.runtime_orchestrator import RuntimeOrchestrator
from daemon.runtime_state import RuntimeState


class TestRuntimeOrchestrator(unittest.TestCase):
    def setUp(self):
        proposal_store.clear()
        self.store = MagicMock()
        self.scorer = MagicMock()
        self.decision_engine = MagicMock()
        self.summary_llm = MagicMock()
        self.session_memory = MagicMock()
        self.memory_store = MagicMock()
        self.runtime_state = RuntimeState()
        self.llm_runtime = MagicMock()
        self.log = MagicMock()

        # Mock FactEngine — évite toute dépendance sur ~/.pulse/facts.db dans les tests
        self.mock_fact_engine = MagicMock()
        self.mock_fact_engine.render_for_context.return_value = ""
        self.mock_fact_engine.decay_all.return_value = 0

        # memory_store.render doit retourner une str (pas un MagicMock)
        self.memory_store.render.return_value = ""

        with patch("daemon.runtime_orchestrator.get_fact_engine", return_value=self.mock_fact_engine):
            self.orchestrator = RuntimeOrchestrator(
                store=self.store,
                scorer=self.scorer,
                decision_engine=self.decision_engine,
                summary_llm=self.summary_llm,
                session_memory=self.session_memory,
                memory_store=self.memory_store,
                runtime_state=self.runtime_state,
                llm_runtime=self.llm_runtime,
                log=self.log,
                commit_poll_sec=0.0,
                commit_confirm_timeout_sec=0.5,
            )

    def test_build_context_snapshot_includes_state_signals_decision_and_memory(self):
        self.store.to_dict.return_value = {
            "active_project": "Pulse",
            "active_file": "/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
            "active_app": "Xcode",
            "session_duration_min": 96,
            "last_event_type": "file_modified",
        }
        self.session_memory.export_session_data.return_value = {
            "session_id": "session-1",
            "files_changed": 4,
            "event_count": 12,
            "max_friction": 0.72,
        }
        self.session_memory.get_recent_events.return_value = [
            {
                "timestamp": "2026-04-12T20:00:00",
                "type": "file_modified",
                "payload": {"path": "/tmp/main.py"},
            }
        ]
        self.runtime_state.set_analysis(
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                friction_score=0.72,
                focus_level="deep",
                session_duration_min=96,
                recent_apps=["Xcode", "Codex"],
                clipboard_context="text",
                edited_file_count_10m=5,
                file_type_mix_10m={"source": 3, "test": 1, "docs": 1},
                rename_delete_ratio_10m=0.2,
                dominant_file_mode="multi_file",
                work_pattern_candidate="feature_candidate",
            ),
            decision=Decision(
                action="notify",
                level=2,
                reason="high_friction",
                payload={"file": "main.py"},
            ),
        )
        self.orchestrator._frozen_memory = "Projet: Pulse"

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("# Contexte session", snapshot)
        self.assertIn("- Projet : Pulse", snapshot)
        self.assertIn("- Tâche probable : coding", snapshot)
        self.assertIn("- Fichiers touchés (10 min) : 5", snapshot)
        self.assertIn("- Mode de travail fichiers : multi_file", snapshot)
        self.assertIn("- Pattern de travail candidat : feature_candidate", snapshot)

    def test_freeze_memory_uses_structured_memory_first(self):
        self.memory_store.render.return_value = "Structured memory"

        self.orchestrator.freeze_memory()

        self.assertEqual(self.orchestrator.get_frozen_memory(), "Structured memory")
        self.assertIsInstance(self.orchestrator.get_frozen_memory_at(), datetime)

    def test_deferred_startup_loads_models_purges_memory_and_warms_provider(self):
        provider = MagicMock()
        provider.model = "gemma4:e4b"
        provider.warmup.return_value = True
        self.llm_runtime.provider.return_value = provider
        self.memory_store.purge_expired.return_value = 2

        with patch("daemon.runtime_orchestrator.time.sleep", return_value=None):
            self.orchestrator.deferred_startup()

        self.llm_runtime.load_persisted_models.assert_called_once()
        self.memory_store.purge_expired.assert_called_once()
        provider.warmup.assert_called_once()

    def test_handle_commit_event_waits_for_new_head_before_processing(self):
        git_root = Path("/tmp/Pulse")

        with patch("daemon.runtime_orchestrator.find_git_root", return_value=git_root), \
             patch("daemon.runtime_orchestrator.read_head_sha", side_effect=["old", "old", "new"]), \
             patch("daemon.runtime_orchestrator.time.sleep", return_value=None), \
             patch.object(self.orchestrator, "_process_confirmed_commit") as process_commit:
            self.orchestrator._handle_commit_event("/tmp/Pulse/.git/COMMIT_EDITMSG")

        process_commit.assert_called_once_with(git_root)

    def test_handle_commit_event_processes_recent_head_immediately_on_first_seen_commit(self):
        git_root = Path("/tmp/Pulse")

        with patch("daemon.runtime_orchestrator.find_git_root", return_value=git_root), \
             patch("daemon.runtime_orchestrator.read_head_sha", return_value="new"), \
             patch.object(self.orchestrator, "_head_commit_is_recent", return_value=True), \
             patch.object(self.orchestrator, "_process_confirmed_commit") as process_commit:
            self.orchestrator._handle_commit_event("/tmp/Pulse/.git/COMMIT_EDITMSG")

        process_commit.assert_called_once_with(git_root)

    def test_summary_llm_for_commit_only(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.1,
            focus_level="deep",
            session_duration_min=45,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )

        self.assertIs(self.orchestrator._summary_llm_for("commit", signals), self.summary_llm)

    def test_summary_llm_for_screen_locked_is_disabled(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.1,
            focus_level="deep",
            session_duration_min=45,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )

        self.assertIsNone(self.orchestrator._summary_llm_for("screen_locked", signals))

    def test_summary_llm_for_user_idle_is_disabled(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.1,
            focus_level="deep",
            session_duration_min=45,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )

        self.assertIsNone(self.orchestrator._summary_llm_for("user_idle", signals))

    def test_summary_llm_for_idle_focus_is_disabled_when_not_commit(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.1,
            focus_level="idle",
            session_duration_min=45,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )

        self.assertIsNone(self.orchestrator._summary_llm_for("screen_unlocked", signals))

    def test_commit_summary_logs_success_terminal_status(self):
        snapshot = {"active_project": "Pulse"}
        with patch("daemon.runtime_orchestrator.enrich_session_report", return_value=True):
            self.orchestrator._enrich_commit_summary_background(
                report_ref=("journal.md", "entry-1"),
                snapshot=snapshot,
                llm=self.summary_llm,
                commit_message="fix: bug",
                diff_summary="diff",
            )

        messages = [call[0][0] for call in self.log.info.call_args_list if call[0]]
        self.assertTrue(any("llm_request_terminal" in msg for msg in messages))
        terminal = next(msg for msg in messages if "llm_request_terminal" in msg)
        self.assertIn("request_kind=commit_summary", terminal)
        self.assertIn("status=success", terminal)

    def test_commit_summary_logs_invalid_when_entry_missing(self):
        snapshot = {"active_project": "Pulse"}
        with patch("daemon.runtime_orchestrator.enrich_session_report", return_value=False):
            self.orchestrator._enrich_commit_summary_background(
                report_ref=("journal.md", "entry-1"),
                snapshot=snapshot,
                llm=self.summary_llm,
                commit_message="fix: bug",
                diff_summary="diff",
            )

        messages = [call[0][0] for call in self.log.warning.call_args_list if call[0]]
        terminal = next(msg for msg in messages if "llm_request_terminal" in msg)
        self.assertIn("request_kind=commit_summary", terminal)
        self.assertIn("status=invalid", terminal)
        self.assertIn("reason=entry_not_found", terminal)

    def test_commit_summary_logs_error_on_exception(self):
        snapshot = {"active_project": "Pulse"}
        with patch("daemon.runtime_orchestrator.enrich_session_report", side_effect=RuntimeError("boom")):
            self.orchestrator._enrich_commit_summary_background(
                report_ref=("journal.md", "entry-1"),
                snapshot=snapshot,
                llm=self.summary_llm,
                commit_message="fix: bug",
                diff_summary="diff",
            )

        messages = [call[0][0] for call in self.log.error.call_args_list if call[0]]
        terminal = next(msg for msg in messages if "llm_request_terminal" in msg)
        self.assertIn("request_kind=commit_summary", terminal)
        self.assertIn("status=error", terminal)
        self.assertIn("reason=runtimeerror", terminal)

    def test_process_signals_ne_met_pas_a_jour_memory_synced_at_avant_sync_reelle(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.1,
            focus_level="deep",
            session_duration_min=45,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )
        decision = Decision(action="silent", level=0, reason="ok", payload={})
        event = MagicMock()
        event.type = "screen_locked"
        self.scorer.compute.return_value = signals
        self.decision_engine.evaluate.return_value = decision
        self.session_memory.export_session_data.return_value = {"active_project": "Pulse", "duration_min": 45}

        class DummyThread:
            def __init__(self, *args, **kwargs):
                self.started = False

            def start(self):
                self.started = True

        with patch("daemon.runtime_orchestrator.threading.Thread", side_effect=lambda *a, **k: DummyThread()):
            self.orchestrator._process_signals(event)

        self.assertIsNone(self.runtime_state.get_last_memory_sync_at())

    def test_sync_memory_background_skipped_ne_freeze_pas_et_ne_met_pas_a_jour_sync_at(self):
        snapshot = {"active_project": "Pulse", "duration_min": 45}

        with patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=None):
            with patch.object(self.orchestrator, "freeze_memory") as freeze_memory:
                self.orchestrator._sync_memory_background(snapshot, llm=None, trigger="screen_lock")

        self.assertIsNone(self.runtime_state.get_last_memory_sync_at())
        freeze_memory.assert_not_called()
        messages = [call[0][0] for call in self.log.info.call_args_list if call[0]]
        self.assertTrue(any("memory sync skipped" in msg for msg in messages))
        self.assertFalse(any("memory sync ok" in msg for msg in messages))

    def test_sync_memory_background_ok_met_a_jour_sync_at_et_freeze(self):
        snapshot = {"active_project": "Pulse", "duration_min": 45}

        with patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=("journal.md", "entry-1")):
            with patch.object(self.orchestrator, "freeze_memory") as freeze_memory:
                self.orchestrator._sync_memory_background(snapshot, llm=None, trigger="screen_lock")

        self.assertIsNotNone(self.runtime_state.get_last_memory_sync_at())
        freeze_memory.assert_called_once()
        messages = [call[0][0] for call in self.log.info.call_args_list if call[0]]
        self.assertTrue(any("memory sync ok" in msg for msg in messages))

    def test_process_signals_cree_une_proposition_executee_pour_context_ready(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.1,
            focus_level="normal",
            session_duration_min=25,
            recent_apps=["Xcode"],
            clipboard_context="text",
            edited_file_count_10m=4,
            file_type_mix_10m={"source": 2, "test": 1, "docs": 1},
            rename_delete_ratio_10m=0.0,
            dominant_file_mode="few_files",
            work_pattern_candidate="feature_candidate",
        )
        decision = Decision(
            action="inject_context",
            level=1,
            reason="context_ready",
            payload={"project": "Pulse", "task": "coding"},
        )
        event = Event("file_modified", {"path": "/tmp/main.py"})
        self.scorer.compute.return_value = signals
        self.decision_engine.evaluate.return_value = decision

        self.orchestrator._process_signals(event)

        history = proposal_store.list_history(limit=1)
        self.assertEqual(len(history), 1)
        proposal = history[0]
        self.assertEqual(proposal.type, "context_injection")
        self.assertEqual(proposal.status, "executed")
        self.assertEqual(
            [entry["status"] for entry in proposal.lifecycle],
            ["created", "pending", "executed"],
        )
        evidence_by_label = {entry["label"]: entry["value"] for entry in proposal.evidence}
        self.assertEqual(evidence_by_label["Fichiers touchés (10 min)"], "4")
        self.assertEqual(evidence_by_label["Mode de travail fichiers"], "few_files")
        self.assertEqual(evidence_by_label["Pattern candidat"], "feature_candidate")
        _, runtime_decision = self.runtime_state.get_context_snapshot()
        self.assertEqual(runtime_decision.action, "inject_context")
        self.assertIn("proposal_id", runtime_decision.payload)

    def test_process_signals_ne_duplique_pas_la_meme_proposition_context_ready(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.1,
            focus_level="normal",
            session_duration_min=25,
            recent_apps=["Xcode"],
            clipboard_context="text",
            edited_file_count_10m=4,
            file_type_mix_10m={"source": 2, "test": 1, "docs": 1},
            rename_delete_ratio_10m=0.0,
            dominant_file_mode="few_files",
            work_pattern_candidate="feature_candidate",
        )
        decision = Decision(
            action="inject_context",
            level=1,
            reason="context_ready",
            payload={"project": "Pulse", "task": "coding"},
        )
        event = Event("file_modified", {"path": "/tmp/main.py"})
        self.scorer.compute.return_value = signals
        self.decision_engine.evaluate.return_value = decision

        self.orchestrator._process_signals(event)
        self.orchestrator._process_signals(event)

        history = proposal_store.list_history()
        self.assertEqual(len(history), 1)


if __name__ == "__main__":
    unittest.main()
