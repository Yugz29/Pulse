"""État d'agent v0 : hooks Claude Code → fichiers d'état → menu SwiftBar.

Hors trace.db, hors Core : rien ici ne parle au daemon. Le test « réel » du
pid remonte l'arbre des processus du test lui-même jusqu'à un processus
``claude`` quand la suite tourne sous Claude Code, et se déclare ignoré
ailleurs (CI) : la partie déterministe est jouée sur des arbres simulés.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import pulse_agent_state as agent_state
from scripts import pulse_agents_menu as menu

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
HOOK = SCRIPTS / "pulse_agent_state_hook.sh"
INSTALLER = SCRIPTS / "install_agent_state_hooks.sh"
PLUGIN = SCRIPTS / "swiftbar" / "pulse-agents.5s.sh"
NOW = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)


def payload(event: str, session: str = "s1", **extra) -> dict:
    return {"hook_event_name": event, "session_id": session, "cwd": "/Users/dev/Projets/Pulse", **extra}


def fake_tree(*rows):
    """rows : (pid, ppid, comm) ; rend la fonction ``rows(pid)`` attendue."""
    table = {pid: (ppid, comm, comm) for pid, ppid, comm in rows}
    return lambda pid: table.get(pid)


def apply(directory: Path, event_payload: dict, *, now=NOW, tree=None) -> dict:
    tree = tree or fake_tree((100, 90, "bash"), (90, 80, "sh"), (80, 70, "claude"), (70, 1, "zsh"))
    agent_state.apply_event(event_payload, directory=directory, hook_pid=100, now=now, rows=tree)
    path = agent_state.state_path(directory, "claude-code", event_payload["session_id"])
    return agent_state.read_state(path) or {}


# --- Transitions ----------------------------------------------------------------


def test_session_start_creates_working_with_the_claude_pid(tmp_path):
    data = apply(tmp_path, payload("SessionStart"))
    assert data["state"] == "working"
    assert data["pid"] == 80  # `claude`, pas le bash (100) ni le sh (90)
    assert data["project"] == "Pulse" and data["cwd"] == "/Users/dev/Projets/Pulse"
    assert data["since"] == data["updated_at"] == NOW.isoformat()
    path = agent_state.state_path(tmp_path, "claude-code", "s1")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(tmp_path.stat().st_mode & 0o777) == "0o700"


def test_stop_means_waiting_for_you_and_only_a_prompt_lifts_it(tmp_path):
    apply(tmp_path, payload("SessionStart"))
    data = apply(tmp_path, payload("Stop"), now=NOW + timedelta(minutes=5))
    assert data["state"] == "waiting_for_you"
    assert data["since"] == (NOW + timedelta(minutes=5)).isoformat()

    # idle_prompt ne change rien : Stop l'a déjà dit, `since` reste.
    data = apply(tmp_path, payload("Notification", notification_type="idle_prompt"), now=NOW + timedelta(hours=2))
    assert data["state"] == "waiting_for_you"
    assert data["since"] == (NOW + timedelta(minutes=5)).isoformat()

    data = apply(tmp_path, payload("UserPromptSubmit"), now=NOW + timedelta(hours=3))
    assert data["state"] == "working"
    assert data["since"] == (NOW + timedelta(hours=3)).isoformat()


def test_permission_prompt_waits_and_a_tool_use_lifts_it(tmp_path):
    apply(tmp_path, payload("SessionStart"))
    data = apply(tmp_path, payload("Notification", notification_type="permission_prompt"), now=NOW + timedelta(minutes=1))
    assert data["state"] == "waiting_permission"
    data = apply(tmp_path, payload("PostToolUse"), now=NOW + timedelta(minutes=2))
    assert data["state"] == "working"
    assert data["since"] == (NOW + timedelta(minutes=2)).isoformat()


def test_repeated_tool_uses_keep_since_but_refresh_updated_at(tmp_path):
    apply(tmp_path, payload("SessionStart"))
    later = NOW + timedelta(minutes=10)
    data = apply(tmp_path, payload("PostToolUse"), now=later)
    assert data["since"] == NOW.isoformat()
    assert data["updated_at"] == later.isoformat()


def test_session_end_removes_the_file_and_unknown_events_are_ignored(tmp_path):
    apply(tmp_path, payload("SessionStart"))
    verdict = agent_state.apply_event(payload("PreCompact"), directory=tmp_path, hook_pid=100, now=NOW)
    assert verdict.startswith("ignored")
    agent_state.apply_event(payload("SessionEnd"), directory=tmp_path, hook_pid=100, now=NOW)
    assert list(tmp_path.glob("*.json")) == []
    assert agent_state.apply_event({}, directory=tmp_path, hook_pid=100).startswith("ignored")


def test_two_parallel_sessions_have_two_files(tmp_path):
    apply(tmp_path, payload("SessionStart", "aaa"))
    apply(tmp_path, payload("SessionStart", "bbb", cwd="/Users/dev/Projets/Autre"))
    apply(tmp_path, payload("Stop", "aaa"))
    files = {p.name: agent_state.read_state(p) for p in tmp_path.glob("*.json")}
    assert set(files) == {"claude-code-aaa.json", "claude-code-bbb.json"}
    assert files["claude-code-aaa.json"]["state"] == "waiting_for_you"
    assert files["claude-code-bbb.json"]["state"] == "working"
    assert files["claude-code-bbb.json"]["project"] == "Autre"


# --- Le pid enregistré est celui de Claude Code ------------------------------------


def test_resolve_agent_pid_skips_intermediate_shells():
    tree = fake_tree((100, 90, "bash"), (90, 80, "/bin/sh"), (80, 70, "claude"), (70, 1, "zsh"))
    assert agent_state.resolve_agent_pid(100, rows=tree) == 80
    # Le shell a fait `exec` : le pid de départ est déjà l'agent.
    assert agent_state.resolve_agent_pid(80, rows=tree) == 80
    # Aucun claude au-dessus : None, jamais un shell par défaut.
    assert agent_state.resolve_agent_pid(100, rows=fake_tree((100, 90, "bash"), (90, 1, "zsh"))) is None
    # `comm` tronqué mais args explicites.
    table = {100: (90, "bash", "bash hook.sh"), 90: (1, "node", "/opt/homebrew/bin/claude --resume")}
    assert agent_state.resolve_agent_pid(100, rows=lambda pid: table.get(pid)) == 90


def _claude_ancestor(pid: int) -> int | None:
    for _ in range(12):
        out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True).stdout.split()
        if len(out) < 2:
            return None
        ppid, comm = int(out[0]), out[1]
        if Path(comm).name == "claude":
            return pid
        if ppid <= 1:
            return None
        pid = ppid
    return None


def test_real_process_tree_records_claude_not_the_shell(tmp_path):
    """Test réel : le hook lancé sous un `sh -c` (comme Claude Code le fait)
    enregistre le pid du processus `claude` au-dessus de ce test, pas celui
    du shell. Ignoré quand la suite ne tourne pas sous Claude Code."""
    expected = _claude_ancestor(os.getpid())
    if expected is None:
        pytest.skip("pas de processus claude au-dessus de la suite")
    env = {**os.environ, "PULSE_AGENT_STATE_DIR": str(tmp_path / "agents"), "PULSE_AGENT_STATE_LOG": str(tmp_path / "log")}
    body = json.dumps(payload("SessionStart", "real"))
    subprocess.run(["/bin/sh", "-c", f"printf '%s' '{body}' | {HOOK}"], env=env, check=True, timeout=30)
    data = agent_state.read_state(tmp_path / "agents" / "claude-code-real.json")
    assert data["pid"] == expected
    assert subprocess.run(["ps", "-o", "comm=", "-p", str(data["pid"])], capture_output=True, text=True).stdout.strip() == "claude"


def test_sweep_removes_dead_sessions_only(tmp_path):
    agent_state.write_state(tmp_path / "claude-code-dead.json", {"state": "working", "pid": 2_000_000_000})
    agent_state.write_state(tmp_path / "claude-code-alive.json", {"state": "working", "pid": os.getpid()})
    removed = agent_state.sweep_dead(tmp_path)
    assert [p.name for p in removed] == ["claude-code-dead.json"]
    assert (tmp_path / "claude-code-alive.json").exists()


# --- Le wrapper bash --------------------------------------------------------------


def _run_hook(tmp_path: Path, body: dict, *args: str) -> str:
    env = {**os.environ, "PULSE_AGENT_STATE_DIR": str(tmp_path / "agents"), "PULSE_AGENT_STATE_LOG": str(tmp_path / "log")}
    subprocess.run([str(HOOK), *args], input=json.dumps(body), text=True, env=env, check=True, timeout=30)
    log = tmp_path / "log"
    return log.read_text() if log.exists() else ""


def test_hook_fast_path_skips_python_for_a_fresh_working_session(tmp_path):
    _run_hook(tmp_path, payload("SessionStart", "fast"))
    path = tmp_path / "agents" / "claude-code-fast.json"
    before = path.stat().st_mtime_ns
    log_lines = len(_run_hook(tmp_path, payload("PostToolUse", "fast")).splitlines())
    assert path.stat().st_mtime_ns == before  # rien réécrit
    assert log_lines == 1  # une seule ligne : le SessionStart ; le chemin rapide ne journalise pas


def test_hook_passes_the_notification_matcher_as_argument(tmp_path):
    _run_hook(tmp_path, payload("SessionStart", "n"))
    log = _run_hook(tmp_path, {"hook_event_name": "Notification", "session_id": "n", "cwd": "/x"}, "permission_prompt")
    assert "working -> waiting_permission" in log
    assert agent_state.read_state(tmp_path / "agents" / "claude-code-n.json")["state"] == "waiting_permission"


def test_hook_never_fails_on_garbage(tmp_path):
    env = {**os.environ, "PULSE_AGENT_STATE_DIR": str(tmp_path / "agents"), "PULSE_AGENT_STATE_LOG": str(tmp_path / "log")}
    for body in ("", "pas du json", "[1,2]"):
        result = subprocess.run([str(HOOK)], input=body, text=True, env=env, timeout=30)
        assert result.returncode == 0


# --- Le menu SwiftBar -------------------------------------------------------------


def _state(directory: Path, name: str, state: str, since: datetime, pid: int = os.getpid(), project: str = "Pulse"):
    agent_state.write_state(
        directory / f"claude-code-{name}.json",
        {"agent": "claude-code", "session_id": name, "state": state, "since": since.isoformat(),
         "updated_at": since.isoformat(), "pid": pid, "cwd": f"/Users/dev/Projets/{project}", "project": project},
    )


def test_menu_lists_waiting_first_hides_dead_and_never_hides_an_old_wait(tmp_path):
    _state(tmp_path, "w", "working", NOW - timedelta(minutes=12))
    _state(tmp_path, "p", "waiting_permission", NOW - timedelta(minutes=3), project="Pulse-exp")
    _state(tmp_path, "y", "waiting_for_you", NOW - timedelta(hours=2, minutes=30), project="Holberton28")
    _state(tmp_path, "dead", "waiting_for_you", NOW - timedelta(minutes=1), pid=2_000_000_000, project="Mort")
    out = menu.render(tmp_path, None, now=NOW)
    lines = out.splitlines()
    assert lines[0] == "⏳ 2" and lines[1] == "---"
    assert lines[2].startswith("Pulse-exp — attend une permission — depuis 3 min")
    assert lines[4].startswith("Holberton28 — attend ta suite — depuis 2 h 30")
    assert lines[6].startswith("Pulse — travaille — depuis 12 min")
    assert "Mort" not in out


def test_menu_without_sessions(tmp_path):
    out = menu.render(tmp_path / "absent", None, now=NOW)
    assert out.splitlines()[:3] == ["·", "---", "Aucune session d'agent"]


def _intel_state(tmp_path: Path, marker: str | None) -> Path:
    path = tmp_path / "state.json"
    data = {"emitted": {}, "pending": {}, "failures": {}, "failed": {}}
    if marker:
        data["last_complete_pass"] = marker
    path.write_text(json.dumps(data))
    return path


def _local(hour: int, minute: int = 0, day: int = 18) -> datetime:
    return datetime(2026, 9, day, hour, minute).astimezone()


def test_last_batch_is_green_when_a_pass_completed_since_the_scheduled_time(tmp_path):
    state = _intel_state(tmp_path, _local(6, 36).astimezone(timezone.utc).isoformat())
    assert "OK, passage complet à 06:36 | color=green" in menu.last_batch_line(state, _local(8))
    # Même avant 07:30 : un passage complet du jour est vert.
    assert "color=green" in menu.last_batch_line(state, _local(6, 50))


def test_last_batch_is_red_after_0730_without_a_pass_since_0630(tmp_path):
    yesterday = _intel_state(tmp_path, _local(6, 40, day=17).astimezone(timezone.utc).isoformat())
    assert menu.last_batch_line(yesterday, _local(7, 30)) == "Dernier lot : aucun passage complet depuis 06:30 | color=red"
    assert "color=red" in menu.last_batch_line(yesterday, _local(23, 59))
    # Sans repère du tout, même verdict une fois 07:30 passé.
    assert "color=red" in menu.last_batch_line(_intel_state(tmp_path, None), _local(9))
    # Un passage à 06:29 est celui d'avant le lot planifié : rouge aussi.
    early = _intel_state(tmp_path, _local(6, 29).astimezone(timezone.utc).isoformat())
    assert "color=red" in menu.last_batch_line(early, _local(8))


def test_last_batch_is_grey_before_0730_and_names_the_last_pass(tmp_path):
    yesterday = _intel_state(tmp_path, _local(11, 32, day=17).astimezone(timezone.utc).isoformat())
    line = menu.last_batch_line(yesterday, _local(7, 0))
    assert line.startswith("Dernier lot : hier 11:32") and line.endswith("| color=gray")
    assert "aucun passage complet connu | color=gray" in menu.last_batch_line(_intel_state(tmp_path, None), _local(7, 0))
    assert "color=gray" in menu.last_batch_line(tmp_path / "absent.json", _local(7, 0))


def test_plugin_wrapper_runs_the_menu(tmp_path):
    _state(tmp_path / "agents", "w", "working", NOW - timedelta(minutes=1))
    env = {**os.environ, "PULSE_AGENT_STATE_DIR": str(tmp_path / "agents"),
           "PULSE_INTEL_STATE_PATH": str(_intel_state(tmp_path, None))}
    out = subprocess.run([str(PLUGIN)], capture_output=True, text=True, env=env, check=True, timeout=30).stdout
    assert out.splitlines()[0] == "·"
    assert "Pulse — travaille" in out and "Dernier lot" in out


# --- L'installateur ---------------------------------------------------------------


def _install(settings: Path, *args: str) -> str:
    env = {**os.environ, "PULSE_CLAUDE_SETTINGS": str(settings), "PULSE_SWIFTBAR_PLUGIN_DIR": str(settings.parent / "plugins")}
    (settings.parent / "plugins").mkdir(parents=True, exist_ok=True)
    return subprocess.run([str(INSTALLER), *args], capture_output=True, text=True, env=env, check=True, timeout=30).stdout


def test_installer_adds_six_hooks_keeps_others_is_idempotent_and_reversible(tmp_path):
    settings = tmp_path / "settings.json"
    original = {"model": "opus", "hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "/x/pulse_session_end_hook.sh"}]}]}}
    settings.write_text(json.dumps(original))

    first = _install(settings)
    assert "posés : 6 hooks" in first and "plugin lié" in first
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    assert {k: len(v) for k, v in data["hooks"].items()} == {
        "SessionEnd": 2, "SessionStart": 1, "UserPromptSubmit": 1, "PostToolUse": 1, "Notification": 1, "Stop": 1}
    assert data["hooks"]["SessionEnd"][0]["hooks"][0]["command"] == "/x/pulse_session_end_hook.sh"
    notification = data["hooks"]["Notification"][0]
    assert notification["matcher"] == "permission_prompt"
    assert notification["hooks"][0]["command"].endswith("pulse_agent_state_hook.sh permission_prompt")
    assert (settings.parent / "settings.json.bak-agent-state").exists()
    assert (tmp_path / "plugins" / "pulse-agents.5s.sh").resolve() == PLUGIN.resolve()

    assert "déjà à jour" in _install(settings)

    assert "retirés" in _install(settings, "--uninstall")
    assert json.loads(settings.read_text()) == original
    assert not (tmp_path / "plugins" / "pulse-agents.5s.sh").exists()


def test_installer_without_settings_file_creates_it(tmp_path):
    settings = tmp_path / "claude" / "settings.json"
    _install(settings)
    assert set(json.loads(settings.read_text())["hooks"]) == {"SessionStart", "UserPromptSubmit", "PostToolUse", "Notification", "Stop", "SessionEnd"}
