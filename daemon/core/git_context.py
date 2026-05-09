from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

GIT_CONTEXT_TIMEOUT_SEC = 0.5


def find_git_root(path: str | Path) -> Path | None:
    try:
        candidate = Path(path).expanduser()
        start = candidate if candidate.is_dir() else candidate.parent
        result = _run_git(["git", "rev-parse", "--show-toplevel"], cwd=start)
        if result is None:
            return None
        root = result.strip()
        return Path(root) if root else None
    except Exception:
        return None


def read_git_context(path: str | Path) -> dict[str, Any] | None:
    root = find_git_root(path)
    if root is None:
        return None

    branch = _read_branch(root)
    head_sha = _run_git(["git", "rev-parse", "--short", "HEAD"], cwd=root)
    status = _run_git(["git", "status", "--porcelain"], cwd=root)
    if branch is None and not head_sha and status is None:
        return None

    staged_count, unstaged_count, untracked_count = _parse_porcelain_counts(status or "")
    context: dict[str, Any] = {
        "repo_root": str(root),
        "repo_name": root.name,
        "is_dirty": bool(staged_count or unstaged_count or untracked_count),
        "staged_count": staged_count,
        "unstaged_count": unstaged_count,
        "untracked_count": untracked_count,
    }
    if branch:
        context["branch"] = branch
    if head_sha:
        context["head_sha"] = head_sha.strip()
    return context


def _read_branch(root: Path) -> str | None:
    branch = _run_git(["git", "branch", "--show-current"], cwd=root)
    if branch and branch.strip():
        return branch.strip()
    detached = _run_git(["git", "rev-parse", "--short", "HEAD"], cwd=root)
    if detached and detached.strip():
        return f"detached:{detached.strip()}"
    return None


def _parse_porcelain_counts(output: str) -> tuple[int, int, int]:
    staged_count = 0
    unstaged_count = 0
    untracked_count = 0
    for line in output.splitlines():
        if not line:
            continue
        status = line[:2]
        if status == "??":
            untracked_count += 1
            continue
        if status[0] != " ":
            staged_count += 1
        if len(status) > 1 and status[1] != " ":
            unstaged_count += 1
    return staged_count, unstaged_count, untracked_count


def _run_git(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GIT_CONTEXT_TIMEOUT_SEC,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
