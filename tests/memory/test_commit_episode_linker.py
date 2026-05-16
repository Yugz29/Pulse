import unittest
from datetime import datetime

from daemon.memory.commit_episode_linker import link_commits_to_episodes


class TestCommitEpisodeLinker(unittest.TestCase):

    def test_commit_during_open_episode_links_to_active_episode(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat(context): add work intent candidate dashboard",
                    "delivered_at": "2026-05-15T08:03:00",
                    "started_at": "2026-05-15T08:03:00",
                    "ended_at": "2026-05-15T08:03:00",
                }
            ],
            [
                {
                    "id": "candidate-open-1",
                    "episode_id": "episode-open-1",
                    "project": "Pulse",
                    "started_at": "2026-05-15T07:52:00",
                    "ended_at": None,
                    "ignored": False,
                }
            ],
            now=datetime(2026, 5, 15, 8, 17, 0),
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["unlinked_count"], 0)
        link = payload["links"][0]
        self.assertEqual(link["episode_id"], "episode-open-1")
        self.assertEqual(link["link_reason"], "linked_to_open_episode")
        self.assertIn("linked_to_open_episode", link["flags"])
        self.assertNotIn("commit_only_journal_entry", link["flags"])
        self.assertEqual(link["episode_ended_at"], None)
        self.assertEqual(link["score_breakdown"]["open_episode_age_min"], 25)

    def test_commit_during_end_of_events_candidate_links_as_open_episode(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix(context): expire stale work intents",
                    "delivered_at": "2026-05-15T08:16:00",
                    "started_at": "2026-05-15T07:59:00",
                    "ended_at": "2026-05-15T08:00:00",
                }
            ],
            [
                {
                    "id": "journal-candidate-open-1",
                    "episode_id": "work-episode-open-1",
                    "project": "Pulse",
                    "started_at": "2026-05-15T07:52:00",
                    "ended_at": "2026-05-15T08:17:00",
                    "boundary_reason": "end_of_events",
                    "ignored": True,
                    "ignore_reason": "open_episode_end_of_events",
                }
            ],
            now=datetime(2026, 5, 15, 8, 17, 0),
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["unlinked_count"], 0)
        link = payload["links"][0]
        self.assertEqual(link["episode_id"], "work-episode-open-1")
        self.assertEqual(link["link_reason"], "linked_to_open_episode")
        self.assertIn("linked_to_open_episode", link["flags"])
        self.assertNotIn("commit_only_journal_entry", link["flags"])
        self.assertEqual(link["score_breakdown"]["open_episode_age_min"], 25)

    def test_commit_during_closed_episode_still_links_as_before(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix(context): expire stale work intents",
                    "delivered_at": "2026-05-15T08:12:00",
                    "started_at": "2026-05-15T08:12:00",
                    "ended_at": "2026-05-15T08:12:00",
                }
            ],
            [
                {
                    "id": "candidate-closed-1",
                    "episode_id": "episode-closed-1",
                    "project": "Pulse",
                    "started_at": "2026-05-15T07:52:00",
                    "ended_at": "2026-05-15T08:17:00",
                    "ignored": False,
                }
            ],
            now=datetime(2026, 5, 15, 8, 17, 0),
        )

        self.assertEqual(payload["linked_count"], 1)
        link = payload["links"][0]
        self.assertEqual(link["episode_id"], "episode-closed-1")
        self.assertIn("delivery_inside_episode", link["flags"])
        self.assertNotIn("linked_to_open_episode", link["flags"])

    def test_delayed_commit_prefers_file_scoped_work_episode_over_git_delivery_episode(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix(memory): tighten lightweight commit summary prompt",
                    "delivered_at": "2026-05-16T14:03:00",
                    "started_at": "2026-05-16T13:12:00",
                    "ended_at": "2026-05-16T13:13:00",
                    "top_files": [
                        "extractor.py",
                        "test_extractor.py",
                        "test_runtime_orchestrator.py",
                    ],
                }
            ],
            [
                {
                    "id": "candidate-code",
                    "episode_id": "episode-code",
                    "project": "Pulse",
                    "started_at": "2026-05-16T13:12:00",
                    "ended_at": "2026-05-16T13:13:00",
                    "dominant_scope": "extractor",
                    "top_files": [
                        "extractor.py",
                        "test_extractor.py",
                        "test_runtime_orchestrator.py",
                    ],
                    "ignored": False,
                },
                {
                    "id": "candidate-git",
                    "episode_id": "episode-git",
                    "project": "Pulse",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:10:00",
                    "dominant_scope": "git",
                    "probable_task": "terminal_execution",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        link = payload["links"][0]
        self.assertEqual(link["episode_id"], "episode-code")
        self.assertEqual(link["link_reason"], "linked_by_journal_file_window")
        self.assertEqual(link["evidence_level"], "file_scope")
        self.assertIn("linked_by_file_overlap", link["flags"])
        self.assertIn("delayed_delivery", link["flags"])
        self.assertIn("work_episode_link", link["flags"])
        self.assertNotIn("temporal_only_link", link["flags"])
        self.assertEqual(link["score_breakdown"]["file_overlap_count"], 3)

    def test_no_file_overlap_keeps_temporal_delivery_behavior(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix(memory): tighten lightweight commit summary prompt",
                    "delivered_at": "2026-05-16T14:03:00",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:03:00",
                    "top_files": ["extractor.py"],
                }
            ],
            [
                {
                    "id": "candidate-code",
                    "episode_id": "episode-code",
                    "project": "Pulse",
                    "started_at": "2026-05-16T13:12:00",
                    "ended_at": "2026-05-16T13:13:00",
                    "dominant_scope": "extractor",
                    "top_files": ["runtime_state.py"],
                    "ignored": False,
                },
                {
                    "id": "candidate-git",
                    "episode_id": "episode-git",
                    "project": "Pulse",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:10:00",
                    "dominant_scope": "git",
                    "probable_task": "terminal_execution",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        link = payload["links"][0]
        self.assertEqual(link["episode_id"], "episode-git")
        self.assertIn("linked_by_delivery_proximity", link["flags"])
        self.assertIn("temporal_only_link", link["flags"])
        self.assertNotIn("linked_by_file_overlap", link["flags"])

    def test_project_mismatch_prevents_candidate_file_overlap_link(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Alpha",
                    "commit_message": "fix: update service",
                    "delivered_at": "2026-05-16T14:03:00",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:03:00",
                    "top_files": ["service.py"],
                }
            ],
            [
                {
                    "id": "candidate-beta",
                    "episode_id": "episode-beta",
                    "project": "Beta",
                    "started_at": "2026-05-16T13:12:00",
                    "ended_at": "2026-05-16T13:13:00",
                    "dominant_scope": "daemon_python",
                    "top_files": ["service.py"],
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 1)

    def test_delayed_file_overlap_too_old_does_not_link(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix: update extractor",
                    "delivered_at": "2026-05-16T15:00:00",
                    "top_files": ["extractor.py"],
                }
            ],
            [
                {
                    "id": "candidate-code",
                    "episode_id": "episode-code",
                    "project": "Pulse",
                    "started_at": "2026-05-16T13:12:00",
                    "ended_at": "2026-05-16T13:13:00",
                    "dominant_scope": "extractor",
                    "top_files": ["extractor.py"],
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 1)

    def test_git_only_candidate_cannot_win_by_file_overlap(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix: update extractor",
                    "delivered_at": "2026-05-16T14:03:00",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:03:00",
                    "top_files": ["extractor.py"],
                }
            ],
            [
                {
                    "id": "candidate-git",
                    "episode_id": "episode-git",
                    "project": "Pulse",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:10:00",
                    "dominant_scope": "git",
                    "probable_task": "terminal_execution",
                    "top_files": ["extractor.py"],
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        link = payload["links"][0]
        self.assertEqual(link["episode_id"], "episode-git")
        self.assertNotIn("linked_by_file_overlap", link["flags"])
        self.assertIn("linked_by_delivery_proximity", link["flags"])

    def test_journal_file_window_beats_older_temporal_git_episode(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix(memory): link delayed commits by file overlap",
                    "delivered_at": "2026-05-16T14:34:00",
                    "started_at": "2026-05-16T14:26:00",
                    "ended_at": "2026-05-16T14:29:00",
                    "top_files": [
                        "commit_episode_linker.py",
                        "journal_candidate_builder.py",
                        "work_episode_builder.py",
                    ],
                }
            ],
            [
                {
                    "id": "candidate-git",
                    "episode_id": "episode-git",
                    "project": "Pulse",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:11:00",
                    "dominant_scope": "git",
                    "probable_task": "terminal_execution",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        link = payload["links"][0]
        self.assertEqual(link["episode_started_at"], "2026-05-16T14:26:00")
        self.assertEqual(link["episode_ended_at"], "2026-05-16T14:29:00")
        self.assertEqual(link["link_reason"], "linked_by_journal_file_window")
        self.assertEqual(link["evidence_level"], "file_scope")
        self.assertIn("work_episode_link", link["flags"])
        self.assertIn("delayed_delivery", link["flags"])
        self.assertNotIn("stale_journal_window_ignored", link["flags"])
        self.assertEqual(link["score_breakdown"]["file_overlap_count"], 3)

    def test_journal_file_window_uses_matching_visible_episode_id(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix(memory): link delayed commits by file overlap",
                    "delivered_at": "2026-05-16T14:34:00",
                    "started_at": "2026-05-16T14:26:00",
                    "ended_at": "2026-05-16T14:29:00",
                    "top_files": [
                        "commit_episode_linker.py",
                        "journal_candidate_builder.py",
                        "work_episode_builder.py",
                    ],
                }
            ],
            [
                {
                    "id": "candidate-work",
                    "episode_id": "work-episode-2026-05-16T14:26:08",
                    "project": "Pulse",
                    "started_at": "2026-05-16T14:26:08",
                    "ended_at": "2026-05-16T14:29:39",
                    "dominant_scope": "memory",
                    "top_files": [
                        "commit_episode_linker.py",
                        "journal_candidate_builder.py",
                        "work_episode_builder.py",
                    ],
                    "ignored": False,
                },
                {
                    "id": "candidate-git",
                    "episode_id": "episode-git",
                    "project": "Pulse",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:11:00",
                    "dominant_scope": "git",
                    "probable_task": "terminal_execution",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        link = payload["links"][0]
        self.assertEqual(link["episode_id"], "work-episode-2026-05-16T14:26:08")
        self.assertEqual(link["candidate_id"], "journal-file-window-entry-1")
        self.assertEqual(link["episode_started_at"], "2026-05-16T14:26:08")
        self.assertEqual(link["episode_ended_at"], "2026-05-16T14:29:39")
        self.assertEqual(link["evidence_candidate_id"], "journal-file-window-entry-1")
        self.assertEqual(link["evidence_episode_id"], "journal-file-window-entry-1")
        self.assertEqual(link["evidence_started_at"], "2026-05-16T14:26:00")
        self.assertEqual(link["evidence_ended_at"], "2026-05-16T14:29:00")
        self.assertEqual(link["evidence_source"], "journal_file_window")
        self.assertEqual(link["link_reason"], "linked_by_journal_file_window")
        self.assertEqual(link["evidence_level"], "file_scope")

    def test_journal_file_window_allows_late_same_day_delivery_when_file_scoped(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-late",
                    "active_project": "Pulse",
                    "commit_message": "fix(dashboard): simplify dashboard navigation",
                    "delivered_at": "2026-05-16T18:57:57",
                    "started_at": "2026-05-16T15:50:11",
                    "ended_at": "2026-05-16T16:25:23",
                    "top_files": [
                        "DashboardRootView.swift",
                        "PulseViewModelInteractionsTests.swift",
                    ],
                }
            ],
            [
                {
                    "id": "candidate-git",
                    "episode_id": "episode-git",
                    "project": "Pulse",
                    "started_at": "2026-05-16T18:57:00",
                    "ended_at": "2026-05-16T19:02:00",
                    "dominant_scope": "git",
                    "probable_task": "terminal_execution",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        link = payload["links"][0]
        self.assertEqual(link["episode_started_at"], "2026-05-16T15:50:11")
        self.assertEqual(link["episode_ended_at"], "2026-05-16T16:25:23")
        self.assertEqual(link["evidence_candidate_id"], "journal-file-window-entry-late")
        self.assertEqual(link["evidence_started_at"], "2026-05-16T15:50:11")
        self.assertEqual(link["evidence_ended_at"], "2026-05-16T16:25:23")
        self.assertEqual(link["evidence_source"], "journal_file_window")
        self.assertEqual(link["link_reason"], "linked_by_journal_file_window")
        self.assertEqual(link["evidence_level"], "file_scope")
        self.assertIn("delayed_delivery", link["flags"])
        self.assertIn("delivery_after_episode", link["flags"])
        self.assertEqual(link["score_breakdown"]["file_overlap_count"], 2)

    def test_late_journal_window_without_files_or_project_does_not_force_link(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-late",
                    "active_project": "Pulse",
                    "commit_message": "fix(dashboard): simplify dashboard navigation",
                    "delivered_at": "2026-05-16T18:57:57",
                    "started_at": "2026-05-16T15:50:11",
                    "ended_at": "2026-05-16T16:25:23",
                },
                {
                    "entry_id": "entry-no-project",
                    "commit_message": "fix(dashboard): simplify dashboard navigation",
                    "delivered_at": "2026-05-16T18:57:57",
                    "started_at": "2026-05-16T15:50:11",
                    "ended_at": "2026-05-16T16:25:23",
                    "top_files": ["DashboardRootView.swift"],
                },
            ],
            [
                {
                    "id": "candidate-old",
                    "episode_id": "episode-old",
                    "project": "Pulse",
                    "started_at": "2026-05-16T15:50:11",
                    "ended_at": "2026-05-16T16:25:23",
                    "dominant_scope": "coding",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 2)

    def test_late_temporal_only_candidate_remains_unlinked(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-late",
                    "active_project": "Pulse",
                    "commit_message": "fix(dashboard): simplify dashboard navigation",
                    "delivered_at": "2026-05-16T18:57:57",
                }
            ],
            [
                {
                    "id": "candidate-old",
                    "episode_id": "episode-old",
                    "project": "Pulse",
                    "started_at": "2026-05-16T15:50:11",
                    "ended_at": "2026-05-16T16:25:23",
                    "dominant_scope": "coding",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 1)

    def test_journal_window_without_files_keeps_temporal_fallback(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "fix(memory): link delayed commits by file overlap",
                    "delivered_at": "2026-05-16T14:34:00",
                    "started_at": "2026-05-16T14:26:00",
                    "ended_at": "2026-05-16T14:29:00",
                }
            ],
            [
                {
                    "id": "candidate-git",
                    "episode_id": "episode-git",
                    "project": "Pulse",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:11:00",
                    "dominant_scope": "git",
                    "probable_task": "terminal_execution",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        link = payload["links"][0]
        self.assertEqual(link["episode_id"], "episode-git")
        self.assertEqual(link["link_reason"], "delivery_near_candidate_end")
        self.assertEqual(link["evidence_level"], "temporal_only")

    def test_journal_window_without_project_keeps_temporal_fallback(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "commit_message": "fix(memory): link delayed commits by file overlap",
                    "delivered_at": "2026-05-16T14:34:00",
                    "started_at": "2026-05-16T14:26:00",
                    "ended_at": "2026-05-16T14:29:00",
                    "top_files": ["commit_episode_linker.py"],
                }
            ],
            [
                {
                    "id": "candidate-git",
                    "episode_id": "episode-git",
                    "project": "Pulse",
                    "started_at": "2026-05-16T14:03:00",
                    "ended_at": "2026-05-16T14:11:00",
                    "dominant_scope": "git",
                    "probable_task": "terminal_execution",
                    "ignored": False,
                },
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        link = payload["links"][0]
        self.assertEqual(link["episode_id"], "episode-git")
        self.assertEqual(link["link_reason"], "delivery_near_candidate_end")
        self.assertEqual(link["evidence_level"], "temporal_only")

    def test_commit_with_no_plausible_open_or_closed_episode_remains_unlinked(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: outside open episode",
                    "delivered_at": "2026-05-15T07:30:00",
                    "started_at": "2026-05-15T07:30:00",
                    "ended_at": "2026-05-15T07:30:00",
                }
            ],
            [
                {
                    "id": "candidate-open-1",
                    "episode_id": "episode-open-1",
                    "project": "Pulse",
                    "started_at": "2026-05-15T07:52:00",
                    "ended_at": None,
                    "ignored": False,
                }
            ],
            now=datetime(2026, 5, 15, 8, 17, 0),
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 1)
        self.assertIn("no_plausible_episode", payload["unlinked_commits"][0]["flags"])

    def test_project_mismatch_prevents_open_episode_link(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: wrong project",
                    "delivered_at": "2026-05-15T08:03:00",
                    "started_at": "2026-05-15T08:03:00",
                    "ended_at": "2026-05-15T08:03:00",
                }
            ],
            [
                {
                    "id": "candidate-open-1",
                    "episode_id": "episode-open-1",
                    "project": "OtherProject",
                    "started_at": "2026-05-15T07:52:00",
                    "ended_at": None,
                    "ignored": False,
                }
            ],
            now=datetime(2026, 5, 15, 8, 17, 0),
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 1)

    def test_stale_open_episode_is_not_linked(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: stale open episode",
                    "delivered_at": "2026-05-15T08:03:00",
                    "started_at": "2026-05-15T08:03:00",
                    "ended_at": "2026-05-15T08:03:00",
                }
            ],
            [
                {
                    "id": "candidate-open-1",
                    "episode_id": "episode-open-1",
                    "project": "Pulse",
                    "started_at": "2026-05-14T22:00:00",
                    "ended_at": None,
                    "ignored": False,
                }
            ],
            now=datetime(2026, 5, 15, 8, 17, 0),
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 1)

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
        self.assertEqual(payload["links"][0]["confidence"], 0.58)
        self.assertEqual(payload["links"][0]["delivery_delta_min"], None)
        self.assertEqual(payload["links"][0]["window_distance_min"], 0)
        self.assertEqual(payload["links"][0]["overlap_min"], 15)

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
        self.assertEqual(payload["links"][0]["status"], "linked")
        self.assertIn("linked_by_delivery_proximity", payload["links"][0]["flags"])
        self.assertIn("delivery_after_episode", payload["links"][0]["flags"])
        self.assertIn("temporal_only_link", payload["links"][0]["flags"])
        self.assertEqual(payload["links"][0]["delivery_delta_min"], 2)
        self.assertLessEqual(payload["links"][0]["confidence"], 0.55)

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
        self.assertIn("delivery_far_from_episode", payload["unlinked_commits"][0]["flags"])

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
        self.assertIn("stale_journal_window_ignored", payload["links"][0]["flags"])

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
        self.assertEqual(payload["links"][0]["status"], "linked")
        self.assertIn("delivery_inside_episode", payload["links"][0]["flags"])
        self.assertIn("no_file_scope_match", payload["links"][0]["flags"])
        self.assertIn("temporal_only_link", payload["links"][0]["flags"])
        self.assertIn("confidence_capped_no_commit_context", payload["links"][0]["flags"])
        self.assertEqual(payload["links"][0]["evidence_level"], "temporal_only")
        self.assertEqual(payload["links"][0]["delivery_delta_min"], -2)
        self.assertLessEqual(payload["links"][0]["confidence"], 0.65)

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

    def test_commit_messages_dupliquees_ne_creent_qu_une_seule_unite(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_messages": [
                        "feat(memory): deduplicate commit messages",
                        "feat(memory): deduplicate commit messages",
                    ],
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

        self.assertEqual(payload["commit_count"], 1)
        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(
            payload["links"][0]["commit_subject"],
            "feat(memory): deduplicate commit messages",
        )

    def test_commit_message_full_body_et_commit_messages_subject_only_sont_deduplicates(self):
        full_message = (
            "feat(memory): compare journal entries with dry-run candidates\n\n"
            "Add read-only debug journal candidates and comparison routes."
        )
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": full_message,
                    "commit_messages": [
                        "feat(memory): compare journal entries with dry-run candidates",
                    ],
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

        self.assertEqual(payload["commit_count"], 1)
        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["links"][0]["commit_message"], full_message)
        self.assertEqual(
            payload["links"][0]["commit_subject"],
            "feat(memory): compare journal entries with dry-run candidates",
        )

    def test_commit_message_full_body_et_commit_messages_different_subject_creent_deux_unites(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat(memory): first subject\n\nBody",
                    "commit_messages": ["fix(memory): second subject"],
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
        self.assertEqual(
            [link["commit_subject"] for link in payload["links"]],
            ["feat(memory): first subject", "fix(memory): second subject"],
        )

    def test_commit_messages_same_subject_keep_longest_body(self):
        body_message = "feat(memory): same subject\n\nDetailed commit body."
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_messages": [
                        "feat(memory): same subject",
                        body_message,
                    ],
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

        self.assertEqual(payload["commit_count"], 1)
        self.assertEqual(payload["links"][0]["commit_message"], body_message)

    def test_commit_messages_different_subjects_remain_distinct(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_messages": [
                        "feat(memory): first subject",
                        "fix(memory): second subject",
                    ],
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
        self.assertEqual(
            [link["commit_subject"] for link in payload["links"]],
            ["feat(memory): first subject", "fix(memory): second subject"],
        )

    def test_commit_subject_deduplication_is_local_per_entry(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_messages": ["feat(memory): same subject"],
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:20:00",
                },
                {
                    "entry_id": "entry-2",
                    "active_project": "Pulse",
                    "commit_messages": ["feat(memory): same subject"],
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:20:00",
                },
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
        self.assertEqual([link["entry_id"] for link in payload["links"]], ["entry-1", "entry-2"])

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
        self.assertEqual(payload["links"][0]["status"], "linked")
        self.assertIn("ambiguous_candidates", payload["links"][0]["flags"])
        self.assertIn("temporal_only_link", payload["links"][0]["flags"])
        self.assertLessEqual(payload["links"][0]["confidence"], 0.60)

    def test_delivery_80_min_after_episode_has_prudent_confidence(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: delayed delivery",
                    "delivered_at": "2026-05-05T13:20:00",
                    "started_at": "2026-05-05T13:20:00",
                    "ended_at": "2026-05-05T13:20:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T11:50:00",
                    "ended_at": "2026-05-05T12:00:00",
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["links"][0]["status"], "linked")
        self.assertEqual(payload["links"][0]["delivery_delta_min"], 80)
        self.assertIn("delivery_after_episode", payload["links"][0]["flags"])
        self.assertIn("temporal_only_link", payload["links"][0]["flags"])
        self.assertLessEqual(payload["links"][0]["confidence"], 0.55)

    def test_delivery_51_min_after_short_candidate_without_overlap_is_unlinked(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: late short episode delivery",
                    "delivered_at": "2026-05-06T11:23:00",
                    "started_at": "2026-05-06T11:23:00",
                    "ended_at": "2026-05-06T11:23:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-06T10:29:36",
                    "ended_at": "2026-05-06T10:31:52",
                    "duration_min": 2,
                    "dominant_scope": "unknown",
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 1)
        flags = payload["unlinked_commits"][0]["flags"]
        self.assertIn("stale_short_episode_candidate", flags)
        self.assertIn("no_plausible_episode", flags)

    def test_delivery_26_min_after_short_candidate_remains_linked(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: recent short episode delivery",
                    "delivered_at": "2026-05-06T10:57:52",
                    "started_at": "2026-05-06T10:57:52",
                    "ended_at": "2026-05-06T10:57:52",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-06T10:29:36",
                    "ended_at": "2026-05-06T10:31:52",
                    "duration_min": 2,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["links"][0]["delivery_delta_min"], 26)
        self.assertIn("delivery_after_episode", payload["links"][0]["flags"])
        self.assertNotIn("stale_short_episode_candidate", payload["links"][0]["flags"])
        self.assertLessEqual(payload["links"][0]["confidence"], 0.55)

    def test_delivery_inside_short_candidate_remains_linked(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: inside short episode",
                    "delivered_at": "2026-05-06T10:30:00",
                    "started_at": "2026-05-06T10:30:00",
                    "ended_at": "2026-05-06T10:30:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-06T10:29:36",
                    "ended_at": "2026-05-06T10:31:52",
                    "duration_min": 2,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["links"][0]["episode_id"], "episode-1")
        self.assertIn("delivery_inside_episode", payload["links"][0]["flags"])
        self.assertIn("temporal_only_link", payload["links"][0]["flags"])
        self.assertLessEqual(payload["links"][0]["confidence"], 0.65)

    def test_delivery_60_min_after_long_candidate_remains_linked(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: long episode delayed delivery",
                    "delivered_at": "2026-05-06T12:00:00",
                    "started_at": "2026-05-06T12:00:00",
                    "ended_at": "2026-05-06T12:00:00",
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-06T10:00:00",
                    "ended_at": "2026-05-06T11:00:00",
                    "duration_min": 60,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["links"][0]["delivery_delta_min"], 60)
        self.assertIn("delivery_after_episode", payload["links"][0]["flags"])
        self.assertLessEqual(payload["links"][0]["confidence"], 0.55)

    def test_commit_only_journal_entry_caps_confidence(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: commit only",
                    "delivered_at": "2026-05-05T12:05:00",
                    "started_at": "2026-05-05T12:05:00",
                    "ended_at": "2026-05-05T12:05:00",
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
        self.assertIn("commit_only_journal_entry", payload["links"][0]["flags"])
        self.assertIn("no_file_scope_match", payload["links"][0]["flags"])
        self.assertIn("temporal_only_link", payload["links"][0]["flags"])
        self.assertLessEqual(payload["links"][0]["confidence"], 0.55)

    def test_overlap_zero_with_no_file_scope_caps_temporal_link_confidence(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: delivery inside candidate but stale journal window",
                    "delivered_at": "2026-05-05T12:05:00",
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
        link = payload["links"][0]
        self.assertEqual(link["status"], "linked")
        self.assertEqual(link["overlap_min"], 0)
        self.assertIn("delivery_inside_episode", link["flags"])
        self.assertIn("no_file_scope_match", link["flags"])
        self.assertIn("temporal_only_link", link["flags"])
        self.assertLessEqual(link["confidence"], 0.55)

    def test_output_exposes_score_breakdown_and_distance_fields(self):
        payload = link_commits_to_episodes(
            [
                {
                    "entry_id": "entry-1",
                    "active_project": "Pulse",
                    "commit_message": "feat: distances",
                    "delivered_at": "2026-05-05T12:12:00",
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
                    "ended_at": "2026-05-05T12:10:00",
                    "ignored": False,
                }
            ],
        )

        link = payload["links"][0]
        self.assertIn("delivery_delta_min", link)
        self.assertIn("window_distance_min", link)
        self.assertIn("overlap_min", link)
        self.assertEqual(link["score_breakdown"]["delivery_delta_min"], 2)
        self.assertEqual(link["score_breakdown"]["window_distance_min"], 0)
        self.assertEqual(link["score_breakdown"]["overlap_min"], 5)


if __name__ == "__main__":
    unittest.main()
