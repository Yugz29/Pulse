import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

from daemon.core.decision_engine import DecisionEngine
from daemon.core.event_bus import EventBus
from daemon.core.signal_scorer import SignalScorer
from daemon.memory.session import SessionMemory
from daemon.routes.runtime import register_runtime_routes
from daemon.runtime_orchestrator import RuntimeOrchestrator
from daemon.runtime_state import RuntimeState


class TestRuntimeLifecycle(unittest.TestCase):
    def _orchestrator(
        self,
        *,
        bus,
        session_memory,
        runtime_state,
        memory_store,
        llm_runtime,
        fact_engine,
        file_debounce_sec=0.01,
    ) -> RuntimeOrchestrator:
        with patch("daemon.runtime_orchestrator.get_fact_engine", return_value=fact_engine):
            return RuntimeOrchestrator(
                store=MagicMock(),
                scorer=SignalScorer(bus),
                decision_engine=DecisionEngine(),
                summary_llm=MagicMock(),
                session_memory=session_memory,
                memory_store=memory_store,
                runtime_state=runtime_state,
                llm_runtime=llm_runtime,
                log=MagicMock(),
                file_debounce_sec=file_debounce_sec,
            )

    def test_runtime_lifecycle_short_restart_restores_session_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            restart_state_path = tmp / "restart_state.json"
            session_db_path = tmp / "session.db"
            tmp_project = tmp / "Pulse"
            tmp_project.mkdir()

            memory_store = MagicMock()
            memory_store.render.return_value = ""
            llm_runtime = MagicMock()
            fact_engine = MagicMock()
            fact_engine.render_for_context.return_value = ""

            bus = EventBus()
            runtime_state = RuntimeState()
            session_memory = SessionMemory(db_path=str(session_db_path))
            orchestrator = self._orchestrator(
                bus=bus,
                session_memory=session_memory,
                runtime_state=runtime_state,
                memory_store=memory_store,
                llm_runtime=llm_runtime,
                fact_engine=fact_engine,
            )

            with patch("daemon.core.restart_manager._STATE_PATH", restart_state_path), \
                 patch("daemon.core.restart_manager._read_project_head_sha", return_value=None), \
                 patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=None):
                orchestrator.start()
                bus.subscribe(orchestrator.handle_event)

                observed_at = datetime.now()
                bus.publish(
                    "terminal_command_finished",
                    {
                        "terminal_project": "Pulse",
                        "terminal_cwd": str(tmp_project),
                        "terminal_success": True,
                        "terminal_action_category": "inspection",
                        "terminal_is_read_only": True,
                    },
                    observed_at,
                )

                present = runtime_state.get_present()
                self.assertEqual(present.active_project, "Pulse")
                self.assertEqual(present.activity_level, "reading")

                recent_events = session_memory.get_recent_events(limit=5)
                self.assertEqual(len(recent_events), 1)
                self.assertEqual(recent_events[0]["type"], "terminal_command_finished")

                active_session = session_memory.get_session()
                self.assertEqual(active_session["active_project"], "Pulse")

                orchestrator.shutdown_runtime()

                self.assertTrue(restart_state_path.exists())
                restart_state = json.loads(restart_state_path.read_text())
                self.assertEqual(restart_state["active_project"], "Pulse")
                self.assertIsNotNone(restart_state["started_at"])

                restored_started_at = datetime.fromisoformat(restart_state["started_at"])

                new_bus = EventBus()
                new_runtime_state = RuntimeState()
                new_session_memory = SessionMemory(db_path=str(session_db_path))
                new_orchestrator = self._orchestrator(
                    bus=new_bus,
                    session_memory=new_session_memory,
                    runtime_state=new_runtime_state,
                    memory_store=memory_store,
                    llm_runtime=llm_runtime,
                    fact_engine=fact_engine,
                )

                loaded_state = new_orchestrator._restart_manager.load()
                self.assertIsNotNone(loaded_state)
                self.assertLessEqual(loaded_state["elapsed_min"], 5)

                new_orchestrator._restart_manager.apply(
                    loaded_state,
                    session_fsm=new_orchestrator.session_fsm,
                    session_memory=new_session_memory,
                )

                self.assertEqual(new_orchestrator.session_fsm.session_started_at, restored_started_at)
                self.assertEqual(new_session_memory.started_at, restored_started_at)
                self.assertEqual(
                    new_session_memory.get_session()["started_at"],
                    restart_state["started_at"],
                )

    def test_file_event_http_to_bus_to_runtime_state_and_session_memory(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            tmp = Path(tmpdir)
            session_db_path = tmp / "session.db"
            tmp_project = tmp / "Pulse"
            source_dir = tmp_project / "daemon"
            source_dir.mkdir(parents=True)
            (tmp_project / ".git").mkdir()
            file_path = source_dir / "main.py"
            file_path.write_text("print('pulse')\n")

            app = Flask(__name__)
            bus = EventBus()
            runtime_state = RuntimeState()
            session_memory = SessionMemory(db_path=str(session_db_path))

            memory_store = MagicMock()
            memory_store.render.return_value = ""
            llm_runtime = MagicMock()
            fact_engine = MagicMock()
            fact_engine.render_for_context.return_value = ""

            orchestrator = self._orchestrator(
                bus=bus,
                session_memory=session_memory,
                runtime_state=runtime_state,
                memory_store=memory_store,
                llm_runtime=llm_runtime,
                fact_engine=fact_engine,
                file_debounce_sec=60.0,
            )
            coalescer = register_runtime_routes(
                app,
                bus=bus,
                store=MagicMock(),
                runtime_state=runtime_state,
                llm_unload_background=MagicMock(),
                llm_warmup_background=MagicMock(),
                shutdown_runtime=MagicMock(),
                log=MagicMock(),
            )
            client = app.test_client()

            with patch("daemon.core.restart_manager._read_project_head_sha", return_value=None), \
                 patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=None):
                orchestrator.start()
                bus.subscribe(orchestrator.handle_event)

                response = client.post(
                    "/event",
                    json={
                        "type": "file_modified",
                        "path": str(file_path),
                        "project": "Pulse",
                        "timestamp": "2026-04-23T10:15:30",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"ok": True})

                coalescer.close()
                orchestrator._flush_file_events()

                recent_bus_events = bus.recent(5)
                self.assertEqual(len(recent_bus_events), 1)
                self.assertEqual(recent_bus_events[0].type, "file_modified")
                self.assertEqual(recent_bus_events[0].payload["path"], str(file_path))

                recent_session_events = session_memory.get_recent_events(limit=5)
                self.assertEqual(len(recent_session_events), 1)
                self.assertEqual(recent_session_events[0]["type"], "file_modified")
                persisted_payload = recent_session_events[0]["payload"]
                self.assertEqual(persisted_payload["path"], str(file_path))
                self.assertNotIn("content", persisted_payload)
                self.assertNotIn("command", persisted_payload)
                self.assertNotIn("raw", persisted_payload)

                present = runtime_state.get_present()
                self.assertEqual(present.active_project, "Pulse")
                self.assertEqual(present.active_file, str(file_path))
                self.assertEqual(present.activity_level, "editing")

                active_session = session_memory.get_session()
                self.assertEqual(active_session["active_project"], "Pulse")
                self.assertEqual(active_session["active_file"], str(file_path))

                orchestrator.shutdown_runtime()


if __name__ == "__main__":
    unittest.main()
