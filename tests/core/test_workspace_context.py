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

    def test_extract_project_name_from_standard_child_dir_without_projects_folder(self):
        file_path = "/tmp/acme-api/src/handler.py"

        self.assertEqual(find_workspace_root(file_path), Path("/tmp/acme-api"))
        self.assertEqual(extract_project_name(file_path), "acme-api")

    def test_extract_project_name_never_returns_filename_from_src_path(self):
        file_path = "/tmp/acme-api/src/handler.py"

        self.assertNotEqual(extract_project_name(file_path), "handler.py")

    def test_git_root_has_priority_over_standard_child_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "client-api"
            nested_dir = repo_root / "packages" / "api" / "src"
            (repo_root / ".git").mkdir(parents=True)
            nested_dir.mkdir(parents=True)
            file_path = nested_dir / "handler.py"
            file_path.write_text("print('ok')\n")

            self.assertEqual(find_workspace_root(str(file_path)), repo_root)
            self.assertEqual(extract_project_name(str(file_path)), "client-api")

    def test_projects_folder_is_not_required(self):
        file_path = "/home/sam/dev/rust-cli/src/main.rs"

        self.assertEqual(find_workspace_root(file_path), Path("/home/sam/dev/rust-cli"))
        self.assertEqual(extract_project_name(file_path), "rust-cli")

    def test_root_project_file_can_identify_parent_without_projects_folder(self):
        file_path = "/Users/sam/dev/client-api/package.json"

        self.assertEqual(find_workspace_root(file_path), Path("/Users/sam/dev/client-api"))
        self.assertEqual(extract_project_name(file_path), "client-api")

    def test_directory_like_cwd_can_be_workspace_root_when_plausible(self):
        cwd = "/tmp/work/client-api"

        self.assertEqual(find_workspace_root(cwd), Path("/tmp/work/client-api"))
        self.assertEqual(extract_project_name(cwd), "client-api")

    def test_terminal_cwd_inside_tools_uses_parent_project(self):
        cwd = "/tmp/work/AlphaApp/tools"

        self.assertEqual(find_workspace_root(cwd), Path("/tmp/work/AlphaApp"))
        self.assertEqual(extract_project_name(cwd), "AlphaApp")

    def test_terminal_cwd_inside_scripts_or_bin_uses_parent_project(self):
        for cwd in ("/tmp/work/AlphaApp/scripts", "/tmp/work/AlphaApp/bin"):
            with self.subTest(cwd=cwd):
                self.assertEqual(find_workspace_root(cwd), Path("/tmp/work/AlphaApp"))
                self.assertEqual(extract_project_name(cwd), "AlphaApp")

    def test_ambiguous_short_path_returns_none(self):
        for file_path in ("handler.py", "/tmp/handler.py", "/src/handler.py"):
            with self.subTest(file_path=file_path):
                self.assertIsNone(find_workspace_root(file_path))
                self.assertIsNone(extract_project_name(file_path))

    def test_path_traversal_outside_observed_roots_returns_none(self):
        file_path = "/tmp/workspace/../../etc/passwd"

        self.assertIsNone(find_workspace_root(file_path))
        self.assertIsNone(extract_project_name(file_path))

    def test_standard_child_dir_parent_must_be_plausible(self):
        for file_path in ("/src/handler.py", "/tmp/src/handler.py"):
            with self.subTest(file_path=file_path):
                self.assertIsNone(find_workspace_root(file_path))
                self.assertIsNone(extract_project_name(file_path))


if __name__ == "__main__":
    unittest.main()
