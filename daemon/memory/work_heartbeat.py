

"""Work heartbeat classification helpers.

A work window should be built from active evidence of work, not from wall-clock
session duration. This module classifies raw events into small, conservative
heartbeat categories that memory/session code can later use for clustering.

Contract:
- strong heartbeats can open and extend a work window.
- weak heartbeats can only support an already active/recent strong window.
- none heartbeats must never extend work time.

User presence is intentionally not a heartbeat by itself. Moving the mouse or
pressing a key during a video should not create work time; presence can only be
used later as corroboration by the clustering layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Literal


HeartbeatStrength = Literal["strong", "weak", "none"]


STRONG_FILE_EVENT_TYPES = {
    "file_created",
    "file_modified",
    "file_renamed",
    "file_deleted",
}

STRONG_TERMINAL_CATEGORIES = {
    "testing",
    "test",
    "debug",
    "debugging",
    "build",
    "vcs",
    "git",
}

READ_ONLY_GIT_COMMANDS = {
    "status",
    "log",
    "show",
    "branch",
    "diff",
    "blame",
    "remote",
}

MUTATING_GIT_COMMANDS = {
    "add",
    "commit",
    "merge",
    "rebase",
    "checkout",
    "switch",
    "push",
    "pull",
    "reset",
    "restore",
    "stash",
    "tag",
}

WORK_APPS = {
    "Code",
    "Visual Studio Code",
    "Xcode",
    "Cursor",
    "Terminal",
    "iTerm2",
}

AI_APPS = {
    "ChatGPT",
    "Claude",
    "Claude Desktop",
    "Codex",
}

NON_WORK_TITLE_HINTS = {
    "youtube",
    "netflix",
    "prime video",
    "disney+",
    "twitch",
    "spotify",
}


@dataclass(frozen=True)
class WorkHeartbeat:
    strength: HeartbeatStrength
    reason: str

    @property
    def is_work(self) -> bool:
        return self.strength in {"strong", "weak"}


NONE_HEARTBEAT = WorkHeartbeat(strength="none", reason="no_work_evidence")


def classify_work_heartbeat(event: Mapping[str, Any]) -> WorkHeartbeat:
    """Classify a raw event as work evidence.

    Strong heartbeats can open or extend a work window. Weak heartbeats should
    only support an already active work window or another recent strong signal.
    None heartbeats should not extend work time.
    """
    event_type = str(event.get("type") or "")
    payload = _payload(event)

    if event_type in STRONG_FILE_EVENT_TYPES:
        if _is_meaningful_file_payload(payload):
            return WorkHeartbeat("strong", "meaningful_file_event")
        return NONE_HEARTBEAT

    if event_type == "terminal_command_finished":
        return _classify_terminal_finished(payload)

    if event_type in {"mcp_command_received", "mcp_decision"}:
        return WorkHeartbeat("strong", "mcp_workflow_event")

    if event_type in {"app_activated", "window_title_poll"}:
        return _classify_app_or_window(payload)

    if event_type == "user_presence":
        return NONE_HEARTBEAT

    return NONE_HEARTBEAT


def is_work_heartbeat(event: Mapping[str, Any]) -> bool:
    return classify_work_heartbeat(event).is_work


def work_heartbeat_strength(event: Mapping[str, Any]) -> HeartbeatStrength:
    return classify_work_heartbeat(event).strength


def _classify_terminal_finished(payload: Mapping[str, Any]) -> WorkHeartbeat:
    project = _text(payload.get("terminal_project"))
    cwd = _text(payload.get("terminal_cwd"))
    command = _text(payload.get("terminal_command"))
    base = _text(payload.get("terminal_command_base")).lower()
    category = _text(payload.get("terminal_action_category")).lower()

    if base == "git" or command.startswith("git "):
        return _classify_git_command(command)
    if category in STRONG_TERMINAL_CATEGORIES:
        return WorkHeartbeat("strong", f"terminal_{category}")
    if project:
        return WorkHeartbeat("strong", "terminal_project_command")
    if cwd and _looks_like_project_path(cwd):
        return WorkHeartbeat("weak", "terminal_project_cwd")
    return WorkHeartbeat("weak", "terminal_command")


def _classify_git_command(command: str) -> WorkHeartbeat:
    subcommand = _git_subcommand(command)
    if subcommand in MUTATING_GIT_COMMANDS:
        return WorkHeartbeat("strong", f"terminal_git_{subcommand}")
    if subcommand in READ_ONLY_GIT_COMMANDS:
        return WorkHeartbeat("weak", f"terminal_git_{subcommand}")
    return WorkHeartbeat("weak", "terminal_git")


def _git_subcommand(command: str) -> str:
    parts = command.strip().split()
    if not parts or parts[0] != "git" or len(parts) < 2:
        return ""
    for part in parts[1:]:
        if part.startswith("-"):
            continue
        return part.lower()
    return ""


def _classify_app_or_window(payload: Mapping[str, Any]) -> WorkHeartbeat:
    app_name = _text(payload.get("app_name"))
    title = _text(payload.get("window_title") or payload.get("title"))
    title_lower = title.lower()

    if title_lower and any(hint in title_lower for hint in NON_WORK_TITLE_HINTS):
        return NONE_HEARTBEAT

    if app_name in WORK_APPS:
        return WorkHeartbeat("weak", "work_app_active")
    if app_name in AI_APPS:
        return WorkHeartbeat("weak", "ai_app_active")
    if _looks_like_code_title(title):
        return WorkHeartbeat("weak", "code_like_window_title")
    return NONE_HEARTBEAT




def _is_meaningful_file_payload(payload: Mapping[str, Any]) -> bool:
    if payload.get("is_meaningful") is False:
        return False
    if payload.get("_noise_policy") == "technical_noise":
        return False
    path = _text(payload.get("path") or payload.get("file_path"))
    if not path:
        return True
    lowered = path.lower()
    noisy_fragments = {
        "/.git/",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "models_cache.json",
        "model-recommendations.json",
    }
    return not any(fragment in lowered for fragment in noisy_fragments)


def _looks_like_project_path(path: str) -> bool:
    lowered = path.lower()
    return "/projets/" in lowered or "/projects/" in lowered or "/src/" in lowered


def _looks_like_code_title(title: str) -> bool:
    lowered = title.lower()
    code_suffixes = {
        ".py",
        ".swift",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".json",
        ".md",
        ".html",
        ".css",
    }
    return any(suffix in lowered for suffix in code_suffixes)


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()

