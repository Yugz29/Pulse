import unittest

from daemon.memory.journal_candidate_comparator import compare_journal_candidates


class TestJournalCandidateComparator(unittest.TestCase):

    def test_entry_et_candidate_alignes_creent_un_match_time_aligned(self):
        payload = compare_journal_candidates(
            [
                {
                    "entry_id": "journal-1",
                    "active_project": "Pulse",
                    "started_at": "2026-05-05T11:00:00",
                    "ended_at": "2026-05-05T11:20:00",
                    "duration_min": 20,
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T11:01:00",
                    "ended_at": "2026-05-05T11:19:00",
                    "duration_min": 18,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["journal_entry_count"], 1)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(len(payload["matches"]), 1)
        self.assertIn("time_aligned", payload["matches"][0]["flags"])

    def test_ecart_temporel_lointain_ne_cree_pas_de_match(self):
        payload = compare_journal_candidates(
            [
                {
                    "entry_id": "journal-1",
                    "active_project": "Pulse",
                    "started_at": "2026-05-05T20:00:00",
                    "ended_at": "2026-05-05T20:00:00",
                    "duration_min": 0,
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T14:44:00",
                    "ended_at": "2026-05-05T14:46:00",
                    "duration_min": 2,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["matches"], [])
        self.assertEqual(payload["unmatched_journal_entries"][0]["entry_id"], "journal-1")
        self.assertEqual(payload["unmatched_candidates"][0]["id"], "candidate-1")

    def test_distance_inferieure_a_vingt_minutes_cree_un_match(self):
        payload = compare_journal_candidates(
            [
                {
                    "entry_id": "journal-1",
                    "active_project": "Pulse",
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:10:00",
                    "duration_min": 10,
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T12:15:00",
                    "ended_at": "2026-05-05T12:20:00",
                    "duration_min": 5,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(len(payload["matches"]), 1)
        flags = payload["matches"][0]["flags"]
        self.assertIn("no_overlap", flags)

    def test_distance_superieure_a_vingt_minutes_ne_cree_pas_de_match(self):
        payload = compare_journal_candidates(
            [
                {
                    "entry_id": "journal-1",
                    "active_project": "Pulse",
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:10:00",
                    "duration_min": 10,
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T12:31:00",
                    "ended_at": "2026-05-05T12:40:00",
                    "duration_min": 9,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["matches"], [])
        self.assertEqual(len(payload["unmatched_journal_entries"]), 1)
        self.assertEqual(len(payload["unmatched_candidates"]), 1)

    def test_overlap_partiel_cree_un_match(self):
        payload = compare_journal_candidates(
            [
                {
                    "entry_id": "journal-1",
                    "active_project": "Pulse",
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:10:00",
                    "duration_min": 10,
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T12:05:00",
                    "ended_at": "2026-05-05T12:20:00",
                    "duration_min": 15,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(len(payload["matches"]), 1)
        self.assertNotIn("no_overlap", payload["matches"][0]["flags"])

    def test_project_mismatch_avec_overlap_ne_force_pas_de_match(self):
        payload = compare_journal_candidates(
            [
                {
                    "entry_id": "journal-1",
                    "active_project": "Pulse",
                    "started_at": "2026-05-05T11:00:00",
                    "ended_at": "2026-05-05T11:20:00",
                    "duration_min": 20,
                }
            ],
            [
                {
                    "id": "candidate-1",
                    "project": "Other",
                    "started_at": "2026-05-05T11:02:00",
                    "ended_at": "2026-05-05T11:18:00",
                    "duration_min": 16,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["matches"], [])
        self.assertEqual(len(payload["unmatched_journal_entries"]), 1)
        self.assertEqual(len(payload["unmatched_candidates"]), 1)

    def test_unmatched_journal_entry(self):
        payload = compare_journal_candidates(
            [
                {
                    "entry_id": "journal-1",
                    "active_project": "Pulse",
                    "started_at": "2026-05-05T11:00:00",
                    "ended_at": "2026-05-05T11:20:00",
                    "duration_min": 20,
                    "commit_message": "feat: shipping",
                }
            ],
            [],
        )

        self.assertEqual(payload["matches"], [])
        self.assertEqual(payload["unmatched_journal_entries"][0]["entry_id"], "journal-1")
        self.assertIn("journal_has_commit", payload["unmatched_journal_entries"][0]["flags"])

    def test_unmatched_candidate(self):
        payload = compare_journal_candidates(
            [],
            [
                {
                    "id": "candidate-1",
                    "episode_id": "episode-1",
                    "project": "Pulse",
                    "started_at": "2026-05-05T11:02:00",
                    "ended_at": "2026-05-05T11:18:00",
                    "duration_min": 16,
                    "ignored": False,
                }
            ],
        )

        self.assertEqual(payload["matches"], [])
        self.assertEqual(payload["unmatched_candidates"][0]["id"], "candidate-1")


if __name__ == "__main__":
    unittest.main()
