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
        self.store.to_dict.return_value = {}

        # mock FactEngine — évite toute dépendance sur ~/.pulse/facts.db dans les tests
        self.mock_fact_engine = MagicMock()
        self.mock_fact_engine.render_for_context.return_value = ""
        self.mock_fact_engine.archive_legacy_facts.return_value = 0
        self.mock_fact_engine.decay_all.return_value = 0

        # _process_signals lit désormais le bus pour laisser la SessionFSM
        # décider des frontières de session.
        self.scorer.bus.recent.return_value = []

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
        self.assertIn("- Activité fichiers : 5 fichier(s) touché(s) sur 10 min, surtout code source (3), documentation (1), tests (1)", snapshot)
        self.assertIn("- Lecture de la session : travail réparti sur plusieurs fichiers, ça ressemble à une évolution de fonctionnalité, avec quelques changements de structure", snapshot)

    def test_build_context_snapshot_golden_legacy_markdown_output_exact(self):
        self.store.to_dict.return_value = {
            "active_project": "Pulse",
            "active_file": "/Users/yugz/Projets/Pulse/Pulse/daemon/runtime_orchestrator.py",
            "active_app": "Cursor",
            "session_duration_min": 96,
            "last_event_type": "file_modified",
        }
        self.runtime_state.set_analysis(
            signals=Signals(
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
            ),
            decision=None,
        )

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

    def test_build_context_snapshot_falls_back_to_signal_context_when_store_is_empty(self):
        self.store.to_dict.return_value = {
            "active_project": None,
            "active_file": None,
            "active_app": None,
            "session_duration_min": 0,
            "last_event_type": None,
        }
        self.runtime_state.set_analysis(
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                friction_score=0.15,
                focus_level="normal",
                session_duration_min=24,
                recent_apps=["Xcode"],
                clipboard_context="text",
            ),
            decision=None,
        )

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Projet : Pulse", snapshot)
        self.assertIn("- Fichier actif : /tmp/main.py", snapshot)
        self.assertIn("- Durée session : 24 min", snapshot)

    def test_build_context_snapshot_falls_back_to_workspace_root_when_git_root_is_absent(self):
        self.store.to_dict.return_value = {
            "active_project": "client-repo",
            "active_file": "/tmp/client-repo/src/main.py",
            "active_app": "Cursor",
            "session_duration_min": 18,
            "last_event_type": "file_modified",
        }
        self.runtime_state.set_analysis(
            signals=Signals(
                active_project="client-repo",
                active_file="/tmp/client-repo/src/main.py",
                probable_task="coding",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=18,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
            decision=None,
        )

        with patch("daemon.runtime_orchestrator.find_git_root", return_value=None), \
             patch("daemon.runtime_orchestrator.find_workspace_root", return_value=Path("/tmp/client-repo")):
            snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Racine projet : /tmp/client-repo", snapshot)

    def test_file_activity_summary_n_affiche_pas_other_comme_insight_principal(self):
        summary = format_file_activity_summary(
            Signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                friction_score=0.2,
                focus_level="normal",
                session_duration_min=12,
                recent_apps=["Cursor"],
                clipboard_context=None,
                edited_file_count_10m=7,
                file_type_mix_10m={"other": 5, "source": 2},
                rename_delete_ratio_10m=0.0,
                dominant_file_mode="few_files",
                work_pattern_candidate=None,
            )
        )

        self.assertEqual(summary, "7 fichier(s) touché(s) sur 10 min, surtout code source (2)")

    def test_file_activity_summary_retombe_sur_un_compte_simple_si_mix_est_trop_generique(self):
        summary = format_file_activity_summary(
            Signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="general",
                friction_score=0.0,
                focus_level="normal",
                session_duration_min=8,
                recent_apps=["Cursor"],
                clipboard_context=None,
                edited_file_count_10m=13,
                file_type_mix_10m={"other": 13},
                rename_delete_ratio_10m=0.0,
                dominant_file_mode="multi_file",
                work_pattern_candidate=None,
            )
        )

        self.assertEqual(summary, "13 fichier(s) touché(s) sur 10 min")

    def test_freeze_memory_uses_structured_memory_first(self):
        self.memory_store.render.return_value = "Structured memory"

        self.orchestrator.freeze_memory()

        self.assertEqual(self.orchestrator.get_frozen_memory(), "Structured memory")
        self.assertIsInstance(self.orchestrator.get_frozen_memory_at(), datetime)

    def test_freeze_memory_mis_a_jour_apres_sync(self):
        """freeze_memory() reflète toujours le contenu le plus récent."""
        self.memory_store.render.return_value = "Avant sync"
        self.orchestrator.freeze_memory()
        self.assertEqual(self.orchestrator.get_frozen_memory(), "Avant sync")

        # Simule une mise à jour de la mémoire après une sync
        self.memory_store.render.return_value = "Après sync"
        self.orchestrator.freeze_memory()

        self.assertEqual(self.orchestrator.get_frozen_memory(), "Après sync")
        self.assertIsInstance(self.orchestrator.get_frozen_memory_at(), datetime)

    def test_freeze_memory_inclut_facts_profile_si_disponible(self):
        """Le profil utilisateur du FactEngine est concaténé à la mémoire structurée."""
        self.memory_store.render.return_value = "Structured memory"
        self.mock_fact_engine.render_for_context.return_value = "── Profil utilisateur ──\n• [workflow] Coding le soir"

        self.orchestrator.freeze_memory()

        frozen = self.orchestrator.get_frozen_memory()
        self.assertIn("Structured memory", frozen)
        self.assertIn("Profil utilisateur", frozen)

    def test_freeze_memory_fonctionne_sans_memory_store(self):
        """Si memory_store.render() retourne vide, legacy load_memory_context est utilisé."""
        self.memory_store.render.return_value = ""

        with patch("daemon.runtime_orchestrator.load_memory_context", return_value="Legacy memory"):
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
        self.mock_fact_engine.archive_legacy_facts.assert_called_once()
        self.mock_fact_engine.decay_all.assert_called_once()
        provider.warmup.assert_called_once()
        messages = [call[0][0] for call in self.log.info.call_args_list if call[0]]
        self.assertTrue(any("legacy archivé" in msg for msg in messages))

    def test_handle_commit_event_waits_for_new_head_before_processing(self):
        git_root = Path("/tmp/Pulse")

        with patch("daemon.runtime_orchestrator.find_git_root", return_value=git_root), \
             patch("daemon.runtime_orchestrator.read_head_sha", side_effect=["old", "old", "new"]), \
             patch("daemon.runtime_orchestrator.time.sleep", return_value=None), \
             patch.object(self.orchestrator, "_process_confirmed_commit") as process_commit:
            self.orchestrator._handle_commit_event("/tmp/Pulse/.git/COMMIT_EDITMSG")

        process_commit.assert_called_once_with(git_root)

    def test_process_signals_opens_first_episode_from_meaningful_activity(self):
        event = Event("file_modified", {"path": "/tmp/main.py"})
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.83,
            friction_score=0.1,
            focus_level="deep",
            session_duration_min=5,
            recent_apps=["Cursor"],
            clipboard_context=None,
        )
        self.scorer.bus.recent.return_value = [event]
        self.scorer.compute.return_value = signals
        self.decision_engine.evaluate.return_value = Decision(action="silent", level=0, reason="ok", payload={})

        with patch("daemon.core.episode_fsm.new_uid", return_value="ep-1"):
            self.orchestrator._process_signals(event)

        self.session_memory.save_episode.assert_called_once()
        saved = self.session_memory.save_episode.call_args[0][0]
        self.assertEqual(saved.id, "ep-1")
        self.assertEqual(saved.session_id, "session-1")
        self.assertEqual(saved.started_at, event.timestamp.isoformat())
        self.assertIsNone(saved.probable_task)
        self.assertIsNone(saved.activity_level)
        self.assertIsNone(saved.task_confidence)

    def test_process_confirmed_commit_closes_and_reopens_episode(self):
        git_root = Path("/tmp/Pulse")
        with patch("daemon.core.episode_fsm.new_uid", side_effect=["ep-1", "ep-2"]):
            self.orchestrator._episode_fsm.ensure_active(
                session_id="session-1",
                started_at=datetime.now(),
            )

        self.session_memory.save_episode.reset_mock()
        self.session_memory.export_session_data.return_value = {"active_project": "Pulse", "duration_min": 30}
        self.scorer.compute.return_value = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.87,
            friction_score=0.1,
            focus_level="deep",
            session_duration_min=12,
            recent_apps=["Cursor"],
            clipboard_context=None,
        )

        class DummyThread:
            def __init__(self, *args, **kwargs):
                self.target = kwargs.get("target")
                self.args = kwargs.get("args", ())

            def start(self):
                return None

        with patch("daemon.runtime_orchestrator.threading.Thread", side_effect=lambda *a, **k: DummyThread(*a, **k)), \
             patch("daemon.runtime_orchestrator.read_commit_message", return_value="feat: split episode"), \
             patch("daemon.runtime_orchestrator.read_commit_diff_summary", return_value="diff"):
            self.orchestrator._process_confirmed_commit(git_root)

        self.assertEqual(self.session_memory.save_episode.call_count, 2)
        closed = self.session_memory.save_episode.call_args_list[0][0][0]
        opened = self.session_memory.save_episode.call_args_list[1][0][0]
        self.assertEqual(closed.boundary_reason, "commit")
        self.assertIsNotNone(closed.ended_at)
        self.assertEqual(closed.probable_task, "coding")
        self.assertEqual(closed.activity_level, "editing")
        self.assertEqual(closed.task_confidence, 0.87)
        self.assertEqual(opened.session_id, "session-1")
        self.assertIsNone(opened.probable_task)

    def test_process_confirmed_commit_uses_non_null_fallback_when_no_signals_exist(self):
        git_root = Path("/tmp/Pulse")
        with patch("daemon.core.episode_fsm.new_uid", side_effect=["ep-1", "ep-2"]):
            self.orchestrator._episode_fsm.ensure_active(
                session_id="session-1",
                started_at=datetime.now(),
            )

        self.session_memory.save_episode.reset_mock()
        self.session_memory.export_session_data.return_value = {"active_project": "Pulse", "duration_min": 30}
        self.scorer.compute.return_value = None

        class DummyThread:
            def __init__(self, *args, **kwargs):
                self.target = kwargs.get("target")
                self.args = kwargs.get("args", ())

            def start(self):
                return None

        with patch("daemon.runtime_orchestrator.threading.Thread", side_effect=lambda *a, **k: DummyThread(*a, **k)), \
             patch("daemon.runtime_orchestrator.read_commit_message", return_value="feat: split episode"), \
             patch("daemon.runtime_orchestrator.read_commit_diff_summary", return_value="diff"):
            self.orchestrator._process_confirmed_commit(git_root)

        closed = self.session_memory.save_episode.call_args_list[0][0][0]
        self.assertEqual(closed.probable_task, "unknown")
        self.assertEqual(closed.activity_level, "idle")
        self.assertEqual(closed.task_confidence, 0.0)

    def test_idle_timeout_closes_episode_with_fresh_semantics(self):
        old_event = Event("file_modified", {"path": "/tmp/old.py"}, timestamp=datetime.now())
        resumed_event = Event(
            "file_modified",
            {"path": "/tmp/new.py"},
            timestamp=old_event.timestamp + timedelta(minutes=40),
        )

        self.orchestrator.session_fsm.observe_recent_events(recent_events=[old_event], now=old_event.timestamp)
        with patch("daemon.core.episode_fsm.new_uid", side_effect=["ep-1", "ep-2"]):
            self.orchestrator._episode_fsm.ensure_active(
                session_id="session-1",
                started_at=old_event.timestamp,
            )

        self.scorer.bus.recent.return_value = [old_event, resumed_event]
        self.scorer.compute.side_effect = [
            Signals(
                active_project="Pulse",
                active_file="/tmp/new.py",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.91,
                friction_score=0.1,
                focus_level="deep",
                session_duration_min=12,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
            Signals(
                active_project="Pulse",
                active_file="/tmp/new.py",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.91,
                friction_score=0.1,
                focus_level="deep",
                session_duration_min=1,
                recent_apps=["Cursor"],
                clipboard_context=None,
            ),
        ]
        self.decision_engine.evaluate.return_value = Decision(action="silent", level=0, reason="ok", payload={})

        self.orchestrator._process_signals(resumed_event)

        closed = self.session_memory.save_episode.call_args_list[0][0][0]
        self.assertEqual(closed.boundary_reason, "idle_timeout")
        self.assertEqual(closed.probable_task, "coding")
        self.assertEqual(closed.activity_level, "editing")
        self.assertEqual(closed.task_confidence, 0.91)

    def test_long_screen_unlock_closes_episode_with_fresh_semantics(self):
        with patch("daemon.core.episode_fsm.new_uid", side_effect=["ep-1", "ep-2"]):
            self.orchestrator._episode_fsm.ensure_active(
                session_id="session-1",
                started_at=datetime.now() - timedelta(minutes=45),
            )

        self.scorer.compute.return_value = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.89,
            friction_score=0.1,
            focus_level="deep",
            session_duration_min=20,
            recent_apps=["Cursor"],
            clipboard_context=None,
        )

        t_lock = datetime.now() - timedelta(minutes=35)
        self.runtime_state.mark_screen_locked(when=t_lock)
        unlock_event = Event("screen_unlocked", {})

        with patch.object(self.orchestrator.session_memory, "export_session_data", return_value={"duration_min": 0}), \
             patch("daemon.runtime_orchestrator.update_memories_from_session"), \
             patch.object(self.orchestrator, "_process_signals"):
            self.orchestrator.handle_event(unlock_event)

        closed = self.session_memory.save_episode.call_args_list[0][0][0]
        self.assertEqual(closed.boundary_reason, "screen_lock")
        self.assertEqual(closed.probable_task, "coding")
        self.assertEqual(closed.activity_level, "editing")
        self.assertEqual(closed.task_confidence, 0.89)

    def test_shutdown_runtime_closes_episode_with_fallback_when_no_signals_exist(self):
        with patch("daemon.core.episode_fsm.new_uid", return_value="ep-1"):
            self.orchestrator._episode_fsm.ensure_active(
                session_id="session-1",
                started_at=datetime.now(),
            )

        self.scorer.compute.return_value = None
        self.session_memory.export_session_data.return_value = {"duration_min": 0}

        with patch("daemon.runtime_orchestrator.update_memories_from_session"):
            self.orchestrator.shutdown_runtime()

        closed = self.session_memory.save_episode.call_args_list[0][0][0]
        self.assertEqual(closed.boundary_reason, "session_end")
        self.assertEqual(closed.probable_task, "unknown")
        self.assertEqual(closed.activity_level, "idle")
        self.assertEqual(closed.task_confidence, 0.0)

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
        self.assertEqual(
            evidence_by_label["Activité fichiers"],
            "4 fichier(s) touché(s) sur 10 min, surtout code source (2), documentation (1), tests (1)",
        )
        self.assertEqual(
            evidence_by_label["Lecture de la session"],
            "petit lot cohérent de 4 fichiers, ça ressemble à une évolution de fonctionnalité",
        )
        _, runtime_decision = self.runtime_state.get_context_snapshot()
        self.assertEqual(runtime_decision.action, "inject_context")
        self.assertIn("proposal_id", runtime_decision.payload)

    def test_process_signals_flow_decision_candidate_adapter_store_preserves_legacy_output(self):
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

        with patch("daemon.runtime_orchestrator.new_uid", return_value="proposal-123"):
            self.orchestrator._process_signals(event)

        history = proposal_store.list_history(limit=1)
        self.assertEqual(len(history), 1)
        proposal = history[0]
        expected_evidence = [
            {"kind": "project", "label": "Projet", "value": "Pulse"},
            {"kind": "task", "label": "Tâche", "value": "coding"},
            {"kind": "focus", "label": "Focus", "value": "normal"},
            {"kind": "session", "label": "Durée session", "value": "25 min"},
            {
                "kind": "file_activity",
                "label": "Activité fichiers",
                "value": "4 fichier(s) touché(s) sur 10 min, surtout code source (2), documentation (1), tests (1)",
            },
            {
                "kind": "file_reading",
                "label": "Lecture de la session",
                "value": "petit lot cohérent de 4 fichiers, ça ressemble à une évolution de fonctionnalité",
            },
            {"kind": "file", "label": "Fichier actif", "value": "/tmp/main.py"},
        ]
        expected_details = {
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

        self.assertEqual(proposal.id, "proposal-123")
        self.assertEqual(proposal.type, "context_injection")
        self.assertEqual(proposal.trigger, "file_modified")
        self.assertEqual(proposal.title, "Contexte de session prêt à être injecté")
        self.assertEqual(proposal.summary, "Le contexte local est jugé assez riche pour une réponse assistée.")
        self.assertEqual(
            proposal.rationale,
            "La session a accumulé assez de contexte local pour justifier une injection de contexte existante.",
        )
        self.assertEqual(proposal.evidence, expected_evidence)
        self.assertEqual(proposal.confidence, 0.66)
        self.assertEqual(proposal.proposed_action, "inject_current_context")
        self.assertEqual(proposal.status, "executed")
        self.assertEqual(proposal.metadata, {"details": expected_details})
        self.assertEqual(
            [entry["status"] for entry in proposal.lifecycle],
            ["created", "pending", "executed"],
        )

        _, runtime_decision = self.runtime_state.get_context_snapshot()
        self.assertEqual(
            runtime_decision.payload,
            {"project": "Pulse", "task": "coding", "proposal_id": "proposal-123"},
        )

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


    # ── C4 : priorité signals > state pour active_file et active_project ──────

    def test_c4_signals_active_file_prime_sur_state_active_file(self):
        """
        Quand signals a un fichier actif, il doit primer sur StateStore.
        StateStore peut pointer un fichier obsolète (ancien session, fichier supprimé).
        """
        self.store.to_dict.return_value = {
            "active_project": "OldProject",
            "active_file": "/stale/path/from_store.py",  # ← StateStore : potentiellement obsolète
            "active_app": "Xcode",
            "session_duration_min": 999,
        }
        self.runtime_state.set_analysis(
            signals=Signals(
                active_project="Pulse",
                active_file="/fresh/path/current.py",  # ← Signals : fenêtre courante
                probable_task="coding",
                friction_score=0.1,
                focus_level="normal",
                session_duration_min=30,
                recent_apps=["Xcode"],
                clipboard_context=None,
            ),
            decision=None,
        )

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("/fresh/path/current.py", snapshot,
            "signals.active_file doit primer sur state.active_file")
        self.assertNotIn("/stale/path/from_store.py", snapshot,
            "Le fichier StateStore obsolète ne doit pas apparaître dans le snapshot LLM")
        self.assertIn("- Projet : Pulse", snapshot,
            "signals.active_project doit primer sur state.active_project")
        self.assertNotIn("OldProject", snapshot)

    def test_c4_fallback_sur_state_si_signals_active_file_est_none(self):
        """
        Quand signals.active_file est None (bus vide ou fenêtre vide),
        on se rabat sur StateStore comme dernier recours.
        """
        self.store.to_dict.return_value = {
            "active_project": "FallbackProject",
            "active_file": "/fallback/from_store.py",
            "active_app": "Terminal",
            "session_duration_min": 10,
        }
        self.runtime_state.set_analysis(
            signals=Signals(
                active_project=None,   # ← Signals n'a pas de fichier courant
                active_file=None,
                probable_task="general",
                friction_score=0.0,
                focus_level="normal",
                session_duration_min=5,
                recent_apps=[],
                clipboard_context=None,
            ),
            decision=None,
        )

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("/fallback/from_store.py", snapshot,
            "state.active_file doit être utilisé en fallback quand signals.active_file est None")
        self.assertIn("FallbackProject", snapshot)

    def test_c4_aucun_fichier_affiche_aucun_si_les_deux_sont_none(self):
        """Cas démarrage à froid : ni signals ni state n'ont de fichier."""
        self.store.to_dict.return_value = {
            "active_project": None,
            "active_file": None,
            "active_app": None,
            "session_duration_min": 0,
        }
        self.runtime_state.set_analysis(
            signals=Signals(
                active_project=None,
                active_file=None,
                probable_task="general",
                friction_score=0.0,
                focus_level="normal",
                session_duration_min=0,
                recent_apps=[],
                clipboard_context=None,
            ),
            decision=None,
        )

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Fichier actif : aucun", snapshot)
        self.assertIn("- Projet : non détecté", snapshot)

    # ── C5 : priorité signals > state pour session_duration_min ─────────────

    def test_c5_signals_duration_prime_sur_state_duration(self):
        """
        StateStore.session_start est figé au démarrage du daemon.
        La valeur renvoyée par state.session_duration_min est presque toujours
        plus grande que la vraie durée de session. Signals doit primer.
        """
        self.store.to_dict.return_value = {
            "active_project": "Pulse",
            "active_file": None,
            "active_app": "Xcode",
            "session_duration_min": 240,  # ← StateStore : depuis le démarrage du daemon
        }
        self.runtime_state.set_analysis(
            signals=Signals(
                active_project="Pulse",
                active_file=None,
                probable_task="coding",
                friction_score=0.0,
                focus_level="normal",
                session_duration_min=45,  # ← Signals : vraie durée de session
                recent_apps=["Xcode"],
                clipboard_context=None,
            ),
            decision=None,
        )

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Durée session : 45 min", snapshot,
            "signals.session_duration_min doit primer sur state.session_duration_min")
        self.assertNotIn("240 min", snapshot,
            "La durée StateStore (depuis démarrage daemon) ne doit pas apparaître")

    def test_c5_zero_si_signals_absent(self):
        """
        Sans signals (démarrage daemon, avant le premier event),
        on préfère 0 à la durée fausse de StateStore.
        """
        self.store.to_dict.return_value = {
            "active_project": None,
            "active_file": None,
            "active_app": None,
            "session_duration_min": 15,  # ← StateStore : depuis le démarrage du daemon
        }
        # Pas de signals : runtime_state non initialisé
        # (get_context_snapshot retourne (None, None) par défaut)

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Durée session : 0 min", snapshot,
            "Sans signals, la durée doit être 0 plutôt que la valeur fausse du StateStore")
        self.assertNotIn("15 min", snapshot)

    def test_c5_zero_si_signals_duration_est_zero(self):
        """
        Si signals.session_duration_min est 0 (scorer vient de reset),
        on affiche 0 — pas la valeur StateStore qui serait trop grande.
        """
        self.store.to_dict.return_value = {
            "active_project": "Pulse",
            "active_file": None,
            "active_app": "Xcode",
            "session_duration_min": 90,  # ← StateStore : ancienne valeur
        }
        self.runtime_state.set_analysis(
            signals=Signals(
                active_project="Pulse",
                active_file=None,
                probable_task="coding",
                friction_score=0.0,
                focus_level="normal",
                session_duration_min=0,  # ← Scorer vient de reset
                recent_apps=["Xcode"],
                clipboard_context=None,
            ),
            decision=None,
        )

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Durée session : 0 min", snapshot,
            "session_duration_min=0 depuis le scorer doit afficher 0, pas la valeur StateStore")
        self.assertNotIn("90 min", snapshot)


    # ── I2 : flush file events — file_deleted ne bloque pas inject_context ────

    def test_i2_burst_terminant_par_delete_utilise_dernier_event_non_delete(self):
        """
        Un burst [modified, modified, deleted] doit passer le dernier 'modified'
        comme trigger, pas le 'deleted'. DecisionEngine refuse file_deleted
        comme trigger pour inject_context.
        """
        from daemon.core.event_bus import Event
        from unittest.mock import patch

        events = [
            Event("file_modified", {"path": "/tmp/a.py"}),
            Event("file_modified", {"path": "/tmp/b.py"}),
            Event("file_deleted", {"path": "/tmp/old.py"}),  # dernier du burst
        ]

        captured_triggers = []

        def fake_process_signals(trigger_event):
            captured_triggers.append(trigger_event)

        with self.orchestrator._debounce_lock:
            self.orchestrator._pending_file_events = events[:]

        with patch.object(self.orchestrator, "_process_signals", side_effect=fake_process_signals):
            self.orchestrator._flush_file_events()

        self.assertEqual(len(captured_triggers), 1)
        self.assertNotEqual(captured_triggers[0].type, "file_deleted",
            "Le trigger ne doit pas être file_deleted quand des events non-delete existent")
        self.assertEqual(captured_triggers[0].type, "file_modified")
        self.assertEqual(captured_triggers[0].payload["path"], "/tmp/b.py",
            "Le trigger doit être le dernier event non-delete du burst")

    def test_i2_burst_tout_delete_utilise_le_dernier_event(self):
        """
        Si tout le burst est des deletions (cas rare), on garde le comportement
        existant : events[-1] est utilisé comme trigger.
        """
        from daemon.core.event_bus import Event
        from unittest.mock import patch

        events = [
            Event("file_deleted", {"path": "/tmp/x.py"}),
            Event("file_deleted", {"path": "/tmp/y.py"}),
        ]

        captured_triggers = []

        def fake_process_signals(trigger_event):
            captured_triggers.append(trigger_event)

        with self.orchestrator._debounce_lock:
            self.orchestrator._pending_file_events = events[:]

        with patch.object(self.orchestrator, "_process_signals", side_effect=fake_process_signals):
            self.orchestrator._flush_file_events()

        self.assertEqual(len(captured_triggers), 1)
        self.assertEqual(captured_triggers[0].type, "file_deleted")
        self.assertEqual(captured_triggers[0].payload["path"], "/tmp/y.py",
            "Fallback : dernier event du burst si tout est delete")

    def test_i2_burst_sans_delete_comportement_inchange(self):
        """
        Régression : un burst sans delete doit continuer à utiliser
        le dernier event du burst (comportement original préservé).
        """
        from daemon.core.event_bus import Event
        from unittest.mock import patch

        events = [
            Event("file_modified", {"path": "/tmp/a.py"}),
            Event("file_created", {"path": "/tmp/b.py"}),
            Event("file_renamed", {"path": "/tmp/c.py"}),
        ]

        captured_triggers = []

        def fake_process_signals(trigger_event):
            captured_triggers.append(trigger_event)

        with self.orchestrator._debounce_lock:
            self.orchestrator._pending_file_events = events[:]

        with patch.object(self.orchestrator, "_process_signals", side_effect=fake_process_signals):
            self.orchestrator._flush_file_events()

        self.assertEqual(captured_triggers[0].type, "file_renamed")
        self.assertEqual(captured_triggers[0].payload["path"], "/tmp/c.py")


    # -- Verrou court : session_duration_min ne doit pas inclure le temps de veille ---

    def test_verrou_court_conserve_session_started_at_sans_nouvelle_session(self):
        """
        Verrou < sleep_session_threshold_min (30 min) :
        - la session est conservee
        - session_memory.new_session() ne doit PAS etre appele
        Le debut de session ne doit pas etre reinitialise.
        """
        from datetime import timedelta
        from daemon.core.event_bus import Event

        original_start = self.orchestrator.session_fsm.session_started_at
        # Simule un verrou qui s'est produit il y a 10 min
        t_lock = datetime.now() - timedelta(minutes=10)
        self.runtime_state.mark_screen_locked(when=t_lock)

        unlock_event = Event("screen_unlocked", {})

        with patch.object(self.orchestrator.session_memory, "new_session") as mock_new_session, \
             patch.object(self.orchestrator, "_process_signals"):
            self.orchestrator.handle_event(unlock_event)

        mock_new_session.assert_not_called(
        ), "session_memory.new_session() ne doit pas etre appele pour un verrou court"
        self.assertEqual(
            self.orchestrator.session_fsm.session_started_at,
            original_start,
            "session_started_at doit rester stable sur un verrou court",
        )

    def test_verrou_long_reset_scorer_et_nouvelle_session(self):
        """
        Verrou >= sleep_session_threshold_min (30 min) :
        - session_memory.new_session() appele
        Comportement existant preserve.
        """
        from datetime import timedelta
        from daemon.core.event_bus import Event

        # Simule un verrou il y a 35 min (> seuil de 30 min)
        t_lock = datetime.now() - timedelta(minutes=35)
        self.runtime_state.mark_screen_locked(when=t_lock)

        unlock_event = Event("screen_unlocked", {})

        with patch.object(self.orchestrator.session_memory, "new_session") as mock_new_session, \
             patch.object(self.orchestrator.session_memory, "export_session_data",
                          return_value={"duration_min": 0}), \
             patch("daemon.runtime_orchestrator.update_memories_from_session"), \
             patch.object(self.orchestrator, "_process_signals"):
            original_start = self.orchestrator.session_fsm.session_started_at
            self.orchestrator.handle_event(unlock_event)

        mock_new_session.assert_called_once(
        ), "session_memory.new_session() doit etre appele pour un verrou long"
        self.assertNotEqual(
            self.orchestrator.session_fsm.session_started_at,
            original_start,
            "session_started_at doit etre reinitialise sur une vraie nouvelle session",
        )

    def test_verrou_court_clear_sleep_markers_apres_unlock(self):
        """
        Apres un verrou court, clear_sleep_markers() doit etre appele pour
        eviter que le prochain unlock calcule sleep_min depuis un ancien lock.
        """
        from datetime import timedelta
        from daemon.core.event_bus import Event

        t_lock = datetime.now() - timedelta(minutes=5)
        self.runtime_state.mark_screen_locked(when=t_lock)

        self.assertIsNotNone(self.runtime_state.get_last_screen_locked_at())

        unlock_event = Event("screen_unlocked", {})

        with patch.object(self.orchestrator, "_process_signals"):
            self.orchestrator.handle_event(unlock_event)

        self.assertIsNone(
            self.runtime_state.get_last_screen_locked_at(),
            "_last_screen_locked_at doit etre efface apres un verrou court"
        )


if __name__ == "__main__":
    unittest.main()
