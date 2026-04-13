import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from daemon.core.decision_engine import Decision
from daemon.core.signal_scorer import Signals
from daemon.runtime_orchestrator import RuntimeOrchestrator
from daemon.runtime_state import RuntimeState


class TestRuntimeOrchestrator(unittest.TestCase):
    def setUp(self):
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


if __name__ == "__main__":
    unittest.main()
