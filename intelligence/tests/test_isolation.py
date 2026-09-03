"""Principe 1 du spec : Core ne sait pas qu'Intelligence existe, et réciproquement
Intelligence n'importe rien de Core."""

import re
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1] / "pulse_intelligence"
TESTS = Path(__file__).resolve().parent
FORBIDDEN = re.compile(
    r"^\s*(?:from|import)\s+(?:daemon_v2|core|scripts)(?:[.\s]|$)", re.MULTILINE
)


def python_files():
    return sorted(list(PACKAGE.rglob("*.py")) + list(TESTS.rglob("*.py")))


def test_nothing_from_core_is_imported():
    offenders = []
    for path in python_files():
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN.search(text):
            offenders.append(str(path.relative_to(PACKAGE.parent)))
    assert offenders == []


SYS_PATH_TRICK = re.compile(r"sys\.path\.(?:insert|append|extend)\(.*core", re.MULTILINE)


def test_no_sys_path_tricks_towards_core():
    offenders = []
    for path in python_files():
        if SYS_PATH_TRICK.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(PACKAGE.parent)))
    assert offenders == []


def test_package_imports_without_core_on_the_path():
    import importlib

    for module in (
        "pulse_intelligence.config",
        "pulse_intelligence.core_client",
        "pulse_intelligence.selection",
        "pulse_intelligence.session_input",
        "pulse_intelligence.session_summary",
        "pulse_intelligence.state",
        "pulse_intelligence.summarizer",
        "pulse_intelligence.cli",
    ):
        importlib.import_module(module)
