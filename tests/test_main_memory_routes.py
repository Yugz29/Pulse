import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ["HOME"] = _TEST_HOME

import daemon.main as daemon_main


class TestMainMemoryRoutes(unittest.TestCase):
    def setUp(self):
        daemon_main.runtime_state.reset_for_tests()
        daemon_main.runtime_orchestrator.reset_for_tests()
        self.client = daemon_main.app.test_client()

    def test_memory_list_includes_usage_and_frozen_timestamp(self):
        frozen_at = datetime(2026, 4, 12, 20, 0, 0)
        with patch.object(daemon_main.runtime_orchestrator, "get_frozen_memory_at", return_value=frozen_at), \
             patch.object(daemon_main.memory_store, "list_entries", return_value=[{"content": "memo"}]) as list_entries, \
             patch.object(daemon_main.memory_store, "usage", return_value={"session": {"chars": 12}}):
            response = self.client.get("/memory?tier=session")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        list_entries.assert_called_once_with(tier="session")
        self.assertEqual(payload["entries"][0]["content"], "memo")
        self.assertEqual(payload["usage"]["session"]["chars"], 12)
        self.assertEqual(payload["frozen_at"], frozen_at.isoformat())

    def test_memory_write_requires_content(self):
        response = self.client.post("/memory/write", json={"content": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "content manquant")

    def test_memory_write_delegates_to_store(self):
        with patch.object(
            daemon_main.memory_store,
            "write",
            return_value={"ok": True, "content": "Projet Pulse"},
        ) as write:
            response = self.client.post(
                "/memory/write",
                json={"content": "Projet Pulse", "tier": "persistent", "topic": "product"},
            )

        self.assertEqual(response.status_code, 200)
        write.assert_called_once_with(
            content="Projet Pulse",
            tier="persistent",
            topic="product",
            source="llm",
            old_text=None,
        )

    def test_memory_remove_requires_old_text(self):
        response = self.client.post("/memory/remove", json={"old_text": ""})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "old_text manquant")

    def test_search_requires_query(self):
        response = self.client.get("/search")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "missing_query")

    def test_search_delegates_to_session_memory(self):
        with patch.object(
            daemon_main.session_memory,
            "search_events",
            return_value=[{"type": "file_modified"}],
        ) as search:
            response = self.client.get("/search?q=panel&limit=7&session=abc")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        search.assert_called_once_with("panel", limit=7, session_id="abc")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["type"], "file_modified")


if __name__ == "__main__":
    unittest.main()
