import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

from daemon.core.event_bus import EventBus
from daemon.routes.runtime import register_runtime_routes
from daemon.runtime_state import RuntimeState


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "observation" / "core_events.json"


def _load_events() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


class TestObservationIngestionGolden(unittest.TestCase):
    def setUp(self):
        self.events = _load_events()
        self.app = Flask(__name__)
        self.bus = EventBus()
        self.store = MagicMock()
        self.store.to_dict.return_value = {}
        self.runtime_state = RuntimeState()
        self.coalescer = register_runtime_routes(
            self.app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            llm_unload_background=MagicMock(),
            llm_warmup_background=MagicMock(),
            shutdown_runtime=MagicMock(),
            log=MagicMock(),
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.coalescer.close()

    def _post_event(self, key: str):
        with patch.dict("os.environ", {"PULSE_MODE": "core"}):
            return self.client.post("/event", json=self.events[key])

    def test_app_activated_is_accepted_and_published_readably(self):
        response = self._post_event("app_activated")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        event = self.bus.recent(1)[0]
        self.assertEqual(event.type, "app_activated")
        self.assertEqual(event.payload["app_name"], "Code")
        self.assertEqual(event.payload["bundle_id"], "com.microsoft.VSCode")
        self.assertEqual(self.runtime_state.get_latest_active_app(), "Code")
        self.assertEqual(self.runtime_state.get_latest_active_app_bundle_id(), "com.microsoft.VSCode")

    def test_meaningful_source_file_enters_bus_with_actor_attribution(self):
        self._post_event("app_activated")

        response = self._post_event("file_source_meaningful")
        self.coalescer.close()

        self.assertEqual(response.status_code, 200)
        event = self.bus.recent(1)[0]
        self.assertEqual(event.type, "file_modified")
        self.assertEqual(event.payload["path"], "/Users/tester/workspace/acme/src/app.py")
        self.assertEqual(event.payload["_actor"], "user")
        self.assertIn("_actor_confidence", event.payload)
        self.assertIn("_automation_score", event.payload)
        self.assertEqual(event.payload["_noise_policy"], "normal")

    def test_cache_file_is_filtered_by_current_observation_policy(self):
        response = self._post_event("file_cache_noise")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "filtered": True})
        self.assertEqual(self.bus.recent(), [])

    def test_terminal_command_finished_is_normalized(self):
        response = self._post_event("terminal_command_finished")

        self.assertEqual(response.status_code, 200)
        event = self.bus.recent(1)[0]
        self.assertEqual(event.type, "terminal_command_finished")
        self.assertEqual(event.payload["source"], "terminal")
        self.assertEqual(event.payload["kind"], "finished")
        self.assertEqual(event.payload["terminal_command"], "pytest tests/test_app.py")
        self.assertEqual(event.payload["terminal_command_base"], "pytest")
        self.assertEqual(event.payload["terminal_action_category"], "testing")
        self.assertEqual(event.payload["terminal_project"], "acme")
        self.assertEqual(event.payload["terminal_exit_code"], 1)
        self.assertFalse(event.payload["terminal_success"])
        self.assertIn("terminal_summary", event.payload)
        self.assertIn("test_result", event.payload)

    def test_screen_lock_and_unlock_remain_publishable(self):
        locked = self._post_event("screen_locked")
        unlocked = self._post_event("screen_unlocked")

        self.assertEqual(locked.status_code, 200)
        self.assertEqual(unlocked.status_code, 200)
        event_types = [event.type for event in self.bus.recent(2)]
        self.assertEqual(event_types, ["screen_locked", "screen_unlocked"])

    def test_feed_stays_readable_after_golden_events(self):
        self._post_event("app_activated")
        self._post_event("terminal_command_finished")
        self._post_event("screen_locked")
        self._post_event("screen_unlocked")

        with patch.dict("os.environ", {"PULSE_MODE": "core"}):
            response = self.client.get("/feed")

        self.assertEqual(response.status_code, 200)
        feed = response.get_json()
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]["kind"], "terminal")
        self.assertFalse(feed[0]["success"])
        self.assertEqual(feed[0]["label"], "pytest test_app")
        self.assertEqual(feed[0]["command"], "pytest tests/test_app.py")


if __name__ == "__main__":
    unittest.main()
