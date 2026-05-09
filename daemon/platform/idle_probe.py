from __future__ import annotations

import sys


def get_user_idle_seconds() -> int | None:
    """Return seconds since last user input, or None when unsupported."""
    if sys.platform != "darwin":
        return None
    try:
        from daemon.platform.macos_iokit_idle import get_macos_user_idle_seconds
    except Exception:
        return None
    try:
        return get_macos_user_idle_seconds()
    except Exception:
        return None

