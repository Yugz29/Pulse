"""Terminal event payload normalization. No Flask dependency."""

from __future__ import annotations

import shlex
from datetime import datetime
from typing import Any


TERMINAL_TEST_COMMANDS: frozenset[str] = frozenset({
    "pytest", "tox", "nosetests", "nose2", "unittest",
})
TERMINAL_BUILD_COMMANDS: frozenset[str] = frozenset({
    "xcodebuild", "make", "cmake", "ninja",
})
TERMINAL_SETUP_COMMANDS: frozenset[str] = frozenset({
    "brew", "pip", "pip3", "npm", "pnpm", "yarn", "uv", "poetry", "cargo",
})


def parse_event_timestamp(raw: Any) -> datetime | None:
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def terminal_action_category(command: str, interpretation) -> str:
    base_cmd, tokens = split_command(command)
    subcommands = set(tokens[1:])

    if base_cmd == "git":
        return "vcs"

    if base_cmd in TERMINAL_TEST_COMMANDS or "test" in subcommands:
        return "testing"

    if base_cmd in TERMINAL_BUILD_COMMANDS:
        return "build"

    if base_cmd in TERMINAL_SETUP_COMMANDS:
        if subcommands & {"install", "add", "init", "bootstrap", "update"}:
            return "setup"
        if subcommands & {"build", "compile", "run"}:
            return "build"

    if interpretation.is_read_only:
        return "inspection"

    return "execution"


def terminal_category_summary(category: str) -> str:
    return {
        "inspection": "Inspection terminal",
        "testing": "Exécution de tests",
        "vcs": "Commande de contrôle de version",
        "build": "Commande de build",
        "setup": "Commande de setup",
        "execution": "Commande terminal",
    }.get(category, "Commande terminal")


def split_command(command: str) -> tuple[str, list[str]]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    return (tokens[0] if tokens else "", tokens)


def coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
