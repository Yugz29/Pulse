"""Schéma `open` v3 : chaque point est d'une nature déclarée et étayé par des
références de l'entrée. Un test par règle de rejet, puis les trois sorties
réelles du 2026-09-07 (D1, D3, D5), transcrites au schéma v3, qui doivent
désormais être rejetées (`docs/audits/2026-09-07-validation-mlx.md`).
"""

from __future__ import annotations

import json

import pytest

from conftest import REFERENCE, at, context_view, session_view, valid_output
from pulse_intelligence import cli
from pulse_intelligence.selection import SessionView
from pulse_intelligence.session_input import (
    build_model_input,
    input_references,
    split_open_text,
)
from pulse_intelligence.session_summary import (
    EMPTY_OPEN_TEXT,
    InvalidModelOutput,
    build_event,
    normalize_open_text,
    open_items_for_core,
    parse_model_output,
    render_open_items,
)


PREVIOUS_OPEN = (
    "Le push n'a pas été observé ; la configuration de llm_max_tokens reste à valider. "
    "La PR #28 attend."
)


def _session() -> SessionView:
    return SessionView(
        raw=session_view(
            "aaaaaaaaaaaaaaaa",
            commits=[{"hash": "a1b2c3", "message": "fix: x"}, {"hash": "d4e5f6", "message": "docs: y"}],
            files={"created": [], "modified": ["core/daemon_v2/routes.py", "config.toml"], "deleted": []},
        ),
        day=REFERENCE.date(),
    )


def _context(session: SessionView, *, previous: bool = True, agent: bool = True) -> dict:
    last_summary = {
        "id": "bbbbbbbbbbbbbbbb", "label": "work-0",
        "session_ended_at": at(-300).isoformat(),
        "reprise": {"doing": "d", "stopped_at": "s", "open": PREVIOUS_OPEN},
        "confidence": "medium", "age_minutes": 240,
    } if previous else None
    last_agent = {
        "agent": "claude-code", "started_at": at(-200).isoformat(), "ended_at": at(-90).isoformat(),
        "summary": "Agent session (claude-code): Peux-tu vérifier l'état de la PR #28 ?",
    } if agent else None
    return context_view(
        reference_at=at(-60), current_session=session.raw,
        last_session_summary=last_summary, last_agent_session=last_agent,
    )


def _references(session=None, **context_kwargs):
    session = session or _session()
    return input_references(build_model_input(session, _context(session, **context_kwargs), references=True))


def _output(*items: dict) -> str:
    return valid_output(
        reprise={"doing": "d", "stopped_at": "s", "open": list(items)},
        structured={"project": None, "intents": [], "central_files": [], "blockers": [], "confidence": "low"},
    )


OBSERVED = {"text": "Aucun push observé pour les commits a1b2c3 et d4e5f6", "kind": "observed",
            "evidence": ["commit:a1b2c3", "commit:d4e5f6"]}
CARRIED = {"text": "La PR #28 attend.", "kind": "carried_over", "evidence": [],
           "carried_from": "previous_summary:2",
           "reason_kept": "aucun événement sur la PR depuis le résumé précédent"}
REQUESTED = {"text": "L'agent devait vérifier l'état de la PR #28", "kind": "requested",
             "evidence": ["agent_request:0"]}
ALLOWED = {"core/daemon_v2/routes.py", "config.toml"}


# --- Ce qui passe ---------------------------------------------------------


def test_the_three_kinds_are_accepted_and_rendered_for_core():
    parsed = parse_model_output(_output(OBSERVED, CARRIED, REQUESTED), ALLOWED, references=_references())

    assert parsed.open_items == [
        {**OBSERVED},
        {**CARRIED},
        {**REQUESTED},
    ]
    assert parsed.reprise["open"] == (
        "Aucun push observé pour les commits a1b2c3 et d4e5f6. "
        "La PR #28 attend (repris : aucun événement sur la PR depuis le résumé précédent). "
        "L'agent devait vérifier l'état de la PR #28."
    )
    # Le rendu se redécoupe en autant de points, dans l'ordre : c'est ce que
    # l'annexe du lendemain recevra.
    assert len(split_open_text(parsed.reprise["open"])) == 3
    assert open_items_for_core(parsed.open_items) == [
        {"kind": "observed", "evidence": ["commit:a1b2c3", "commit:d4e5f6"]},
        {"kind": "carried_over", "evidence": [], "carried_from": "previous_summary:2"},
        {"kind": "requested", "evidence": ["agent_request:0"]},
    ]


def test_an_empty_open_is_valid_and_rendered_with_the_fixed_sentence():
    parsed = parse_model_output(_output(), ALLOWED, references=_references())

    assert parsed.open_items == []
    assert parsed.reprise["open"] == EMPTY_OPEN_TEXT
    assert render_open_items([]) == EMPTY_OPEN_TEXT


def test_without_references_the_legacy_free_text_open_is_unchanged():
    parsed = parse_model_output(valid_output(), ALLOWED)

    assert parsed.open_items is None
    assert parsed.reprise["open"] == "La PR attend ta relecture."
    # Et une liste v3 ne passe pas au contrat d'origine : le prompt v2 reste v2.
    with pytest.raises(InvalidModelOutput, match="reprise.open"):
        parse_model_output(_output(OBSERVED), ALLOWED)


def test_normalize_open_text_ignores_case_punctuation_and_the_carry_note():
    assert normalize_open_text("La PR #28 attend (repris : rien vu).") == normalize_open_text("la PR #28 attend")
    assert normalize_open_text("Le push n'a pas été observé") == "le push n'a pas été observé"


# --- Une règle de rejet, un test --------------------------------------------


def _rejects(output: str, message: str, **context_kwargs) -> None:
    with pytest.raises(InvalidModelOutput, match=message):
        parse_model_output(output, ALLOWED, references=_references(**context_kwargs))


def test_a_string_open_is_rejected_under_the_v3_schema():
    _rejects(valid_output(), "liste de points")


def test_an_unknown_kind_is_rejected():
    _rejects(_output({**OBSERVED, "kind": "guessed"}), "kind doit être observed, carried_over, requested")
    _rejects(_output({"text": "x", "evidence": ["commit:a1b2c3"]}), "kind doit être")


def test_an_observed_item_without_evidence_is_rejected():
    _rejects(_output({**OBSERVED, "evidence": []}), "observed exige evidence non vide")
    _rejects(_output({"text": "x", "kind": "observed"}), "observed exige evidence non vide")


def test_an_evidence_reference_absent_from_the_input_is_rejected():
    _rejects(_output({**OBSERVED, "evidence": ["commit:deadbeef"]}), "commit:deadbeef absente de l'entrée")
    _rejects(_output({**OBSERVED, "evidence": ["path:inventé.py"]}), "path:inventé.py absente")
    # Une absence n'est pas un fait citable.
    _rejects(_output({**OBSERVED, "evidence": ["git:push_observed"]}), "git:push_observed absente")
    _rejects(_output({**OBSERVED, "evidence": "commit:a1b2c3"}), "liste de références")


def test_an_observed_item_cannot_lean_on_an_annex():
    _rejects(_output({**OBSERVED, "evidence": ["agent_request:0"]}), "ne s'étaye pas sur une annexe")
    _rejects(_output({**OBSERVED, "evidence": ["commit:a1b2c3", "previous_summary:0"]}), "previous_summary:0")


def test_a_carried_over_item_must_point_to_a_real_previous_item():
    _rejects(_output({**CARRIED, "carried_from": "previous_summary:3"}), "previous_summary:3 absent de l'annexe")
    _rejects(_output({**CARRIED, "carried_from": "commit:a1b2c3"}), "carried_from doit désigner")
    _rejects(_output({k: v for k, v in CARRIED.items() if k != "carried_from"}), "carried_from doit désigner")
    # Sans annexe previous_summary, aucun point ne peut être repris.
    _rejects(_output(CARRIED), "previous_summary:2 absent", previous=False)


def test_a_carried_over_item_requires_reason_kept():
    _rejects(_output({k: v for k, v in CARRIED.items() if k != "reason_kept"}), "reason_kept absente ou vide")
    _rejects(_output({**CARRIED, "reason_kept": "  "}), "reason_kept absente ou vide")


def test_carried_from_and_reason_kept_are_only_for_carried_over():
    _rejects(_output({**OBSERVED, "carried_from": "previous_summary:0"}), "carried_from n'a de sens que pour")
    _rejects(_output({**REQUESTED, "reason_kept": "x"}), "reason_kept n'a de sens que pour")


def test_a_requested_item_must_cite_the_agent_annex_and_nothing_else():
    _rejects(_output({**REQUESTED, "evidence": []}), "requested cite l'annexe d'agent")
    _rejects(_output({**REQUESTED, "evidence": ["commit:a1b2c3"]}), "requested cite l'annexe d'agent")
    _rejects(_output({**REQUESTED, "evidence": ["agent_request:0", "commit:a1b2c3"]}), "requested cite l'annexe")
    _rejects(_output(REQUESTED), "agent_request:0 absente de l'entrée", agent=False)


def test_a_text_copied_from_previous_summary_without_carried_over_is_rejected():
    copied = {"text": "La PR #28 attend.", "kind": "observed", "evidence": ["commit:a1b2c3"]}
    _rejects(_output(copied), "identique à previous_summary:2 sans kind carried_over")
    # La comparaison ignore casse et ponctuation finale : une recopie maquillée reste une recopie.
    _rejects(_output({**copied, "text": "la pr #28 attend"}), "identique à previous_summary:2")
    _rejects(_output({**REQUESTED, "text": "Le push n'a pas été observé."}), "identique à previous_summary:0")


def test_an_observed_item_asserting_a_push_did_not_happen_is_rejected():
    for text in (
        "Le push n'a pas été effectué",
        "Les commits ne sont pas poussés (push_observed: false)",
        "Le push n'est pas encore fait",
    ):
        _rejects(_output({**OBSERVED, "text": text}), "affirme un push non effectué")
    # « non observé » reste la formulation attendue.
    parse_model_output(_output({**OBSERVED, "text": "Aucun push observé après le commit a1b2c3"}),
                       ALLOWED, references=_references())


def test_shape_limits_of_the_item_list():
    _rejects(_output(*([OBSERVED] * 6)), "6 points, max 5")
    _rejects(_output("une chaîne"), r"open\[0\] doit être un objet")
    _rejects(_output({**OBSERVED, "note": "x"}), "clés inconnues note")
    _rejects(_output({**OBSERVED, "text": "x" * 301}), "301 caractères")
    _rejects(_output({**OBSERVED, "text": ""}), r"open\[0\].text absente")


# --- L'événement et la fiche ------------------------------------------------


def test_the_event_carries_kinds_and_evidence_but_no_free_text_outside_reprise():
    session = _session()
    parsed = parse_model_output(_output(OBSERVED, CARRIED), ALLOWED, references=_references(session))

    event = build_event(
        session, parsed, prompt_version="v3", model_id="m", generated_at=REFERENCE,
        generation_ms=1, context_hash="h" * 64, workspace=None,
    )

    details = event["details"]
    assert details["open_items"] == [
        {"kind": "observed", "evidence": ["commit:a1b2c3", "commit:d4e5f6"]},
        {"kind": "carried_over", "evidence": [], "carried_from": "previous_summary:2"},
    ]
    assert json.dumps(details["open_items"]).count("PR #28") == 0
    assert "PR #28" in details["reprise"]["open"]


def test_legacy_events_have_no_open_items():
    session = _session()
    parsed = parse_model_output(valid_output(), ALLOWED)
    event = build_event(
        session, parsed, prompt_version="v2", model_id="m", generated_at=REFERENCE,
        generation_ms=1, context_hash="h" * 64, workspace=None,
    )
    assert "open_items" not in event["details"]


def test_show_card_lists_each_v3_point_with_its_kind_and_evidence():
    rendered = render_open_items([OBSERVED, CARRIED])
    details = {
        "session_id": "aaaaaaaaaaaaaaaa", "reprise": {"doing": "d", "stopped_at": "s", "open": rendered},
        "structured": {"confidence": "high", "central_files": []},
        "open_items": open_items_for_core([OBSERVED, CARRIED]),
    }

    card = cli._card(details, previous_summary=None, previous_known=True).splitlines()

    open_index = next(i for i, line in enumerate(card) if line.startswith("open "))
    assert card[open_index + 1] == (
        "  · observed      Aucun push observé pour les commits a1b2c3 et d4e5f6.  ← commit:a1b2c3, commit:d4e5f6"
    )
    assert card[open_index + 2] == (
        "  · carried_over  La PR #28 attend (repris : aucun événement sur la PR depuis le résumé précédent)."
        "  ← —  repris de previous_summary:2"
    )
    assert card[open_index + 3].startswith("  ↳ reçu")


def test_show_card_of_a_legacy_summary_is_unchanged():
    details = {
        "session_id": "aaaaaaaaaaaaaaaa",
        "reprise": {"doing": "d", "stopped_at": "s", "open": "La PR attend ta relecture."},
        "structured": {"confidence": "high", "central_files": []},
    }
    card = cli._card(details, previous_summary=None, previous_known=False).splitlines()
    open_index = next(i for i, line in enumerate(card) if line.startswith("open "))
    assert card[open_index] == "open            La PR attend ta relecture."
    assert card[open_index + 1].startswith("  ↳ reçu")
