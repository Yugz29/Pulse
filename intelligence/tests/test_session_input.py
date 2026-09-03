import copy
import json

from conftest import REFERENCE, at, context_view, session_view
from pulse_intelligence.selection import SessionView
from pulse_intelligence.session_input import (
    build_model_input,
    input_hash,
    input_paths,
    serialize_input,
)


def view(**kwargs) -> SessionView:
    return SessionView(raw=session_view("aaaaaaaaaaaaaaaa", **kwargs), day=REFERENCE.date())


def test_input_hash_is_stable_between_two_constructions():
    session = view()
    context = context_view(reference_at=at(-60), current_session=session.raw)

    first = serialize_input(build_model_input(session, context))
    second = serialize_input(build_model_input(session, context))

    assert first == second
    assert input_hash(first) == input_hash(second)
    assert len(input_hash(first)) == 64


def test_core_view_is_passed_through_untouched():
    session = view()
    snapshot = copy.deepcopy(session.raw)
    context = context_view(reference_at=at(-60), current_session=session.raw)

    model_input = build_model_input(session, context)

    assert model_input["session"] == snapshot
    assert session.raw == snapshot
    assert set(model_input) == {"session", "previous_summary", "agent_session"}
    # Sérialisation à clés triées : l'ordre du dict source ne compte pas.
    serialized = serialize_input(model_input)
    assert json.loads(serialized)["session"] == snapshot
    assert serialized.index('"agent_session"') < serialized.index('"session"')


def test_annexes_are_absent_when_core_has_nothing():
    session = view()
    context = context_view(reference_at=at(-60), current_session=session.raw)

    model_input = build_model_input(session, context)

    assert model_input["previous_summary"] is None
    assert model_input["agent_session"] is None


def test_previous_summary_of_the_same_day_is_annexed_but_not_own_or_other_day():
    session = view()
    same_day = {
        "id": "bbbbbbbbbbbbbbbb",
        "label": "work-1",
        "session_ended_at": at(-300).isoformat(),
        "reprise": {"doing": "Tu reprenais le parseur.", "stopped_at": "—", "open": "—"},
        "confidence": "medium",
        "age_minutes": 240,
    }
    own = {**same_day, "id": "aaaaaaaaaaaaaaaa"}
    other_day = {**same_day, "session_ended_at": at(-2000).isoformat()}

    annexed = build_model_input(session, context_view(reference_at=at(-60), last_session_summary=same_day))
    skipped_own = build_model_input(session, context_view(reference_at=at(-60), last_session_summary=own))
    skipped_day = build_model_input(session, context_view(reference_at=at(-60), last_session_summary=other_day))

    assert annexed["previous_summary"] == {
        "id": "bbbbbbbbbbbbbbbb",
        "label": "work-1",
        "reprise": same_day["reprise"],
    }
    assert skipped_own["previous_summary"] is None
    assert skipped_day["previous_summary"] is None


def test_agent_session_is_annexed_only_when_it_overlaps():
    session = view(started=-120, ended=-60)
    overlapping = {
        "agent": "claude-code",
        "started_at": at(-100).isoformat(),
        "ended_at": at(-80).isoformat(),
        "workspace": "/Users/dev/Projets/Pulse",
        "summary": "Agent session (claude-code): Implémente la route",
        "age_minutes": 80,
    }
    earlier = {**overlapping, "started_at": at(-300).isoformat(), "ended_at": at(-200).isoformat()}

    annexed = build_model_input(session, context_view(reference_at=at(-60), last_agent_session=overlapping))
    skipped = build_model_input(session, context_view(reference_at=at(-60), last_agent_session=earlier))

    assert annexed["agent_session"] == {
        "agent": "claude-code",
        "started_at": overlapping["started_at"],
        "ended_at": overlapping["ended_at"],
        "summary": overlapping["summary"],
    }
    assert skipped["agent_session"] is None


def test_input_paths_are_the_files_of_the_view():
    session = view(files={"created": ["docs/VISION.md"], "modified": ["core/README.md"], "deleted": ["old.py"]})

    assert input_paths(session) == {"docs/VISION.md", "core/README.md", "old.py"}
