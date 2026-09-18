"""Le repère de rattrapage : quand un passage l'avance, quand il le laisse.

Le lot du 2026-09-18 a échoué à 06:36 et à 09:18 sur un Core lent ; sans
repère, la fenêtre d'un jour aurait perdu le 17 dès le lendemain. Ici : un
passage complet pose `last_complete_pass` à son début, quel que soit le sort
de chaque candidate ; un passage interrompu (Core ou modèle injoignable) ne
le touche pas, et le suivant relit les mêmes jours.
"""

from __future__ import annotations

from datetime import timedelta

from conftest import REFERENCE, session_view, valid_output
from pulse_intelligence.core_client import CoreClient, CoreUnavailable
from pulse_intelligence.session_summary import run_pass
from pulse_intelligence.summarizer import FakeSummarizer, SummarizerUnavailable


def _today() -> str:
    return REFERENCE.astimezone().date().isoformat()


def test_a_complete_pass_records_its_start_even_with_no_candidate(client, config, state):
    started = REFERENCE - timedelta(minutes=30)

    report = run_pass(client, FakeSummarizer(outputs=[], model_id="m"), config, state, now=started)

    assert report.error is None and report.candidates == 0
    assert state.last_complete_pass_at() == started


def test_a_failed_candidate_does_not_hold_the_marker_back(fake_core, client, config, state):
    # La sortie non JSON est un verdict sur la session (tentative comptée),
    # pas une panne : la fenêtre a été lue, le repère avance.
    fake_core.add_sessions(_today(), session_view("aaaaaaaaaaaaaaaa"))
    summarizer = FakeSummarizer(outputs=["pas du json"], model_id="fake/summarizer")

    report = run_pass(client, summarizer, config, state, now=REFERENCE)

    assert [o.status for o in report.outcomes] == ["failed"]
    assert state.last_complete_pass_at() == REFERENCE


def test_a_pass_cut_by_core_leaves_the_marker_where_it_was(fake_core, config, state, monkeypatch):
    fake_core.add_sessions(_today(), session_view("aaaaaaaaaaaaaaaa"))
    previous = REFERENCE - timedelta(days=1)
    state.record_complete_pass(previous)
    client = CoreClient(fake_core.url, timeout_s=5.0)

    def core_is_gone(*args, **kwargs):
        raise CoreUnavailable("Core injoignable")

    monkeypatch.setattr(client, "get_sessions", core_is_gone)

    report = run_pass(client, FakeSummarizer(outputs=valid_output(), model_id="m"), config, state, now=REFERENCE)

    assert report.error and "injoignable" in report.error
    assert state.last_complete_pass_at() == previous


def test_a_pass_cut_by_the_model_leaves_the_marker_where_it_was(fake_core, client, config, state):
    fake_core.add_sessions(_today(), session_view("aaaaaaaaaaaaaaaa"))
    summarizer = FakeSummarizer(
        outputs=[SummarizerUnavailable("mlx: chargement du modèle : mémoire")], model_id="fake/summarizer"
    )

    report = run_pass(client, summarizer, config, state, now=REFERENCE)

    assert report.error and "modèle" in report.error
    assert state.last_complete_pass_at() is None


def test_the_next_pass_rereads_what_the_cut_one_missed(fake_core, config, state, monkeypatch):
    # Passage 1 coupé par Core ; passage 2, deux jours plus tard : la session
    # du jour 1 est encore dans la fenêtre, et résumée.
    fake_core.add_sessions(_today(), session_view("aaaaaaaaaaaaaaaa"))
    client = CoreClient(fake_core.url, timeout_s=5.0)
    real = client.get_sessions
    state.record_complete_pass(REFERENCE - timedelta(days=1))

    def gone_once(*args, **kwargs):
        monkeypatch.setattr(client, "get_sessions", real)
        raise CoreUnavailable("Core injoignable")

    monkeypatch.setattr(client, "get_sessions", gone_once)
    summarizer = FakeSummarizer(outputs=[valid_output()], model_id="fake/summarizer")

    first = run_pass(client, summarizer, config, state, now=REFERENCE)
    later = REFERENCE + timedelta(days=2)
    second = run_pass(client, summarizer, config, state, now=later)

    assert first.error and second.error is None
    assert [o.status for o in second.outcomes] == ["created"]
    assert fake_core.requested_dates[-4:] == [
        (later.astimezone().date() - timedelta(days=offset)).isoformat() for offset in range(4)
    ]
    assert state.last_complete_pass_at() == later
