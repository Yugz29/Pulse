import json
import subprocess
import sys
from pathlib import Path

from daemon_v2.producer_outbox import ProducerOutbox

from tests_v2.test_agent_sessions import _write_transcript, claude_lines


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "scripts" / "pulse_session_end_hook.sh"


def run_hook(tmp_path, stdin_text, *, archive_root=None):
    environment = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        # Sources isolées : jamais les vraies données de la machine.
        "PULSE_AGENT_CLAUDE_DIR": str(tmp_path / "claude"),
        "PULSE_AGENT_CODEX_DIR": str(tmp_path / "codex"),
        "PULSE_TRANSCRIPT_ARCHIVE_PATH": str(archive_root or tmp_path / "archive"),
        "PULSE_AGENT_SESSIONS_MANIFEST_PATH": str(tmp_path / "manifest.json"),
        "PULSE_CORE_OUTBOX_PATH": str(tmp_path / "outbox.sqlite3"),
        "PULSE_SESSION_END_LOG": str(tmp_path / "hook.log"),
    }
    return subprocess.run(
        [str(HOOK)],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


def _pending_count(tmp_path):
    outbox_path = tmp_path / "outbox.sqlite3"
    if not outbox_path.exists():
        return 0
    return 1 if ProducerOutbox(outbox_path).oldest() is not None else 0


def test_hook_archives_then_emits_the_fresh_session(tmp_path):
    # Transcript « chaud » (la session vient de finir) : le hook doit quand
    # même émettre — c'est tout l'intérêt du mode ciblé.
    transcript = _write_transcript(
        tmp_path / "claude", "proj/abc-123.jsonl", claude_lines(), age_hours=0
    )
    payload = json.dumps(
        {
            "transcript_path": str(transcript),
            "session_id": "abc-123",
            "reason": "exit",
        }
    )

    result = run_hook(tmp_path, payload)

    assert result.returncode == 0, result.stderr
    log = (tmp_path / "hook.log").read_text(encoding="utf-8")
    # Garde-fou 2 : l'archive tourne avant l'émission.
    assert log.index("Archived: 1") < log.index("Emitted: 1")
    assert _pending_count(tmp_path) == 1
    # L'archive zstd du transcript existe bien avant que le pointeur parte.
    assert list((tmp_path / "archive").rglob("*.zst"))


def test_hook_cancels_emission_when_archiving_fails_but_exits_zero(tmp_path):
    transcript = _write_transcript(
        tmp_path / "claude", "proj/abc-123.jsonl", claude_lines(), age_hours=0
    )
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    (archive_root / "manifest.json").write_text("broken{{", encoding="utf-8")
    payload = json.dumps({"transcript_path": str(transcript)})

    result = run_hook(tmp_path, payload, archive_root=archive_root)

    # Garde-fou 1 : jamais d'échec visible pour Claude Code.
    assert result.returncode == 0, result.stderr
    # Garde-fou 2 : archivage en échec = aucun pointeur émis.
    log = (tmp_path / "hook.log").read_text(encoding="utf-8")
    assert "émission annulée" in log
    assert "Emitted:" not in log
    assert _pending_count(tmp_path) == 0


def test_hook_ignores_malformed_or_empty_payloads(tmp_path):
    (tmp_path / "claude").mkdir()

    for stdin_text in ("pas du json", "{}", json.dumps({"reason": "exit"})):
        result = run_hook(tmp_path, stdin_text)
        assert result.returncode == 0, result.stderr

    log = (tmp_path / "hook.log").read_text(encoding="utf-8")
    assert log.count("ignoré") == 3
    assert _pending_count(tmp_path) == 0
