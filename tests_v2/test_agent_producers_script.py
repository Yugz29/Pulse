import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "scripts" / "pulse_agent_producers.sh"


def run_wrapper(tmp_path, *, archive_root=None):
    environment = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        # Sources isolées et vides : jamais les vraies données de la machine.
        "PULSE_AGENT_CLAUDE_DIR": str(tmp_path / "claude"),
        "PULSE_AGENT_CODEX_DIR": str(tmp_path / "codex"),
        "PULSE_TRANSCRIPT_ARCHIVE_PATH": str(archive_root or tmp_path / "archive"),
        "PULSE_AGENT_SESSIONS_MANIFEST_PATH": str(tmp_path / "manifest.json"),
        "PULSE_CORE_OUTBOX_PATH": str(tmp_path / "outbox.sqlite3"),
    }
    return subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


def test_wrapper_runs_archive_then_sessions_and_exits_zero(tmp_path):
    (tmp_path / "claude").mkdir()
    (tmp_path / "codex").mkdir()

    result = run_wrapper(tmp_path)

    assert result.returncode == 0, result.stderr
    # L'ordre est le contrat : l'archive s'exécute avant l'émission.
    archive_at = result.stdout.index("archive")
    sessions_at = result.stdout.index("agent sessions")
    assert archive_at < sessions_at
    assert "Emitted: 0" in result.stdout


def test_wrapper_skips_emission_when_archiving_fails(tmp_path):
    (tmp_path / "claude").mkdir()
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    (archive_root / "manifest.json").write_text("broken{{", encoding="utf-8")

    result = run_wrapper(tmp_path, archive_root=archive_root)

    # Archive en erreur d'infrastructure : aucun pointeur ne doit partir.
    assert result.returncode == 2
    assert "Emitted:" not in result.stdout
    assert "émission annulée" in result.stderr
