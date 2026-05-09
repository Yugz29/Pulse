from __future__ import annotations

import re
import shlex
from typing import Any


_COUNT_KEYS = {
    "passed": "passed_count",
    "failed": "failed_count",
    "error": "error_count",
    "errors": "error_count",
    "skipped": "skipped_count",
}
_COUNT_RE = re.compile(r"\b(\d+)\s+(passed|failed|errors?|skipped)\b", re.IGNORECASE)


def parse_test_result(
    *,
    command: str | None,
    terminal_action_category: str | None,
    success: bool | None = None,
    exit_code: int | None = None,
    output_summary: str | None = None,
) -> dict[str, Any] | None:
    if terminal_action_category != "testing":
        return None

    command_text = str(command or "").strip()
    output_text = str(output_summary or "").strip()
    framework = _detect_framework(command_text, output_text)
    if framework is None:
        return None

    result: dict[str, Any] = {"framework": framework}
    if success is not None:
        result["success"] = bool(success)
    if exit_code is not None:
        result["exit_code"] = exit_code

    counts = _parse_counts(output_text)
    result.update(counts)

    target = _detect_target(command_text, framework)
    if target:
        result["target"] = target

    summary = _build_summary(counts)
    if summary:
        result["summary"] = summary

    if len(result) <= 1:
        return None
    return result


def _detect_framework(command: str, output_summary: str) -> str | None:
    lower_command = command.lower()
    lower_output = output_summary.lower()
    tokens = _tokens(command)
    if "pytest" in tokens or "pytest" in lower_command:
        return "pytest"
    if "vitest" in tokens or "vitest" in lower_command or "vitest" in lower_output:
        return "vitest"
    if tokens[:2] in (["npm", "test"], ["npm", "t"]):
        return "npm"
    if len(tokens) >= 2 and tokens[0] == "npm" and tokens[1] == "run" and "test" in tokens[2:3]:
        return "npm"
    return None


def _parse_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw_count, raw_name in _COUNT_RE.findall(text or ""):
        key = _COUNT_KEYS[raw_name.lower()]
        counts[key] = counts.get(key, 0) + int(raw_count)
    return counts


def _build_summary(counts: dict[str, int]) -> str | None:
    labels = [
        ("failed_count", "failed"),
        ("error_count", "error"),
        ("skipped_count", "skipped"),
        ("passed_count", "passed"),
    ]
    parts = []
    for key, label in labels:
        count = counts.get(key)
        if count is not None:
            parts.append(f"{count} {label}")
    return ", ".join(parts) if parts else None


def _detect_target(command: str, framework: str) -> str | None:
    tokens = _tokens(command)
    if not tokens:
        return None
    if framework == "pytest":
        pytest_index = _pytest_index(tokens)
        if pytest_index is None:
            return None
        return _first_test_target(tokens[pytest_index + 1 :])
    if framework in {"npm", "vitest"}:
        marker_index = _first_index(tokens, {"--"})
        if marker_index is not None:
            return _first_test_target(tokens[marker_index + 1 :])
    return None


def _pytest_index(tokens: list[str]) -> int | None:
    for index, token in enumerate(tokens):
        if token == "pytest":
            return index
        if token == "-m" and index + 1 < len(tokens) and tokens[index + 1] == "pytest":
            return index + 1
    return None


def _first_test_target(tokens: list[str]) -> str | None:
    skip_next = False
    options_with_values = {"-k", "-m", "--maxfail", "--rootdir", "--confcutdir"}
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token in options_with_values:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        if token.startswith(("tests/", "test/", "spec/")) or "::" in token:
            return token
    return None


def _first_index(tokens: list[str], wanted: set[str]) -> int | None:
    for index, token in enumerate(tokens):
        if token in wanted:
            return index
    return None


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command or "")
    except ValueError:
        return str(command or "").split()
