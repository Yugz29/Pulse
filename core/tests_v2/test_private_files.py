import os
import stat
import subprocess
from pathlib import Path

from daemon_v2 import private_files
from daemon_v2.private_files import (
    PRIVATE_UMASK,
    apply_private_umask,
    ensure_private_directory,
    restrict_private_file,
)


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_apply_private_umask_sets_077_and_returns_the_previous_one():
    previous = os.umask(0o022)
    try:
        assert apply_private_umask() == 0o022
        assert os.umask(0o022) == PRIVATE_UMASK
    finally:
        os.umask(previous)


def test_ensure_private_directory_creates_the_whole_chain_in_0700(tmp_path):
    previous = os.umask(0o022)  # umask large : le mode doit quand même être 0700
    try:
        created = ensure_private_directory(tmp_path / "a" / "b" / "c")
    finally:
        os.umask(previous)

    assert created.is_dir()
    assert mode_of(tmp_path / "a") == 0o700
    assert mode_of(tmp_path / "a" / "b") == 0o700
    assert mode_of(created) == 0o700


def test_existing_directory_outside_pulse_roots_is_left_alone(tmp_path):
    foreign = tmp_path / "foreign"
    foreign.mkdir(mode=0o755)
    os.chmod(foreign, 0o755)

    ensure_private_directory(foreign)

    assert mode_of(foreign) == 0o755


def test_existing_directory_under_a_pulse_root_is_tightened(tmp_path, monkeypatch):
    root = tmp_path / ".pulse_v2"
    root.mkdir(mode=0o755)
    os.chmod(root, 0o755)
    logs = root / "logs"
    logs.mkdir(mode=0o755)
    os.chmod(logs, 0o755)
    monkeypatch.setattr(private_files, "private_roots", lambda: (root,))

    ensure_private_directory(logs)

    assert mode_of(logs) == 0o700
    assert mode_of(root) == 0o755  # seul le dossier demandé est resserré


def test_restrict_private_file_only_touches_wide_files(tmp_path):
    wide = tmp_path / "trace.db"
    wide.write_text("x")
    os.chmod(wide, 0o644)
    tight = tmp_path / "already.db"
    tight.write_text("x")
    os.chmod(tight, 0o600)

    restrict_private_file(wide)
    restrict_private_file(tight)
    restrict_private_file(tmp_path / "absent.db")

    assert mode_of(wide) == 0o600
    assert mode_of(tight) == 0o600


def run_fix_permissions(home: Path) -> str:
    script = Path(__file__).resolve().parents[1] / "scripts" / "fix_permissions.sh"
    result = subprocess.run(
        ["bash", str(script)],
        env={
            **os.environ,
            "HOME": str(home),
            "PULSE_V2_HOME": str(home / ".pulse_v2"),
            "PULSE_CORE_HOME": str(home / ".pulse_core"),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    # chmod de BSD ne connaît pas « -- » après le mode : toute plainte sur
    # stderr est un bug du script, pas un chemin exotique.
    assert result.stderr == ""
    return result.stdout


def test_fix_permissions_script_tightens_only_pulse_roots_and_is_idempotent(tmp_path):
    home = tmp_path
    pulse = home / ".pulse_v2"
    (pulse / "logs").mkdir(parents=True)
    (pulse / "bin").mkdir()
    trace = pulse / "trace.db"
    trace.write_text("db")
    log = pulse / "logs" / "daemon.log"
    log.write_text("log")
    binary = pulse / "bin" / "PulseApplicationObserver"
    binary.write_text("#!/bin/sh\n")
    outbox_dir = home / ".pulse_core"
    outbox_dir.mkdir()
    outbox = outbox_dir / "outbox.sqlite3"
    outbox.write_text("db")
    foreign = home / "elsewhere"
    foreign.mkdir()
    foreign_file = foreign / "notes.txt"
    foreign_file.write_text("mine")
    for path, mode in (
        (pulse, 0o755), (pulse / "logs", 0o755), (pulse / "bin", 0o755),
        (trace, 0o644), (log, 0o644), (binary, 0o755),
        (outbox_dir, 0o755), (outbox, 0o644), (foreign, 0o755), (foreign_file, 0o644),
    ):
        os.chmod(path, mode)

    output = run_fix_permissions(home)

    assert mode_of(pulse) == 0o700
    assert mode_of(pulse / "logs") == 0o700
    assert mode_of(pulse / "bin") == 0o700
    assert mode_of(trace) == 0o600
    assert mode_of(log) == 0o600
    assert mode_of(binary) == 0o700  # reste exécutable
    assert mode_of(outbox_dir) == 0o700
    assert mode_of(outbox) == 0o600
    # Rien hors des racines Pulse.
    assert mode_of(foreign) == 0o755
    assert mode_of(foreign_file) == 0o644
    assert str(trace) in output and str(binary) in output
    assert "elsewhere" not in output

    assert run_fix_permissions(home) == ""


# --- Casse divergente sous une racine Pulse (hardening 0.5.6) -------------


def _filesystem_ignores_case(tmp_path: Path) -> bool:
    probe = tmp_path / "CaseProbe"
    probe.mkdir()
    return (tmp_path / "caseprobe").is_dir()


def test_a_pulse_root_written_in_another_case_is_recognized(tmp_path, monkeypatch):
    import pytest

    if not _filesystem_ignores_case(tmp_path):
        pytest.skip("volume sensible à la casse : la divergence est impossible")
    root = tmp_path / ".pulse_v2"
    (root / "logs").mkdir(parents=True)
    monkeypatch.setattr(private_files, "private_roots", lambda: (root,))

    # Le même dossier, écrit dans une autre casse : `relative_to` échoue,
    # le noyau confirme que c'est le même objet.
    assert private_files.is_private_path(tmp_path / ".PULSE_V2" / "logs")


def test_a_case_divergent_directory_under_a_root_is_tightened(tmp_path, monkeypatch):
    import pytest

    if not _filesystem_ignores_case(tmp_path):
        pytest.skip("volume sensible à la casse : la divergence est impossible")
    root = tmp_path / ".pulse_v2"
    logs = root / "logs"
    logs.mkdir(parents=True)
    os.chmod(root, 0o755)
    os.chmod(logs, 0o755)
    monkeypatch.setattr(private_files, "private_roots", lambda: (root,))

    ensure_private_directory(tmp_path / ".PULSE_V2" / "logs")

    assert mode_of(logs) == 0o700


def test_the_identity_fallback_does_not_widen_to_lookalike_names(tmp_path, monkeypatch):
    root = tmp_path / ".pulse_v2"
    root.mkdir()
    lookalike = tmp_path / ".pulse_v2_backup"
    lookalike.mkdir(mode=0o755)
    os.chmod(lookalike, 0o755)
    monkeypatch.setattr(private_files, "private_roots", lambda: (root,))

    # Nom voisin, objet différent : ni reconnu, ni resserré.
    assert not private_files.is_private_path(lookalike)
    ensure_private_directory(lookalike)
    assert mode_of(lookalike) == 0o755


def test_the_identity_fallback_leaves_unrelated_paths_out(tmp_path, monkeypatch):
    root = tmp_path / ".pulse_v2"
    root.mkdir()
    foreign = tmp_path / "foreign" / "deep"
    foreign.mkdir(parents=True)
    monkeypatch.setattr(private_files, "private_roots", lambda: (root,))

    assert not private_files.is_private_path(foreign)
    assert not private_files.is_private_path(tmp_path / "absent" / "child")
