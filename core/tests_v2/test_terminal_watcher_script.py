import os
import sqlite3
import subprocess
import time
from pathlib import Path

from daemon_v2.producer_outbox import ProducerOutbox


def test_terminal_hook_reports_enqueue_failure_without_echoing_command():
    hook = Path(__file__).parents[1] / "scripts" / "pulse_terminal_watcher.zsh"
    secret_command = "deploy --token never-print-this"
    script = f"""
source "$1"
_PULSE_TERMINAL_PYTHON=/usr/bin/false
_PULSE_TERMINAL_COMMAND={secret_command!r}
_PULSE_TERMINAL_CWD=/tmp
_PULSE_TERMINAL_STARTED_AT=2026-09-03T20:00:00+00:00
_PULSE_TERMINAL_ACTIVE=1
_pulse_terminal_precmd
"""

    result = subprocess.run(
        ["zsh", "-c", script, "pulse-terminal-test", str(hook)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == (
        "Pulse : commande non enregistrée "
        "(outbox temporairement indisponible).\n"
    )
    assert secret_command not in result.stderr


def test_terminal_hook_reports_sqlite_lock_timeout(tmp_path):
    hook = Path(__file__).parents[1] / "scripts" / "pulse_terminal_watcher.zsh"
    database = tmp_path / "outbox.sqlite3"
    ProducerOutbox(database)
    lock = sqlite3.connect(database)
    lock.execute("BEGIN IMMEDIATE")
    secret_command = "deploy --password never-print-this-either"
    script = f"""
source "$1"
_PULSE_TERMINAL_COMMAND={secret_command!r}
_PULSE_TERMINAL_CWD=/tmp
_PULSE_TERMINAL_STARTED_AT=2026-09-03T20:00:00+00:00
_PULSE_TERMINAL_ACTIVE=1
_pulse_terminal_precmd
"""

    started_at = time.monotonic()
    try:
        result = subprocess.run(
            ["zsh", "-c", script, "pulse-terminal-test", str(hook)],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            env={**os.environ, "PULSE_CORE_OUTBOX_PATH": str(database)},
        )
    finally:
        lock.rollback()
        lock.close()
    elapsed = time.monotonic() - started_at

    assert result.returncode == 0
    assert 4.5 <= elapsed < 8
    assert result.stdout == ""
    assert result.stderr == (
        "Pulse : commande non enregistrée "
        "(outbox temporairement indisponible).\n"
    )
    assert secret_command not in result.stderr
    assert ProducerOutbox(database).counts() == (0, 0)
