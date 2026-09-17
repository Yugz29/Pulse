"""Worktrees liés : rattachement au dépôt principal, liste de ceux qui existent."""

import os
import subprocess
from pathlib import Path

from daemon_v2.analysis.projects import resolve_project_context
from daemon_v2.git_worktree import linked_worktrees, main_repository_root, repository_name
from daemon_v2.workspace_context import read_workspace_context
from tests_v2.test_git_context import create_repository, git

HOOK = Path(__file__).resolve().parents[1] / "scripts" / "pulse_git_hook.sh"


def add_worktree(repository: Path, path: Path, branch: str = "wt") -> Path:
    git("worktree", "add", "-b", branch, str(path), cwd=repository)
    return path


# --- a. Attribution -------------------------------------------------------------


def test_linked_worktree_belongs_to_its_main_repository(tmp_path):
    main = create_repository(tmp_path / "Pulse")
    worktree = add_worktree(main, tmp_path / "Pulse-live")

    assert (worktree / ".git").is_file()
    assert main_repository_root(worktree) == main.resolve()
    assert repository_name(worktree) == "Pulse"
    # Le dépôt principal, lui, n'est rattaché à personne.
    assert main_repository_root(main) is None and repository_name(main) == "Pulse"


def test_a_relative_gitdir_line_is_resolved_from_the_worktree(tmp_path):
    main = create_repository(tmp_path / "Pulse")
    worktree = add_worktree(main, tmp_path / "Pulse-live")
    absolute = (worktree / ".git").read_text().split("gitdir:", 1)[1].strip()
    (worktree / ".git").write_text(f"gitdir: {os.path.relpath(absolute, worktree)}\n")

    assert main_repository_root(worktree) == main.resolve()


def test_whatever_is_not_a_linked_worktree_is_left_alone(tmp_path):
    # Sous-module : .git en fichier, mais son dossier Git n'a pas de commondir.
    submodule = tmp_path / "vendor"
    modules = tmp_path / "parent.git" / "modules" / "vendor"
    modules.mkdir(parents=True)
    submodule.mkdir()
    (submodule / ".git").write_text(f"gitdir: {modules}\n")
    assert main_repository_root(submodule) is None and repository_name(submodule) == "vendor"

    for content in ("", "pas une ligne gitdir\n", "gitdir: /nulle/part\n"):
        broken = tmp_path / f"broken-{len(content)}"
        broken.mkdir()
        (broken / ".git").write_text(content)
        assert main_repository_root(broken) is None

    assert main_repository_root(tmp_path / "absent") is None


def test_workspace_context_keeps_the_worktree_as_workspace(tmp_path):
    main = create_repository(tmp_path / "Pulse")
    worktree = add_worktree(main, tmp_path / "Pulse-live")
    (worktree / "core").mkdir()

    context = read_workspace_context(worktree / "core")

    assert context is not None
    assert context.project_name == "Pulse"
    assert context.workspace_root == str(worktree) and context.git_root == str(worktree)
    assert context.resolution_method == "git"


def test_display_resolver_names_a_worktree_after_its_main_repository(tmp_path):
    main = create_repository(tmp_path / "Pulse")
    worktree = add_worktree(main, tmp_path / "Pulse-live")

    context = resolve_project_context(str(worktree))

    assert context.project_name == "Pulse"
    assert context.project_root == str(worktree)
    # Worktree retiré : plus rien à lire, le nom du dossier revient.
    git("worktree", "remove", "--force", str(worktree), cwd=main)
    assert resolve_project_context(str(worktree)).project_name == "Pulse-live"


def test_git_hook_reports_the_main_repository_for_a_worktree_commit(tmp_path):
    main = create_repository(tmp_path / "Pulse")
    worktree = add_worktree(main, tmp_path / "Pulse-live")
    script = HOOK.read_text()
    start = script.index("# Un worktree lié appartient au dépôt principal")
    end = script.index("shortstat=")
    probe = (
        'set -u\nrepo_root="$(git rev-parse --show-toplevel)"\n'
        + script[start:end]
        + 'printf "%s|%s" "$repository" "$repo_root"\n'
    )

    def run(cwd: Path) -> str:
        return subprocess.run(
            ["bash", "-c", probe], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout

    assert run(worktree) == f"Pulse|{worktree.resolve()}"
    assert run(main) == f"Pulse|{main.resolve()}"


# --- b. Liste des worktrees ---------------------------------------------------------


def test_linked_worktrees_lists_existing_ones_and_never_the_main_repository(tmp_path):
    main = create_repository(tmp_path / "Pulse")
    first = add_worktree(main, tmp_path / "Pulse-exp", "exp")
    second = add_worktree(main, tmp_path / "Pulse-live", "live")

    assert sorted(linked_worktrees(main)) == sorted([first.resolve(), second.resolve()])
    # Depuis un worktree, la liste est la même : le dépôt principal en tête, écarté.
    assert main.resolve() not in linked_worktrees(first)


def test_a_worktree_whose_directory_vanished_is_not_listed(tmp_path):
    import shutil

    main = create_repository(tmp_path / "Pulse")
    gone = add_worktree(main, tmp_path / "Pulse-gone", "gone")
    kept = add_worktree(main, tmp_path / "Pulse-kept", "kept")
    shutil.rmtree(gone)  # supprimé à la main, sans `git worktree remove`

    assert linked_worktrees(main) == [kept.resolve()]


def test_linked_worktrees_of_something_that_is_not_a_repository_is_empty(tmp_path):
    assert linked_worktrees(tmp_path) == []
    assert linked_worktrees(tmp_path / "absent") == []
