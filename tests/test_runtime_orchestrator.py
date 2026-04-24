import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from daemon.core.context_formatter import format_file_activity_summary
from daemon.core.contracts import Episode
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

    def _set_runtime_analysis(
        self,
        signals,
        *,
        decision=None,
        session_status="active",
        awake=True,
        locked=False,
    ):
        self.runtime_state.update_present(
            signals=signals,
            session_status=session_status,
            awake=awake,
            locked=locked,
        )
        self.runtime_state.set_analysis(
            signals=signals,
            decision=decision,
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
        self._set_runtime_analysis(
            signals,
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
        self.assertEqual(present.active_file, "/tmp/pulse/runtime.py")
        self.assertEqual(present.probable_task, "debug")
        self.assertEqual(present.activity_level, "executing")
        self.assertEqual(present.focus_level, "deep")
        self.assertEqual(present.session_duration_min, 31)
        self.assertEqual(present.updated_at, event.timestamp)
        current_context = self.orchestrator._render_current_context(
            present=present,
            signals=self.scorer.compute.return_value,
            active_app=self.store.to_dict().get("active_app"),
        )
        self.assertEqual(current_context.active_project, present.active_project)
        self.assertEqual(current_context.active_file, present.active_file)
        self.assertEqual(current_context.probable_task, present.probable_task)
        self.assertEqual(current_context.activity_level, present.activity_level)
        self.assertEqual(current_context.focus_level, present.focus_level)
        self.assertEqual(current_context.session_duration_min, present.session_duration_min)

    def test_handle_event_updates_present_via_single_runtime_state_path(self):
        event = Event("app_activated", {"app_name": "Xcode"})
        event.timestamp = datetime(2026, 4, 23, 11, 15, 0)
        self.scorer.bus.recent.return_value = [event]
        self.scorer.compute.return_value = self._signals()
        self.decision_engine.evaluate.return_value = Decision("silent", 0, "nothing_relevant")

        with patch.object(
            self.runtime_state,
            "update_present",
            wraps=self.runtime_state.update_present,
        ) as update_present:
            self.orchestrator.handle_event(event)

        update_present.assert_called_once()
        kwargs = update_present.call_args.kwargs
        self.assertEqual(kwargs["session_status"], "active")
        self.assertTrue(kwargs["awake"])
        self.assertFalse(kwargs["locked"])
        self.assertEqual(kwargs["updated_at"], event.timestamp)
        self.assertEqual(kwargs["signals"].active_project, "Pulse")

    def test_build_context_snapshot_golden_legacy_markdown_output_exact(self):
        self.store.to_dict.return_value = {
            "active_project": "Pulse",
            "active_file": "/Users/yugz/Projets/Pulse/Pulse/daemon/runtime_orchestrator.py",
            "active_app": "Cursor",
            "session_duration_min": 96,
            "last_event_type": "file_modified",
        }
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
        self.store.to_dict.return_value = {
            "active_app": "Cursor",
            "last_event_type": "file_modified",
        }

        with patch.object(self.runtime_state, "get_context_snapshot", side_effect=AssertionError("legacy context snapshot must not be used")), \
             patch.object(self.runtime_state, "get_present", side_effect=AssertionError("legacy present getter must not be used")):
            snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Projet : Pulse", snapshot)

    def test_build_context_snapshot_falls_back_to_signal_context_when_store_is_empty(self):
        self.store.to_dict.return_value = {
            "active_project": None,
            "active_file": None,
            "active_app": None,
            "session_duration_min": 0,
            "last_event_type": None,
        }
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=24,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )
        self._set_runtime_analysis(signals)

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
        signals = Signals(
            active_project="client-repo",
            active_file="/tmp/client-repo/src/main.py",
            probable_task="coding",
            friction_score=0.1,
            focus_level="normal",
            session_duration_min=18,
            recent_apps=["Cursor"],
            clipboard_context=None,
        )
        self._set_runtime_analysis(signals)

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

    def test_freeze_memory_uses_project_memory_before_support_layers(self):
        self.memory_store.render.return_value = "Structured memory"

        with patch("daemon.runtime_orchestrator.render_project_memory", return_value="# Projets\n\n## Pulse"):
            self.orchestrator.freeze_memory()

        self.assertEqual(self.orchestrator.get_frozen_memory(), "# Projets\n\n## Pulse\n\nStructured memory")
        self.assertIsInstance(self.orchestrator.get_frozen_memory_at(), datetime)

    def test_freeze_memory_mis_a_jour_apres_sync(self):
        """freeze_memory() reflète toujours le contenu le plus récent."""
        self.memory_store.render.return_value = "Avant sync"
        with patch("daemon.runtime_orchestrator.render_project_memory", return_value="# Projets\n\n## Pulse"):
            self.orchestrator.freeze_memory()
        self.assertEqual(self.orchestrator.get_frozen_memory(), "# Projets\n\n## Pulse\n\nAvant sync")

        # Simule une mise à jour de la mémoire après une sync
        self.memory_store.render.return_value = "Après sync"
        with patch("daemon.runtime_orchestrator.render_project_memory", return_value="# Projets\n\n## Pulse"):
            self.orchestrator.freeze_memory()

        self.assertEqual(self.orchestrator.get_frozen_memory(), "# Projets\n\n## Pulse\n\nAprès sync")
        self.assertIsInstance(self.orchestrator.get_frozen_memory_at(), datetime)

    def test_freeze_memory_inclut_memoire_comportementale_apres_memoire_projet(self):
        """Le profil utilisateur vient après la mémoire projet et avant le support technique."""
        self.memory_store.render.return_value = "Structured memory"
        self.mock_fact_engine.render_for_context.return_value = "── Profil utilisateur ──\n• [workflow] Coding le soir"

        with patch("daemon.runtime_orchestrator.render_project_memory", return_value="# Projets\n\n## Pulse"):
            self.orchestrator.freeze_memory()

        frozen = self.orchestrator.get_frozen_memory()
        self.assertEqual(
            frozen,
            "# Projets\n\n## Pulse\n\n── Profil utilisateur ──\n• [workflow] Coding le soir\n\nStructured memory",
        )

    def test_freeze_memory_fallback_legacy_si_projet_et_support_absents(self):
        """Le fallback legacy ne s'active que si mémoire projet et support sont absents."""
        self.memory_store.render.return_value = ""

        with patch("daemon.runtime_orchestrator.render_project_memory", return_value=""), \
             patch("daemon.runtime_orchestrator.load_memory_context", return_value="Legacy memory"):
            self.orchestrator.freeze_memory()

        self.assertEqual(self.orchestrator.get_frozen_memory(), "Legacy memory")

    def test_freeze_memory_ignore_legacy_si_memoire_projet_disponible(self):
        self.memory_store.render.return_value = ""

        with patch("daemon.runtime_orchestrator.render_project_memory", return_value="# Projets\n\n## Pulse"), \
             patch("daemon.runtime_orchestrator.load_memory_context", return_value="Legacy memory"):
            self.orchestrator.freeze_memory()

        self.assertEqual(self.orchestrator.get_frozen_memory(), "# Projets\n\n## Pulse")

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
        self.assertEqual(saved.active_project, "Pulse")
        self.assertEqual(saved.probable_task, "coding")
        self.assertEqual(saved.activity_level, "editing")
        self.assertEqual(saved.task_confidence, 0.83)
        self.assertEqual(self.orchestrator.current_episode, saved)

    def test_process_signals_updates_active_episode_semantics_from_present(self):
        started_at = datetime(2026, 4, 23, 17, 0, 0)
        with patch("daemon.core.episode_fsm.new_uid", return_value="ep-1"):
            self.orchestrator._episode_fsm.ensure_active(
                session_id="session-1",
                started_at=started_at,
            )
        event = Event("app_activated", {"app_name": "Cursor"}, timestamp=started_at + timedelta(minutes=3))
        self.scorer.bus.recent.return_value = [event]
        self.scorer.compute.return_value = self._signals(
            probable_task="debug",
            activity_level="executing",
            session_duration_min=8,
            task_confidence=0.82,
        )
        self.decision_engine.evaluate.return_value = Decision(action="silent", level=0, reason="ok", payload={})

        self.session_memory.save_episode.reset_mock()
        self.orchestrator._process_signals(event)

        saved = self.session_memory.save_episode.call_args[0][0]
        present = self.runtime_state.get_runtime_snapshot().present
        self.assertEqual(saved.id, "ep-1")
        self.assertEqual(saved.active_project, present.active_project)
        self.assertEqual(saved.probable_task, present.probable_task)
        self.assertEqual(saved.activity_level, present.activity_level)
        self.assertEqual(saved.task_confidence, 0.82)

    def test_process_signals_stable_task_change_opens_new_episode(self):
        start = datetime.now()
        first = Event("file_modified", {"path": "/tmp/main.py"}, timestamp=start)
        second = Event("app_activated", {"app_name": "Terminal"}, timestamp=start + timedelta(minutes=2))
        third = Event("app_activated", {"app_name": "Terminal"}, timestamp=start + timedelta(minutes=3))

        self.scorer.bus.recent.return_value = [first]
        self.scorer.compute.return_value = self._signals(
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.91,
        )
        self.decision_engine.evaluate.return_value = Decision(action="silent", level=0, reason="ok", payload={})
        with patch("daemon.core.episode_fsm.new_uid", side_effect=["ep-1", "ep-2"]):
            self.orchestrator._process_signals(first)
            self.session_memory.save_episode.reset_mock()

            self.scorer.bus.recent.return_value = [first, second]
            self.scorer.compute.return_value = self._signals(
                probable_task="debug",
                activity_level="executing",
                task_confidence=0.89,
                active_file="/tmp/main.py",
            )
            self.orchestrator._process_signals(second)
            self.session_memory.save_episode.assert_not_called()
            self.assertEqual(self.orchestrator.current_episode.id, "ep-1")
            self.assertEqual(self.orchestrator.current_episode.probable_task, "coding")

            self.scorer.bus.recent.return_value = [first, second, third]
            self.scorer.compute.return_value = self._signals(
                probable_task="debug",
                activity_level="executing",
                task_confidence=0.89,
                active_file="/tmp/main.py",
            )
            self.orchestrator._process_signals(third)

        self.assertEqual(self.session_memory.save_episode.call_count, 2)
        saved_episodes = [call[0][0] for call in self.session_memory.save_episode.call_args_list]
        closed = next(episode for episode in saved_episodes if episode.boundary_reason == "task_change")
        opened = next(episode for episode in saved_episodes if episode.ended_at is None and episode.id != closed.id)
        self.assertEqual(closed.probable_task, "coding")
        self.assertEqual(opened.probable_task, "debug")
        self.assertEqual(opened.activity_level, "executing")

    def test_process_signals_stable_project_change_opens_new_episode(self):
        start = datetime.now()
        first = Event("file_modified", {"path": "/tmp/pulse/main.py"}, timestamp=start)
        second = Event("browser_active", {"app_name": "Chrome"}, timestamp=start + timedelta(minutes=2))
        third = Event("browser_active", {"app_name": "Chrome"}, timestamp=start + timedelta(minutes=3))

        self.scorer.bus.recent.return_value = [first]
        self.scorer.compute.return_value = self._signals(
            active_project="Pulse",
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.91,
        )
        self.decision_engine.evaluate.return_value = Decision(action="silent", level=0, reason="ok", payload={})
        with patch("daemon.core.episode_fsm.new_uid", side_effect=["ep-1", "ep-2"]):
            self.orchestrator._process_signals(first)
            self.session_memory.save_episode.reset_mock()

            self.scorer.bus.recent.return_value = [first, second]
            self.scorer.compute.return_value = self._signals(
                active_project="Client",
                probable_task="coding",
                activity_level="reading",
                task_confidence=0.91,
                active_file="/tmp/client/main.py",
                recent_apps=["Chrome"],
            )
            self.orchestrator._process_signals(second)
            self.session_memory.save_episode.assert_not_called()

            self.scorer.bus.recent.return_value = [first, second, third]
            self.scorer.compute.return_value = self._signals(
                active_project="Client",
                probable_task="coding",
                activity_level="reading",
                task_confidence=0.91,
                active_file="/tmp/client/main.py",
                recent_apps=["Chrome"],
            )
            self.orchestrator._process_signals(third)

        saved_episodes = [call[0][0] for call in self.session_memory.save_episode.call_args_list]
        closed = next(episode for episode in saved_episodes if episode.boundary_reason == "project_change")
        opened = next(episode for episode in saved_episodes if episode.ended_at is None and episode.id != closed.id)
        self.assertEqual(closed.active_project, "Pulse")
        self.assertEqual(opened.active_project, "Client")
        self.assertEqual(opened.probable_task, "coding")

    def test_process_signals_mode_oscillation_does_not_split_episode(self):
        start = datetime.now()
        first = Event("file_modified", {"path": "/tmp/main.py"}, timestamp=start)
        second = Event("browser_active", {"app_name": "Chrome"}, timestamp=start + timedelta(minutes=1))

        self.scorer.bus.recent.return_value = [first]
        self.scorer.compute.return_value = self._signals(
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.91,
        )
        self.decision_engine.evaluate.return_value = Decision(action="silent", level=0, reason="ok", payload={})
        with patch("daemon.core.episode_fsm.new_uid", return_value="ep-1"):
            self.orchestrator._process_signals(first)

        self.session_memory.save_episode.reset_mock()
        self.scorer.bus.recent.return_value = [first, second]
        self.scorer.compute.return_value = self._signals(
            probable_task="coding",
            activity_level="reading",
            task_confidence=0.91,
            recent_apps=["Chrome"],
        )
        self.orchestrator._process_signals(second)

        self.assertEqual(self.session_memory.save_episode.call_count, 1)
        saved = self.session_memory.save_episode.call_args[0][0]
        self.assertIsNone(saved.boundary_reason)
        self.assertEqual(saved.id, "ep-1")
        self.assertEqual(saved.probable_task, "coding")
        self.assertEqual(saved.activity_level, "reading")

    def test_process_signals_navigation_dans_le_meme_bloc_ne_split_pas(self):
        start = datetime.now()
        first = Event("file_modified", {"path": "/tmp/main.py"}, timestamp=start)
        second = Event("browser_active", {"app_name": "Chrome"}, timestamp=start + timedelta(minutes=1))

        self.scorer.bus.recent.return_value = [first]
        self.scorer.compute.return_value = self._signals(
            active_project="Pulse",
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.91,
        )
        self.decision_engine.evaluate.return_value = Decision(action="silent", level=0, reason="ok", payload={})
        with patch("daemon.core.episode_fsm.new_uid", return_value="ep-1"):
            self.orchestrator._process_signals(first)

        self.session_memory.save_episode.reset_mock()
        self.scorer.bus.recent.return_value = [first, second]
        self.scorer.compute.return_value = self._signals(
            active_project="Pulse",
            probable_task="coding",
            activity_level="navigating",
            task_confidence=0.91,
            recent_apps=["Chrome"],
        )
        self.orchestrator._process_signals(second)

        saved = self.session_memory.save_episode.call_args[0][0]
        self.assertIsNone(saved.boundary_reason)
        self.assertEqual(saved.id, "ep-1")
        self.assertEqual(saved.active_project, "Pulse")
        self.assertEqual(saved.probable_task, "coding")
        self.assertEqual(saved.activity_level, "navigating")

    def test_process_signals_ne_fait_pas_regresser_observed_now_si_event_ancien_arrive_en_retard(self):
        newer = Event("app_activated", {"app_name": "Chrome"})
        newer.timestamp = datetime(2026, 4, 23, 18, 10, 0)
        older = Event("app_activated", {"app_name": "Cursor"})
        older.timestamp = datetime(2026, 4, 23, 18, 5, 0)

        self.scorer.bus.recent.return_value = [newer, older]
        self.scorer.compute.return_value = self._signals(session_duration_min=10)
        self.decision_engine.evaluate.return_value = Decision(action="silent", level=0, reason="ok", payload={})

        with patch.object(self.runtime_state, "update_present", wraps=self.runtime_state.update_present) as update_present:
            self.orchestrator._process_signals(older)

        self.assertEqual(
            self.scorer.compute.call_args.kwargs["observed_now"],
            newer.timestamp,
        )
        self.assertEqual(
            update_present.call_args.kwargs["updated_at"],
            newer.timestamp,
        )

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

        self.assertEqual(self.session_memory.save_episode.call_count, 3)
        saved_episodes = [call[0][0] for call in self.session_memory.save_episode.call_args_list]
        closed = next(episode for episode in saved_episodes if episode.boundary_reason == "commit")
        opened = next(
            episode
            for episode in saved_episodes
            if episode.ended_at is None and episode.id != closed.id
        )
        self.assertEqual(closed.boundary_reason, "commit")
        self.assertIsNotNone(closed.ended_at)
        self.assertEqual(closed.active_project, "Pulse")
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

        closed = next(
            episode
            for episode in (call[0][0] for call in self.session_memory.save_episode.call_args_list)
            if episode.boundary_reason == "idle_timeout"
        )
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

        closed = next(
            episode
            for episode in (call[0][0] for call in self.session_memory.save_episode.call_args_list)
            if episode.boundary_reason == "screen_lock"
        )
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

    def test_freeze_closed_episode_preserves_existing_semantics(self):
        self.runtime_state.update_present(
            signals=self._signals(
                active_project="Other",
                probable_task="writing",
                activity_level="reading",
                task_confidence=0.25,
            ),
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(
            signals=self._signals(
                active_project="Other",
                probable_task="writing",
                activity_level="reading",
                task_confidence=0.25,
            ),
            decision=Decision(action="silent", level=0, reason="ok", payload={}),
        )

        frozen = self.orchestrator._freeze_closed_episode_semantics(
            Episode(
                id="ep-1",
                session_id="session-1",
                started_at="2026-04-23T16:00:00",
                ended_at="2026-04-23T16:20:00",
                boundary_reason="commit",
                duration_sec=1200,
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.91,
            )
        )

        self.assertEqual(frozen.active_project, "Pulse")
        self.assertEqual(frozen.probable_task, "coding")
        self.assertEqual(frozen.activity_level, "editing")
        self.assertEqual(frozen.task_confidence, 0.91)

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
        signals = Signals(
            active_project="Pulse",
            active_file="/fresh/path/current.py",  # ← Present canonique
            probable_task="coding",
            friction_score=0.1,
            focus_level="normal",
            session_duration_min=30,
            recent_apps=["Xcode"],
            clipboard_context=None,
        )
        self._set_runtime_analysis(signals)

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("/fresh/path/current.py", snapshot,
            "signals.active_file doit primer sur state.active_file")
        self.assertNotIn("/stale/path/from_store.py", snapshot,
            "Le fichier StateStore obsolète ne doit pas apparaître dans le snapshot LLM")
        self.assertIn("- Projet : Pulse", snapshot,
            "signals.active_project doit primer sur state.active_project")
        self.assertNotIn("OldProject", snapshot)

    def test_c4_aucun_fallback_sur_state_si_present_n_a_pas_de_fichier(self):
        """
        Le renderer de contexte ne doit plus relire StateStore pour reconstruire
        active_file / active_project.
        """
        self.store.to_dict.return_value = {
            "active_project": "FallbackProject",
            "active_file": "/fallback/from_store.py",
            "active_app": "Terminal",
            "session_duration_min": 10,
        }
        signals = Signals(
            active_project=None,
            active_file=None,
            probable_task="general",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=5,
            recent_apps=[],
            clipboard_context=None,
        )
        self._set_runtime_analysis(signals)

        snapshot = self.orchestrator.build_context_snapshot()

        self.assertIn("- Fichier actif : aucun", snapshot)
        self.assertIn("- Projet : non détecté", snapshot)
        self.assertNotIn("/fallback/from_store.py", snapshot)
        self.assertNotIn("FallbackProject", snapshot)

    def test_c4_aucun_fichier_affiche_aucun_si_les_deux_sont_none(self):
        """Cas démarrage à froid : ni signals ni state n'ont de fichier."""
        self.store.to_dict.return_value = {
            "active_project": None,
            "active_file": None,
            "active_app": None,
            "session_duration_min": 0,
        }
        signals = Signals(
            active_project=None,
            active_file=None,
            probable_task="general",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=0,
            recent_apps=[],
            clipboard_context=None,
        )
        self._set_runtime_analysis(signals)

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
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="coding",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=45,  # ← Present canonique
            recent_apps=["Xcode"],
            clipboard_context=None,
        )
        self._set_runtime_analysis(signals)

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
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="coding",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=0,  # ← Scorer vient de reset
            recent_apps=["Xcode"],
            clipboard_context=None,
        )
        self._set_runtime_analysis(signals)

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

    def test_i2_burst_hors_ordre_choisit_le_plus_recent_par_timestamp(self):
        from datetime import datetime, timedelta
        from daemon.core.event_bus import Event
        from unittest.mock import patch

        base = datetime.now()
        latest = Event("file_modified", {"path": "/tmp/new.py"})
        latest.timestamp = base
        older = Event("file_modified", {"path": "/tmp/old.py"})
        older.timestamp = base - timedelta(minutes=2)

        events = [latest, older]
        captured_triggers = []

        def fake_process_signals(trigger_event):
            captured_triggers.append(trigger_event)

        with self.orchestrator._debounce_lock:
            self.orchestrator._pending_file_events = events[:]

        with patch.object(self.orchestrator, "_process_signals", side_effect=fake_process_signals):
            self.orchestrator._flush_file_events()

        self.assertEqual(len(captured_triggers), 1)
        self.assertEqual(captured_triggers[0].payload["path"], "/tmp/new.py")


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

    def test_verrou_court_puis_reprise_d_activite_ne_cree_pas_de_session_fantome(self):
        t_before = datetime.now() - timedelta(minutes=20)
        t_lock = datetime.now() - timedelta(minutes=10)
        t_unlock = datetime.now() - timedelta(minutes=9)
        t_after = datetime.now()

        previous_event = Event("file_modified", {"path": "/tmp/main.py"})
        previous_event.timestamp = t_before
        lock_event = Event("screen_locked", {})
        lock_event.timestamp = t_lock
        resumed_event = Event("file_modified", {"path": "/tmp/main.py"})
        resumed_event.timestamp = t_after

        self.orchestrator.session_fsm._session_started_at = t_before - timedelta(minutes=30)
        self.orchestrator.session_fsm.observe_recent_events(
            recent_events=[previous_event],
            now=t_before,
        )
        original_start = self.orchestrator.session_fsm.session_started_at
        self.orchestrator.session_fsm.on_screen_locked(when=t_lock)
        transition = self.orchestrator.session_fsm.on_screen_unlocked(
            when=t_unlock,
            sleep_session_threshold_min=30,
        )
        self.assertFalse(transition.should_start_new_session)

        self.scorer.bus.recent.return_value = [previous_event, lock_event, resumed_event]
        self.scorer.compute.return_value = self._signals(session_duration_min=5)
        self.decision_engine.evaluate.return_value = Decision("silent", 0, "nothing_relevant")

        with patch.object(self.session_memory, "new_session") as mock_new_session:
            self.orchestrator._process_signals(resumed_event)

        mock_new_session.assert_not_called()
        self.assertEqual(self.orchestrator.session_fsm.session_started_at, original_start)

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
