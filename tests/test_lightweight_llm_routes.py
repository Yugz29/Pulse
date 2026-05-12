import unittest

from flask import Flask

from daemon.llm.lightweight_queue import LightweightLLMQueue
from daemon.routes.lightweight_llm import register_lightweight_llm_routes


class TestLightweightLLMRoutes(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.queue = LightweightLLMQueue()
        self.applied = []

        def apply_result(**kwargs):
            self.applied.append(kwargs)
            self.queue.complete(
                kwargs["request_id"],
                status=kwargs["status"],
                text=kwargs.get("text") or "",
                error=kwargs.get("error"),
            )
            return {"ok": True, "applied": True, "status": kwargs["status"]}

        register_lightweight_llm_routes(
            self.app,
            lightweight_queue=self.queue,
            apply_result=apply_result,
        )
        self.client = self.app.test_client()

    def test_pending_returns_null_when_queue_empty(self):
        response = self.client.get("/llm/lightweight/pending")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["request"])

    def test_pending_claims_request(self):
        item = self.queue.enqueue(kind="journal_commit_summary", prompt="Résume", max_tokens=120)

        response = self.client.get("/llm/lightweight/pending")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["request"]
        self.assertEqual(payload["id"], item.id)
        self.assertEqual(payload["kind"], "journal_commit_summary")
        self.assertEqual(payload["status"], "in_progress")

    def test_result_posts_to_apply_callback(self):
        item = self.queue.enqueue(kind="journal_commit_summary", prompt="Résume")

        response = self.client.post(
            "/llm/lightweight/result",
            json={"id": item.id, "status": "generated", "text": "Résumé.", "error": None},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "generated")
        self.assertEqual(self.applied[0]["request_id"], item.id)
        self.assertEqual(self.applied[0]["text"], "Résumé.")

    def test_result_rejects_invalid_payload(self):
        response = self.client.post(
            "/llm/lightweight/result",
            json={"id": "x", "status": "pending"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_status")


if __name__ == "__main__":
    unittest.main()
