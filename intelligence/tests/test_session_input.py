import copy
import json

from conftest import REFERENCE, at, context_view, session_view
from pulse_intelligence.selection import SessionView
from pulse_intelligence.session_input import (
    build_model_input,
    input_hash,
    input_paths,
    input_references,
    serialize_input,
    split_open_text,
    uses_open_items,
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


# --- Références stables (schéma `open` v3) --------------------------------


def _annexed_context(session: SessionView) -> dict:
    previous = {
        "id": "bbbbbbbbbbbbbbbb",
        "label": "work-0",
        "session_ended_at": at(-300).isoformat(),
        "reprise": {
            "doing": "Tu reprenais le parseur.",
            "stopped_at": "Après un commit.",
            "open": "Le push n'a pas été observé ; la configuration de llm_max_tokens reste à valider. La PR #28 attend.",
        },
        "confidence": "medium",
        "age_minutes": 240,
    }
    agent = {
        "agent": "claude-code",
        "started_at": at(-200).isoformat(),
        "ended_at": at(-90).isoformat(),
        "summary": "Agent session (claude-code): Peux-tu vérifier l'état de la PR #28 ?",
        "workspace": "/w",
    }
    return context_view(
        reference_at=at(-60), current_session=session.raw,
        last_session_summary=previous, last_agent_session=agent,
    )


def test_split_open_text_cuts_a_core_string_into_sentences():
    assert split_open_text(
        "Le push n'a pas été observé ; la configuration reste à valider. La PR #28 attend."
    ) == ["Le push n'a pas été observé", "la configuration reste à valider.", "La PR #28 attend."]
    # Un point sans blanc derrière n'est pas une fin de phrase (versions, chemins).
    assert split_open_text("La v2.1 de docs/dogfooding.md attend.") == ["La v2.1 de docs/dogfooding.md attend."]
    assert split_open_text(["a", " ", "b "]) == ["a", "b"]
    assert split_open_text(None) == [] and split_open_text("") == []


def test_legacy_prompts_keep_the_free_text_open():
    assert not uses_open_items("v1") and not uses_open_items("v2")
    assert uses_open_items("v3")


def test_without_references_the_input_is_byte_identical_to_before():
    session = view(commits=[{"hash": "a1b2c3", "message": "fix: x"}])
    context = _annexed_context(session)

    legacy = build_model_input(session, context)

    assert legacy == build_model_input(session, context, references=False)
    assert "open_items" not in legacy["previous_summary"]
    assert "ref" not in legacy["agent_session"]
    assert input_hash(serialize_input(legacy)) != input_hash(
        serialize_input(build_model_input(session, context, references=True))
    )


def test_references_number_the_previous_open_and_the_agent_request_without_touching_the_view():
    session = view(commits=[{"hash": "a1b2c3", "message": "fix: x"}])
    snapshot = copy.deepcopy(session.raw)

    referenced = build_model_input(session, _annexed_context(session), references=True)

    assert referenced["session"] == snapshot
    assert referenced["previous_summary"]["open_items"] == [
        {"ref": "previous_summary:0", "text": "Le push n'a pas été observé"},
        {"ref": "previous_summary:1", "text": "la configuration de llm_max_tokens reste à valider."},
        {"ref": "previous_summary:2", "text": "La PR #28 attend."},
    ]
    assert referenced["previous_summary"]["reprise"]["open"].startswith("Le push")
    assert referenced["agent_session"]["ref"] == "agent_request:0"


def test_input_references_enumerate_exactly_what_the_view_and_annexes_carry():
    session = view(
        commits=[{"hash": "a1b2c3", "message": "fix: x"}],
        files={"created": ["new.py"], "modified": ["core/daemon_v2/routes.py"], "deleted": ["old.py"]},
        activity_count=2,
    )
    model_input = build_model_input(session, _annexed_context(session), references=True)

    references = input_references(model_input)

    assert references.paths == {"new.py", "core/daemon_v2/routes.py", "old.py"}
    assert {"path:new.py", "path:core/daemon_v2/routes.py", "path:old.py"} <= references.refs
    assert "commit:a1b2c3" in references and "app:Terminal" in references
    assert {"test_passed:pytest -q", "signal:file_changed", "signal:terminal_finished"} <= references.refs
    assert {"event:evt-aaaaaaaaaaaaaaaa-0", "event:evt-aaaaaaaaaaaaaaaa-1"} <= references.refs
    assert references.agent_requests == ("agent_request:0",)
    assert references.previous_open == (
        "Le push n'a pas été observé",
        "la configuration de llm_max_tokens reste à valider.",
        "La PR #28 attend.",
    )
    assert {"previous_summary:0", "previous_summary:1", "previous_summary:2"} <= references.refs
    # Une absence n'est pas un fait citable ; un hash inventé non plus.
    assert "git:push_observed" not in references
    assert "commit:deadbeef" not in references and "previous_summary:3" not in references
    # Même énumération sans annexes référencées : les clés viennent de la vue.
    assert input_references(build_model_input(session, _annexed_context(session))).refs == references.refs


def test_input_references_are_empty_without_annexes_or_facts():
    session = view(files={"created": [], "modified": [], "deleted": []}, activity_count=0)
    raw = session.raw
    raw["apps"] = []
    raw["terminal"] = {"tests_passed": [], "tests_failed": [], "errors": [], "truncated": False}
    raw["signals"] = []
    context = context_view(reference_at=at(-60), current_session=raw)

    references = input_references(build_model_input(session, context, references=True))

    assert references.refs == frozenset()
    assert references.previous_open == () and references.agent_requests == ()
