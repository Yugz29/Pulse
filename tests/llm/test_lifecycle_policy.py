import unittest
from unittest.mock import patch

from daemon.llm.lifecycle_policy import classify_llm_path, is_heavy_llm_autowarm_enabled


class TestLifecyclePolicy(unittest.TestCase):
    def test_autowarm_desactive_par_defaut(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(is_heavy_llm_autowarm_enabled())

    def test_autowarm_active_par_env(self):
        with patch.dict("os.environ", {"PULSE_HEAVY_LLM_AUTOWARM": "1"}):
            self.assertTrue(is_heavy_llm_autowarm_enabled())

    def test_paths_lourds_restent_classes_ollama(self):
        for path in ("chat", "chat_tools", "daydream", "mcp_translation", "debug_resume_card_llm", "legacy_journal_repair"):
            self.assertEqual(classify_llm_path(path), "ollama_heavy")

    def test_resume_card_runtime_est_no_llm(self):
        self.assertEqual(classify_llm_path("resume_card"), "no_llm")

    def test_commit_summary_est_classe_apple_lightweight(self):
        self.assertEqual(classify_llm_path("journal_commit_summary"), "apple_lightweight")


if __name__ == "__main__":
    unittest.main()
