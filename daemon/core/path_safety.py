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

        raw = Path(raw_text).expanduser()
        if not raw.is_absolute():
            return None

        for base in _DEFAULT_OBSERVED_BASES:
            resolved = _resolve_under_base(base, raw)
            if resolved is not None:
                return resolved
    except (OSError, RuntimeError, ValueError):
        return None
    return None


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
