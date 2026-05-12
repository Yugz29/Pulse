import unittest

from daemon.llm.lightweight_queue import LightweightLLMQueue


class TestLightweightLLMQueue(unittest.TestCase):
    def test_enqueue_and_claim_pending_request(self):
        queue = LightweightLLMQueue()
        item = queue.enqueue(kind="journal_commit_summary", prompt="Résume", max_tokens=160)

        claimed = queue.claim_next()

        self.assertEqual(claimed.id, item.id)
        self.assertEqual(claimed.status, "in_progress")
        self.assertEqual(claimed.public_payload()["max_tokens"], 160)
        self.assertIsNone(queue.claim_next())

    def test_complete_returns_request_with_metadata(self):
        queue = LightweightLLMQueue()
        item = queue.enqueue(
            kind="journal_commit_summary",
            prompt="Résume",
            metadata={"report_ref": ("journal.md", "entry-1")},
        )

        completed = queue.complete(item.id, status="generated", text="Résumé.")

        self.assertEqual(completed.status, "generated")
        self.assertEqual(completed.text, "Résumé.")
        self.assertEqual(completed.metadata["report_ref"], ("journal.md", "entry-1"))

    def test_complete_rejects_invalid_status(self):
        queue = LightweightLLMQueue()
        item = queue.enqueue(kind="journal_commit_summary", prompt="Résume")

        with self.assertRaises(ValueError):
            queue.complete(item.id, status="pending")

    def test_complete_unknown_id_raises_key_error(self):
        queue = LightweightLLMQueue()

        with self.assertRaises(KeyError):
            queue.complete("missing", status="failed", error="offline")


if __name__ == "__main__":
    unittest.main()
