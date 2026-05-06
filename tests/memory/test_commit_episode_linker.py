import unittest

from daemon.memory.commit_episode_linker import link_commits_to_episodes


class TestCommitEpisodeLinker(unittest.TestCase):

    def test_commit_avec_journal_window_chevauchant_candidate_linked_by_overlap(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: add dry run",
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:20:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T12:05:00",
                    "ended_at": "2026-05-05T12:25:00",
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["commit_count"], 1)
        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["links"][0]["episode_id"], "episode-1")
        self.assertIn("linked_by_overlap", payload["links"][0]["flags"])

    def test_commit_delivered_at_proche_de_candidate_end_linked_by_delivery_proximity(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix: close candidate",
                    "delivered_at": "2026-05-05T12:12:00",
                    "started_at": "2026-05-05T13:00:00",
                    "ended_at": "2026-05-05T13:00:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:10:00",
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertIn("linked_by_delivery_proximity", payload["links"][0]["flags"])

    def test_commit_tres_loin_de_toute_candidate_reste_unlinked(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: late commit",
                    "delivered_at": "2026-05-05T20:00:00",
                    "started_at": "2026-05-05T20:00:00",
                    "ended_at": "2026-05-05T20:00:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T14:44:00",
                    "ended_at": "2026-05-05T14:46:00",
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 1)
        self.assertIn("no_plausible_episode", payload["unlinked_commits"][0]["flags"])
        self.assertIn("no_delivery_near_episode", payload["unlinked_commits"][0]["flags"])

    def test_delivered_at_refuse_overlap_journal_stale(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat(memory): introduce pure work episode builder",
                    "delivered_at": "2026-05-05T13:46:38",
                    "started_at": "2026-05-05T11:16:00",
                    "ended_at": "2026-05-05T12:29:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T11:36:00",
                    "ended_at": "2026-05-05T11:43:00",
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 1)
        self.assertIn("no_delivery_near_episode", payload["unlinked_commits"][0]["flags"])

    def test_delivered_at_prefere_candidate_proche_a_overlap_journal_stale(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat(memory): introduce pure work episode builder",
                    "delivered_at": "2026-05-05T13:46:38",
                    "started_at": "2026-05-05T11:16:00",
                    "ended_at": "2026-05-05T12:29:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T11:36:00",
                    "ended_at": "2026-05-05T11:43:00",
                    "ignored": False,
                },
                {
                    "id": "candidate-2",
                    "episode_id": "episode-2",
                    "project": "Pulse",
                    "started_at": "2026-05-05T13:38:00",
                    "ended_at": "2026-05-05T13:56:00",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["links"][0]["episode_id"], "episode-2")
        self.assertIn("linked_by_delivery_proximity", payload["links"][0]["flags"])

    def test_delivered_at_prefere_episode_couvrant_la_livraison(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "Filter technical file artifacts from work heartbeats",
                    "delivered_at": "2026-05-05T21:20:00",
                    "started_at": "2026-05-05T19:04:00",
                    "ended_at": "2026-05-05T20:18:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T19:04:00",
                    "ended_at": "2026-05-05T20:18:00",
                    "ignored": False,
                },
                {
                    "id": "candidate-2",
                    "episode_id": "episode-2",
                    "project": "Pulse",
                    "started_at": "2026-05-05T20:48:00",
                    "ended_at": "2026-05-05T21:22:00",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["links"][0]["episode_id"], "episode-2")

    def test_ignored_candidate_n_est_jamais_utilisee(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: ignored candidate",
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:20:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T12:05:00",
                    "ended_at": "2026-05-05T12:25:00",
                    "ignored": True,
                    "boundary_reason": "end_of_events",
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_commits"][0]["episode_id"], None)

    def test_multiple_commit_messages_creent_plusieurs_unites(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_messages": ["feat: first", "fix: second"],
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:20:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:20:00",
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["commit_count"], 2)
        self.assertEqual(payload["linked_count"], 2)
        self.assertEqual([link["commit_subject"] for link in payload["links"]], ["feat: first", "fix: second"])

    def test_ambiguite_entre_deux_candidates_proches_est_signalee(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: ambiguous",
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:20:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:15:00",
                    "ignored": False,
                },
                {
                    "id": "candidate-2",
                    "episode_id": "episode-2",
                    "project": "Pulse",
                    "started_at": "2026-05-05T12:05:00",
                    "ended_at": "2026-05-05T12:20:00",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertIn("ambiguous_candidates", payload["links"][0]["flags"])


if __name__ == "__main__":
    unittest.main()
