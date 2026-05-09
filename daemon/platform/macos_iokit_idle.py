from __future__ import annotations

import re
import subprocess
import sys


_HID_IDLE_RE = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')


def get_macos_user_idle_seconds() -> int | None:
    """Read IOHIDSystem HIDIdleTime on macOS and return whole seconds."""
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    match = _HID_IDLE_RE.search(result.stdout or "")
    if match is None:
        return None
    try:
        idle_ns = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return max(int(idle_ns / 1_000_000_000), 0)

