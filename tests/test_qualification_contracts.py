import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from flask import Flask

from daemon.core.event_bus import EventBus
from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.signal_scorer import SignalScorer, Signals
from daemon.core.work_context_card import build_work_context_card
from daemon.mcp.handlers import build_runtime_signal
from daemon.memory.session import SessionMemory
from daemon.memory.work_episode_builder import build_work_episodes
from daemon.routes.mcp import register_mcp_routes
from daemon.runtime_state import RuntimeState


class TestQualificationContracts(unittest.TestCase):
    def test_mcp_route_events_are_tool_context_not_user_file_activity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = EventBus()
            memory = SessionMemory(db_path=str(Path(tmpdir) / "session.db"))
            bus.subscribe(memory.record_event)
            app = Flask(__name__)
            register_mcp_routes(
                app,
                bus=bus,
                get_pending_command=lambda: None,
                get_proposal_history=lambda limit: [],
                intercept_command=lambda command, tool_use_id: {"decision": "allow", "allowed": True},
                build_runtime_signal=build_runtime_signal,
                receive_decision=lambda tool_use_id, decision: True,
                get_scoring_status=lambda: {},
                log=MagicMock(),
            )

            response = app.test_client().post(
                "/mcp/intercept",
                json={
                    "command": "cat README.md --token secret-token",
                    "tool_use_id": "tool-qualification",
                },
            )

            self.assertEqual(response.status_code, 200)
            events = bus.recent(10)
            self.assertEqual([event.type for event in events], ["mcp_command_received", "mcp_decision"])
            self.assertTrue(all(event.payload.get("mcp_action_category") for event in events))
            self.assertTrue(all("_actor" not in event.payload for event in events))

            signals = SignalScorer(bus).compute()
            self.assertIsNone(signals.active_project)
            self.assertIsNone(signals.active_file)
            self.assertEqual(signals.edited_file_count_10m, 0)
            self.assertEqual(signals.file_type_mix_10m, {})

            episodes = build_work_episodes(memory.get_recent_events())
            self.assertEqual(len(episodes), 1)
            self.assertEqual(episodes[0].probable_task, "assisted_workflow")
            self.assertNotEqual(episodes[0].probable_task, "coding")

            stored_payloads = [event["payload"] for event in memory.get_recent_events()]
            stored_text = str(stored_payloads)
            self.assertNotIn("secret-token", stored_text)
            self.assertIn("[REDACTED", stored_text)

    def test_window_title_sensitive_content_is_not_exposed_by_state_or_work_context(self):
        runtime_state = RuntimeState()
        sensitive_title = (
            "Pulse — yugz@example.com — https://example.com/private — "
            "/Users/yugz/Projects/Pulse — sk-abcdefghijklmnopqrstuvwxyz123456"
        )
        signals = Signals(
            active_project=None,
            active_file=None,
            probable_task="general",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=0,
            recent_apps=["Code"],
            clipboard_context=None,
            activity_level="reading",
            window_title=sensitive_title,
            window_title_app="Code",
        )
        runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        runtime_state.set_analysis(signals=signals, decision=None)
        snapshot = runtime_state.get_runtime_snapshot()
        current_context = CurrentContextBuilder().build(
            present=snapshot.present,
            active_app=snapshot.latest_active_app,
            signals=snapshot.signals,
            find_git_root_fn=lambda path: None,
            find_workspace_root_fn=lambda path: None,
        )
        card = build_work_context_card(
            current_context,
            present=snapshot.present,
            signals=snapshot.signals,
            decision=None,
        )

        combined = f"{snapshot.present.to_dict()} {card.to_dict()}"
        self.assertNotIn("yugz@example.com", combined)
        self.assertNotIn("https://example.com/private", combined)
        self.assertNotIn("/Users/yugz", combined)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", combined)

    def test_internal_daemon_events_do_not_create_work_or_user_activity(self):
        bus = EventBus()
        for event_type, payload in [
            ("context_probe_executed", {"kind": "app_context", "data_keys": ["active_project"]}),
            ("llm_loading", {"model": "local"}),
            ("llm_ready", {"model": "local"}),
            ("resume_card", {"project": "Pulse", "summary": "Resume available"}),
        ]:
            bus.publish(event_type, payload)

        signals = SignalScorer(bus).compute()

        self.assertIsNone(signals.active_project)
        self.assertIsNone(signals.active_file)
        self.assertEqual(signals.edited_file_count_10m, 0)
        self.assertEqual(signals.probable_task, "general")
        self.assertEqual(build_work_episodes([
            {
                "type": event.type,
                "payload": event.payload,
                "timestamp": event.timestamp,
            }
            for event in bus.recent(10)
        ]), [])


if __name__ == "__main__":
    unittest.main()
