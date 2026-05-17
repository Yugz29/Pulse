from __future__ import annotations

from pathlib import Path
from typing import Optional


_STANDARD_PROJECT_CHILD_DIRS = {
    "src",
    "tests",
    "test",
    "docs",
    "doc",
    "config",
    "app",
    "lib",
    "packages",
}

_TECHNICAL_CWD_DIRS = {
    ".venv",
    "bin",
    "build",
    "dist",
    "node_modules",
    "scripts",
    "temp",
    "tmp",
    "tools",
    "venv",
    * _STANDARD_PROJECT_CHILD_DIRS,
}

_PROJECT_ROOT_FILENAMES = {
    "package.json",
    "pyproject.toml",
    "cargo.toml",
    "go.mod",
    "package.swift",
    "makefile",
    "dockerfile",
}

_IMPLAUSIBLE_PROJECT_NAMES = {
    "",
    ".",
    "/",
    "tmp",
    "temp",
    "var",
    "private",
    "home",
    "users",
    * _STANDARD_PROJECT_CHILD_DIRS,
}


def find_workspace_root(file_path: Optional[str]) -> Optional[Path]:
    if not file_path:
        return None

    path = Path(file_path)
    if not path.is_absolute():
        return None

    start = path if path.is_dir() else path.parent

    for candidate in [start, *start.parents]:
        git_entry = candidate / ".git"
        if git_entry.is_dir() or git_entry.is_file():
            return candidate

    return (
        _standard_child_workspace_root(path)
        or _root_file_workspace_root(path)
        or _directory_like_workspace_root(path)
    )


def extract_project_name(file_path: Optional[str]) -> Optional[str]:
    root = find_workspace_root(file_path)
    if root is None:
        return None
    name = root.name.strip()
    if not _is_plausible_project_root(root):
        return None
    original_path = Path(file_path) if file_path else None
    if original_path and original_path.suffix and name == original_path.name:
        return None
    return name or None


def _standard_child_workspace_root(path: Path) -> Optional[Path]:
    parts = path.parts
    for index, part in enumerate(parts):
        if part.lower() not in _STANDARD_PROJECT_CHILD_DIRS:
            continue
        if index == 0:
            continue
        parent = Path(*parts[:index])
        if _is_plausible_project_root(parent):
            return parent
    return None


def _root_file_workspace_root(path: Path) -> Optional[Path]:
    if path.name.lower() not in _PROJECT_ROOT_FILENAMES:
        return None
    parent = path.parent
    return parent if _is_plausible_project_root(parent) else None


def _directory_like_workspace_root(path: Path) -> Optional[Path]:
    if path.suffix:
        return None
    if len(path.parts) < 3:
        return None
    if path.name.lower() in _TECHNICAL_CWD_DIRS:
        parent = path.parent
        return parent if _is_plausible_project_root(parent) else None
    return path if _is_plausible_project_root(path) else None


def _is_plausible_project_root(path: Path) -> bool:
    name = path.name.strip()
    if not name:
        return False
    if "." in name:
        return False
    lowered = name.lower()
    if lowered.startswith("tmp"):
        return False
    return lowered not in _IMPLAUSIBLE_PROJECT_NAMES
