import unittest
from datetime import datetime, timedelta

from daemon.core.event_actor import EventActor, EventActorClassifier, NoisePolicy
from daemon.core.event_bus import Event


def _file_event(path: str, ts: datetime, kind: str = "file_modified") -> Event:
    event = Event(kind, {"path": path})
    event.timestamp = ts
    return event


class TestEventActorClassifier(unittest.TestCase):
    def setUp(self):
        self.classifier = EventActorClassifier()
        self.now = datetime.now()

    def test_cache_huggingface_est_system_et_ignore(self):
        path = (
            "/Users/yugz/.cache/huggingface/modules/transformers_modules/"
            "Qwen/Qwen2-VL-2B-Instruct/adapter_config.json"
        )
        result = self.classifier.classify(
            "file_modified",
            {"path": path},
            latest_app="Codex",
            recent_events=[],
            now=self.now,
        )

        self.assertEqual(result.actor, EventActor.SYSTEM)
        self.assertEqual(result.noise_policy, NoisePolicy.IGNORE)

    def test_capture_ecran_est_observe_only(self):
        path = "/Users/yugz/Desktop/Capture d’écran 2026-04-28 à 10.49.52.png"
        result = self.classifier.classify(
            "file_created",
            {"path": path},
            latest_app="Claude",
            recent_events=[],
            now=self.now,
        )

        self.assertEqual(result.noise_policy, NoisePolicy.OBSERVE_ONLY)

    def test_burst_codex_vendor_imports_reste_systeme(self):
        base = self.now - timedelta(milliseconds=400)
        recent_events = [
            _file_event(
                f"/Users/yugz/.codex/vendor_imports/cache/file-{idx}.json",
                base + timedelta(milliseconds=idx * 50),
            )
            for idx in range(5)
        ]
        result = self.classifier.classify(
            "file_modified",
            {"path": "/Users/yugz/.codex/vendor_imports/cache/file-5.json"},
            latest_app="Codex",
            recent_events=recent_events,
            now=self.now,
        )

        self.assertEqual(result.actor, EventActor.SYSTEM)
        self.assertEqual(result.noise_policy, NoisePolicy.IGNORE)

    def test_codex_plugin_cache_est_ignore(self):
        result = self.classifier.classify(
            "file_created",
            {
                "path": "/Users/yugz/.codex/plugins/cache/openai-bundled/browser-use/"
                        "0.1.0-alpha1/skills/browser/SKILL.md"
            },
            latest_app="Codex",
            recent_events=[],
            now=self.now,
        )

        self.assertEqual(result.actor, EventActor.SYSTEM)
        self.assertEqual(result.noise_policy, NoisePolicy.IGNORE)


if __name__ == "__main__":
    unittest.main()
