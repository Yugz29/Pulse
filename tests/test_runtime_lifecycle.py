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

    def _runtime_app(self, tmp: Path, *, file_debounce_sec: float = 60.0):
        app = Flask(__name__)
        bus = EventBus()
        runtime_state = RuntimeState()
        session_memory = SessionMemory(db_path=str(tmp / "session.db"))
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
            file_debounce_sec=file_debounce_sec,
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
        return app, bus, runtime_state, session_memory, orchestrator, coalescer

    @staticmethod
    def _file_event_payload(session_memory: SessionMemory) -> dict:
        events = session_memory.get_recent_events(limit=20)
        matches = [event for event in events if event["type"] == "file_modified"]
        if not matches:
            raise AssertionError(f"missing file_modified event in {events}")
        return matches[-1]["payload"]

    def _run_file_event_flow(
        self,
        *,
        app_name: str,
        file_path: Path,
        tmp: Path,
    ):
        app, bus, runtime_state, session_memory, orchestrator, coalescer = self._runtime_app(tmp)
        client = app.test_client()

        with patch("daemon.core.restart_manager._read_project_head_sha", return_value=None), \
             patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=None):
            orchestrator.start()
            bus.subscribe(orchestrator.handle_event)

            app_response = client.post(
                "/event",
                json={
                    "type": "app_activated",
                    "app_name": app_name,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            self.assertEqual(app_response.status_code, 200)

            response = client.post(
                "/event",
                json={
                    "type": "file_modified",
                    "path": str(file_path),
                    "timestamp": datetime.now().isoformat(),
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"ok": True})

            coalescer.close()
            orchestrator._flush_file_events()

            return bus, runtime_state, session_memory, orchestrator

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

    def test_file_event_dev_app_is_ingested_as_user_activity(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            tmp = Path(tmpdir)
            tmp_project = tmp / "Pulse"
            source_dir = tmp_project / "src"
            source_dir.mkdir(parents=True)
            (tmp_project / ".git").mkdir()
            file_path = source_dir / "main.py"
            file_path.write_text("print('pulse')\n")

            _, runtime_state, session_memory, orchestrator = self._run_file_event_flow(
                app_name="Xcode",
                file_path=file_path,
                tmp=tmp,
            )

            payload = self._file_event_payload(session_memory)
            self.assertEqual(payload["path"], str(file_path))
            self.assertEqual(payload["_actor"], "user")
            self.assertLess(payload["_automation_score"], 0.5)

            present = runtime_state.get_present()
            self.assertEqual(present.active_project, "Pulse")
            self.assertEqual(present.active_file, str(file_path))
            self.assertEqual(present.activity_level, "editing")
            orchestrator.shutdown_runtime()

    def test_file_event_codex_app_is_accepted_as_tool_assisted_activity(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            tmp = Path(tmpdir)
            tmp_project = tmp / "Pulse"
            source_dir = tmp_project / "src"
            source_dir.mkdir(parents=True)
            (tmp_project / ".git").mkdir()
            file_path = source_dir / "main.py"
            file_path.write_text("print('pulse')\n")

            _, runtime_state, session_memory, orchestrator = self._run_file_event_flow(
                app_name="Codex",
                file_path=file_path,
                tmp=tmp,
            )

            payload = self._file_event_payload(session_memory)
            self.assertEqual(payload["path"], str(file_path))
            self.assertEqual(payload["_actor"], "tool_assisted")
            self.assertGreaterEqual(payload["_automation_score"], 0.5)

            present = runtime_state.get_present()
            self.assertEqual(present.active_project, "Pulse")
            self.assertEqual(present.active_file, str(file_path))
            orchestrator.shutdown_runtime()

    def test_system_cache_file_event_is_filtered_before_bus_and_runtime_state(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            tmp = Path(tmpdir)
            app, bus, runtime_state, session_memory, orchestrator, _ = self._runtime_app(tmp)
            client = app.test_client()
            system_path = tmp / "Pulse" / "node_modules" / "pkg" / "index.js"
            system_path.parent.mkdir(parents=True)
            system_path.write_text("module.exports = {}\n")

            with patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=None):
                orchestrator.start()
                bus.subscribe(orchestrator.handle_event)
                response = client.post(
                    "/event",
                    json={
                        "type": "file_modified",
                        "path": str(system_path),
                        "timestamp": datetime.now().isoformat(),
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"ok": True, "filtered": True})
                self.assertEqual(bus.recent(5), [])
                self.assertEqual(session_memory.get_recent_events(limit=5), [])
                self.assertIsNone(runtime_state.get_present().active_file)
                self.assertIsNone(runtime_state.get_present().active_project)
                orchestrator.shutdown_runtime()

    def test_terminal_event_privacy_persists_redacted_command_but_not_raw_fields(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            tmp = Path(tmpdir)
            app, bus, _, session_memory, orchestrator, _ = self._runtime_app(tmp)
            client = app.test_client()
            fake_secret = "sk-test-secret-1234567890"
            raw_command = f"curl -H 'Authorization: Bearer {fake_secret}' https://example.test"

            with patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=None):
                orchestrator.start()
                bus.subscribe(orchestrator.handle_event)
                response = client.post(
                    "/event",
                    json={
                        "type": "terminal_command_finished",
                        "command": raw_command,
                        "raw": f"raw {fake_secret}",
                        "cwd": str(tmp),
                        "exit_code": 0,
                        "duration_ms": 12,
                        "timestamp": datetime.now().isoformat(),
                    },
                )

                self.assertEqual(response.status_code, 200)
                events = session_memory.get_recent_events(limit=5)
                self.assertEqual(len(events), 1)
                payload = events[0]["payload"]
                self.assertNotIn("command", payload)
                self.assertNotIn("raw", payload)
                self.assertIn("terminal_command", payload)
                self.assertIn("Authorization: Bearer [REDACTED_TOKEN]", payload["terminal_command"])
                self.assertNotIn(fake_secret, payload["terminal_command"])
                self.assertIn("terminal_action_category", payload)
                self.assertTrue(payload["terminal_action_category"])
                self.assertIn("terminal_summary", payload)
                orchestrator.shutdown_runtime()

    def test_terminal_event_privacy_keeps_simple_command_readable(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            tmp = Path(tmpdir)
            app, bus, _, session_memory, orchestrator, _ = self._runtime_app(tmp)
            client = app.test_client()

            with patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=None):
                orchestrator.start()
                bus.subscribe(orchestrator.handle_event)
                response = client.post(
                    "/event",
                    json={
                        "type": "terminal_command_finished",
                        "command": "python -m pytest tests/test_runtime_lifecycle.py",
                        "cwd": str(tmp),
                        "exit_code": 0,
                        "duration_ms": 12,
                        "timestamp": datetime.now().isoformat(),
                    },
                )

                self.assertEqual(response.status_code, 200)
                payload = session_memory.get_recent_events(limit=5)[0]["payload"]
                self.assertEqual(
                    payload["terminal_command"],
                    "python -m pytest tests/test_runtime_lifecycle.py",
                )
                self.assertNotIn("command", payload)
                self.assertNotIn("raw", payload)
                orchestrator.shutdown_runtime()

    def test_mcp_command_received_persists_redacted_command(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            tmp = Path(tmpdir)
            bus = EventBus()
            runtime_state = RuntimeState()
            session_memory = SessionMemory(db_path=str(tmp / "session.db"))
            memory_store = MagicMock()
            memory_store.render.return_value = ""
            llm_runtime = MagicMock()
            fact_engine = MagicMock()
            fact_engine.render_for_context.return_value = ""
            fake_secret = "sk-test-secret-1234567890"
            orchestrator = self._orchestrator(
                bus=bus,
                session_memory=session_memory,
                runtime_state=runtime_state,
                memory_store=memory_store,
                llm_runtime=llm_runtime,
                fact_engine=fact_engine,
            )

            with patch("daemon.runtime_orchestrator.update_memories_from_session", return_value=None):
                orchestrator.start()
                bus.subscribe(orchestrator.handle_event)
                bus.publish(
                    "mcp_command_received",
                    {
                        "command": f"cat {fake_secret}",
                        "tool_use_id": "tool-1",
                        "mcp_action_category": "inspection",
                        "mcp_summary": "Inspection MCP",
                    },
                    datetime.now(),
                )

                events = session_memory.get_recent_events(limit=5)
                self.assertEqual(len(events), 1)
                payload = events[0]["payload"]
                self.assertEqual(payload["command"], "cat [REDACTED_TOKEN]")
                self.assertNotIn(fake_secret, payload["command"])
                self.assertEqual(payload["mcp_action_category"], "inspection")
                orchestrator.shutdown_runtime()


if __name__ == "__main__":
    unittest.main()
