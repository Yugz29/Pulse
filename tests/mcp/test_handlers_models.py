import unittest
from unittest.mock import patch

from daemon.mcp import handlers


class TestHandlersModels(unittest.TestCase):

    def test_get_available_models_returns_empty_on_error(self):
        with patch.object(handlers.llm_router, "list_models", side_effect=RuntimeError("offline")):
            self.assertEqual(handlers.get_available_llm_models(), [])

    def test_set_selected_model_rejects_unknown_model(self):
        with patch("daemon.mcp.handlers.get_available_llm_models", return_value=["mistral"]):
            self.assertFalse(handlers.set_selected_command_llm_model("qwen2.5-coder:1.5b"))

    def test_set_selected_model_accepts_known_model(self):
        with patch("daemon.mcp.handlers.get_available_llm_models", return_value=["mistral", "qwen2.5-coder:1.5b"]):
            self.assertTrue(handlers.set_selected_command_llm_model("qwen2.5-coder:1.5b"))
            self.assertEqual(handlers.get_selected_command_llm_model(), "qwen2.5-coder:1.5b")

    def test_legacy_accessors_remain_compatible(self):
        with patch("daemon.mcp.handlers.get_available_llm_models", return_value=["mistral", "qwen2.5-coder:1.5b"]):
            self.assertTrue(handlers.set_selected_llm_model("mistral"))
            self.assertEqual(handlers.get_selected_llm_model(), "mistral")


if __name__ == "__main__":
    unittest.main()
