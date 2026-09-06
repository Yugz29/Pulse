"""Budget d'échecs par identité de résumé, pas par session, et distinction
entre sortie invalide, refus d'entrée, panne transitoire et indisponibilité
du modèle (audit 2026-09-06, défaut 5).
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from conftest import REFERENCE, session_view, valid_output
from pulse_intelligence import cli
from pulse_intelligence.session_summary import run_pass, summary_event_id
from pulse_intelligence.state import JobState
from pulse_intelligence.summarizer import FakeSummarizer, SummarizerError


SESSION = "aaaaaaaaaaaaaaaa"
V1 = summary_event_id(SESSION, "v1", "fake/summarizer")


def today() -> str:
    return REFERENCE.astimezone().date().isoformat()


def _three_invalid_then_given_up(fake_core, client, config, state) -> FakeSummarizer:
    fake_core.add_sessions(today(), session_view(SESSION))
    summarizer = FakeSummarizer(outputs="pas du json", model_id="fake/summarizer")
    statuses = [run_pass(client, summarizer, config, state, now=REFERENCE).outcomes[0].status for _ in range(3)]
    assert statuses == ["failed", "failed", "given_up"]
    assert len(summarizer.calls) == 3
    return summarizer


def test_a_new_prompt_version_gets_a_real_attempt_after_a_given_up(fake_core, client, config, state):
    """Scénario de l'audit : given_up sur v1, puis v2 → aujourd'hui given_up
    sans appel au modèle. Attendu : une vraie tentative, et un résumé."""
    _three_invalid_then_given_up(fake_core, client, config, state)
    fresh = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")

    report = run_pass(client, fresh, replace(config, prompt_version="v2"), state, now=REFERENCE)

    assert [o.status for o in report.outcomes] == ["created"]
    assert len(fresh.calls) == 1 and len(fake_core.posts) == 1
    assert fake_core.posts[0]["details"]["prompt_version"] == "v2"
    # L'abandon de v1 n'a pas bougé : même session, autre identité.
    assert state.is_failed(SESSION, V1)


def test_a_new_model_gets_a_real_attempt_after_a_given_up(fake_core, client, config, state):
    _three_invalid_then_given_up(fake_core, client, config, state)
    other = FakeSummarizer(outputs=valid_output(), model_id="other/model")

    report = run_pass(client, other, config, state, now=REFERENCE)

    assert [o.status for o in report.outcomes] == ["created"]
    assert len(other.calls) == 1
    assert fake_core.posts[0]["details"]["model_id"] == "other/model"


def test_transient_provider_errors_never_reach_given_up(fake_core, client, config, state):
    """Trois indisponibilités transitoires (timeout, 5xx…) : failed trois
    fois, jamais abandonnée, aucune tentative consommée ; le quatrième
    passage résume."""
    fake_core.add_sessions(today(), session_view(SESSION))
    outage = SummarizerError("openai-compatible: délai dépassé")
    summarizer = FakeSummarizer(outputs=[outage, outage, outage, valid_output()], model_id="fake/summarizer")

    statuses = [run_pass(client, summarizer, config, state, now=REFERENCE).outcomes[0].status for _ in range(4)]

    assert statuses == ["failed", "failed", "failed", "created"]
    assert len(summarizer.calls) == 4
    assert not state.is_failed(SESSION, V1)
    assert state.failures == {}


def test_a_refused_input_consumes_the_budget_like_an_invalid_output(fake_core, client, config, state):
    from pulse_intelligence.summarizer import SummarizerInputRefused

    fake_core.add_sessions(today(), session_view(SESSION))
    refused = SummarizerInputRefused("mlx: entrée de 50000 tokens au-dessus du plafond 30000")
    summarizer = FakeSummarizer(outputs=[refused], model_id="fake/summarizer")

    statuses = [run_pass(client, summarizer, config, state, now=REFERENCE).outcomes[0].status for _ in range(4)]

    assert statuses == ["failed", "failed", "given_up", "given_up"]
    assert len(summarizer.calls) == 3
    assert state.is_failed(SESSION, V1)


def test_an_unavailable_model_stops_the_pass_like_a_core_outage(fake_core, client, config, state):
    """Modèle non chargeable ou endpoint injoignable : la même erreur pour
    toutes. Arrêt à la première, aucune tentative consommée."""
    from pulse_intelligence.summarizer import SummarizerUnavailable

    fake_core.add_sessions(
        today(),
        session_view(SESSION),
        session_view("bbbbbbbbbbbbbbbb", label="work-2", started=-200, ended=-150),
        session_view("cccccccccccccccc", label="work-3", started=-140, ended=-100),
    )
    summarizer = FakeSummarizer(
        outputs=[SummarizerUnavailable("mlx: chargement du modèle : mémoire")], model_id="fake/summarizer"
    )

    report = run_pass(client, summarizer, config, state, now=REFERENCE)

    assert report.candidates == 3 and report.outcomes == []
    assert report.error and "modèle" in report.error
    assert len(summarizer.calls) == 1
    assert state.failures == {} and state.failed == {}


def test_cli_run_once_exits_2_when_the_model_is_unavailable(fake_core, tmp_path, monkeypatch, capsys):
    from pulse_intelligence.summarizer import SummarizerUnavailable

    fake_core.add_sessions(today(), session_view(SESSION))
    monkeypatch.setattr(
        cli, "_summarizer",
        lambda args, config: FakeSummarizer(outputs=[SummarizerUnavailable("mlx-lm absent")], model_id="fake/summarizer"),
    )

    code = cli.main([*_base(fake_core, tmp_path), "run", "--once", "--fake", "unused"])

    assert code == cli.EXIT_INFRASTRUCTURE
    assert "mlx-lm absent" in capsys.readouterr().err


def test_a_legacy_session_keyed_state_is_honoured_and_preserved(fake_core, client, config, tmp_path):
    """Ancien état : `failed` et `failures` par session (16 hex). Toujours
    respecté comme abandon de la session, et resauvegardé à l'identique."""
    fake_core.add_sessions(today(), session_view(SESSION))
    path = tmp_path / "state" / "state.json"
    path.parent.mkdir(parents=True)
    before = {
        "emitted": {}, "pending": {},
        "failures": {SESSION: 3},
        "failed": {SESSION: "tentative 3: sortie non JSON"},
    }
    path.write_text(json.dumps(before), encoding="utf-8")
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")
    state = JobState.load(path)

    report = run_pass(client, summarizer, config, state, now=REFERENCE)
    state.save()

    assert [o.status for o in report.outcomes] == ["given_up"]
    assert report.outcomes[0].detail == "tentative 3: sortie non JSON"
    assert summarizer.calls == []
    assert json.loads(path.read_text(encoding="utf-8")) == before


def test_summarize_retry_clears_both_key_forms_and_replays_the_pending(
    fake_core, tmp_path, monkeypatch, capsys
):
    """`summarize <id> --retry` : efface l'abandon sous ses deux formes de clé
    (session et identité) et repart ; un `pending` existant est rejoué tel
    que figé, sans appel au modèle."""
    from pulse_intelligence.config import Config

    fake_core.add_sessions(today(), session_view(SESSION))
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")
    monkeypatch.setattr(cli, "_summarizer", lambda args, config: summarizer)
    path = tmp_path / "state.json"
    base = [*_base_path(fake_core, path)]
    # Jour J : Core refuse, le payload validé est gelé en pending (tentative 1).
    fake_core.fail_posts = 1
    assert cli.main([*base, "run", "--once", "--fake", "unused"]) == cli.EXIT_PARTIAL
    capsys.readouterr()
    cli_id = summary_event_id(SESSION, Config().prompt_version, "fake/summarizer")
    frozen = JobState.load(path).pending_event(cli_id)
    assert frozen is not None and len(summarizer.calls) == 1
    # Abandon sous les deux formes : clé ancienne (session) et identité.
    state = JobState.load(path)
    for _ in range(3):
        state.record_failure(SESSION, "tentative 3: Core 503")
        state.record_failure(SESSION, "tentative 3: Core 503", event_id=cli_id)
    assert state.is_failed(SESSION) and state.is_failed(SESSION, cli_id)

    without = cli.main([*base, "summarize", SESSION, "--fake", "unused"])
    without_out = capsys.readouterr().out
    code = cli.main([*base, "summarize", SESSION, "--retry", "--fake", "unused"])
    out = capsys.readouterr().out

    assert without == cli.EXIT_USAGE and "given_up" in without_out
    assert code == cli.EXIT_OK and "created" in out
    assert len(fake_core.posts) == 1 and fake_core.posts[0] == frozen  # tel que figé
    assert len(summarizer.calls) == 1  # aucune régénération
    after = JobState.load(path)
    assert after.failed == {} and after.failures == {} and after.pending == {}
    assert after.knows(cli_id)


def _base(fake_core, tmp_path) -> list[str]:
    return _base_path(fake_core, tmp_path / "state.json")


def _base_path(fake_core, path) -> list[str]:
    return ["--core-url", fake_core.url, "--state", str(path)]
