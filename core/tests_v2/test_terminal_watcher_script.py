import os
import sqlite3
import subprocess
import time
from pathlib import Path

from daemon_v2.producer_outbox import _BUSY_TIMEOUT_MS, ProducerOutbox


# Le hook doit renoncer *après* avoir attendu le busy timeout de l'outbox. La
# borne basse est dérivée de la constante plutôt que recopiée : elle suit le
# jour où le timeout change. Marge de 10 % — SQLite ne rend pas la main à la
# milliseconde près.
_EXPECTED_WAIT_S = _BUSY_TIMEOUT_MS / 1000
_MIN_WAIT_S = _EXPECTED_WAIT_S * 0.9
# Plafond large : il n'existe que pour attraper un blocage franc. Un plafond
# serré assertait en réalité la vitesse du runner — 5 s d'attente plus deux
# démarrages de processus dépassaient les 8 s d'origine sur macos-latest, et
# la CI tombait sur une machine lente, pas sur une régression.
_HANG_TIMEOUT_S = 60


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
            timeout=_HANG_TIMEOUT_S,
            check=False,
            env={**os.environ, "PULSE_CORE_OUTBOX_PATH": str(database)},
        )
    finally:
        lock.rollback()
        lock.close()
    elapsed = time.monotonic() - started_at

    assert result.returncode == 0
    # Une machine lente ne peut qu'allonger `elapsed`, jamais le raccourcir :
    # la borne basse reste vraie partout, et c'est elle qui porte le contrat
    # (« il a attendu le verrou »). Un blocage franc est attrapé par le
    # `timeout=` du sous-processus, qui lève plutôt que de laisser passer.
    assert elapsed >= _MIN_WAIT_S
    assert result.stdout == ""
    assert result.stderr == (
        "Pulse : commande non enregistrée "
        "(outbox temporairement indisponible).\n"
    )
    assert secret_command not in result.stderr
    assert ProducerOutbox(database).counts() == (0, 0)
