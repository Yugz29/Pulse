import tempfile
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path

from daemon.core.event_bus import Event
from daemon.memory.debug_memory_views import DebugMemoryViews
from daemon.memory.session import SessionMemory


class TestDebugMemoryViews(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "session.db")
        self.memory = SessionMemory(db_path=self.db_path, session_id="test-session")
        self.views = DebugMemoryViews(self.memory)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_work_episodes_expose_les_episodes_du_jour(self):
        observed_at = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        repo = "/Users/yugz/Projets/Pulse/Pulse"

        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/memory/work_episode_builder.py"},
            timestamp=observed_at,
        ))

        payload = self.views.get_work_episodes(date=observed_at)

        self.assertEqual(payload["date"], observed_at.date().isoformat())
        self.assertEqual(payload["episode_count"], 1)
        self.assertEqual(payload["episodes"][0]["project"], "Pulse")
        self.assertEqual(payload["episodes"][0]["dominant_scope"], "work_episode")
        self.assertEqual(payload["episodes"][0]["boundary_reason"], "end_of_events")

    def test_journal_candidates_ignore_end_of_events(self):
        observed_at = datetime.now().replace(hour=10, minute=15, second=0, microsecond=0)
        repo = "/Users/yugz/Projets/Pulse/Pulse"

        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/memory/work_episode_builder.py"},
            timestamp=observed_at,
        ))
        self.memory.record_event(Event(
            "screen_locked",
            {},
            timestamp=observed_at + timedelta(minutes=5),
        ))
        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/tests/memory/test_work_episode_builder.py"},
            timestamp=observed_at + timedelta(minutes=6),
        ))

        payload = self.views.get_journal_candidates(date=observed_at)

        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["ignored_count"], 1)
        self.assertEqual(payload["candidates"][0]["ignored"], False)
        self.assertEqual(payload["ignored"][0]["ignored"], True)
        self.assertEqual(payload["ignored"][0]["ignore_reason"], "open_episode_end_of_events")

    def test_journal_comparison_without_journal_file_returns_candidates(self):
        observed_at = datetime.now().replace(hour=10, minute=30, second=0, microsecond=0)
        repo = "/Users/yugz/Projets/Pulse/Pulse"

        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/memory/work_episode_builder.py"},
            timestamp=observed_at,
        ))
        self.memory.record_event(Event(
            "screen_locked",
            {},
            timestamp=observed_at + timedelta(minutes=5),
        ))

        payload = self.views.get_journal_comparison(date=observed_at)

        self.assertEqual(payload["date"], observed_at.date().isoformat())
        self.assertEqual(payload["journal_entry_count"], 0)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["matches"], [])
        self.assertEqual(len(payload["unmatched_candidates"]), 1)

    def test_commit_episode_links_without_journal_entries_returns_empty_counts(self):
        observed_at = datetime.now().replace(hour=10, minute=45, second=0, microsecond=0)
        repo = "/Users/yugz/Projets/Pulse/Pulse"

        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/memory/work_episode_builder.py"},
            timestamp=observed_at,
        ))
        self.memory.record_event(Event(
            "screen_locked",
            {},
            timestamp=observed_at + timedelta(minutes=5),
        ))

        payload = self.views.get_commit_episode_links(date=observed_at)

        self.assertEqual(payload["date"], observed_at.date().isoformat())
        self.assertEqual(payload["commit_count"], 0)
        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 0)
        self.assertEqual(payload["links"], [])
        self.assertEqual(payload["unlinked_commits"], [])

    def test_commit_episode_links_include_open_end_of_events_episode(self):
        observed_at = datetime.now().replace(hour=7, minute=52, second=0, microsecond=0)
        repo = "/Users/yugz/Projets/Pulse/Pulse"
        sessions_dir = Path(self.tmpdir.name) / "memory" / "sessions"
        sessions_dir.mkdir(parents=True)
        journal_entries = [
            {
                "entry_id": "journal-1",
                "active_project": "Pulse",
                "commit_message": "fix(context): expire stale work intents",
                "delivered_at": observed_at.replace(hour=8, minute=16).isoformat(),
                "started_at": observed_at.replace(hour=7, minute=59).isoformat(),
                "ended_at": observed_at.replace(hour=8, minute=0).isoformat(),
            }
        ]
        (sessions_dir / f"{observed_at.date().isoformat()}.md").write_text(
            "# Journal\n\n"
            "<!-- pulse-journal-data:start\n"
            f"{json.dumps(journal_entries)}\n"
            "pulse-journal-data:end -->",
            encoding="utf-8",
        )
        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/runtime_state.py"},
            timestamp=observed_at,
        ))
        self.memory.record_event(Event(
            "file_modified",
            {"path": f"{repo}/daemon/runtime_state.py"},
            timestamp=observed_at.replace(hour=8, minute=17),
        ))

        payload = self.views.get_commit_episode_links(date=observed_at)

        self.assertEqual(payload["commit_count"], 1)
        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["unlinked_count"], 0)
        self.assertEqual(payload["links"][0]["link_reason"], "linked_to_open_episode")
        self.assertIn("linked_to_open_episode", payload["links"][0]["flags"])
