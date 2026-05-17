import unittest
from unittest.mock import patch

from daemon.llm.lifecycle_policy import (
    classify_llm_path,
    is_heavy_llm_autowarm_enabled,
    require_heavy_llm,
)


class TestLifecyclePolicy(unittest.TestCase):
    def test_autowarm_desactive_par_defaut(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(is_heavy_llm_autowarm_enabled())

    def test_autowarm_active_par_env(self):
        with patch.dict("os.environ", {"PULSE_HEAVY_LLM_AUTOWARM": "1"}):
            self.assertTrue(is_heavy_llm_autowarm_enabled())

    def test_paths_lourds_restent_classes_ollama(self):
        for path in ("ask", "ask_stream", "chat", "chat_tools", "daydream", "mcp_translation", "debug_resume_card_llm", "legacy_journal_repair"):
            self.assertEqual(classify_llm_path(path), "ollama_heavy")

    def test_resume_card_runtime_est_no_llm(self):
        self.assertEqual(classify_llm_path("resume_card"), "no_llm")

    def test_commit_summary_est_classe_apple_lightweight(self):
        self.assertEqual(classify_llm_path("journal_commit_summary"), "apple_lightweight")

    def test_resume_card_summary_est_classe_apple_lightweight(self):
        self.assertEqual(classify_llm_path("resume_card_summary"), "apple_lightweight")

    def test_unknown_path_est_no_llm_et_refusee_par_require(self):
        self.assertEqual(classify_llm_path("unknown"), "no_llm")
        self.assertFalse(require_heavy_llm("unknown", reason="test"))

    def test_require_heavy_llm_accepte_chemin_lourd_avec_reason(self):
        self.assertTrue(require_heavy_llm("ask", reason="explicit_user_chat"))

    def test_require_heavy_llm_refuse_chemin_lourd_sans_reason(self):
        self.assertFalse(require_heavy_llm("ask"))
        self.assertFalse(require_heavy_llm("ask", reason=""))

    def test_require_heavy_llm_refuse_chemin_vide(self):
        self.assertFalse(require_heavy_llm("", reason="missing"))

    def test_legacy_journal_repair_requiert_flag(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(require_heavy_llm("legacy_journal_repair", reason="manual_repair"))
        with patch.dict("os.environ", {"PULSE_LEGACY_JOURNAL_REPAIR": "1"}):
            self.assertTrue(require_heavy_llm("legacy_journal_repair", reason="manual_repair"))


if __name__ == "__main__":
    unittest.main()
