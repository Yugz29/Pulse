import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from daemon.core.context_formatter import format_file_activity_summary
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
        self.session_memory.session_id = "session-1"
        self.memory_store = MagicMock()
        self.runtime_state = RuntimeState()
        self.llm_runtime = MagicMock()
        self.log = MagicMock()
        self.store.to_dict.side_effect = AssertionError("RuntimeOrchestrator must not read legacy StateStore")

        self.mock_fact_engine = MagicMock()
        self.mock_fact_engine.render_for_context.return_value = ""
        self.mock_fact_engine.archive_legacy_facts.return_value = 0
        self.mock_fact_engine.decay_all.return_value = 0

        self.scorer.bus.recent.return_value = []
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

    def _signals(self, **overrides):
        payload = {
            "active_project": "Pulse",
            "active_file": "/tmp/pulse/main.py",
            "probable_task": "coding",
            "friction_score": 0.15,
            "focus_level": "normal",
            "session_duration_min": 24,
            "recent_apps": ["Xcode"],
            "clipboard_context": "text",
            "activity_level": "editing",
        }
        payload.update(overrides)
        return Signals(**payload)

    def _set_runtime_analysis(self, signals, *, decision=None, session_status="active", awake=True, locked=False):
        self.runtime_state.update_present(signals=signals, session_status=session_status, awake=awake, locked=locked)
        self.runtime_state.set_analysis(signals=signals, decision=decision)

    def test_build_context_snapshot_includes_state_signals_decision_and_memory(self):
        signals = Signals(
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
        )
        self._set_runtime_analysis(signals, decision=Decision(action="notify", level=2, reason="high_friction", payload={"file": "main.py"}))
        self.orchestrator._frozen_memory = "Projet: Pulse"

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("# Contexte session", snapshot)
        self.assertIn("- Projet : Pulse", snapshot)
        self.assertIn("- Tâche probable : coding", snapshot)

    def test_handle_event_updates_present_from_signals_and_session_fsm(self):
        event = Event("screen_locked", {})
        event.timestamp = datetime(2026, 4, 23, 10, 0, 0)
        self.scorer.compute.return_value = self._signals(
            active_file="/tmp/pulse/runtime.py",
            probable_task="debug",
            focus_level="deep",
            session_duration_min=31,
            activity_level="executing",
        )
        self.decision_engine.evaluate.return_value = Decision("silent", 0, "nothing_relevant")

        self.orchestrator.handle_event(event)

        present = self.runtime_state.get_present()
        self.assertEqual(present.session_status, "locked")
        self.assertFalse(present.awake)
        self.assertTrue(present.locked)
        self.assertEqual(present.active_project, "Pulse")
        self.assertEqual(present.probable_task, "debug")

    def test_handle_event_updates_present_via_single_runtime_state_path(self):
        event = Event("app_activated", {"app_name": "Xcode"})
        event.timestamp = datetime(2026, 4, 23, 11, 15, 0)
        self.scorer.bus.recent.return_value = [event]
        self.scorer.compute.return_value = self._signals()
        self.decision_engine.evaluate.return_value = Decision("silent", 0, "nothing_relevant")

        with patch.object(self.runtime_state, "update_present", wraps=self.runtime_state.update_present) as update_present:
            self.orchestrator.handle_event(event)

        update_present.assert_called_once()
        kwargs = update_present.call_args.kwargs
        self.assertEqual(kwargs["session_status"], "active")
        self.assertTrue(kwargs["awake"])
        self.assertFalse(kwargs["locked"])

    def test_build_context_snapshot_golden_legacy_markdown_output_exact(self):
        self.runtime_state.set_latest_active_app("Cursor")
        signals = Signals(
            active_project="Pulse",
            active_file="/Users/yugz/Projets/Pulse/Pulse/daemon/runtime_orchestrator.py",
            probable_task="coding",
            friction_score=0.72,
            focus_level="normal",
            session_duration_min=96,
            recent_apps=["Cursor", "Terminal", "Safari", "Xcode", "Codex"],
            clipboard_context="text",
            edited_file_count_10m=5,
            file_type_mix_10m={"source": 3, "test": 1, "docs": 1},
            rename_delete_ratio_10m=0.2,
            dominant_file_mode="multi_file",
            work_pattern_candidate="feature_candidate",
            activity_level="editing",
            task_confidence=0.82,
        )
        self._set_runtime_analysis(signals)

        expected = "\n".join([
            "# Contexte session",
            "- Projet : Pulse",
            "- Racine projet : /Users/yugz/Projets/Pulse/Pulse",
            "- Fichier actif : /Users/yugz/Projets/Pulse/Pulse/daemon/runtime_orchestrator.py",
            "- App active : Cursor",
            "- Durée session : 96 min",
            "- Tâche probable : coding",
            "- Focus : normal",
            "- Activité fichiers : 5 fichier(s) touché(s) sur 10 min, surtout code source (3), documentation (1), tests (1)",
            "- Lecture de la session : travail réparti sur plusieurs fichiers, ça ressemble à une évolution de fonctionnalité, avec quelques changements de structure",
            "- Apps récentes : Cursor, Terminal, Safari, Xcode",
            "- diff --git a/daemon/runtime_orchestrator.py b/daemon/runtime_orchestrator.py\n"
            "  + 3 insertions(+)\n"
            "  - 1 suppression(-)",
            "- Dernière session Pulse : hier (développement, 45 min)",
        ])

        with patch("daemon.runtime_orchestrator.find_git_root", return_value=Path("/Users/yugz/Projets/Pulse/Pulse")), \
             patch("daemon.runtime_orchestrator.read_diff_summary", return_value="diff --git a/daemon/runtime_orchestrator.py b/daemon/runtime_orchestrator.py\n+ 3 insertions(+)\n- 1 suppression(-)"), \
             patch("daemon.runtime_orchestrator.last_session_context", return_value="Dernière session Pulse : hier (développement, 45 min)"):
            snapshot = self.orchestrator.build_context_snapshot()

        self.assertEqual(snapshot, expected)

    def test_build_context_snapshot_uses_atomic_runtime_snapshot(self):
        signals = self._signals()
        self._set_runtime_analysis(signals)

        with patch.object(self.runtime_state, "get_context_snapshot", side_effect=AssertionError("legacy must not be used")), \
             patch.object(self.runtime_state, "get_present", side_effect=AssertionError("legacy must not be used")):
            snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Projet : Pulse", snapshot)

    def test_build_context_snapshot_falls_back_to_signal_context_when_store_is_empty(self):
        signals = Signals(
            active_project="Pulse", active_file="/tmp/main.py", probable_task="coding",
            friction_score=0.15, focus_level="normal", session_duration_min=24,
            recent_apps=["Xcode"], clipboard_context="text",
        )
        self._set_runtime_analysis(signals)

        snapshot = self.orchestrator.build_context_snapshot()
        self.assertIn("- Projet : Pulse", snapshot)
        self.assertIn("- Fichier actif : /tmp/main.py", snapshot)

    def test_build_context_snapshot_falls_back_to_workspace_root_when_git_root_is_absent(self):
        signals = Signals(active_project="client-repo", active_file="/tmp/client-repo/src/main.py", probable_task="coding", friction_score=0.1, focus_level="normal", session_duration_min=18, recent_apps=["Cursor"], clipboard_context=None)
        self._set_runtime_analysis(signals)

        with patch("daemon.runtime_orchestrator.find_git_root", return_value=None), \
             patch("daemon.runtime_orchestrator.find_workspace_root", return_value=Path("/tmp/client-repo")):
            snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Racine projet : /tmp/client-repo", snapshot)

    def test_file_activity_summary_n_affiche_pas_other_comme_insight_principal(self):
        summary = format_file_activity_summary(Signals(
            active_project="Pulse", active_file="/tmp/main.py", probable_task="coding",
            friction_score=0.2, focus_level="normal", session_duration_min=12,
            recent_apps=["Cursor"], clipboard_context=None,
            edited_file_count_10m=7, file_type_mix_10m={"other": 5, "source": 2},
            rename_delete_ratio_10m=0.0, dominant_file_mode="few_files", work_pattern_candidate=None,
        ))
        self.assertEqual(summary, "7 fichier(s) touché(s) sur 10 min, surtout code source (2)")

    def test_freeze_memory_uses_project_memory_before_support_layers(self):
        self.memory_store.render.return_value = "Structured memory"
        with patch("daemon.runtime_orchestrator.render_project_memory", return_value="# Projets\n\n## Pulse"):
            self.orchestrator.freeze_memory()
        self.assertEqual(self.orchestrator.get_frozen_memory(), "# Projets\n\n## Pulse\n\nStructured memory")

    def test_freeze_memory_fallback_legacy_si_projet_et_support_absents(self):
        self.memory_store.render.return_value = ""
        with patch("daemon.runtime_orchestrator.render_project_memory", return_value=""), \
             patch("daemon.runtime_orchestrator.load_memory_context", return_value="Legacy memory"):
            self.orchestrator.freeze_memory()
        self.assertEqual(self.orchestrator.get_frozen_memory(), "Legacy memory")

    def test_deferred_startup_loads_models_purges_memory_and_warms_provider(self):
        provider = MagicMock()
        provider.model = "gemma4:e4b"
        provider.warmup.return_value = True
        self.llm_runtime.provider.return_value = provider
        self.memory_store.purge_expired.return_value = 2
        self.mock_fact_engine.archive_legacy_facts.return_value = 3

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

    def test_process_signals_ne_fait_pas_regresser_observed_now(self):
        newer = Event("app_activated", {"app_name": "Chrome"})
        newer.timestamp = datetime(2026, 4, 23, 18, 10, 0)
        older = Event("app_activated", {"app_name": "Cursor"})
        older.timestamp = datetime(2026, 4, 23, 18, 5, 0)
        self.scorer.bus.recent.return_value = [newer, older]
        self.scorer.compute.return_value = self._signals(session_duration_min=10)
        self.decision_engine.evaluate.return_value = Decision(action="silent", level=0, reason="ok", payload={})

        with patch.object(self.runtime_state, "update_present", wraps=self.runtime_state.update_present):
            self.orchestrator._process_signals(older)

        self.assertEqual(self.scorer.compute.call_args.kwargs["observed_now"], newer.timestamp)

    def test_process_confirmed_commit_ancre_snapshot_sur_le_repo_et_le_diff(self):
        git_root = Path("/tmp/Pulse")
        self.session_memory.export_memory_payload.return_value = {
            "active_project": "plugins",
            "duration_min": 19,
            "started_at": "2026-04-28T11:46:01",
            "updated_at": "2026-04-28T12:04:48.365316",
            "top_files": ["plugin.json", "openai.yaml"],
            "files_changed": 20,
        }
        self.scorer.compute.return_value = self._signals(session_duration_min=19)
        self.orchestrator.session_fsm.restore_session_start(datetime(2026, 4, 28, 11, 46, 1))
        self.runtime_state.update_present(
            signals=self._signals(session_duration_min=19),
            session_status="active", awake=True, locked=False,
            updated_at=datetime(2026, 4, 28, 12, 4, 48, 365316),
        )

        captured_threads = []
        class DummyThread:
            def __init__(self, *args, **kwargs):
                self.target = kwargs.get("target")
                self.args = kwargs.get("args", ())
                captured_threads.append(self)
            def start(self): return None

        with patch("daemon.runtime_orchestrator.threading.Thread", side_effect=lambda *a, **k: DummyThread(*a, **k)), \
             patch("daemon.runtime_orchestrator.read_commit_message", return_value="feat: split episode"), \
             patch("daemon.runtime_orchestrator.read_commit_diff_summary", return_value="Diff en cours : DashboardViewModel.swift (+10 -2), DashboardRootView.swift (+22 -4)"):
            self.orchestrator._process_confirmed_commit(git_root)

        sync_thread = next(t for t in captured_threads if t.target == self.orchestrator._sync_memory_background)
        snapshot = sync_thread.args[0]
        self.assertEqual(snapshot["active_project"], "Pulse")
        self.assertEqual(snapshot["top_files"], ["DashboardViewModel.swift", "DashboardRootView.swift"])
        self.assertEqual(snapshot["work_block_started_at"], "2026-04-28T11:46:01")

    def test_process_confirmed_commit_utilise_les_fichiers_git_si_diff_non_parseable(self):
        git_root = Path("/tmp/Pulse")
        self.session_memory.export_memory_payload.return_value = {
            "active_project": "plugins", "duration_min": 19,
            "top_files": ["plugin.json", "openai.yaml"], "files_changed": 20,
        }
        self.scorer.compute.return_value = self._signals(session_duration_min=19)

        captured_threads = []
        class DummyThread:
            def __init__(self, *args, **kwargs):
                self.target = kwargs.get("target")
                self.args = kwargs.get("args", ())
                captured_threads.append(self)
            def start(self): return None

        with patch("daemon.runtime_orchestrator.threading.Thread", side_effect=lambda *a, **k: DummyThread(*a, **k)), \
             patch("daemon.runtime_orchestrator.read_commit_message", return_value="feat: split episode"), \
             patch("daemon.runtime_orchestrator.read_commit_diff_summary", return_value="Fonctions touchées : refresh"), \
             patch("daemon.runtime_orchestrator.read_commit_file_names", return_value=["DashboardViewModel.swift", "DashboardRootView.swift"]):
            self.orchestrator._process_confirmed_commit(git_root)

        sync_thread = next(t for t in captured_threads if t.target == self.orchestrator._sync_memory_background)
        snapshot = sync_thread.args[0]
        self.assertEqual(snapshot["active_project"], "Pulse")
        self.assertEqual(snapshot["commit_scope_files"], ["DashboardViewModel.swift", "DashboardRootView.swift"])

    def test_annotate_commit_work_block_prefere_l_activite_des_fichiers_du_commit(self):
        self.session_memory.find_file_activity_window.return_value = {
            "started_at": "2026-04-29T10:33:04",
            "ended_at": "2026-04-29T10:48:12",
            "duration_min": 15,
            "event_count": 4,
        }
        snapshot = {"work_block_started_at": "2026-04-29T10:00:00", "work_block_ended_at": "2026-04-29T11:42:00"}
        commit_at = datetime(2026, 4, 29, 11, 42, 0)

        self.orchestrator._annotate_commit_work_block(
            snapshot, commit_at=commit_at,
            commit_scope_files=["DashboardContentView.swift"],
            git_root=Path("/Users/yugz/Projets/Pulse/Pulse"),
        )

        self.assertEqual(snapshot["work_block_started_at"], "2026-04-29T10:33:04")
        self.assertEqual(snapshot["work_block_ended_at"], "2026-04-29T10:48:12")
        self.assertEqual(snapshot["commit_activity_event_count"], 4)

    def test_annotate_commit_work_window_alias_reste_compatible(self):
        snapshot = {
            "work_window_started_at": "2026-04-29T10:00:00",
            "work_window_ended_at": "2026-04-29T11:42:00",
        }
        commit_at = datetime(2026, 4, 29, 11, 42, 0)

        self.orchestrator._annotate_commit_work_window(snapshot, commit_at=commit_at)

        self.assertEqual(snapshot["work_block_started_at"], "2026-04-29T10:00:00")
        self.assertEqual(snapshot["work_block_ended_at"], "2026-04-29T11:42:00")
        self.assertEqual(snapshot["work_window_started_at"], "2026-04-29T10:00:00")
        self.assertEqual(snapshot["work_window_ended_at"], "2026-04-29T11:42:00")

    def test_apply_restart_state_resume_aussi_la_session_memory(self):
        started_at = datetime(2026, 4, 23, 17, 0, 0)
        self.orchestrator._restart_manager.apply(
            {"elapsed_min": 3, "active_project": "Pulse", "probable_task": "coding", "started_at": started_at.isoformat()},
            session_fsm=self.orchestrator._session_fsm,
            session_memory=self.session_memory,
        )
        self.assertEqual(self.orchestrator.session_fsm.session_started_at, started_at)
        self.session_memory.resume_session.assert_called_once_with(started_at=started_at)

    def test_summary_llm_for_commit_only(self):
        signals = self._signals(session_duration_min=45)
        self.assertIs(self.orchestrator._summary_llm_for("commit", signals), self.summary_llm)

    def test_summary_llm_for_screen_locked_is_disabled(self):
        signals = self._signals(session_duration_min=45)
        self.assertIsNone(self.orchestrator._summary_llm_for("screen_locked", signals))

    def test_commit_summary_logs_success_terminal_status(self):
        with patch("daemon.runtime_orchestrator.enrich_session_report", return_value=True):
            self.orchestrator._enrich_commit_summary_background(
                report_ref=("journal.md", "entry-1"), snapshot={"active_project": "Pulse"},
                llm=self.summary_llm, commit_message="fix: bug", diff_summary="diff",
            )
        messages = [call[0][0] for call in self.log.info.call_args_list if call[0]]
        self.assertTrue(any("llm_request_terminal" in msg and "status=success" in msg for msg in messages))

    def test_process_signals_ne_met_pas_a_jour_memory_synced_at_avant_sync_reelle(self):
        signals = self._signals(session_duration_min=45)
        decision = Decision(action="silent", level=0, reason="ok", payload={})
        event = MagicMock()
        event.type = "screen_locked"
        self.scorer.compute.return_value = signals
        self.decision_engine.evaluate.return_value = decision
        self.session_memory.export_memory_payload.return_value = {"active_project": "Pulse", "duration_min": 45}

        class DummyThread:
            def __init__(self, *args, **kwargs): self.started = False
            def start(self): self.started = True

        with patch("daemon.runtime_orchestrator.threading.Thread", side_effect=lambda *a, **k: DummyThread()):
            self.orchestrator._process_signals(event)
        self.assertIsNone(self.runtime_state.get_last_memory_sync_at())

    def test_sync_memory_background_skipped_ne_freeze_pas(self):
        with patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=None):
            with patch.object(self.orchestrator, "freeze_memory") as freeze_memory:
                self.orchestrator._sync_memory_background({"active_project": "Pulse", "duration_min": 45}, llm=None)
        self.assertIsNone(self.runtime_state.get_last_memory_sync_at())
        freeze_memory.assert_not_called()

    def test_sync_memory_background_ok_met_a_jour_sync_at_et_freeze(self):
        with patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=("journal.md", "entry-1")):
            with patch.object(self.orchestrator, "freeze_memory") as freeze_memory:
                self.orchestrator._sync_memory_background({"active_project": "Pulse", "duration_min": 45}, llm=None)
        self.assertIsNotNone(self.runtime_state.get_last_memory_sync_at())
        freeze_memory.assert_called_once()

    def test_process_signals_cree_une_proposition_executee_pour_context_ready(self):
        signals = Signals(
            active_project="Pulse", active_file="/tmp/main.py", probable_task="coding",
            friction_score=0.1, focus_level="normal", session_duration_min=25,
            recent_apps=["Xcode"], clipboard_context="text",
            edited_file_count_10m=4, file_type_mix_10m={"source": 2, "test": 1, "docs": 1},
            rename_delete_ratio_10m=0.0, dominant_file_mode="few_files", work_pattern_candidate="feature_candidate",
        )
        decision = Decision(action="inject_context", level=1, reason="context_ready", payload={"project": "Pulse", "task": "coding"})
        event = Event("file_modified", {"path": "/tmp/main.py"})
        self.scorer.compute.return_value = signals
        self.decision_engine.evaluate.return_value = decision

        self.orchestrator._process_signals(event)

        history = proposal_store.list_history(limit=1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "context_injection")
        self.assertEqual(history[0].status, "executed")

    def test_process_signals_ne_duplique_pas_la_meme_proposition(self):
        signals = self._signals(
            edited_file_count_10m=4, file_type_mix_10m={"source": 2},
            rename_delete_ratio_10m=0.0, dominant_file_mode="few_files",
        )
        decision = Decision(action="inject_context", level=1, reason="context_ready", payload={"project": "Pulse"})
        event = Event("file_modified", {"path": "/tmp/main.py"})
        self.scorer.compute.return_value = signals
        self.decision_engine.evaluate.return_value = decision

        self.orchestrator._process_signals(event)
        self.orchestrator._process_signals(event)

        self.assertEqual(len(proposal_store.list_history()), 1)

    # ── C4 : le contexte runtime ne retombe plus sur StateStore ──────────────

    def test_c4_signals_active_file_prime_sur_state_active_file(self):
        signals = Signals(active_project="Pulse", active_file="/fresh/path/current.py", probable_task="coding", friction_score=0.1, focus_level="normal", session_duration_min=30, recent_apps=["Xcode"], clipboard_context=None)
        self._set_runtime_analysis(signals)

        snapshot = self.orchestrator.build_context_snapshot()
        self.assertIn("/fresh/path/current.py", snapshot)
        self.assertNotIn("/stale/path.py", snapshot)

    def test_c4_aucun_fallback_sur_state_si_present_n_a_pas_de_fichier(self):
        signals = Signals(active_project=None, active_file=None, probable_task="general", friction_score=0.0, focus_level="normal", session_duration_min=5, recent_apps=[], clipboard_context=None)
        self._set_runtime_analysis(signals)

        snapshot = self.orchestrator.build_context_snapshot()
        self.assertIn("- Fichier actif : aucun", snapshot)
        self.assertNotIn("/fallback/from_store.py", snapshot)

    # ── C5 : la durée vient du PresentState, pas du StateStore ───────────────

    def test_c5_signals_duration_prime_sur_state_duration(self):
        signals = Signals(active_project="Pulse", active_file=None, probable_task="coding", friction_score=0.0, focus_level="normal", session_duration_min=45, recent_apps=["Xcode"], clipboard_context=None)
        self._set_runtime_analysis(signals)

        snapshot = self.orchestrator.build_context_snapshot()
        self.assertIn("- Durée session : 45 min", snapshot)
        self.assertNotIn("240 min", snapshot)

    # ── I2 : flush file events ────────────────────────────────────────────────

    def test_i2_burst_terminant_par_delete_utilise_dernier_event_non_delete(self):
        events = [
            Event("file_modified", {"path": "/tmp/a.py"}),
            Event("file_modified", {"path": "/tmp/b.py"}),
            Event("file_deleted", {"path": "/tmp/old.py"}),
        ]
        captured_triggers = []

        def fake_process_signals(trigger_event):
            captured_triggers.append(trigger_event)

        with self.orchestrator._debounce_lock:
            self.orchestrator._pending_file_events = events[:]

        with patch.object(self.orchestrator, "_process_signals", side_effect=fake_process_signals):
            self.orchestrator._flush_file_events()

        self.assertEqual(len(captured_triggers), 1)
        self.assertNotEqual(captured_triggers[0].type, "file_deleted")
        self.assertEqual(captured_triggers[0].payload["path"], "/tmp/b.py")

    def test_i2_burst_hors_ordre_choisit_le_plus_recent_par_timestamp(self):
        base = datetime.now()
        latest = Event("file_modified", {"path": "/tmp/new.py"})
        latest.timestamp = base
        older = Event("file_modified", {"path": "/tmp/old.py"})
        older.timestamp = base - timedelta(minutes=2)
        captured_triggers = []

        def fake_process_signals(trigger_event):
            captured_triggers.append(trigger_event)

        with self.orchestrator._debounce_lock:
            self.orchestrator._pending_file_events = [latest, older]

        with patch.object(self.orchestrator, "_process_signals", side_effect=fake_process_signals):
            self.orchestrator._flush_file_events()

        self.assertEqual(len(captured_triggers), 1)
        self.assertEqual(captured_triggers[0].payload["path"], "/tmp/new.py")

    # ── Verrous écran ─────────────────────────────────────────────────────────

    def test_verrou_court_conserve_session_started_at_sans_nouvelle_session(self):
        original_start = self.orchestrator.session_fsm.session_started_at
        t_lock = datetime.now() - timedelta(minutes=10)
        self.runtime_state.mark_screen_locked(when=t_lock)
        unlock_event = Event("screen_unlocked", {})

        with patch.object(self.orchestrator.session_memory, "new_session") as mock_new_session, \
             patch.object(self.orchestrator, "_process_signals"):
            self.orchestrator.handle_event(unlock_event)

        mock_new_session.assert_not_called()
        self.assertEqual(self.orchestrator.session_fsm.session_started_at, original_start)

    def test_verrou_long_reset_scorer_et_nouvelle_session(self):
        t_lock = datetime.now() - timedelta(minutes=35)
        self.runtime_state.mark_screen_locked(when=t_lock)
        unlock_event = Event("screen_unlocked", {})

        with patch.object(self.orchestrator.session_memory, "new_session") as mock_new_session, \
             patch.object(self.orchestrator.session_memory, "export_memory_payload", return_value={"duration_min": 0}), \
             patch("daemon.runtime_orchestrator.update_memories_from_session"), \
             patch.object(self.orchestrator, "_process_signals"):
            self.orchestrator.handle_event(unlock_event)

        mock_new_session.assert_called_once()

    def test_verrou_court_clear_sleep_markers_apres_unlock(self):
        t_lock = datetime.now() - timedelta(minutes=5)
        self.runtime_state.mark_screen_locked(when=t_lock)
        self.assertIsNotNone(self.runtime_state.get_last_screen_locked_at())

        with patch.object(self.orchestrator, "_process_signals"):
            self.orchestrator.handle_event(Event("screen_unlocked", {}))

        self.assertIsNone(self.runtime_state.get_last_screen_locked_at())

    # ── Resume card ──────────────────────────────────────────────────────────

    def test_resume_card_est_publiee_apres_reprise_longue(self):
        event = Event("screen_unlocked", {})
        event.timestamp = datetime(2026, 4, 29, 10, 0, 0)
        signals = self._signals(active_project="Pulse", session_duration_min=42)
        self._set_runtime_analysis(signals)
        self.session_memory.export_memory_payload.return_value = {
            "active_project": "Pulse", "duration_min": 42,
            "top_files": ["/tmp/Pulse/daemon/runtime_orchestrator.py"],
            "work_block_started_at": "2026-04-29T09:00:00",
        }

        self.orchestrator._maybe_emit_resume_card(event=event, sleep_minutes=35)

        self.scorer.bus.publish.assert_called_once()
        args = self.scorer.bus.publish.call_args.args
        self.assertEqual(args[0], "resume_card")
        self.assertEqual(args[1]["project"], "Pulse")

    def test_resume_card_respecte_le_cooldown(self):
        event = Event("screen_unlocked", {})
        event.timestamp = datetime(2026, 4, 29, 10, 0, 0)
        self._set_runtime_analysis(self._signals())
        self.session_memory.export_memory_payload.return_value = {"active_project": "Pulse", "duration_min": 42}
        self.orchestrator._last_resume_card_at = event.timestamp - timedelta(minutes=30)

        self.orchestrator._maybe_emit_resume_card(event=event, sleep_minutes=35)
        self.scorer.bus.publish.assert_not_called()

    def test_recover_missed_daydream_marque_la_veille_et_declenche(self):
        with patch("daemon.memory.daydream.mark_daydream_pending") as mark_pending, \
             patch.object(self.orchestrator, "_run_daydream_if_pending") as run_daydream:
            self.orchestrator._recover_missed_daydream()
        mark_pending.assert_called_once()
        run_daydream.assert_called_once()


if __name__ == "__main__":
    unittest.main()
