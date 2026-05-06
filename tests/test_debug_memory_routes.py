import unittest

from flask import Flask

from daemon.routes.debug_memory import register_debug_memory_routes


def _payload_for(route_name, date="2026-05-05"):
    base = {
        "date": date,
        "generated_at": "2026-05-05T12:00:00",
    }
    if route_name == "work_episodes":
        return {
            **base,
            "episode_count": 1,
            "episodes": [{"id": "episode-1", "project": "Pulse"}],
        }
    if route_name == "journal_candidates":
        return {
            **base,
            "candidate_count": 1,
            "ignored_count": 0,
            "candidates": [{"id": "candidate-1"}],
            "ignored": [],
        }
    if route_name == "journal_comparison":
        return {
            **base,
            "journal_entry_count": 1,
            "candidate_count": 1,
            "matches": [{"journal_entry_id": "journal-1", "candidate_id": "candidate-1"}],
            "unmatched_journal_entries": [],
            "unmatched_candidates": [],
        }
    if route_name == "commit_episode_links":
        return {
            **base,
            "commit_count": 1,
            "linked_count": 1,
            "unlinked_count": 0,
            "links": [{"id": "link-1", "episode_id": "episode-1"}],
            "unlinked_commits": [],
        }
    raise AssertionError(f"unknown route payload {route_name}")


class TestDebugMemoryRoutes(unittest.TestCase):

    def _client(self, **callbacks):
        app = Flask(__name__)
        register_debug_memory_routes(app, **callbacks)
        return app.test_client()

    def test_les_quatre_routes_retournent_200_avec_callback(self):
        client = self._client(
            get_work_episodes=lambda: _payload_for("work_episodes"),
            get_journal_candidates=lambda: _payload_for("journal_candidates"),
            get_journal_comparison=lambda: _payload_for("journal_comparison"),
            get_commit_episode_links=lambda: _payload_for("commit_episode_links"),
        )

        cases = [
            ("/debug/work-episodes", "episode_count", 1),
            ("/debug/journal-candidates", "candidate_count", 1),
            ("/debug/journal-comparison", "journal_entry_count", 1),
            ("/debug/commit-episode-links", "commit_count", 1),
        ]
        for path, key, value in cases:
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()[key], value)

    def test_les_quatre_routes_retournent_un_fallback_vide_sans_callback(self):
        client = self._client()

        cases = [
            ("/debug/work-episodes", {"episode_count": 0, "episodes": []}),
            (
                "/debug/journal-candidates",
                {"candidate_count": 0, "ignored_count": 0, "candidates": [], "ignored": []},
            ),
            (
                "/debug/journal-comparison",
                {
                    "journal_entry_count": 0,
                    "candidate_count": 0,
                    "matches": [],
                    "unmatched_journal_entries": [],
                    "unmatched_candidates": [],
                },
            ),
            (
                "/debug/commit-episode-links",
                {
                    "commit_count": 0,
                    "linked_count": 0,
                    "unlinked_count": 0,
                    "links": [],
                    "unlinked_commits": [],
                },
            ),
        ]
        for path, expected in cases:
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                for key, value in expected.items():
                    self.assertEqual(payload[key], value)

    def test_query_param_date_est_propage_aux_quatre_callbacks(self):
        client = self._client(
            get_work_episodes=lambda date=None: _payload_for("work_episodes", date.date().isoformat()),
            get_journal_candidates=lambda date=None: _payload_for("journal_candidates", date.date().isoformat()),
            get_journal_comparison=lambda date=None: _payload_for("journal_comparison", date.date().isoformat()),
            get_commit_episode_links=lambda date=None: _payload_for("commit_episode_links", date.date().isoformat()),
        )

        for path in (
            "/debug/work-episodes",
            "/debug/journal-candidates",
            "/debug/journal-comparison",
            "/debug/commit-episode-links",
        ):
            with self.subTest(path=path):
                response = client.get(f"{path}?date=2026-05-05")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["date"], "2026-05-05")

    def test_date_invalide_retourne_400_invalid_date(self):
        client = self._client()

        for path in (
            "/debug/work-episodes",
            "/debug/journal-candidates",
            "/debug/journal-comparison",
            "/debug/commit-episode-links",
        ):
            with self.subTest(path=path):
                response = client.get(f"{path}?date=bad-date")
                self.assertEqual(response.status_code, 400)
                payload = response.get_json()
                self.assertEqual(payload["error"], "invalid_date")
                self.assertEqual(payload["message"], "date must use YYYY-MM-DD")
