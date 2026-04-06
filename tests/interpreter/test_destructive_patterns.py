import unittest
from daemon.interpreter.destructive_patterns import get_destructive_warning


class TestGetDestructiveWarning(unittest.TestCase):

    # --- Git ---
    def test_git_reset_hard(self):
        result = get_destructive_warning("git reset --hard")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "high")

    def test_git_push_force(self):
        result = get_destructive_warning("git push origin main --force")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "high")

    def test_git_stash_drop(self):
        result = get_destructive_warning("git stash drop")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "medium")

    # --- Suppression ---
    def test_rm_rf(self):
        result = get_destructive_warning("rm -rf node_modules")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "critical")

    def test_rm_f(self):
        result = get_destructive_warning("rm -f fichier.txt")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "medium")

    # --- Base de données ---
    def test_drop_table(self):
        result = get_destructive_warning("DROP TABLE users;")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "critical")

    def test_drop_table_minuscule(self):
        # re.IGNORECASE → doit matcher aussi en minuscules
        result = get_destructive_warning("drop table users;")
        self.assertIsNotNone(result)

    # --- Infrastructure ---
    def test_terraform_destroy(self):
        result = get_destructive_warning("terraform destroy")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "critical")

    # --- Commandes sûres ---
    def test_npm_install_est_safe(self):
        self.assertIsNone(get_destructive_warning("npm install"))

    def test_git_status_est_safe(self):
        self.assertIsNone(get_destructive_warning("git status"))

    def test_ls_est_safe(self):
        self.assertIsNone(get_destructive_warning("ls -la"))


if __name__ == "__main__":
    unittest.main()
