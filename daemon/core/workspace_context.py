from __future__ import annotations

from pathlib import Path
from typing import Optional


_PROJECT_MARKERS = ("Projets", "Projects", "Developer", "workspace", "src")


def find_workspace_root(file_path: Optional[str]) -> Optional[Path]:
    if not file_path:
        return None

    path = Path(file_path)
    start = path if path.is_dir() else path.parent

    for candidate in [start, *start.parents]:
        git_entry = candidate / ".git"
        if git_entry.is_dir() or git_entry.is_file():
            return candidate

    marker_root = _marker_workspace_root(file_path)
    return Path(marker_root) if marker_root else None


def extract_project_name(file_path: Optional[str]) -> Optional[str]:
    root = find_workspace_root(file_path)
    if root is None:
        return None
    name = root.name.strip()
    return name or None


def _marker_workspace_root(file_path: str) -> Optional[str]:
    parts = file_path.split("/")
    for marker in _PROJECT_MARKERS:
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                return "/" + "/".join(parts[1:idx + 2])
    return None
