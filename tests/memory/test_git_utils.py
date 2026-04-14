"""
Tests pour les fonctions git d'extractor.py.

Couvre :
  - find_git_root : dépôt standard, worktree (.git fichier), absent
  - read_head_sha : branche normale, HEAD détaché, ref absente, worktree
  - read_commit_message : message normal, lignes commentaires filtrées, vide
"""

import tempfile
import unittest
from pathlib import Path

from daemon.memory.extractor import _resolve_git_dir, find_git_root, read_commit_message, read_head_sha


class TestFindGitRoot(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_trouve_depot_standard(self):
        git_dir = self.root / ".git"
        git_dir.mkdir()
        subdir  = self.root / "src" / "module"
        subdir.mkdir(parents=True)
        result = find_git_root(str(subdir / "file.py"))
        self.assertEqual(result, self.root)

    def test_trouve_worktree_git_fichier(self):
        """Supporte .git comme fichier (worktree / submodule)."""
        worktree = self.root / "wt"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: /some/real/.git")
        result = find_git_root(str(worktree / "main.py"))
        self.assertEqual(result, worktree)

    def test_retourne_none_sans_git(self):
        nongit = self.root / "nongit"
        nongit.mkdir()
        self.assertIsNone(find_git_root(str(nongit / "file.py")))

    def test_fonctionne_sur_fichier_direct(self):
        git_dir = self.root / ".git"
        git_dir.mkdir()
        f = self.root / "main.py"
        f.write_text("# code")
        self.assertEqual(find_git_root(str(f)), self.root)


class TestReadHeadSha(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".git").mkdir()
        (self.root / ".git" / "refs" / "heads").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_head(self, content: str):
        (self.root / ".git" / "HEAD").write_text(content)

    def _write_ref(self, sha: str, branch: str = "main"):
        (self.root / ".git" / "refs" / "heads" / branch).write_text(sha + "\n")

    def test_branche_normale(self):
        sha = "a" * 40
        self._write_head("ref: refs/heads/main\n")
        self._write_ref(sha)
        self.assertEqual(read_head_sha(self.root), sha)

    def test_head_detache(self):
        sha = "b" * 40
        self._write_head(sha + "\n")
        self.assertEqual(read_head_sha(self.root), sha)

    def test_retourne_none_si_ref_absente(self):
        self._write_head("ref: refs/heads/inexistante\n")
        self.assertIsNone(read_head_sha(self.root))

    def test_retourne_none_si_head_absent(self):
        # Pas de fichier HEAD du tout
        self.assertIsNone(read_head_sha(self.root))

    def test_deux_commits_sha_different(self):
        """Simule un avancement de HEAD (nouveau commit)."""
        self._write_head("ref: refs/heads/main\n")
        sha1 = "1" * 40
        self._write_ref(sha1)
        first  = read_head_sha(self.root)

        sha2 = "2" * 40
        self._write_ref(sha2)
        second = read_head_sha(self.root)

        self.assertNotEqual(first, second)

    def test_worktree_gitfile_avec_gitdir_relatif(self):
        worktree = self.root / "wt"
        gitdir = self.root / "gitdirs" / "wt"
        gitdir_refs = gitdir / "refs" / "heads"
        gitdir_refs.mkdir(parents=True)
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: ../gitdirs/wt\n")
        (gitdir / "HEAD").write_text("ref: refs/heads/main\n")
        sha = "c" * 40
        (gitdir_refs / "main").write_text(sha + "\n")
        self.assertEqual(read_head_sha(worktree), sha)


class TestResolveGitDir(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_git_dossier_retourne_dossier_git(self):
        git_dir = self.root / ".git"
        git_dir.mkdir()
        self.assertEqual(_resolve_git_dir(self.root), git_dir)

    def test_gitfile_avec_gitdir_absolu_retourne_vrai_gitdir(self):
        worktree = self.root / "wt"
        gitdir = self.root / "realgit"
        worktree.mkdir()
        gitdir.mkdir()
        (worktree / ".git").write_text(f"gitdir: {gitdir}\n")
        self.assertEqual(_resolve_git_dir(worktree), gitdir)

    def test_gitfile_avec_gitdir_relatif_est_resolu_depuis_parent(self):
        worktree = self.root / "wt"
        gitdir = self.root / "gitdirs" / "wt"
        worktree.mkdir()
        gitdir.mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: ../gitdirs/wt\n")
        self.assertEqual(_resolve_git_dir(worktree), gitdir.resolve())

    def test_retourne_none_si_gitfile_invalide(self):
        worktree = self.root / "wt"
        worktree.mkdir()
        (worktree / ".git").write_text("pas-un-gitdir\n")
        self.assertIsNone(_resolve_git_dir(worktree))


class TestReadCommitMessage(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".git").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_commit_msg(self, content: str):
        (self.root / ".git" / "COMMIT_EDITMSG").write_text(content)

    def test_message_simple(self):
        self._write_commit_msg("fix: correction du bug\n")
        self.assertEqual(read_commit_message(self.root), "fix: correction du bug")

    def test_filtre_lignes_commentaire(self):
        self._write_commit_msg(
            "feat: nouvelle feature\n"
            "# Ceci est un commentaire git\n"
            "# Un autre commentaire\n"
        )
        msg = read_commit_message(self.root)
        self.assertEqual(msg, "feat: nouvelle feature")
        self.assertNotIn("#", msg)

    def test_message_multilignes(self):
        self._write_commit_msg("feat: titre\n\nCorps du message\n")
        msg = read_commit_message(self.root)
        self.assertIn("feat: titre", msg)
        self.assertIn("Corps du message", msg)

    def test_retourne_none_si_message_vide(self):
        self._write_commit_msg("# Seulement des commentaires\n# Rien d'autre\n")
        self.assertIsNone(read_commit_message(self.root))

    def test_retourne_none_si_fichier_absent(self):
        self.assertIsNone(read_commit_message(self.root))

    def test_worktree_gitfile_lit_commit_editmsg_depuis_vrai_gitdir(self):
        worktree = self.root / "wt"
        gitdir = self.root / "gitdirs" / "wt"
        worktree.mkdir()
        gitdir.mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: ../gitdirs/wt\n")
        (gitdir / "COMMIT_EDITMSG").write_text("fix: worktree commit\n")
        self.assertEqual(read_commit_message(worktree), "fix: worktree commit")


if __name__ == "__main__":
    unittest.main()
