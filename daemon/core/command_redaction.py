from __future__ import annotations

import re


_MAX_COMMAND_CHARS = 500

_AUTH_BEARER_RE = re.compile(
    r"(Authorization\s*:\s*Bearer\s+)([^\s'\";]+)",
    re.IGNORECASE,
)
_ENV_SECRET_RE = re.compile(
    r"\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s]+)",
    re.IGNORECASE,
)
_FLAG_SECRET_RE = re.compile(
    r"(--(?:token|password))(?:\s+|=)(\"[^\"]*\"|'[^']*'|[^\s]+)",
    re.IGNORECASE,
)
_DB_URL_RE = re.compile(
    r"\b((?:postgres|mysql)://[^:\s/@]+:)([^@\s]+)(@)",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{16,})\b"
)


def redact_sensitive_command(command: object, *, max_chars: int = _MAX_COMMAND_CHARS) -> str:
    raw = "" if command is None else str(command)
    redacted = raw
    redacted = _AUTH_BEARER_RE.sub(r"\1[REDACTED_TOKEN]", redacted)
    redacted = _ENV_SECRET_RE.sub(r"\1=[REDACTED_SECRET]", redacted)
    redacted = _FLAG_SECRET_RE.sub(r"\1 [REDACTED_SECRET]", redacted)
    redacted = _DB_URL_RE.sub(r"\1[REDACTED_PASSWORD]\3", redacted)
    redacted = _TOKEN_RE.sub("[REDACTED_TOKEN]", redacted)
    redacted = redacted.strip()

    if max_chars >= 0 and len(redacted) > max_chars:
        return redacted[:max_chars].rstrip() + "…"
    return redacted
