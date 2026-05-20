from __future__ import annotations

import os
from collections.abc import Mapping


PULSE_MODE_ENV = "PULSE_MODE"
PULSE_MODE_CORE = "core"
PULSE_MODE_LAB = "lab"
PULSE_MODE_DEV = "dev"
VALID_PULSE_MODES = frozenset({
    PULSE_MODE_CORE,
    PULSE_MODE_LAB,
    PULSE_MODE_DEV,
})


def get_pulse_mode(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    raw = str(env.get(PULSE_MODE_ENV, "") or "").strip().lower()
    if raw in VALID_PULSE_MODES:
        return raw
    return PULSE_MODE_CORE


def is_lab_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return get_pulse_mode(environ) in {PULSE_MODE_LAB, PULSE_MODE_DEV}
