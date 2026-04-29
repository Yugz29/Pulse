import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from daemon.core.resume_card import (
    build_resume_card_context,
    generate_resume_card,
    should_offer_resume_card,
)
from daemon.runtime_state import PresentState, RuntimeSnapshot


class TestResumeCard(unittest.TestCase):
    def test_should_offer_resume_card_requires_long_unlock_and_project(self):
        payload = {"duration_min": 30}

        self.assertFalse(should_offer_resume_card(
            event_type="screen_unlocked",
            sleep_minutes=5,
            active_project="Pulse",
            memory_payload=payload,
            last_offered_at=None,
        ))
        self.assertFalse(should_offer_resume_card(
            event_type="screen_unlocked",
            sleep_minutes=25,
            active_project=None,
            memory_payload=payload,
            last_offered_at=None,
        ))
        self.assertTrue(should_offer_resume_card(
            event_type="screen_unlocked",
            sleep_minutes=25,
            active_project="Pulse",
            memory_payload=payload,
            last_offered_at=None,
        ))
        self.assertTrue(should_offer_resume_card(
            event_type="resume_after_pause",
            sleep_minutes=35,
            active_project="Pulse",
            memory_payload=payload,
            last_offered_at=None,
        ))

    def test_should_offer_resume_card_respects_cooldown(self):
        now = datetime(2026, 4, 29, 10, 0, 0)
        payload = {"duration_min": 30}

        self.assertFalse(should_offer_resume_card(
            event_type="screen_unlocked",
            sleep_minutes=25,
            active_project="Pulse",
            memory_payload=payload,
            last_offered_at=now - timedelta(minutes=30),
            now=now,
        ))
        self.assertTrue(should_offer_resume_card(
            event_type="screen_unlocked",
            sleep_minutes=25,
            active_project="Pulse",
            memory_payload=payload,
            last_offered_at=now - timedelta(minutes=130),
            now=now,
        ))

    def test_generate_resume_card_fallback_is_short_and_explainable(self):
        snapshot = RuntimeSnapshot(
            present=PresentState(
                active_project="Pulse",
                active_file="/tmp/Pulse/daemon/runtime_orchestrator.py",
                probable_task="coding",
                activity_level="editing",
                session_duration_min=48,
            ),
            signals=SimpleNamespace(active_file="/tmp/Pulse/daemon/runtime_orchestrator.py"),
            last_diff_summary="diff --git a/daemon/runtime_orchestrator.py",
        )
        context = build_resume_card_context(
            runtime_snapshot=snapshot,
            memory_payload={
                "duration_min": 48,
                "top_files": ["/tmp/Pulse/tests/test_runtime_orchestrator.py"],
                "work_window_started_at": "2026-04-29T09:00:00",
            },
            sleep_minutes=32,
            diff_summary=snapshot.last_diff_summary,
        )

        card = generate_resume_card(context)

        self.assertEqual(card.project, "Pulse")
        self.assertEqual(card.generated_by, "deterministic")
        self.assertIn("present_state", card.source_refs)
        self.assertIn("git_diff", card.source_refs)
        self.assertLessEqual(len(card.summary), 110)
        self.assertLessEqual(len(card.next_action), 130)

    def test_generate_resume_card_accepts_valid_llm_json(self):
        class FakeLLM:
            def complete(self, prompt, max_tokens=180):
                return json.dumps({
                    "title": "Reprise de contexte",
                    "summary": "Tu étais sur Pulse.",
                    "last_objective": "Stabiliser la Resume Card.",
                    "next_action": "Relancer les tests ciblés.",
                    "confidence": 0.81,
                })

        context = {
            "project": "Pulse",
            "probable_task": "coding",
            "source_refs": ["present_state", "session_memory"],
        }

        card = generate_resume_card(context, llm=FakeLLM())

        self.assertEqual(card.generated_by, "llm")
        self.assertEqual(card.next_action, "Relancer les tests ciblés.")
        self.assertEqual(card.confidence, 0.81)


if __name__ == "__main__":
    unittest.main()
