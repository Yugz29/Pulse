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

    def test_status_counts_without_exposing_prompt_or_text(self):
        queue = LightweightLLMQueue()
        pending = queue.enqueue(kind="journal_commit_summary", prompt="Prompt sensible")
        in_progress = queue.enqueue(kind="journal_commit_summary", prompt="Autre prompt")
        generated = queue.enqueue(kind="journal_commit_summary", prompt="Secret")
        failed = queue.enqueue(kind="journal_commit_summary", prompt="Secret")
        self.assertEqual(queue.claim_next().id, pending.id)
        self.assertEqual(queue.claim_next().id, in_progress.id)
        queue.complete(generated.id, status="generated", text="Texte généré sensible")
        queue.complete(failed.id, status="failed", error="offline")

        status = queue.status()

        self.assertEqual(status["queue"], {
            "pending": 0,
            "in_progress": 2,
            "completed": 1,
            "failed": 1,
        })
        self.assertIn(status["last_result"]["status"], {"generated", "failed"})
        self.assertNotIn("prompt", status["last_result"])
        self.assertNotIn("text", status["last_result"])

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
