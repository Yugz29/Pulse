import unittest
from daemon.interpreter.command_semantics import get_command_description


class TestGetCommandDescription(unittest.TestCase):

    def test_grep_recursif_avec_pattern(self):
        result = get_command_description('grep -R "API_KEY" .', "grep")
        self.assertIn("API_KEY", result)
        self.assertIn("récursive", result)

    def test_git_push(self):
        result = get_command_description("git push origin main", "git")
        self.assertIn("distant", result)

    def test_git_status(self):
        result = get_command_description("git status", "git")
        self.assertIsNotNone(result)

    def test_npm_install(self):
        result = get_command_description("npm install", "npm")
        self.assertIn("dépendances", result)

    def test_npm_run_build(self):
        result = get_command_description("npm run build", "npm")
        self.assertIn("build", result)

    def test_curl_avec_url(self):
        result = get_command_description("curl https://api.github.com", "curl")
        self.assertIn("api.github.com", result)

    def test_commande_inconnue_retourne_none(self):
        result = get_command_description("unknowncommand --flag", "unknowncommand")
        self.assertIsNone(result)

    def test_awk(self):
        result = get_command_description("awk '{print $2}' file.txt", "awk")
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
