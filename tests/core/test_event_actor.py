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

    def test_tool_assisted_app_remains_tool_assisted_after_catalog_centralization(self):
        result = self.classifier.classify(
            "file_modified",
            {"path": "/Users/yugz/Projets/Alpha/src/main.py"},
            latest_app="Cursor",
            recent_events=[],
            now=self.now,
        )

        self.assertEqual(result.actor, EventActor.TOOL_ASSISTED)
        self.assertGreater(result.automation_score, 0.5)

    def test_tool_assisted_app_recognized_by_existing_name(self):
        result = self.classifier.classify(
            "file_modified",
            {"path": "/tmp/acme-api/src/main.py"},
            latest_app="Codex",
            recent_events=[],
            now=self.now,
        )

        self.assertEqual(result.actor, EventActor.TOOL_ASSISTED)
        self.assertGreater(result.automation_score, 0.5)

    def test_ai_support_app_is_not_automatically_tool_assisted(self):
        result = self.classifier.classify(
            "file_modified",
            {"path": "/tmp/acme-api/src/main.py"},
            latest_app="RandomAssistant",
            latest_app_bundle_id="dev.pulse.test.UnknownAI",
            recent_events=[],
            now=self.now,
        )

        self.assertNotEqual(result.actor, EventActor.TOOL_ASSISTED)
        self.assertLessEqual(result.automation_score, 0.5)

    def test_tool_assisted_bundle_can_mark_tool_assisted_if_supported(self):
        result = self.classifier.classify(
            "file_modified",
            {"path": "/tmp/acme-api/src/main.py"},
            latest_app="RandomToolAssistant",
            latest_app_bundle_id="dev.pulse.test.ToolAssistant",
            recent_events=[],
            now=self.now,
        )

        self.assertEqual(result.actor, EventActor.TOOL_ASSISTED)
        self.assertGreater(result.automation_score, 0.5)

    def test_user_file_event_stays_user_when_only_regular_dev_tool(self):
        result = self.classifier.classify(
            "file_modified",
            {"path": "/tmp/acme-api/src/main.py"},
            latest_app="RandomIDE",
            latest_app_bundle_id="dev.pulse.test.UnknownIDE",
            recent_events=[],
            now=self.now,
        )

        self.assertNotEqual(result.actor, EventActor.TOOL_ASSISTED)
        self.assertLessEqual(result.automation_score, 0.5)


if __name__ == "__main__":
    unittest.main()
