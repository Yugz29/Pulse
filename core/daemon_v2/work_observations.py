"""Versioned factual projection of an already reconstructed work session.

No I/O, reconstruction, interpretation, or model dependency. File notifications
are grouped per path between command/commit barriers. Every transition and its
interval survive; intervals may overlap, they are not an invented total order.
Provenance is a sibling of the model-visible observations, never their content.
"""
from __future__ import annotations

import shlex
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .file_policy import should_ignore
from .analysis.terminal import is_test_command, useful_command_lines
from .analysis.timeline import display_file_path

OBSERVATION_VERSION = 1


def _utc(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()


def _simple_command(command: str) -> bool:
    # An overall shell exit code is not the result of each subcommand. Even
    # quoted operators are conservatively treated as compound (false unknown
    # is preferable to a false success). No shell evaluation takes place.
    return not any(c in command for c in "\n;&|<>`$()")


def project_work_observations(activities: list[dict[str, Any]]) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    sources: dict[str, list[str]] = {}
    files: dict[str, dict[str, Any]] = {}
    apps: dict[str, dict[str, Any]] = {}
    last_commands: dict[tuple[str, str | None], str] = {}
    last_files: dict[str, str] = {}
    last_git: dict[str, dict[str, str]] = {}
    excluded: dict[str, int] = {}
    origin = min((_utc(a["occurred_at"]) for a in activities), default=None)

    def offset(value: str | None) -> float | None:
        if value is None or origin is None:
            return None
        return round((datetime.fromisoformat(_utc(value)) - datetime.fromisoformat(origin)).total_seconds(), 6)

    def add(kind: str, at: float, event_id: str, **fields: Any) -> dict[str, Any]:
        fact = {"ref": f"o{len(facts) + 1}", "kind": kind, "at": at, **fields}
        facts.append(fact)
        sources[fact["ref"]] = [event_id]
        return fact

    for activity in sorted(activities, key=lambda a: (_utc(a["occurred_at"]), a["id"])):
        kind, details = activity["type"], activity.get("details", {})
        at, event_id = offset(activity["occurred_at"]), activity["event_id"]
        if kind == "file_changed":
            path = details.get("path")
            change = details.get("event", details.get("change"))
            if not path or change not in {"created", "modified", "deleted"}:
                excluded[kind] = excluded.get(kind, 0) + 1
                continue
            root = details.get("workspace")
            if isinstance(root, dict):
                root = root.get("workspace_root")
            # A historical inconsistent workspace is unknown attribution,
            # not proof that the observed file is noise.
            if root and not Path(path).is_relative_to(root):
                root = None
            if root and should_ignore(Path(path), Path(root)):
                excluded["file_noise"] = excluded.get("file_noise", 0) + 1
                continue
            # Absolute identity prevents equal relative names in two roots
            # from merging. Display paths retain their workspace below.
            fact = files.get(path)
            if fact is None:
                fact = add("file", at, event_id, path=display_file_path(path, root),
                           workspace=root, changes=[])
                files[path] = fact
            else:
                sources[fact["ref"]].append(event_id)
            changes = fact["changes"]
            if changes and changes[-1]["event"] == change:
                changes[-1]["last_at"] = at
                changes[-1]["count"] += 1
            else:
                changes.append({"event": change, "first_at": at, "last_at": at, "count": 1})
            last_files[path] = fact["ref"]
        elif kind == "app_activated":
            name = details.get("app")
            if not name:
                continue
            if name not in apps:
                apps[name] = {"ref": f"app:{len(apps) + 1}", "name": name,
                              "first_at": at, "last_at": at, "activations": 0}
                sources[apps[name]["ref"]] = []
            apps[name]["activations"] += 1
            apps[name]["last_at"] = at
            sources[apps[name]["ref"]].append(event_id)
        elif kind == "terminal_finished":
            files.clear()  # Even an omitted inspection command is a barrier.
            command = details.get("command", "")
            lines = useful_command_lines(command)
            if not lines:
                excluded[kind] = excluded.get(kind, 0) + 1
                continue
            # Keep the whole command when useful; never attribute its exit to
            # separately filtered lines. Pasted prompt text remains excluded.
            simple = _simple_command(command)
            fact = add("command", at, event_id, command=command,
                       cwd=details.get("cwd"), started_at=offset(details.get("started_at")),
                       exit_code=details.get("exit_code"), exit_scope="whole_command",
                       test_command=simple and is_test_command(command))
            if simple:
                try:
                    parts = shlex.split(command)
                except ValueError:
                    parts = []
                if len(parts) >= 2 and parts[0] == "git":
                    fact["git_action"] = parts[1]
            last_commands[(command, details.get("cwd"))] = fact["ref"]
            git = details.get("git")
            if isinstance(git, dict) and git.get("git_root"):
                snapshot = {key: git[key] for key in ("git_root", "branch", "dirty") if key in git}
                fact["git_snapshot"] = snapshot
                state = last_git.setdefault(git["git_root"], {})
                for key in ("branch", "dirty"):
                    if key in snapshot:
                        state[key] = fact["ref"]
        elif kind == "git_commit":
            files.clear()
            fact = add("commit", at, event_id, hash=details.get("commit_hash"),
                       message=details.get("message"), workspace=details.get("git_root"),
                       branch=details.get("branch"))
            if details.get("git_root"):
                state = last_git.setdefault(details["git_root"], {})
                state["commit"] = fact["ref"]
                if details.get("branch"):
                    state["branch"] = fact["ref"]
                # A commit is never evidence for a clean worktree.
        elif kind in {"screen_locked", "screen_unlocked", "system_sleep", "system_wake"}:
            files.clear()
            add(kind, at, event_id)
        else:
            excluded[kind] = excluded.get(kind, 0) + 1
    return {
        "version": OBSERVATION_VERSION,
        "time_origin": origin,
        "time_unit": "seconds",
        "timeline": facts,
        "applications": list(apps.values()),
        "last_observed": {
            "commands": list(last_commands.values()),
            "files": list(last_files.values()),
            "git": last_git,
        },
        "coverage": {"omitted_events": excluded, "command_output": "not_collected",
                     "commit_files": "not_collected", "remote_push_state": "not_collected"},
        "sources": sources,
    }
