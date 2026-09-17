"""L'empreinte du code : ce qui la change, ce qui ne la change pas."""

from __future__ import annotations

from daemon_v2.code_fingerprint import (
    observer_source_fingerprint,
    python_fingerprint,
)

MODULE = '''"""Docstring de module."""
import os


def answer(value):
    """Docstring de fonction."""
    # un commentaire
    return value + 1
'''


def core(tmp_path, source=MODULE, version="0.8.9.0", requirements="flask\n"):
    root = tmp_path / "core"
    (root / "daemon_v2" / "analysis").mkdir(parents=True, exist_ok=True)
    (root / "daemon_v2" / "module.py").write_text(source)
    (root / "daemon_v2" / "analysis" / "__init__.py").write_text("")
    if version is not None:
        (root / "VERSION").write_text(version)
    (root / "requirements.txt").write_text(requirements)
    return root


def test_comments_docstrings_and_layout_do_not_change_it(tmp_path):
    reference = python_fingerprint(core(tmp_path / "a"))
    rewritten = MODULE.replace("Docstring de fonction.", "Un docstring rétabli (#106).")
    rewritten = rewritten.replace("# un commentaire", "# un autre\n\n    # et encore")
    rewritten = rewritten.replace('"""Docstring de module."""\n', "")

    assert reference is not None and len(reference) == 12
    assert python_fingerprint(core(tmp_path / "b", rewritten)) == reference


def test_a_code_change_without_a_version_bump_changes_it(tmp_path):
    reference = python_fingerprint(core(tmp_path / "a"))
    changed = MODULE.replace("value + 1", "value + 2")

    assert python_fingerprint(core(tmp_path / "b", changed)) != reference


def test_a_string_that_is_not_a_docstring_counts(tmp_path):
    reference = python_fingerprint(core(tmp_path / "a", 'LABEL = "avant"\n'))

    assert python_fingerprint(core(tmp_path / "b", 'LABEL = "après"\n')) != reference


def test_version_requirements_and_file_set_are_part_of_it(tmp_path):
    reference = python_fingerprint(core(tmp_path / "a"))
    extra = core(tmp_path / "e")
    (extra / "daemon_v2" / "nouveau.py").write_text("X = 1\n")

    assert python_fingerprint(core(tmp_path / "b", version="0.9.0.0")) != reference
    assert python_fingerprint(core(tmp_path / "c", version=None)) != reference
    assert python_fingerprint(core(tmp_path / "d", requirements="flask\nrequests\n")) != reference
    assert python_fingerprint(extra) != reference


def test_tests_docs_and_caches_are_outside_it(tmp_path):
    root = core(tmp_path)
    reference = python_fingerprint(root)
    (root / "tests_v2").mkdir()
    (root / "tests_v2" / "test_x.py").write_text("assert True\n")
    (root / "README.md").write_text("doc")
    (root / "daemon_v2" / "__pycache__").mkdir()
    (root / "daemon_v2" / "__pycache__" / "module.cpython-314.pyc").write_bytes(b"\x00")

    assert python_fingerprint(root) == reference


def test_an_unparseable_file_falls_back_to_its_bytes(tmp_path):
    broken = python_fingerprint(core(tmp_path / "a", "def (:\n"))

    assert broken is not None
    assert python_fingerprint(core(tmp_path / "b", "def (:\n")) == broken
    assert python_fingerprint(core(tmp_path / "c", "def (:  \n")) != broken


def test_an_unreadable_core_has_no_fingerprint(tmp_path):
    assert python_fingerprint(tmp_path / "absent") is None


def test_it_reads_the_real_package_without_git_or_subprocess(monkeypatch):
    import subprocess

    def forbidden(*_args, **_kwargs):
        raise AssertionError("l'empreinte ne lance aucun sous-processus")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    assert python_fingerprint() == python_fingerprint()
    assert python_fingerprint() is not None


def test_observer_sources_are_hashed_as_bytes(tmp_path):
    root = tmp_path / "macos_observer"
    (root / "Sources" / "Core").mkdir(parents=True)
    (root / "Package.swift").write_text("// swift-tools-version:5.9\n")
    (root / "Sources" / "Core" / "A.swift").write_text("let a = 1\n")
    (root / "Tests").mkdir()
    reference = observer_source_fingerprint(root)

    (root / "Tests" / "T.swift").write_text("// hors empreinte\n")
    assert observer_source_fingerprint(root) == reference
    # Pas d'analyse syntaxique du Swift : un commentaire compte.
    (root / "Sources" / "Core" / "A.swift").write_text("let a = 1 // note\n")
    assert observer_source_fingerprint(root) != reference
    assert observer_source_fingerprint(tmp_path / "absent") is None
