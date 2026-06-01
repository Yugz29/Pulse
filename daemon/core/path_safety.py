from __future__ import annotations

from pathlib import Path


_DEFAULT_OBSERVED_BASES = (
    Path.home(),
    Path("/Users"),
    Path("/home"),
    Path("/tmp"),
    Path("/private/tmp"),
    Path("/var/folders"),
    Path("/private/var/folders"),
    Path("/Volumes"),
    Path("/workspace"),
    Path("/workspaces"),
    Path("/repo"),
)


def resolve_observed_path(raw_path: str | Path | None) -> Path | None:
    if raw_path is None:
        return None
    try:
        raw_text = str(raw_path)
        if not raw_text or "\x00" in raw_text:
            return None

        expanded_text = _expand_user_text(raw_text)
        raw = _safe_absolute_path_from_text(expanded_text)
        if raw is None:
            return None

        for base in _DEFAULT_OBSERVED_BASES:
            resolved = _resolve_under_base(base, raw)
            if resolved is not None:
                return resolved
    except (OSError, RuntimeError, ValueError):
        return None
    return None


def _expand_user_text(raw_text: str) -> str:
    if raw_text == "~":
        return str(Path.home())
    if raw_text.startswith("~/"):
        return f"{Path.home()}{raw_text[1:]}"
    return raw_text


def _safe_absolute_path_from_text(raw_text: str) -> Path | None:
    if not raw_text.startswith("/"):
        return None
    parts = raw_text.split("/")
    if parts[0] != "":
        return None
    safe_parts: list[str] = []
    for part in parts[1:]:
        if part in {"", ".", ".."}:
            return None
        safe_parts.append(part)
    if not safe_parts:
        return None
    return Path("/", *safe_parts)


def _resolve_under_base(base: Path, raw_path: Path) -> Path | None:
    expanded_base = base.expanduser()
    resolved_base = base.expanduser().resolve(strict=False)
    try:
        relative = raw_path.relative_to(expanded_base)
    except ValueError:
        return None

    lexical_candidate = expanded_base / relative
    resolved_candidate = lexical_candidate.resolve(strict=False)
    if resolved_candidate == resolved_base or resolved_candidate.is_relative_to(resolved_base):
        return lexical_candidate
    return None
