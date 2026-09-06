"""Vidage de la file `pending` indépendant de la fenêtre de sélection
(audit 2026-09-06, défaut 4 ; contraintes de l'issue #62).

Un payload gelé après une panne Core doit repartir au passage suivant même
si sa session est sortie de la fenêtre `lookback_days` : tel que figé,
sans modèle, sans commande datée. Le budget d'échecs et le 409 restent.
"""

from __future__ import annotations

import json
from datetime import timedelta

from conftest import REFERENCE, session_view, valid_output
from pulse_intelligence import cli
from pulse_intelligence.session_summary import run_pass, summary_event_id
from pulse_intelligence.state import JobState
from pulse_intelligence.summarizer import FakeSummarizer


SESSION = "aaaaaaaaaaaaaaaa"
EVENT_ID = summary_event_id(SESSION, "v1", "fake/summarizer")


def today() -> str:
    return REFERENCE.astimezone().date().isoformat()


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _freeze_a_pending(fake_core, client, config, state_path) -> FakeSummarizer:
    """Jour J : Core refuse le POST, le payload validé reste `pending`."""
    fake_core.add_sessions(today(), session_view(SESSION))
    fake_core.fail_posts = 1
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")
    report = run_pass(client, summarizer, config, JobState.load(state_path), now=REFERENCE)
    assert [o.status for o in report.outcomes] == ["failed"]
    assert JobState.load(state_path).pending_event(EVENT_ID) == fake_core.refused[0]
    return summarizer


def test_a_pending_out_of_the_window_is_drained_as_frozen_without_the_model(
    fake_core, client, config, tmp_path
):
    """Scénario de l'audit : résumé figé le 6, redémarrage le 9 avec
    lookback_days=1. Aujourd'hui candidates=0, pending=1, aucun POST."""
    state_path = tmp_path / "state" / "state.json"
    summarizer = _freeze_a_pending(fake_core, client, config, state_path)
    three_days_later = REFERENCE + timedelta(days=3)

    report = run_pass(client, summarizer, config, JobState.load(state_path), now=three_days_later)

    assert report.candidates == 0  # la session est hors fenêtre
    assert len(fake_core.posts) == 1  # aujourd'hui : aucun POST, pending=1
    assert report.replayed == 1
    assert [o.status for o in report.outcomes] == ["created"]
    assert report.outcomes[0].session_id == SESSION and report.outcomes[0].event_id == EVENT_ID
    assert canonical(fake_core.posts[0]) == canonical(fake_core.refused[0])  # tel que figé
    assert len(summarizer.calls) == 1  # aucun nouvel appel modèle
    assert fake_core.context_requests == 1  # ni /context
    confirmed = JobState.load(state_path)
    assert confirmed.knows(EVENT_ID) and confirmed.pending == {}


def test_a_replayed_pending_that_core_still_refuses_counts_as_failed(
    fake_core, client, config, tmp_path
):
    state_path = tmp_path / "state" / "state.json"
    summarizer = _freeze_a_pending(fake_core, client, config, state_path)
    fake_core.fail_posts = 1

    report = run_pass(
        client, summarizer, config, JobState.load(state_path), now=REFERENCE + timedelta(days=3)
    )

    assert report.replayed == 1 and report.count("failed") == 1
    assert report.outcomes[0].detail and "tentative 2" in report.outcomes[0].detail
    assert JobState.load(state_path).pending_event(EVENT_ID) == fake_core.refused[0]
    assert len(summarizer.calls) == 1


def test_a_pending_of_a_given_up_session_stays_on_disk(fake_core, client, config, tmp_path):
    """Note de la spec : pas rejoué par le vidage, il attend une reprise
    explicite (--retry, PR 2). Il compte comme given_up dans le bilan."""
    state_path = tmp_path / "state" / "state.json"
    summarizer = _freeze_a_pending(fake_core, client, config, state_path)
    state = JobState.load(state_path)
    state.record_failure(SESSION, "tentative 2: Core 503")
    state.record_failure(SESSION, "tentative 3: Core 503")
    assert state.is_failed(SESSION)

    report = run_pass(client, summarizer, config, JobState.load(state_path), now=REFERENCE + timedelta(days=3))

    assert report.replayed == 0
    assert [o.status for o in report.outcomes] == ["given_up"]
    assert fake_core.posts == []
    assert JobState.load(state_path).pending_event(EVENT_ID) == fake_core.refused[0]


def test_a_drained_session_still_in_the_window_is_not_posted_twice(
    fake_core, client, config, tmp_path
):
    """Le vidage précède la sélection : la session, encore dans la fenêtre,
    est ensuite connue, donc plus candidate. Un seul POST, zéro modèle."""
    state_path = tmp_path / "state" / "state.json"
    summarizer = _freeze_a_pending(fake_core, client, config, state_path)

    report = run_pass(
        client, summarizer, config, JobState.load(state_path), now=REFERENCE + timedelta(minutes=10)
    )

    assert report.replayed == 1 and report.candidates == 0
    assert [o.status for o in report.outcomes] == ["created"]
    assert len(fake_core.posts) == 1 and len(summarizer.calls) == 1


def test_cli_run_once_reports_the_drain_and_keeps_the_exit_codes(
    fake_core, tmp_path, fake_output_file, capsys
):
    """`replayed=` dans le bilan ; un rejeu qui échoue encore vaut 3 (#56)."""
    fake_core.add_sessions(today(), session_view(SESSION))
    fake_core.fail_posts = 1
    args = [*_base(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)]
    assert cli.main(args) == cli.EXIT_PARTIAL
    capsys.readouterr()

    fake_core.fail_posts = 1
    still_failing = cli.main(args)
    failing_out = capsys.readouterr().out
    accepted = cli.main(args)
    accepted_out = capsys.readouterr().out

    assert still_failing == cli.EXIT_PARTIAL
    assert "replayed=1" in failing_out and "failed=1" in failing_out
    assert accepted == cli.EXIT_OK
    assert "replayed=1" in accepted_out and "created=1" in accepted_out
    assert len(fake_core.posts) == 1


def _base(fake_core, tmp_path) -> list[str]:
    return ["--core-url", fake_core.url, "--state", str(tmp_path / "state.json")]
