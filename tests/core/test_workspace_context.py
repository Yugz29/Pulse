import tempfile
import unittest
from pathlib import Path

from daemon.core.workspace_context import extract_project_name, find_workspace_root


class TestWorkspaceContext(unittest.TestCase):
    def test_detecte_racine_git_hors_chemins_marqueurs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "client-work" / "alpha-repo"
            (repo_root / ".git").mkdir(parents=True)
            file_path = repo_root / "src" / "main.py"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("print('ok')\n")

            self.assertEqual(find_workspace_root(str(file_path)), repo_root)
            self.assertEqual(extract_project_name(str(file_path)), "alpha-repo")

    def test_retombe_sur_marqueur_si_pas_de_git(self):
        file_path = "/Users/yugz/workspace/demo-app/src/main.py"

        self.assertEqual(find_workspace_root(file_path), Path("/Users/yugz/workspace/demo-app"))
        self.assertEqual(extract_project_name(file_path), "demo-app")


if __name__ == "__main__":
    unittest.main()
