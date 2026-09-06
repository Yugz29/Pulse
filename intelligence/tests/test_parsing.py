import json
import uuid

import pytest

from conftest import REFERENCE, at, context_view, session_view, valid_output
from pulse_intelligence.selection import SessionView
from pulse_intelligence.session_summary import (
    InvalidModelOutput,
    parse_model_output,
    summarize_session,
    summary_event_id,
)
from pulse_intelligence.summarizer import FakeSummarizer


ALLOWED = {"core/daemon_v2/routes.py"}


def test_valid_output_is_parsed_and_normalised():
    parsed = parse_model_output(valid_output(), ALLOWED)

    assert parsed.reprise["doing"].startswith("Tu implémentais")
    assert parsed.structured == {
        "project": "Pulse",
        "intents": ["livrer le pas 2"],
        "central_files": ["core/daemon_v2/routes.py"],
        "blockers": [],
        "confidence": "high",
    }


def test_markdown_fences_are_tolerated():
    parsed = parse_model_output(f"```json\n{valid_output()}\n```", ALLOWED)

    assert parsed.structured["confidence"] == "high"


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("pas du json", "non JSON"),
        ("[]", "objet JSON"),
        (valid_output(reprise={"stopped_at": "x", "open": "y"}), "reprise.doing"),
        (valid_output(reprise={"doing": "", "stopped_at": "x", "open": "y"}), "reprise.doing"),
        (valid_output(structured={"project": "Pulse", "confidence": "sure"}), "confidence"),
        (
            valid_output(structured={"project": None, "confidence": "low", "central_files": ["inventé.py"]}),
            "absent de l'entrée",
        ),
        (
            valid_output(reprise={"doing": "x" * 301, "stopped_at": "y", "open": "z"}),
            "301 caractères",
        ),
        (
            valid_output(structured={"project": None, "confidence": "low", "intents": ["a", "b", "c", "d"]}),
            "max 3",
        ),
    ],
)
def test_invalid_outputs_are_rejected(output, message):
    with pytest.raises(InvalidModelOutput, match=message):
        parse_model_output(output, ALLOWED)


def test_event_id_is_the_expected_uuid5():
    expected = str(
        uuid.uuid5(uuid.NAMESPACE_URL, "pulse-session-summary:aaaaaaaaaaaaaaaa:v1:fake/summarizer")
    )

    assert summary_event_id("aaaaaaaaaaaaaaaa", "v1", "fake/summarizer") == expected


def test_dry_run_builds_the_event_without_emitting(fake_core, client, config, state):
    session = SessionView(raw=session_view("aaaaaaaaaaaaaaaa"), day=REFERENCE.date())
    fake_core.add_context(at(-60), context_view(reference_at=at(-60), current_session=session.raw))
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")

    outcome = summarize_session(
        session, client=client, summarizer=summarizer, config=config, state=state,
        dry_run=True, now=REFERENCE,
    )

    assert outcome.status == "dry_run"
    assert fake_core.posts == []
    assert state.emitted == {} and state.failures == {}
    event = outcome.event
    assert event["type"] == "session_summary"
    assert event["event_id"] == summary_event_id("aaaaaaaaaaaaaaaa", "v1", "fake/summarizer")
    assert event["occurred_at"] == at(-60).isoformat()
    assert event["producer"] == {"name": "pulse-intelligence", "version": "0.1.0"}
    details = event["details"]
    assert details["session_id"] == details["source_event_ids_hash"] == "aaaaaaaaaaaaaaaa"
    assert details["session_label"] == "work-1"
    assert details["session_date"] == "2026-09-02"
    assert details["source_event_count"] == 40
    assert details["reconstruction_version"] == 1
    assert details["prompt_version"] == "v1" and details["model_id"] == "fake/summarizer"
    assert details["generated_at"] == REFERENCE.isoformat()
    assert details["workspace"] == "/Users/dev/Projets/Pulse"
    assert len(details["input_hash"]) == 64
    assert json.loads(summarizer.calls[0])["session"] == session.raw


def test_three_rejections_mark_the_session_failed(fake_core, client, config, state):
    session = SessionView(raw=session_view("aaaaaaaaaaaaaaaa"), day=REFERENCE.date())
    summarizer = FakeSummarizer(outputs="pas du json", model_id="fake/summarizer")

    statuses = [
        summarize_session(session, client=client, summarizer=summarizer, config=config, state=state).status
        for _ in range(4)
    ]

    assert statuses == ["failed", "failed", "given_up", "given_up"]
    # Budget par identité (session, prompt, modèle), audit 2026-09-06 défaut 5.
    identity = summary_event_id("aaaaaaaaaaaaaaaa", "v1", "fake/summarizer")
    assert state.failures[identity] == 3
    assert "non JSON" in state.failed[identity]
    assert len(summarizer.calls) == 3  # plus d'appel au modèle une fois abandonnée
    assert fake_core.posts == []


def test_dry_run_rejection_does_not_touch_the_state(fake_core, client, config, state):
    session = SessionView(raw=session_view("aaaaaaaaaaaaaaaa"), day=REFERENCE.date())
    summarizer = FakeSummarizer(outputs="pas du json", model_id="fake/summarizer")

    outcome = summarize_session(
        session, client=client, summarizer=summarizer, config=config, state=state, dry_run=True
    )

    assert outcome.status == "failed"
    assert state.failures == {}
