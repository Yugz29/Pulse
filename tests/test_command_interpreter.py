import unittest
from daemon.interpreter.command_interpreter import CommandInterpreter


class TestCommandInterpreter(unittest.TestCase):

    def setUp(self):
        # setUp est appelé avant chaque test — crée une instance fraîche
        self.ci = CommandInterpreter()

    def test_commande_lecture_seule(self):
        result = self.ci.interpret("ls -la")
        self.assertTrue(result.is_read_only)
        self.assertEqual(result.risk_level, "safe")
        self.assertEqual(result.risk_score, 0)

    def test_git_status_lecture_seule(self):
        result = self.ci.interpret("git status")
        self.assertTrue(result.is_read_only)
        self.assertEqual(result.risk_level, "safe")

    def test_rm_rf_critique(self):
        result = self.ci.interpret("rm -rf node_modules")
        self.assertFalse(result.is_read_only)
        self.assertEqual(result.risk_level, "critical")
        self.assertEqual(result.risk_score, 100)

    def test_git_reset_hard_eleve(self):
        result = self.ci.interpret("git reset --hard")
        self.assertEqual(result.risk_level, "high")
        self.assertIsNotNone(result.warning)

    def test_variable_env_safe_retiree(self):
        # NODE_ENV doit être retiré avant l'analyse
        result = self.ci.interpret("NODE_ENV=production npm start")
        self.assertEqual(result.risk_level, "medium")
        self.assertFalse(result.needs_llm)

    def test_commande_inconnue_needs_llm(self):
        result = self.ci.interpret("unknowncommand --flag")
        self.assertTrue(result.needs_llm)

    def test_commande_connue_pas_llm(self):
        result = self.ci.interpret("npm install")
        self.assertFalse(result.needs_llm)

    def test_grep_traduit_correctement(self):
        result = self.ci.interpret('grep -R "API_KEY" .')
        self.assertIn("API_KEY", result.translated)

    def test_original_preserve(self):
        # La commande originale (avec variables) doit être conservée
        cmd = "NODE_ENV=prod npm start"
        result = self.ci.interpret(cmd)
        self.assertEqual(result.original, cmd)


if __name__ == "__main__":
    unittest.main()
