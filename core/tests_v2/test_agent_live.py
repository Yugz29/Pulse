"""Étape 1 bis : « Session en cours » lit le transcript live d'une session Claude Code.

Transcript figé sous ``fixtures/claude_transcript_live.jsonl`` : deux tests
(le premier en échec), un ``Read`` (ignoré), un ``Edit`` et un ``Write``,
une commande avec un mot de passe factice dans l'URL et dans la description, une
interruption (130), deux entrées de sous-agent, une ligne illisible et une
dernière ligne tronquée. Ce qui ne doit jamais apparaître porte le mot
``NE_DOIT_PAS_APPARAITRE``.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import timezone
from pathlib import Path

from daemon_v2 import agent_transcript
from daemon_v2.agent_live import live_agent_sessions
from daemon_v2.agent_transcript import read_transcript
from daemon_v2.daily_trace import build_daily_trace, render_daily_trace_html
from tests_v2.test_context_snapshot import REFERENCE, app, make_store, terminal

FIXTURE = Path(__file__).parent / "fixtures" / "claude_transcript_live.jsonl"
FORBIDDEN = "NE_DOIT_PAS_APPARAITRE"


def copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "session.jsonl"
    shutil.copy(FIXTURE, target)
    return target


def read(path: Path, states=None):
    return read_transcript(path, states={} if states is None else states)


# --- Le lecteur -------------------------------------------------------------------


def test_commands_carry_description_redacted_command_outcome_and_time(tmp_path):
    view = read(copy_fixture(tmp_path))
    assert view["command_count"] == 5
    first, curl, wait, second, commit = view["commands"]
    assert first == {
        "at": "2026-09-18T09:01:30.000Z",
        "command": "cd core && python -m pytest tests_v2 -q",
        "description": "Run the Core suite",
        "test_command": True,
        "outcome": "échec",
    }
    # Mot de passe factice (mot-clé que le scan de pré-poussée reconnaît comme tel) :
    # le masquage doit le traiter comme un vrai.
    assert curl["outcome"] == "ok" and "[REDACTED]" in curl["command"] and "YOUR_PASSWORD" not in curl["command"]
    assert "YOUR_PASSWORD" not in curl["description"] and "[REDACTED]@localhost" in curl["description"]
    assert wait["outcome"] == "interrompue"
    assert second["outcome"] == "ok" and second["test_command"]
    assert commit["outcome"] == "échec" and commit["description"] is None and not commit["test_command"]


def test_last_test_failures_and_files(tmp_path):
    view = read(copy_fixture(tmp_path))
    assert view["last_test"]["at"] == "2026-09-18T09:07:20.000Z" and view["last_test"]["outcome"] == "ok"
    assert view["test_count"] == 2 and view["failed_test_count"] == 1
    # Échecs bruts, du plus récent au plus ancien ; l'interruption n'en est pas un.
    assert [f["command"] for f in view["failures"]] == ["git commit -am 'fix'", "cd core && python -m pytest tests_v2 -q"]
    assert view["failure_count"] == 2
    assert [(f["path"].rsplit("/", 1)[-1], f["changes"]) for f in view["files"]] == [
        ("test_new.py", {"écrit": 1}),
        ("x.py", {"modifié": 1}),
    ]
    assert view["file_count"] == 2  # le Read n'est pas un fichier écrit


def test_nothing_forbidden_leaks_and_sidechain_is_ignored(tmp_path):
    view = read(copy_fixture(tmp_path))
    assert FORBIDDEN not in json.dumps(view, ensure_ascii=False)
    assert "SIDECHAIN" not in json.dumps(view)
    assert view["skipped_lines"] == 1  # « ceci n'est pas du JSON »


def test_truncated_last_line_waits_for_the_next_read(tmp_path):
    path = copy_fixture(tmp_path)
    states = {}
    view = read(path, states)
    assert view["command_count"] == 5
    offset = states[str(path)].offset
    assert offset < path.stat().st_size  # la ligne tronquée n'est pas consommée

    # La ligne se termine, son résultat arrive : lecture incrémentale.
    with path.open("a") as handle:
        handle.write("\n")
        handle.write(json.dumps({"type": "user", "timestamp": "2026-09-18T09:09:05.000Z", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_09", "content": "ok", "is_error": False}]}}) + "\n")
    again = read(path, states)
    assert again["command_count"] == 6
    assert again["commands"][-1]["command"] == "make test" and again["commands"][-1]["test_command"]
    assert again["last_test"]["command"] == "make test"
    assert states[str(path)].offset == path.stat().st_size


def test_a_shrunken_or_replaced_file_is_read_from_the_start(tmp_path):
    path = copy_fixture(tmp_path)
    states = {}
    read(path, states)
    path.write_text(json.dumps({"type": "assistant", "timestamp": "2026-09-18T10:00:00Z", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "echo un"}}]}}) + "\n"
        + json.dumps({"type": "user", "timestamp": "2026-09-18T10:00:01Z", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "un"}]}}) + "\n")
    view = read(path, states)
    assert view["command_count"] == 1 and view["commands"][0]["command"] == "echo un"


def test_missing_file_and_garbage_are_tolerated(tmp_path):
    assert read(tmp_path / "absent.jsonl") is None
    garbage = tmp_path / "garbage.jsonl"
    garbage.write_text("{\n[1,2]\n\"x\"\n{\"type\": \"assistant\"}\n")
    view = read(garbage)
    assert view["command_count"] == 0 and view["skipped_lines"] == 1


def test_only_the_last_ten_commands_are_kept_but_all_are_counted(tmp_path):
    path = tmp_path / "many.jsonl"
    lines = []
    for i in range(25):
        lines.append(json.dumps({"type": "assistant", "timestamp": f"2026-09-18T09:{i:02d}:00Z", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": f"echo {i}"}}]}}))
        lines.append(json.dumps({"type": "user", "timestamp": f"2026-09-18T09:{i:02d}:01Z", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "x", "is_error": i % 2 == 0}]}}))
    path.write_text("\n".join(lines) + "\n")
    view = read(path)
    assert view["command_count"] == 25 and len(view["commands"]) == agent_transcript.MAX_COMMANDS
    assert view["commands"][-1]["command"] == "echo 24"
    assert view["failure_count"] == 13 and len(view["failures"]) == agent_transcript.MAX_FAILURES
    assert view["failures"][0]["command"] == "echo 24"


def test_description_gets_every_command_rule_plus_the_free_text_one():
    """La description passe par toutes les règles de ``redact_command`` (jetons
    connus, en-têtes, options sensibles, ``user:pass`` en URL), puis par le
    masque ``utilisateur:secret@`` du texte libre. Les faux secrets sont
    assemblés à l'exécution pour que ce fichier n'en contienne aucun en clair
    (le scan de pré-poussée du dépôt public les bloquerait, à raison)."""
    redact = agent_transcript.redact_description
    openai_like = "sk-" + "proj-" + "Zx9Qw8Er7Ty6Ui5Op4As3Df2"
    github_like = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab"
    jwt_like = "eyJ" + "hbGciOiJIUzI1NiJ9.abc.def"
    aws_like = "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY"
    url_with_password = "https://" + "user:" + "hunter2@" + "localhost/x"
    assert redact(f"Call the API with {openai_like} as key") == "Call the API with [REDACTED] as key"
    assert redact(f"Use token {github_like} for gh") == "Use token [REDACTED] for gh"
    assert redact(f"Header Authorization: Bearer {jwt_like}") == "Header Authorization: Bearer [REDACTED]"
    assert redact(f"Export AWS_SECRET_ACCESS_KEY={aws_like}") == "Export AWS_SECRET_ACCESS_KEY=[REDACTED]"
    assert redact("Run with --password=hunter2 on the db") == "Run with --password=[REDACTED] on the db"
    fetched = redact(f"Fetch {url_with_password}")
    assert fetched.endswith("user:[REDACTED]@localhost/x") and "hunter2" not in fetched
    assert redact("Check the registry with user:YOUR_PASSWORD@localhost") == "Check the registry with user:[REDACTED]@localhost"
    assert redact("ssh admin:hunter2@10.0.0.1") == "ssh admin:[REDACTED]@10.0.0.1"
    assert redact("Push to origin") == "Push to origin"


def test_test_detection_looks_at_each_segment():
    assert agent_transcript.is_agent_test_command("cd core && python -m pytest tests_v2 -q")
    assert agent_transcript.is_agent_test_command("make test 2>&1 | tail -3")
    assert agent_transcript.is_agent_test_command("git pull\nnpm test")
    assert not agent_transcript.is_agent_test_command("echo pytest")
    assert not agent_transcript.is_agent_test_command("git commit -m 'pytest vert'")


# --- Les sessions vivantes ---------------------------------------------------------


def state_file(directory: Path, name: str, transcript: Path | None, *, pid=None, state="working", **extra) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = {"agent": "claude-code", "session_id": name, "state": state, "since": "2026-09-18T09:00:00+00:00",
            "updated_at": REFERENCE.isoformat(), "pid": pid if pid is not None else os.getpid(),
            "cwd": "/Users/dev/Projets/Pulse", "project": "Pulse",
            "transcript_path": str(transcript) if transcript else None, **extra}
    path = directory / f"claude-code-{name}.json"
    path.write_text(json.dumps(data))
    return path


def test_live_sessions_absent_directory_is_empty(tmp_path):
    assert live_agent_sessions(tmp_path / "nowhere") == []


def test_live_sessions_skip_dead_pids_and_read_transcripts(tmp_path):
    transcript = copy_fixture(tmp_path)
    folder = tmp_path / "agents"
    state_file(folder, "alive", transcript)
    state_file(folder, "dead", transcript, pid=2_000_000_000)
    state_file(folder, "notranscript", None, state="waiting_for_you")
    (folder / "claude-code-broken.json").write_text("{pas du json")
    sessions = live_agent_sessions(folder, now=REFERENCE, states={})
    assert [s["session_id"] for s in sessions] == ["alive", "notranscript"]
    assert sessions[0]["transcript"]["command_count"] == 5
    assert sessions[1]["transcript"] is None and sessions[1]["state_label"] == "attend ta suite"


# --- La page --------------------------------------------------------------------------


def open_session_store(tmp_path):
    return make_store(tmp_path, app(-20, "Terminal"), terminal(-18, "ls"), terminal(-10, "git status"))


def render(store, folder):
    trace = build_daily_trace(store, REFERENCE.date(), timezone.utc, now=REFERENCE)
    html = render_daily_trace_html(trace, agent_state_dir=folder)
    assert html.count('id="session-en-cours"') == 1
    return html.split('id="session-en-cours"', 1)[1].split("</section>", 1)[0]


def test_block_is_silent_without_the_state_directory(tmp_path):
    html = render(open_session_store(tmp_path), tmp_path / "absent")
    assert "Claude Code en cours" in html
    assert "Aucune session Claude Code vivante connue" in html
    assert "fait-live-agent-live" not in html


def test_block_shows_the_agent_from_its_transcript_and_nothing_forbidden(tmp_path):
    transcript = copy_fixture(tmp_path)
    folder = tmp_path / "agents"
    state_file(folder, "abcdef1234", transcript)
    html = render(open_session_store(tmp_path), folder)
    assert "Claude Code en cours (1)" in html
    assert "<strong>Pulse</strong> · travaille depuis" in html
    assert "Dernières commandes (5 sur 5)" in html
    assert "Run the Core suite again" in html and "python -m pytest tests_v2 -q" in html
    assert "[REDACTED]@localhost" in html and "YOUR_PASSWORD" not in html
    assert 'class="live-outcome">échec</span>' in html and 'class="live-outcome">interrompue</span>' in html
    assert "Dernier test" in html and "2 commande(s) de test, dont 1 en échec" in html
    assert "Échecs bruts (2" in html
    assert "Fichiers écrits par l’agent (2)" in html and "test_new.py" in html and "écrit ×1" in html
    assert "1 ligne(s) du transcript ignorée(s)" in html
    assert FORBIDDEN not in html and "Exit code" not in html and "SIDECHAIN" not in html
    assert html.count('id="fait-live-agent-live-1-cmd-') == 5


def test_archive_page_never_reads_transcripts(tmp_path):
    transcript = copy_fixture(tmp_path)
    folder = tmp_path / "agents"
    state_file(folder, "abcdef1234", transcript)
    trace = build_daily_trace(open_session_store(tmp_path), REFERENCE.date(), timezone.utc, now=REFERENCE)
    html = render_daily_trace_html(trace, archive_mode=True, agent_state_dir=folder)
    assert "Claude Code en cours" not in html and "session-en-cours" not in html
