"""Politique de permissions de ~/.pulse_intelligence : 0700 / 0600, comme Core."""

import os
import stat
import subprocess
from pathlib import Path

from conftest import REFERENCE, session_view, valid_output
from pulse_intelligence import cli
from pulse_intelligence.state import JobState, ensure_private_home


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_state_save_creates_a_private_home_regardless_of_the_ambient_umask(tmp_path):
    previous = os.umask(0o022)
    try:
        state = JobState.load(tmp_path / "home" / ".pulse_intelligence" / "state.json")
        state.record_failure("aaaaaaaaaaaaaaaa", "essai")
    finally:
        os.umask(previous)

    assert mode_of(tmp_path / "home" / ".pulse_intelligence") == 0o700
    assert mode_of(state.path) == 0o600
    assert not (state.path.with_suffix(".json.tmp")).exists()


def test_ensure_private_home_tightens_a_wide_existing_directory(tmp_path):
    home = tmp_path / ".pulse_intelligence"
    home.mkdir(mode=0o755)
    os.chmod(home, 0o755)

    ensure_private_home(home)

    assert mode_of(home) == 0o700


def test_cli_writes_its_state_privately(fake_core, tmp_path, fake_output_file):
    fake_core.add_sessions(REFERENCE.astimezone().date().isoformat(), session_view("aaaaaaaaaaaaaaaa"))
    state_path = tmp_path / "home" / ".pulse_intelligence" / "state.json"
    previous = os.umask(0o022)
    try:
        code = cli.main(
            ["--core-url", fake_core.url, "--state", str(state_path), "run", "--once", "--fake", str(fake_output_file)]
        )
    finally:
        os.umask(previous)

    assert code == 0
    assert mode_of(state_path.parent) == 0o700
    assert mode_of(state_path) == 0o600


def run_fix_permissions(home: Path) -> subprocess.CompletedProcess:
    script = Path(__file__).resolve().parents[1] / "scripts" / "fix_permissions.sh"
    return subprocess.run(
        ["bash", str(script)],
        env={**os.environ, "HOME": str(home), "PULSE_INTELLIGENCE_HOME": str(home / ".pulse_intelligence")},
        capture_output=True,
        text=True,
        check=True,
    )


def test_fix_permissions_script_tightens_only_the_intelligence_home_and_is_idempotent(tmp_path):
    home = tmp_path
    root = home / ".pulse_intelligence"
    (root / "logs").mkdir(parents=True)
    state = root / "state.json"
    state.write_text("{}")
    log = root / "logs" / "run.log"
    log.write_text("log")
    foreign = home / "elsewhere"
    foreign.mkdir()
    foreign_file = foreign / "notes.txt"
    foreign_file.write_text("mine")
    for path, mode in ((root, 0o755), (root / "logs", 0o755), (state, 0o644), (log, 0o644), (foreign, 0o755), (foreign_file, 0o644)):
        os.chmod(path, mode)

    result = run_fix_permissions(home)

    assert result.stderr == ""
    assert mode_of(root) == 0o700 and mode_of(root / "logs") == 0o700
    assert mode_of(state) == 0o600 and mode_of(log) == 0o600
    assert mode_of(foreign) == 0o755 and mode_of(foreign_file) == 0o644
    assert str(state) in result.stdout and "elsewhere" not in result.stdout

    again = run_fix_permissions(home)
    assert again.stdout == "" and again.stderr == ""


def test_fix_permissions_script_is_silent_without_a_home(tmp_path):
    result = run_fix_permissions(tmp_path)

    assert result.stdout == "" and result.stderr == ""
