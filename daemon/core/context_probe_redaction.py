"""Redaction helpers for future sensitive context probes.

This module centralizes how raw probe values are transformed before anything
can be shown, stored, audited, or passed to another layer.

It is deliberately conservative:
- it never persists raw values;
- it masks obvious secrets;
- it masks local home paths;
- it masks emails and URLs;
- it truncates long values;
- it returns metadata about what was redacted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ContextProbeRedactionFlag(str, Enum):
    """Redaction markers returned with a redacted value."""

    EMPTY = "empty"
    TRUNCATED = "truncated"
    EMAIL = "email"
    URL = "url"
    HOME_PATH = "home_path"
    TOKEN = "token"
    SSH_KEY = "ssh_key"
    ENV_SECRET = "env_secret"


@dataclass(frozen=True)
class ContextProbeRedactionResult:
    """Safe representation of a raw probe value."""

    redacted_value: str
    original_length: int
    redacted_length: int
    flags: tuple[ContextProbeRedactionFlag, ...]

    @property
    def was_redacted(self) -> bool:
        return bool(self.flags)

    def to_dict(self) -> dict[str, object]:
        return {
            "redacted_value": self.redacted_value,
            "original_length": self.original_length,
            "redacted_length": self.redacted_length,
            "flags": [flag.value for flag in self.flags],
            "was_redacted": self.was_redacted,
        }


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"\bhttps?://[^\s<>'\"]+", re.IGNORECASE)
_HOME_PATH_RE = re.compile(r"/Users/[^/\s]+")
_SSH_KEY_RE = re.compile(
    r"-----BEGIN (?:(?:OPENSSH|RSA|DSA|EC) )?PRIVATE KEY-----.*?-----END (?:(?:OPENSSH|RSA|DSA|EC) )?PRIVATE KEY-----",
    re.DOTALL,
)
_ENV_SECRET_RE = re.compile(
    r"\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY|PRIVATE_KEY)[A-Z0-9_]*)\s*=\s*([^\s]+)",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{16,}|[A-Za-z0-9_-]{32,})\b"
)


def redact_context_probe_value(
    value: object,
    *,
    max_chars: int = 500,
) -> ContextProbeRedactionResult:
    """Return a safe redacted representation of a raw probe value."""
    raw = "" if value is None else str(value)
    flags: list[ContextProbeRedactionFlag] = []

    if raw == "":
        flags.append(ContextProbeRedactionFlag.EMPTY)
        return _result("", original=raw, flags=flags)

    redacted = raw

    redacted, changed = _sub_with_flag(
        redacted,
        _SSH_KEY_RE,
        "[REDACTED_SSH_PRIVATE_KEY]",
    )
    if changed:
        flags.append(ContextProbeRedactionFlag.SSH_KEY)

    redacted, changed = _sub_with_flag(
        redacted,
        _ENV_SECRET_RE,
        r"\1=[REDACTED_SECRET]",
    )
    if changed:
        flags.append(ContextProbeRedactionFlag.ENV_SECRET)

    redacted, changed = _sub_with_flag(
        redacted,
        _EMAIL_RE,
        "[REDACTED_EMAIL]",
    )
    if changed:
        flags.append(ContextProbeRedactionFlag.EMAIL)

    redacted, changed = _sub_with_flag(
        redacted,
        _URL_RE,
        "[REDACTED_URL]",
    )
    if changed:
        flags.append(ContextProbeRedactionFlag.URL)

    redacted, changed = _sub_with_flag(
        redacted,
        _HOME_PATH_RE,
        "/Users/[REDACTED_USER]",
    )
    if changed:
        flags.append(ContextProbeRedactionFlag.HOME_PATH)

    redacted, changed = _sub_with_flag(
        redacted,
        _TOKEN_RE,
        "[REDACTED_TOKEN]",
    )
    if changed:
        flags.append(ContextProbeRedactionFlag.TOKEN)

    redacted = redacted.strip()

    if max_chars >= 0 and len(redacted) > max_chars:
        redacted = redacted[:max_chars].rstrip() + "…"
        flags.append(ContextProbeRedactionFlag.TRUNCATED)

    return _result(redacted, original=raw, flags=_dedupe_flags(flags))


def redact_context_probe_values(
    values: Iterable[object],
    *,
    max_chars: int = 500,
) -> list[ContextProbeRedactionResult]:
    """Redact several raw values using the same policy."""
    return [
        redact_context_probe_value(value, max_chars=max_chars)
        for value in values
    ]


def _sub_with_flag(text: str, pattern: re.Pattern[str], replacement: str) -> tuple[str, bool]:
    updated, count = pattern.subn(replacement, text)
    return updated, count > 0


def _dedupe_flags(flags: Iterable[ContextProbeRedactionFlag]) -> tuple[ContextProbeRedactionFlag, ...]:
    seen: set[ContextProbeRedactionFlag] = set()
    ordered: list[ContextProbeRedactionFlag] = []
    for flag in flags:
        if flag in seen:
            continue
        seen.add(flag)
        ordered.append(flag)
    return tuple(ordered)


def _result(
    redacted: str,
    *,
    original: str,
    flags: Iterable[ContextProbeRedactionFlag],
) -> ContextProbeRedactionResult:
    return ContextProbeRedactionResult(
        redacted_value=redacted,
        original_length=len(original),
        redacted_length=len(redacted),
        flags=tuple(flags),
    )