from __future__ import annotations

from daemon.runtime_mode import get_pulse_mode, is_lab_enabled


def test_get_pulse_mode_defaults_to_core_without_environment():
    assert get_pulse_mode({}) == "core"
    assert is_lab_enabled({}) is False


def test_get_pulse_mode_accepts_core():
    environ = {"PULSE_MODE": "core"}

    assert get_pulse_mode(environ) == "core"
    assert is_lab_enabled(environ) is False


def test_get_pulse_mode_accepts_lab():
    environ = {"PULSE_MODE": "lab"}

    assert get_pulse_mode(environ) == "lab"
    assert is_lab_enabled(environ) is True


def test_get_pulse_mode_accepts_dev():
    environ = {"PULSE_MODE": "dev"}

    assert get_pulse_mode(environ) == "dev"
    assert is_lab_enabled(environ) is True


def test_get_pulse_mode_falls_back_to_core_for_invalid_value():
    environ = {"PULSE_MODE": "experimental"}

    assert get_pulse_mode(environ) == "core"
    assert is_lab_enabled(environ) is False


def test_get_pulse_mode_normalizes_case_and_whitespace():
    environ = {"PULSE_MODE": " LAB "}

    assert get_pulse_mode(environ) == "lab"
    assert is_lab_enabled(environ) is True
