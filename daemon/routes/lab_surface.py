from __future__ import annotations

from flask import jsonify

from daemon.runtime_mode import get_pulse_mode, is_lab_enabled


def lab_surface_metadata() -> dict[str, object]:
    mode = get_pulse_mode()
    return {
        "pulse_mode": mode,
        "experimental": True,
        "lab_only": True,
        "disabled_in_core": not is_lab_enabled(),
    }


def lab_surface_disabled_response(surface: str):
    return jsonify({
        "ok": False,
        "error": "lab_surface_disabled",
        "surface": surface,
        **lab_surface_metadata(),
    }), 403
