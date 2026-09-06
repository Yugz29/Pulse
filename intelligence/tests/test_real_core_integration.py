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
