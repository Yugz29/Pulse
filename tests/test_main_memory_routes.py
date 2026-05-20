import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ["HOME"] = _TEST_HOME

import daemon.main as daemon_main


class TestMainMemoryRoutes(unittest.TestCase):
    def setUp(self):
        daemon_main.runtime_state.reset_for_tests()
        daemon_main.runtime_orchestrator.reset_for_tests()
        self.client = daemon_main.app.test_client()
        self.sessions_dir = Path(_TEST_HOME) / ".pulse" / "memory" / "sessions"
        if self.sessions_dir.exists():
            for file in self.sessions_dir.glob("*.md"):
                file.unlink()

    def _write_session_journal(self, name: str = "2026-05-20", *, hidden: bool = True) -> Path:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        content = "# Journal Pulse\n\n## Acme\n\nVisible session.\n"
        if hidden:
            content += (
                "\n<!-- pulse-journal-data:start\n"
                "[{\"entry_id\":\"journal-1\",\"truth_layers\":{\"inferred\":[]}}]\n"
                "pulse-journal-data:end -->\n"
            )
        path = self.sessions_dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        return path

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
        ) as write, \
             patch.dict("os.environ", {"PULSE_MODE": "lab"}):
            response = self.client.post(
                "/memory/write",
                json={"content": "Projet Pulse", "tier": "persistent", "topic": "product"},
            )

        self.assertEqual(response.status_code, 200)
        write.assert_called_once_with(
            content="Projet Pulse",
            tier="persistent",
            topic="product",
            source="manual",
            old_text=None,
        )

    def test_memory_write_preserves_explicit_llm_source(self):
        with patch.object(
            daemon_main.memory_store,
            "write",
            return_value={"ok": True, "content": "Résumé proposé"},
        ) as write, \
             patch.dict("os.environ", {"PULSE_MODE": "lab"}):
            response = self.client.post(
                "/memory/write",
                json={"content": "Résumé proposé", "source": "llm"},
            )

        self.assertEqual(response.status_code, 200)
        write.assert_called_once_with(
            content="Résumé proposé",
            tier="session",
            topic="general",
            source="llm",
            old_text=None,
        )

    def test_memory_write_preserves_explicit_user_source(self):
        with patch.object(
            daemon_main.memory_store,
            "write",
            return_value={"ok": True, "content": "Préférence utilisateur"},
        ) as write, \
             patch.dict("os.environ", {"PULSE_MODE": "lab"}):
            response = self.client.post(
                "/memory/write",
                json={"content": "Préférence utilisateur", "source": "user"},
            )

        self.assertEqual(response.status_code, 200)
        write.assert_called_once_with(
            content="Préférence utilisateur",
            tier="session",
            topic="general",
            source="user",
            old_text=None,
        )

    def test_memory_write_core_marks_lab_surface_without_writing(self):
        with patch.object(daemon_main.memory_store, "write") as write, \
             patch.dict("os.environ", {"PULSE_MODE": "core"}):
            response = self.client.post(
                "/memory/write",
                json={"content": "Projet Pulse", "tier": "persistent", "topic": "product"},
            )

        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertEqual(payload["error"], "lab_surface_disabled")
        self.assertEqual(payload["surface"], "memory_write")
        self.assertEqual(payload["pulse_mode"], "core")
        self.assertTrue(payload["disabled_in_core"])
        write.assert_not_called()

    def test_memory_remove_requires_old_text(self):
        response = self.client.post("/memory/remove", json={"old_text": ""})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "old_text manquant")

    def test_memory_remove_core_marks_lab_surface_without_removing(self):
        with patch.object(daemon_main.memory_store, "remove") as remove, \
             patch.dict("os.environ", {"PULSE_MODE": "core"}):
            response = self.client.post("/memory/remove", json={"old_text": "Projet Pulse"})

        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertEqual(payload["error"], "lab_surface_disabled")
        self.assertEqual(payload["surface"], "memory_remove")
        remove.assert_not_called()

    def test_memory_sessions_strips_hidden_payload_by_default(self):
        self._write_session_journal()

        response = self.client.get("/memory/sessions")

        self.assertEqual(response.status_code, 200)
        session = response.get_json()["sessions"][0]
        self.assertIn("Visible session.", session["content"])
        self.assertNotIn("pulse-journal-data", session["content"])
        self.assertNotIn("truth_layers", session["content"])
        self.assertTrue(session["has_hidden_payload"])
        self.assertFalse(session["include_hidden"])
        self.assertEqual(session["surface"], "product_memory_sessions")

    def test_memory_sessions_include_hidden_true_preserves_raw_payload(self):
        self._write_session_journal()

        response = self.client.get("/memory/sessions?include_hidden=true")

        self.assertEqual(response.status_code, 200)
        session = response.get_json()["sessions"][0]
        self.assertIn("Visible session.", session["content"])
        self.assertIn("pulse-journal-data", session["content"])
        self.assertIn("truth_layers", session["content"])
        self.assertTrue(session["has_hidden_payload"])
        self.assertTrue(session["include_hidden"])
        self.assertEqual(session["surface"], "product_memory_sessions_raw")

    def test_memory_sessions_marks_absent_hidden_payload(self):
        self._write_session_journal(hidden=False)

        response = self.client.get("/memory/sessions")

        self.assertEqual(response.status_code, 200)
        session = response.get_json()["sessions"][0]
        self.assertIn("Visible session.", session["content"])
        self.assertFalse(session["has_hidden_payload"])
        self.assertFalse(session["include_hidden"])

    def test_memory_sessions_absent_directory_still_returns_empty_list(self):
        if self.sessions_dir.exists():
            for file in self.sessions_dir.glob("*.md"):
                file.unlink()
            self.sessions_dir.rmdir()

        response = self.client.get("/memory/sessions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"sessions": []})

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
