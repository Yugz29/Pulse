"""Interactions de show/relecture et retry/dry-run (revue du 6 septembre)."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from conftest import REFERENCE, context_view, session_view, valid_output
from pulse_intelligence import cli
from pulse_intelligence.config import Config
from pulse_intelligence.session_summary import run_pass, summary_event_id
from pulse_intelligence.state import JobState
from pulse_intelligence.summarizer import FakeSummarizer


SESSION = "aaaaaaaaaaaaaaaa"


def _versions_with_missing_readback(fake_core, client, config, state):
    fake_core.add_sessions(REFERENCE.astimezone().date().isoformat(), session_view(SESSION))
    for version, marker in (("v1", "ANCIEN RESUME"), ("v2", "NOUVEAU RESUME")):
        summarizer = FakeSummarizer(outputs=valid_output(
            reprise={"doing": marker, "stopped_at": "pause", "open": "suite"},
        ))
        report = run_pass(
            client, summarizer, replace(config, prompt_version=version), state,
            now=REFERENCE + timedelta(minutes=1 if version == "v2" else 0),
        )
        assert report.count("created") == 1
        # La panne suivante survient après le POST accepté, à sa relecture.
        fake_core.fail_readbacks = 1
    fake_core.fail_readbacks = 0
    event_id = summary_event_id(SESSION, "v2", "fake/summarizer")
    assert "event" not in state.emitted[event_id]
    fake_core.default_context = context_view(
        reference_at=REFERENCE,
        last_session_summary={"id": SESSION, **fake_core.stored[event_id]["details"]},
    )
    return event_id


@pytest.mark.parametrize("target,options", [
    (SESSION, ["--json"]),
    ("aaaa", ["--md"]),
    ("aaaa", ["--all", "--json"]),
    ("latest", ["--all"]),
])
def test_show_reads_missing_version_instead_of_silently_using_the_old_one(
    fake_core, client, config, state, capsys, target, options
):
    event_id = _versions_with_missing_readback(fake_core, client, config, state)
    # La lecture doit préserver l'annexe locale et utiliser l'identité
    # enregistrée, même si la configuration a changé depuis l'émission.
    state.emitted[event_id]["previous_summary"] = {"reprise": {"open": "ANNEXE LOCALE"}}
    state.save()
    before = state.path.read_bytes()
    capsys.readouterr()

    code = cli.main(["--core-url", fake_core.url, "--state", str(state.path),
                     "show", target, *options])
    captured = capsys.readouterr()

    assert code == cli.EXIT_OK
    assert "NOUVEAU RESUME" in captured.out
    assert ("ANCIEN RESUME" in captured.out) == ("--all" in options)
    if target == "latest":
        assert "ANNEXE LOCALE" in captured.out
    if "--json" in options:
        result = json.loads(captured.out)
        latest = result[-1] if "--all" in options else result
        assert latest["details"] == fake_core.stored[event_id]["details"]
    assert state.path.read_bytes() == before  # show ne sauvegarde jamais l'état


@pytest.mark.parametrize("failure", ["503", "404"])
def test_show_does_not_fall_back_to_stale_content_when_core_cannot_read_the_new_one(
    fake_core, client, config, state, capsys, failure
):
    event_id = _versions_with_missing_readback(fake_core, client, config, state)
    if failure == "503":
        fake_core.fail_readbacks = 1
    else:
        fake_core.stored.pop(event_id)
    before = state.path.read_bytes()
    capsys.readouterr()

    code = cli.main(["--core-url", fake_core.url, "--state", str(state.path),
                     "show", SESSION, "--json"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_INFRASTRUCTURE
    assert captured.out == ""
    assert event_id in captured.err
    assert state.path.read_bytes() == before


def test_show_resolves_an_uncached_session_by_prefix_and_stored_identity(
    fake_core, client, config, state, monkeypatch, capsys
):
    event_id = _versions_with_missing_readback(fake_core, client, config, state)
    # Une seule entrée, sans copie ; le modèle/prompt courant ne correspond
    # plus à celui enregistré. L'identifiant d'émission suffit à la retrouver.
    state.emitted = {event_id: state.emitted[event_id]}
    state.save()
    monkeypatch.setattr(cli, "load_config", lambda path: replace(config, prompt_version="v3"))
    capsys.readouterr()

    code = cli.main(["--core-url", fake_core.url, "--state", str(state.path),
                     "show", "aaaa", "--json"])

    assert code == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["event_id"] == event_id


def test_show_latest_cached_version_does_not_require_an_older_missing_copy(
    fake_core, client, config, state, capsys
):
    event_id = _versions_with_missing_readback(fake_core, client, config, state)
    state.emitted[event_id]["event"] = fake_core.payloads[event_id]
    old_id = summary_event_id(SESSION, "v1", "fake/summarizer")
    state.emitted[old_id].pop("event")
    state.save()
    fake_core.fail_readbacks = 1
    capsys.readouterr()

    code = cli.main(["--core-url", fake_core.url, "--state", str(state.path),
                     "show", SESSION, "--json"])

    assert code == cli.EXIT_OK
    assert "NOUVEAU RESUME" in capsys.readouterr().out
    assert fake_core.fail_readbacks == 1


@pytest.mark.parametrize("initial", ["fresh", "failed", "pending"])
def test_retry_dry_run_preserves_the_state_including_both_failure_key_forms(
    fake_core, tmp_path, fake_output_file, capsys, initial
):
    fake_core.add_sessions(REFERENCE.astimezone().date().isoformat(), session_view(SESSION))
    path = tmp_path / "state.json"
    base = ["--core-url", fake_core.url, "--state", str(path)]
    event_id = summary_event_id(SESSION, Config().prompt_version, "fake/summarizer")
    if initial == "pending":
        fake_core.fail_posts = 1
        assert cli.main([*base, "run", "--once", "--fake", str(fake_output_file)]) == cli.EXIT_PARTIAL
    if initial != "fresh":
        state = JobState.load(path)
        for _ in range(3):
            state.record_failure(SESSION, "abandon historique")
            state.record_failure(SESSION, "abandon de l'identité", event_id=event_id)
    before = path.read_bytes() if path.exists() else None
    before_mtime = path.stat().st_mtime_ns if path.exists() else None
    capsys.readouterr()

    code = cli.main([*base, "summarize", SESSION, "--retry", "--dry-run",
                     "--fake", str(fake_output_file)])
    captured = capsys.readouterr()

    assert code == cli.EXIT_OK and "dry_run" in captured.out
    assert "budget d'échecs effacé" not in captured.out
    assert (path.read_bytes() if path.exists() else None) == before
    assert (path.stat().st_mtime_ns if path.exists() else None) == before_mtime
    assert fake_core.posts == []
