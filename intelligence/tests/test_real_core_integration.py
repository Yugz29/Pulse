"""Intelligence ↔ vrai Core : le contrat réel, pas le faux (audit 2026-09-06,
défauts 2 et 3). Core tourne **en sous-processus** (`daemon_v2.main`) sur une
base temporaire, sans watchers ni outbox : Intelligence n'importe rien de
Core, tests compris (principe 1, `test_isolation.py`).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import requests

from conftest import REFERENCE, valid_output
from pulse_intelligence.core_client import CoreClient
from pulse_intelligence.selection import fetch_sessions
from pulse_intelligence.session_summary import summarize_session
from pulse_intelligence.state import JobState
from pulse_intelligence.summarizer import FakeSummarizer


CORE_DIR = Path(__file__).resolve().parents[2] / "core"


def _core_interpreter() -> str:
    """La venv de Core quand elle existe (dépendances épinglées), sinon
    l'interpréteur courant : Core n'a besoin que de Flask pour servir."""
    candidate = CORE_DIR / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def real_core(tmp_path):
    if not (CORE_DIR / "daemon_v2" / "main.py").exists():
        pytest.skip("core/ absent du dépôt")
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PULSE_V2_DB_PATH": str(tmp_path / "trace.db"),
        "PULSE_CORE_HOST": "127.0.0.1",
        "PULSE_CORE_PORT": str(port),
        "PULSE_CORE_EVENT_LOG": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    (tmp_path / "home").mkdir()
    process = subprocess.Popen(
        [_core_interpreter(), "-m", "daemon_v2.main"],
        cwd=CORE_DIR, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                if requests.get(f"{url}/status", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                pass
            if process.poll() is not None:
                raise RuntimeError(f"Core n'a pas démarré : {process.stderr.read()[-800:]}")
            if time.monotonic() > deadline:
                raise RuntimeError("Core ne répond pas sur /status après 15 s")
            time.sleep(0.1)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _file_changed(minutes_before_reference: int, index: int) -> dict:
    occurred = REFERENCE - timedelta(minutes=minutes_before_reference)
    return {
        "event_id": str(uuid.uuid4()),
        "schema_version": 1,
        "type": "file_changed",
        "producer": {"name": "pulse-test", "version": "1.0", "instance_id": "integration"},
        "occurred_at": occurred.isoformat(),
        "details": {
            "path": f"/project/Pulse/src/module_{index}.py",
            "event": "modified",
            "workspace": "/project/Pulse",
        },
    }


def _seed_one_closed_session(client: CoreClient) -> None:
    # 30 modifications de 10:00 à 10:12 UTC ; lecture à 16:00 : session
    # de travail fermée par inactivité, éligible (≥ 10 min, ≥ 30 activités).
    for index in range(30):
        minutes = 360 - int(index * 12 / 29)
        result = client.post_activity(_file_changed(minutes, index))
        assert result.status_code == 201, result


def test_lost_state_recovers_the_summary_core_already_accepted(real_core, config, tmp_path):
    client = CoreClient(real_core, timeout_s=5.0)
    _seed_one_closed_session(client)
    sessions = fetch_sessions(client, REFERENCE.astimezone().date(), at=REFERENCE)
    assert len(sessions) == 1 and sessions[0].is_open is False
    session = sessions[0]
    assert session.duration_minutes >= 10 and session.activity_count == 30
    # La sortie fixe cite un fichier réellement présent dans la vue servie par
    # Core : la validation des chemins est la vraie, pas une fixture.
    output = json.loads(valid_output())
    output["structured"]["central_files"] = [session.raw["files"]["modified"][0]]
    summarizer = FakeSummarizer(outputs=json.dumps(output), model_id="fake/summarizer")

    first = summarize_session(
        session, client=client, summarizer=summarizer, config=config,
        state=JobState.load(tmp_path / "state-a" / "state.json"),
    )
    # Perte de l'état local : même session, mêmes versions, état vide.
    fresh = JobState.load(tmp_path / "state-b" / "state.json")
    second = summarize_session(
        session, client=client, summarizer=summarizer, config=config, state=fresh,
    )

    assert first.status == "created", first
    assert second.status == "already_known", second
    assert "Core" in (second.detail or "")
    assert len(summarizer.calls) == 1  # aucune régénération
    assert fresh.knows(first.event_id)
    assert fresh.emitted[first.event_id]["origin"] == "core"
    # Ce que Core a stocké, pas ce qu'on aurait régénéré : même reprise.
    stored = client.get_activity(first.event_id)
    assert stored is not None and stored["type"] == "session_summary"
    assert stored["details"]["reprise"] == first.event["details"]["reprise"]
    assert fresh.emitted[first.event_id]["event"]["details"] == stored["details"]
    # Le 409 est préservé : un contenu différent sous le même id reste refusé.
    conflicting = dict(first.event)
    conflicting["details"] = {**first.event["details"], "generated_at": "2030-01-01T00:00:00+00:00"}
    assert client.post_activity(conflicting).status_code == 409


def test_both_show_paths_display_the_event_core_accepted_with_secrets_redacted(
    real_core, tmp_path, monkeypatch, capsys
):
    """Audit 2026-09-06, défaut 9, marqueurs artificiels : `TOKEN=audit-secret-123`
    dans `doing`, `TOKEN=audit-project-secret` dans `structured.project`. Après
    émission, `show <id>` et `show latest` affichent ce que Core a accepté :
    `[REDACTED]` partout, aucun chemin ne fait réapparaître un marqueur. Le
    seul Core qui rédige est le vrai : cette assertion ne vit qu'ici."""
    from pulse_intelligence import cli

    client = CoreClient(real_core, timeout_s=5.0)
    _seed_one_closed_session(client)
    session = fetch_sessions(client, REFERENCE.astimezone().date(), at=REFERENCE)[0]
    output = json.loads(valid_output())
    output["reprise"]["doing"] = "Tu réglais TOKEN=audit-secret-123 dans la config."
    output["structured"]["project"] = "TOKEN=audit-project-secret"
    output["structured"]["central_files"] = [session.raw["files"]["modified"][0]]
    marked = tmp_path / "marked.json"
    marked.write_text(json.dumps(output), encoding="utf-8")
    monkeypatch.setattr(cli, "_now", lambda: REFERENCE)
    base = ["--core-url", real_core, "--state", str(tmp_path / "state.json")]

    assert cli.main([*base, "run", "--once", "--fake", str(marked)]) == 0
    run_out = capsys.readouterr()
    by_id = cli.main([*base, "show", session.id, "--json"])
    by_id_out = capsys.readouterr().out
    card = cli.main([*base, "show", session.id])
    card_out = capsys.readouterr().out
    latest = cli.main([*base, "show", "latest"])
    latest_out = capsys.readouterr().out

    assert by_id == card == latest == 0
    event_id = json.loads(by_id_out)["event_id"]
    stored = client.get_activity(event_id)
    assert json.loads(by_id_out)["details"] == stored["details"]
    for text in (by_id_out, card_out, latest_out, run_out.out, run_out.err):
        assert "audit-secret-123" not in text
        assert "audit-project-secret" not in text
    assert stored["details"]["structured"]["project"] == "TOKEN=[REDACTED]"
    assert "TOKEN=[REDACTED]" in card_out and "TOKEN=[REDACTED]" in latest_out
    state = JobState.load(tmp_path / "state.json")
    assert state.emitted[event_id]["origin"] == "core"
    assert json.dumps(state.emitted[event_id]).count("audit-") == 0


def _assert_source_unchanged(client, session, *, event_count):
    """L'enrichissement ne devient pas une activité source de sa propre session."""
    sessions = fetch_sessions(client, REFERENCE.date(), at=REFERENCE)
    assert len(sessions) == 1
    current = sessions[0]
    assert current.id == session.id
    assert current.ended_at == session.ended_at
    assert current.raw["source_event_ids"] == session.raw["source_event_ids"]
    assert current.activity_count == 30
    response = requests.get(
        f"{client.base_url}/trace/{REFERENCE.date().isoformat()}", timeout=5,
    )
    response.raise_for_status()
    assert response.json()["activity_count"] == event_count


@pytest.mark.parametrize("restart_command", ["summarize", "run"])
def test_sigkill_after_core_acceptance_replays_without_regenerating(
    real_core, tmp_path, restart_command
):
    from cli_process_support import cli_environment, paused_cli, run_cli

    client = CoreClient(real_core, timeout_s=5)
    _seed_one_closed_session(client)
    session = fetch_sessions(client, REFERENCE.date(), at=REFERENCE)[0]
    output = json.loads(valid_output())
    output["structured"]["central_files"] = [session.raw["files"]["modified"][0]]
    fake = tmp_path / "output.json"
    fake.write_text(json.dumps(output), encoding="utf-8")
    path = tmp_path / "state.json"
    base = ["--core-url", real_core, "--state", str(path)]
    command = ["summarize", session.id, "--date", REFERENCE.date().isoformat()]
    env = cli_environment(tmp_path)

    with paused_cli([*base, *command, "--fake", str(fake)], env,
                    stage="after_acceptance") as process:
        pending = JobState.load(path)
        assert len(pending.pending) == 1 and pending.emitted == {}
        event_id = next(iter(pending.pending))
        frozen = pending.pending_event(event_id)
        accepted = client.get_activity(event_id)
        assert accepted is not None
        assert accepted["details"]["reprise"] == frozen["details"]["reprise"]
        process.kill()
        process.communicate(timeout=5)
        assert process.returncode < 0

    # Toute régénération ferait échouer la validation. Le rejeu doit utiliser
    # le payload durable, même après la disparition brutale du détenteur du verrou.
    fake.write_text("invalid model output", encoding="utf-8")
    if restart_command == "run":
        command = ["run", "--once"]
    restarted = run_cli([*base, *command, "--fake", str(fake)], env)
    assert restarted.returncode == 0, (restarted.stdout, restarted.stderr)
    assert "duplicate" in restarted.stdout
    state = JobState.load(path)
    assert state.pending == {} and state.failures == {} and state.failed == {}
    assert set(state.emitted) == {event_id}
    assert state.emitted[event_id]["event"]["details"] == accepted["details"]
    assert client.get_activity(event_id) == accepted
    _assert_source_unchanged(client, session, event_count=31)


def test_restored_backup_with_conflicting_pending_recovers_actual_core_version(
    real_core, config, tmp_path
):
    from pulse_intelligence.session_summary import run_pass

    client = CoreClient(real_core, timeout_s=5)
    _seed_one_closed_session(client)
    session = fetch_sessions(client, REFERENCE.date(), at=REFERENCE)[0]
    output = json.loads(valid_output())
    output["structured"]["central_files"] = [session.raw["files"]["modified"][0]]
    summarizer = FakeSummarizer(outputs=json.dumps(output), model_id=config.model_id)
    state = JobState.load(tmp_path / "state.json")
    draft = summarize_session(
        session, client=client, summarizer=summarizer, config=config,
        state=state, dry_run=True, now=REFERENCE,
    )
    state.record_pending(
        draft.event_id, session_id=session.id, prompt_version=config.prompt_version,
        model_id=config.model_id, at=REFERENCE.isoformat(), event=draft.event,
    )
    backup = state.path.read_bytes()
    # Une autre installation a émis une version différente sous la même identité.
    accepted = summarize_session(
        session, client=client, summarizer=summarizer, config=config,
        state=JobState.load(tmp_path / "other.json"), now=REFERENCE + timedelta(minutes=1),
    )
    assert accepted.status == "created"
    assert client.post_activity(draft.event).status_code == 409
    state.path.write_bytes(backup)
    no_generation = FakeSummarizer(outputs="invalid model output", model_id=config.model_id)
    report = run_pass(
        client, no_generation, config, JobState.load(state.path),
        now=REFERENCE + timedelta(days=3),
    )
    assert report.candidates == 0 and report.replayed == 1
    assert [outcome.status for outcome in report.outcomes] == ["already_known"]
    assert no_generation.calls == []
    recovered = JobState.load(state.path)
    assert recovered.pending == {} and recovered.failures == {} and recovered.failed == {}
    assert recovered.emitted[draft.event_id]["event"] == accepted.event
    _assert_source_unchanged(client, session, event_count=31)


@pytest.mark.parametrize("all_versions", [False, True], ids=["latest-version", "all-versions"])
def test_show_after_readback_failure_recovers_newest_redacted_version(
    real_core, config, tmp_path, monkeypatch, capsys, all_versions
):
    from dataclasses import replace
    from pulse_intelligence import cli
    from pulse_intelligence.core_client import CoreUnavailable

    client = CoreClient(real_core, timeout_s=5)
    _seed_one_closed_session(client)
    session = fetch_sessions(client, REFERENCE.date(), at=REFERENCE)[0]
    state = JobState.load(tmp_path / "state.json")
    output = json.loads(valid_output())
    output["structured"]["central_files"] = [session.raw["files"]["modified"][0]]
    output["reprise"]["doing"] = "ANCIEN RESUME"
    first = summarize_session(
        session, client=client, config=config, state=state,
        summarizer=FakeSummarizer(outputs=json.dumps(output), model_id=config.model_id),
        now=REFERENCE,
    )
    assert first.status == "created"
    original = client.get_activity
    missed = []

    def lose_readback(event_id):
        stored = original(event_id)
        if stored is not None:
            missed.append(event_id)
            raise CoreUnavailable("injected readback connection loss")
        return stored

    monkeypatch.setattr(client, "get_activity", lose_readback)
    output["reprise"]["doing"] = "NOUVEAU RESUME : TOKEN=synthetic-private-value"
    second = summarize_session(
        session, client=client, config=replace(config, prompt_version="v2"), state=state,
        summarizer=FakeSummarizer(outputs=json.dumps(output), model_id=config.model_id),
        now=REFERENCE + timedelta(minutes=1),
    )
    assert second.status == "created" and missed == [second.event_id]
    assert "event" not in state.emitted[second.event_id]
    before = state.path.read_bytes()
    mtime = state.path.stat().st_mtime_ns
    capsys.readouterr()
    args = ["--core-url", real_core, "--state", str(state.path),
            "show", session.id[:8], "--json"]
    if all_versions:
        args.append("--all")
    assert cli.main(args) == 0
    displayed = capsys.readouterr().out
    result = json.loads(displayed)
    latest = result[-1] if all_versions else result
    assert latest["event_id"] == second.event_id
    assert latest["details"] == original(second.event_id)["details"]
    assert "NOUVEAU RESUME" in displayed and "TOKEN=[REDACTED]" in displayed
    assert "synthetic-private-value" not in displayed
    assert ("ANCIEN RESUME" in displayed) == all_versions
    assert state.path.read_bytes() == before and state.path.stat().st_mtime_ns == mtime
    assert "synthetic-private-value" not in before.decode()
    _assert_source_unchanged(client, session, event_count=32)


@pytest.mark.slow
def test_real_mlx_summary_is_accepted_shown_and_not_generated_twice(
    real_core, tmp_path, monkeypatch, capsys
):
    """Parcours CLI → MLX → vrai Core → état → show, sans modèle simulé."""
    from pulse_intelligence import cli
    from pulse_intelligence.llm.mlx import DEFAULT_MODEL, MLXProvider

    client = CoreClient(real_core, timeout_s=5)
    _seed_one_closed_session(client)
    session = fetch_sessions(client, REFERENCE.date(), at=REFERENCE)[0]
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'llm_provider = "mlx"\nmodel_id = "{DEFAULT_MODEL}"\nprompt_version = "v2"\n',
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    base = ["--config", str(config_path), "--core-url", real_core, "--state", str(state_path)]
    args = [*base, "summarize", session.id, "--date", REFERENCE.date().isoformat()]
    assert cli.main(args) == 0
    first_output = capsys.readouterr()
    assert "created" in first_output.out
    state = JobState.load(state_path)
    assert len(state.emitted) == 1 and state.pending == {} and state.failures == {}
    event_id = next(iter(state.emitted))
    stored = client.get_activity(event_id)
    assert stored is not None and stored["type"] == "session_summary"
    assert state.emitted[event_id]["model_id"] == DEFAULT_MODEL
    assert state.emitted[event_id]["prompt_version"] == "v2"
    assert state.emitted[event_id]["event"]["details"] == stored["details"]

    def forbidden_loading(*args, **kwargs):
        pytest.fail("Un résumé déjà accepté ne doit pas recharger le modèle")

    monkeypatch.setattr(MLXProvider, "_ensure_loaded", forbidden_loading)
    before = state_path.read_bytes()
    assert cli.main(args) == 0
    assert "already_known" in capsys.readouterr().out
    assert cli.main([*base, "show", session.id, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["event_id"] == event_id and shown["details"] == stored["details"]
    assert state_path.read_bytes() == before
    _assert_source_unchanged(client, session, event_count=31)
