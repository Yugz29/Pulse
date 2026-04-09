import tempfile
import unittest
from pathlib import Path

from daemon.settings import load_runtime_settings, save_runtime_settings


class TestSettings(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmpdir.name) / "settings.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_returns_empty_dict_when_missing(self):
        self.assertEqual(load_runtime_settings(self.settings_path), {})

    def test_save_and_load_round_trip(self):
        payload = {
            "command_model": "qwen2.5-coder:1.5b",
            "summary_model": "huihui_ai/qwen3.5-abliterated:4b",
        }

        save_runtime_settings(payload, self.settings_path)

        self.assertEqual(load_runtime_settings(self.settings_path), payload)

    def test_load_returns_empty_dict_on_invalid_json(self):
        self.settings_path.write_text("{invalid", encoding="utf-8")
        self.assertEqual(load_runtime_settings(self.settings_path), {})


if __name__ == "__main__":
    unittest.main()
