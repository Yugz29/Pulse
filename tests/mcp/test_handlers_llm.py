import unittest
from unittest.mock import patch

from daemon.mcp import handlers


class TestHandlersLLM(unittest.TestCase):

    def test_translate_with_llm_returns_llm_text(self):
        with patch.object(handlers.llm_router, "complete", return_value="Installe des dépendances Node.js"):
            translated = handlers._translate_with_llm("npm install", "Exécute : `npm install`")
        self.assertEqual(translated, "Installe des dépendances Node.js")

    def test_translate_with_llm_falls_back_on_error(self):
        with patch.object(handlers.llm_router, "complete", side_effect=RuntimeError("offline")):
            translated = handlers._translate_with_llm("unknowncmd", "Exécute : `unknowncmd`")
        self.assertEqual(translated, "Exécute : `unknowncmd`")


if __name__ == "__main__":
    unittest.main()
