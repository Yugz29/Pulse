from __future__ import annotations

from types import SimpleNamespace

from daemon.routes.runtime_ingestion import _normalize_terminal_event_payload
from daemon.core.terminal_event_normalizer import (
    coerce_int,
    parse_event_timestamp,
    split_command,
    terminal_action_category,
    terminal_category_summary,
)


def test_split_command_single_command():
    assert split_command("pytest tests/core")[0] == "pytest"
    assert split_command("pytest tests/core")[1] == ["pytest", "tests/core"]


def test_split_command_piped_command():
    assert split_command("cat file.txt | grep error") == (
        "cat",
        ["cat", "file.txt", "|", "grep", "error"],
    )


def test_split_command_empty_string():
    assert split_command("") == ("", [])


def test_coerce_int_valid_string():
    assert coerce_int("42") == 42


def test_coerce_int_invalid_string():
    assert coerce_int("nope") is None


def test_coerce_int_none():
    assert coerce_int(None) is None


def test_parse_event_timestamp_valid_iso_string():
    assert parse_event_timestamp("2026-05-06T10:11:12").isoformat() == "2026-05-06T10:11:12"


def test_parse_event_timestamp_invalid_string_returns_none():
    assert parse_event_timestamp("not-a-timestamp") is None


def test_parse_event_timestamp_missing_key():
    payload = {}
    assert parse_event_timestamp(payload.get("timestamp")) is None


def test_parse_event_timestamp_none_value():
    assert parse_event_timestamp(None) is None


def test_terminal_action_category_known_commands():
    read_write = SimpleNamespace(is_read_only=False)
    read_only = SimpleNamespace(is_read_only=True)

    assert terminal_action_category("pytest tests", read_write) == "testing"
    assert terminal_action_category("git status", read_only) == "vcs"
    assert terminal_action_category("make build", read_write) == "build"
    assert terminal_action_category("npm install", read_write) == "setup"
    assert terminal_action_category("ls -la", read_only) == "inspection"


def test_terminal_category_summary_known_categories():
    assert terminal_category_summary("testing") == "Exécution de tests"
    assert terminal_category_summary("build") == "Commande de build"
    assert terminal_category_summary("setup") == "Commande de setup"
    assert terminal_category_summary("inspection") == "Inspection terminal"


def test_unknown_terminal_command_uses_deterministic_category_summary_without_llm(monkeypatch):
    interpretation = SimpleNamespace(
        is_read_only=False,
        affects=["système"],
        translated="LLM-style translation should not be used",
        needs_llm=True,
    )
    monkeypatch.setattr(
        "daemon.routes.runtime_ingestion._terminal_interpreter",
        SimpleNamespace(interpret=lambda command: interpretation),
    )
    monkeypatch.setattr("daemon.routes.runtime_ingestion.find_workspace_root", lambda cwd: None)
    monkeypatch.setattr("daemon.core.git_context.read_git_context", lambda cwd: None)

    payload = _normalize_terminal_event_payload(
        "terminal_command_finished",
        {
            "command": "unknowncmd --flag",
            "cwd": "/Users/tester/workspace/acme",
            "exit_code": 0,
            "duration_ms": "42",
        },
    )

    assert payload["terminal_command"] == "unknowncmd --flag"
    assert payload["terminal_command_base"] == "unknowncmd"
    assert payload["terminal_action_category"] == "execution"
    assert payload["terminal_summary"] == "✓ Commande terminal"
    assert payload["terminal_duration_ms"] == 42
    assert payload["terminal_success"] is True
