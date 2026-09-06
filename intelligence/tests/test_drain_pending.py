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
    state.record_failure(SESSION, "tentative 2: Core 503", event_id=EVENT_ID)
    state.record_failure(SESSION, "tentative 3: Core 503", event_id=EVENT_ID)
    assert state.is_failed(SESSION, EVENT_ID)

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


# --- vidage et identité, récupération après conflit (relecture 2026-09-06, sondes A et B) ---


def _abandon_the_pending(fake_core, client, config, state_path) -> FakeSummarizer:
    """Trois refus Core du payload figé : l'identité v1 est abandonnée, le
    `pending` reste sur disque."""
    summarizer = _freeze_a_pending(fake_core, client, config, state_path)
    fake_core.fail_posts = 2
    statuses = [
        run_pass(client, summarizer, config, JobState.load(state_path), now=REFERENCE).outcomes[0].status
        for _ in range(2)
    ]
    assert statuses == ["failed", "given_up"]
    state = JobState.load(state_path)
    assert state.is_failed(SESSION, EVENT_ID) and state.pending_event(EVENT_ID) is not None
    return summarizer


def test_a_pending_given_up_under_an_old_identity_does_not_hide_the_session_from_a_new_one(
    fake_core, client, config, tmp_path
):
    """Sonde A : le `pending` v1 est abandonné, la configuration passe en v2.
    Aujourd'hui `run` rapporte given_up et n'appelle jamais le modèle pour v2.
    Attendu : le saut post-vidage porte sur l'identité rejouée, pas sur la
    session ; v2 est une vraie candidate, résumée et émise."""
    from dataclasses import replace

    state_path = tmp_path / "state" / "state.json"
    _abandon_the_pending(fake_core, client, config, state_path)
    v2 = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")

    report = run_pass(client, v2, replace(config, prompt_version="v2"), JobState.load(state_path), now=REFERENCE)

    assert [o.status for o in report.outcomes] == ["given_up", "created"]
    assert report.outcomes[0].event_id == EVENT_ID  # l'abandon v1 est toujours rapporté
    assert report.outcomes[1].event_id == summary_event_id(SESSION, "v2", "fake/summarizer")
    assert len(v2.calls) == 1 and len(fake_core.posts) == 1
    assert fake_core.posts[0]["details"]["prompt_version"] == "v2"
    after = JobState.load(state_path)
    assert after.is_failed(SESSION, EVENT_ID) and after.pending_event(EVENT_ID) is not None  # v1 intact
    assert after.knows(summary_event_id(SESSION, "v2", "fake/summarizer"))


def test_a_pending_given_up_under_the_current_identity_is_reported_once(
    fake_core, client, config, tmp_path
):
    """Contrôle : même identité, l'abandon est rapporté une fois par passage,
    pas une fois par le vidage et une fois par la sélection."""
    state_path = tmp_path / "state" / "state.json"
    summarizer = _abandon_the_pending(fake_core, client, config, state_path)

    report = run_pass(client, summarizer, config, JobState.load(state_path), now=REFERENCE)

    assert [o.status for o in report.outcomes] == ["given_up"]
    assert report.candidates == 1 and fake_core.posts == []


def test_a_restored_pending_that_conflicts_with_core_is_recovered_not_abandoned(
    fake_core, client, config, tmp_path
):
    """Sonde B, restauration de sauvegarde (critère 3 de l'audit) : un état
    sauvegardé avec un `pending` T1 ; l'état vivant perd ce `pending`,
    régénère T2 que Core accepte ; la sauvegarde est restaurée. Aujourd'hui
    le rejeu de T1 reçoit 409 trois fois, la session est abandonnée et
    ignorée alors que Core détient le résumé. Attendu : sur 409, Intelligence
    relit Core et reprend l'événement accepté, sans consommer le budget."""
    state_path = tmp_path / "state" / "state.json"
    summarizer = _freeze_a_pending(fake_core, client, config, state_path)  # T1 figé, Core en panne
    backup = state_path.read_text(encoding="utf-8")
    live = JobState.load(state_path)
    live.pending.clear()
    live.save()
    regenerated = run_pass(client, summarizer, config, JobState.load(state_path), now=REFERENCE + timedelta(minutes=1))
    assert [o.status for o in regenerated.outcomes] == ["created"]  # T2, accepté par Core
    state_path.write_text(backup, encoding="utf-8")
    assert JobState.load(state_path).pending_event(EVENT_ID) == fake_core.refused[0]  # T1 de retour
    posts_before = len(fake_core.posts)

    report = run_pass(client, summarizer, config, JobState.load(state_path), now=REFERENCE + timedelta(days=1))

    assert report.replayed == 1
    assert [o.status for o in report.outcomes] == ["already_known"]
    assert "conflit" in (report.outcomes[0].detail or "")
    assert len(fake_core.posts) == posts_before + 1  # le rejeu de T1, refusé 409, rien d'autre
    assert len(summarizer.calls) == 2  # T1 puis T2 : aucune régénération
    after = JobState.load(state_path)
    assert after.knows(EVENT_ID) and after.pending == {}
    assert after.failures == {} and after.failed == {}  # zéro budget consommé
    entry = after.emitted[EVENT_ID]
    assert entry["origin"] == "core"
    assert entry["event"]["details"] == fake_core.stored[EVENT_ID]["details"]  # T2, tel que Core l'a stocké
    again = run_pass(client, summarizer, config, JobState.load(state_path), now=REFERENCE + timedelta(days=1, minutes=1))
    assert again.outcomes == [] and len(fake_core.posts) == posts_before + 1


def test_a_replayed_pending_refused_again_is_not_posted_twice_in_the_same_pass(
    fake_core, client, config, tmp_path
):
    """Contrôle du cas que #63 protégeait : le rejeu refusé (503) garde son
    unique tentative du passage ; la sélection, qui voit encore la session
    dans la fenêtre, ne la POSTe pas une seconde fois."""
    state_path = tmp_path / "state" / "state.json"
    summarizer = _freeze_a_pending(fake_core, client, config, state_path)
    fake_core.fail_posts = 1

    report = run_pass(client, summarizer, config, JobState.load(state_path), now=REFERENCE + timedelta(minutes=10))

    assert report.candidates == 1 and report.replayed == 1
    assert [o.status for o in report.outcomes] == ["failed"]
    assert "tentative 2" in (report.outcomes[0].detail or "")
    assert len(fake_core.refused) == 2 and fake_core.posts == []
    assert JobState.load(state_path).failures == {EVENT_ID: 2}
    assert len(summarizer.calls) == 1
