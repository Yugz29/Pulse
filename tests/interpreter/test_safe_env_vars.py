import unittest
from daemon.interpreter.safe_env_vars import strip_safe_env_vars


class TestStripSafeEnvVars(unittest.TestCase):

    def test_retire_variable_safe(self):
        # NODE_ENV est dans SAFE_ENV_VARS → doit être retiré
        self.assertEqual(strip_safe_env_vars("NODE_ENV=production npm start"), "npm start")

    def test_retire_plusieurs_variables_safe(self):
        # Deux variables sûres à la suite
        self.assertEqual(strip_safe_env_vars("NO_COLOR=1 RUST_LOG=debug cargo run"), "cargo run")

    def test_garde_variable_dangereuse(self):
        # PYTHONPATH est dans NEVER_SAFE → ne doit pas être retiré
        self.assertEqual(strip_safe_env_vars("PYTHONPATH=. python app.py"), "PYTHONPATH=. python app.py")

    def test_garde_variable_inconnue(self):
        # MY_VAR n'est pas dans SAFE_ENV_VARS → ne doit pas être retiré
        self.assertEqual(strip_safe_env_vars("MY_VAR=foo npm install"), "MY_VAR=foo npm install")

    def test_commande_sans_variable(self):
        # Pas de variable → commande inchangée
        self.assertEqual(strip_safe_env_vars("rm -rf ."), "rm -rf .")

    def test_commande_vide(self):
        self.assertEqual(strip_safe_env_vars(""), "")


if __name__ == "__main__":
    unittest.main()
