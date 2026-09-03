"""Idempotence des résumés (audit 2026-09-03) : le payload canonique est
gelé dans l'état local avant le POST, et rejoué octet pour octet."""

import json
from datetime import timedelta

from conftest import REFERENCE, session_view, valid_output
from pulse_intelligence.config import Config
from pulse_intelligence.core_client import CoreClient, CoreUnavailable
from pulse_intelligence.selection import SessionView
from pulse_intelligence.session_summary import run_pass, summarize_session, summary_event_id
from pulse_intelligence.state import JobState
from pulse_intelligence.summarizer import FakeSummarizer


def today() -> str:
    return REFERENCE.astimezone().date().isoformat()


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def test_failed_post_is_replayed_byte_for_byte_then_never_again(fake_core, client, config, tmp_path):
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))
    fake_core.fail_posts = 1
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")
    state_path = tmp_path / "state" / "state.json"
    event_id = summary_event_id("aaaaaaaaaaaaaaaa", "v1", "fake/summarizer")

    # Tick 1 : Core refuse. Le payload était déjà sur disque avant l'envoi.
    first = run_pass(client, summarizer, config, JobState.load(state_path), now=REFERENCE)

    assert [o.status for o in first.outcomes] == ["failed"]
    assert fake_core.posts == [] and len(fake_core.refused) == 1
    on_disk = JobState.load(state_path)
    assert on_disk.pending_event(event_id) == fake_core.refused[0]
    assert not on_disk.knows(event_id)
    assert on_disk.known_summaries() == set()

    # Tick 2, plus tard, autre processus : mêmes octets, ni modèle ni /context.
    second = run_pass(
        client, summarizer, config, JobState.load(state_path), now=REFERENCE + timedelta(minutes=10)
    )

    assert [o.status for o in second.outcomes] == ["created"]
    assert len(fake_core.posts) == 1
    assert canonical(fake_core.posts[0]) == canonical(fake_core.refused[0])
    assert fake_core.posts[0]["details"]["generated_at"] == REFERENCE.isoformat()
    assert len(summarizer.calls) == 1
    assert fake_core.context_requests == 1
    confirmed = JobState.load(state_path)
    assert confirmed.knows(event_id) and confirmed.pending == {}
    assert confirmed.known_summaries() == {("aaaaaaaaaaaaaaaa", "v1", "fake/summarizer")}

    # Tick 3 : succès confirmé, plus rien ne bouge.
    third = run_pass(
        client, summarizer, config, JobState.load(state_path), now=REFERENCE + timedelta(minutes=20)
    )

    assert third.candidates == 0 and third.outcomes == []
    assert len(fake_core.posts) == 1
    assert len(summarizer.calls) == 1


def test_lost_confirmation_is_replayed_and_core_answers_duplicate(fake_core, config, state, monkeypatch):
    # Core a bien enregistré, mais la réponse s'est perdue : le tick suivant
    # renvoie le même payload, Core répond duplicate, l'état se confirme.
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))
    client = CoreClient(fake_core.url, timeout_s=5.0)
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")
    real_post = client.post_activity

    def post_then_lose_the_answer(payload):
        real_post(payload)
        monkeypatch.setattr(client, "post_activity", real_post)
        raise CoreUnavailable("réponse perdue")

    monkeypatch.setattr(client, "post_activity", post_then_lose_the_answer)

    first = run_pass(client, summarizer, config, state, now=REFERENCE)
    second = run_pass(client, summarizer, config, state, now=REFERENCE + timedelta(minutes=10))

    assert first.error and "réponse perdue" in first.error
    assert [o.status for o in second.outcomes] == ["duplicate"]
    assert len(fake_core.posts) == 2
    assert canonical(fake_core.posts[0]) == canonical(fake_core.posts[1])
    assert len(summarizer.calls) == 1
    assert state.pending == {} and state.known_summaries() == {
        ("aaaaaaaaaaaaaaaa", "v1", "fake/summarizer")
    }


def test_voluntary_regeneration_is_the_only_way_to_get_a_new_payload(fake_core, client, state):
    session = SessionView(raw=session_view("aaaaaaaaaaaaaaaa"), day=REFERENCE.date())
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")
    fake_core.fail_posts = 1
    pending = summarize_session(
        session, client=client, summarizer=summarizer, config=Config(model_id="fake/summarizer"),
        state=state, now=REFERENCE,
    )
    assert pending.status == "failed" and len(state.pending) == 1

    # Nouveau prompt : autre event_id, le modèle est rappelé, nouveau payload.
    regenerated = summarize_session(
        session, client=client, summarizer=summarizer,
        config=Config(model_id="fake/summarizer", prompt_version="v2"),
        state=state, now=REFERENCE + timedelta(minutes=10),
    )

    assert regenerated.status == "created"
    assert regenerated.event_id != pending.event_id
    assert len(summarizer.calls) == 2
    assert fake_core.posts[0]["details"]["prompt_version"] == "v2"
    assert fake_core.posts[0]["details"]["generated_at"] != fake_core.refused[0]["details"]["generated_at"]
    # Le payload v1 gelé attend toujours, intact.
    assert state.pending_event(pending.event_id) == fake_core.refused[0]


def test_dry_run_freezes_nothing(fake_core, client, config, state):
    session = SessionView(raw=session_view("aaaaaaaaaaaaaaaa"), day=REFERENCE.date())
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")

    outcome = summarize_session(
        session, client=client, summarizer=summarizer, config=config, state=state, dry_run=True
    )

    assert outcome.status == "dry_run"
    assert state.pending == {} and not state.path.exists()


def test_state_file_round_trips_the_frozen_payload(tmp_path):
    path = tmp_path / "state.json"
    state = JobState.load(path)
    state.record_pending(
        "evt", session_id="s", prompt_version="v1", model_id="m", at="t", event={"event_id": "evt"}
    )

    reloaded = JobState.load(path)

    assert reloaded.pending == state.pending
    assert reloaded.pending_event("evt") == {"event_id": "evt"}
    assert reloaded.pending_event("other") is None
