from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace
from unittest.mock import patch

from daemon.core.git_context import find_git_root, read_git_context


def _result(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode)


def test_read_git_context_repo_normal_branch_head_and_status():
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[-1] == "--show-toplevel":
            return _result("/repo/Pulse\n")
        if args[-1] == "--show-current":
            return _result("main\n")
        if args[-2:] == ["--short", "HEAD"]:
            return _result("abc1234\n")
        if args[-1] == "--porcelain":
            return _result("M  staged.py\n M unstaged.py\n?? new.py\n")
        raise AssertionError(args)

    with patch("daemon.core.git_context.Path.is_dir", return_value=True), \
         patch("daemon.core.git_context.subprocess.run", side_effect=fake_run):
        context = read_git_context("/repo/Pulse")

    assert context == {
        "repo_root": "/repo/Pulse",
        "repo_name": "Pulse",
        "branch": "main",
        "head_sha": "abc1234",
        "is_dirty": True,
        "staged_count": 1,
        "unstaged_count": 1,
        "untracked_count": 1,
    }
    assert ["git", "status", "--porcelain"] in calls


def test_read_git_context_detached_head_fallback():
    def fake_run(args, **kwargs):
        if args[-1] == "--show-toplevel":
            return _result("/repo/Pulse\n")
        if args[-1] == "--show-current":
            return _result("")
        if args[-2:] == ["--short", "HEAD"]:
            return _result("def5678\n")
        if args[-1] == "--porcelain":
            return _result("")
        raise AssertionError(args)

    with patch("daemon.core.git_context.Path.is_dir", return_value=True), \
         patch("daemon.core.git_context.subprocess.run", side_effect=fake_run):
        context = read_git_context("/repo/Pulse")

    assert context["branch"] == "detached:def5678"
    assert context["head_sha"] == "def5678"
    assert context["is_dirty"] is False


def test_git_context_returns_none_when_git_unavailable():
    with patch("daemon.core.git_context.Path.is_dir", return_value=True), \
         patch("daemon.core.git_context.subprocess.run", return_value=_result(returncode=128)):
        assert find_git_root("/tmp/not-git") is None
        assert read_git_context("/tmp/not-git") is None


def test_git_context_returns_none_on_timeout():
    with patch("daemon.core.git_context.Path.is_dir", return_value=True), \
         patch("daemon.core.git_context.subprocess.run", side_effect=TimeoutExpired("git", 0.5)):
        assert read_git_context("/tmp/slow") is None


def test_status_porcelain_counts_are_aggregate_only():
    def fake_run(args, **kwargs):
        if args[-1] == "--show-toplevel":
            return _result("/repo/Pulse\n")
        if args[-1] == "--show-current":
            return _result("main\n")
        if args[-2:] == ["--short", "HEAD"]:
            return _result("abc1234\n")
        if args[-1] == "--porcelain":
            return _result("A  file_a.py\nMM file_b.py\n D file_c.py\n?? file_d.py\n")
        raise AssertionError(args)

    with patch("daemon.core.git_context.Path.is_dir", return_value=True), \
         patch("daemon.core.git_context.subprocess.run", side_effect=fake_run):
        context = read_git_context(Path("/repo/Pulse"))

    assert context["staged_count"] == 2
    assert context["unstaged_count"] == 2
    assert context["untracked_count"] == 1
    assert "file_a.py" not in str(context)
