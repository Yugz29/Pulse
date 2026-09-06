"""Attentes annotées (`eval/expected/`) : elles sont elles-mêmes des sorties
v3 valides pour leur session, et la comparaison rend un écart lisible."""

from __future__ import annotations

import json

import pytest

from pulse_intelligence.evaluation import (
    DEFAULT_CORPUS,
    DEFAULT_EXPECTED,
    compare_open,
    compare_run,
    format_comparison,
    load_corpus,
    load_expectations,
)
from pulse_intelligence.session_input import build_model_input, input_paths, input_references
from pulse_intelligence.session_summary import parse_model_output


TARGETS = {"1e420dda8b6eee77", "eef4956b36dd37ce", "8af930d9ef437d2a", "d98778994319cd07"}


def _output(items: list[dict]) -> str:
    return json.dumps({
        "reprise": {"doing": "d", "stopped_at": "s", "open": items},
        "structured": {"project": None, "intents": [], "central_files": [], "blockers": [], "confidence": "low"},
    }, ensure_ascii=False)


def _strip(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "why"}


def test_there_is_one_annotated_expectation_per_target_session():
    expectations = load_expectations(DEFAULT_EXPECTED)
    assert set(expectations) == TARGETS
    for session_id, expectation in expectations.items():
        assert expectation["notes"]
        for item in [*expectation["open"], *expectation["optional"]]:
            assert item["why"], (session_id, item)
        for rule in expectation["must_not"]:
            assert rule["why"] and set(rule) & {"kind", "carried_from", "text_matches"}, (session_id, rule)


def test_every_expected_and_optional_point_is_a_valid_v3_output_for_its_session(capture_timezone):
    """Les attentes ne demandent rien que le validateur refuserait."""
    corpus = {e.id: e for e in load_corpus(DEFAULT_CORPUS)}
    for session_id, expectation in load_expectations(DEFAULT_EXPECTED).items():
        entry = corpus[session_id]
        model_input = build_model_input(entry.view, entry.context, references=True)
        references = input_references(model_input)
        items = [_strip(item) for item in [*expectation["open"], *expectation["optional"]]]
        parsed = parse_model_output(_output(items), input_paths(entry.view), references=references)
        assert len(parsed.open_items) == len(items), session_id
        # Et l'attente ne se contredit pas : aucun point attendu n'est interdit.
        comparison = compare_open(session_id, parsed.open_items, expectation)
        assert comparison.ok and not comparison.unexpected, format_comparison(comparison)


def test_the_expectations_refuse_yesterdays_defects_even_when_declared(capture_timezone):
    """Si le modèle habillait les sorties du 07 au schéma v3 de façon valide,
    les attentes les signaleraient encore."""
    corpus = {e.id: e for e in load_corpus(DEFAULT_CORPUS)}
    expectations = load_expectations(DEFAULT_EXPECTED)
    # D3 déclaré observed sur d9877899 : interdit par la règle kind+PR #28.
    d3 = {"text": "L'état de la PR #28 n'a pas été confirmé", "kind": "observed", "evidence": ["commit:40316b2"]}
    comparison = compare_open("d98778994319cd07", [d3], expectations["d98778994319cd07"])
    assert not comparison.ok and comparison.forbidden
    # D1 sur eef4956b repris avec la mauvaise origine (le push) : interdit.
    d5_carried = {"text": "Le push n'a pas été observé", "kind": "carried_over", "evidence": [],
                  "carried_from": "previous_summary:0", "reason_kept": "rien de neuf"}
    comparison = compare_open("eef4956b36dd37ce", [d5_carried], expectations["eef4956b36dd37ce"])
    assert [rule["carried_from"] for rule, _ in comparison.forbidden if "carried_from" in rule] == ["previous_summary:0"]
    assert comparison.missing  # et le vrai point repris manque
    del corpus  # la validité v3 de ces points est le sujet du test précédent


def test_compare_open_matches_on_kind_and_evidence_not_on_prose():
    expectation = {
        "open": [{"text": "A", "kind": "observed", "evidence": ["commit:1", "path:x"], "why": "w"}],
        "optional": [{"text": "B", "kind": "requested", "evidence": ["agent_request:0"], "why": "w"}],
        "must_not": [{"text_matches": "push", "why": "D5"}],
    }
    produced = [
        {"text": "Autre prose, mêmes preuves", "kind": "observed", "evidence": ["path:x", "commit:1"]},
        {"text": "Demande rappelée", "kind": "requested", "evidence": ["agent_request:0"]},
        {"text": "Un point en plus", "kind": "observed", "evidence": ["commit:2"]},
    ]

    comparison = compare_open("s", produced, expectation)

    assert comparison.ok
    assert [a["text"] for _, a in comparison.matched] == ["Autre prose, mêmes preuves"]
    assert [a["text"] for _, a in comparison.optional_matched] == ["Demande rappelée"]
    assert [a["text"] for a in comparison.unexpected] == ["Un point en plus"]
    report = format_comparison(comparison)
    assert report.startswith("s  conforme") and "? en plus" in report


def test_compare_open_reports_missing_forbidden_and_errors_readably():
    expectation = {
        "open": [{"text": "A", "kind": "carried_over", "carried_from": "previous_summary:1", "why": "raison A"}],
        "optional": [],
        "must_not": [{"kind": "observed", "text_matches": "push", "why": "D5 encore"}],
    }
    produced = [{"text": "Le push n'a pas été observé", "kind": "observed", "evidence": ["commit:1"]}]

    comparison = compare_open("s", produced, expectation)
    report = format_comparison(comparison)

    assert not comparison.ok and len(comparison.missing) == 1 and len(comparison.forbidden) == 1
    assert "s  écart" in report
    assert "✗ manquant          [carried_over] A  ← — · repris de previous_summary:1" in report
    assert "pourquoi : raison A" in report
    assert "✗ interdit (kind=observed, text_matches=push)" in report and "pourquoi : D5 encore" in report
    # Sans open_items (rejet ou ancien schéma) : l'écart le dit, tout manque.
    legacy = compare_open("s", None, expectation)
    assert not legacy.ok and legacy.error and legacy.missing
    # Un point requested ne viole pas une règle observed+push.
    only_kind = compare_open("s", [{"text": "push ?", "kind": "requested", "evidence": ["agent_request:0"]}], expectation)
    assert not only_kind.forbidden


def test_compare_run_reads_an_eval_output_directory(tmp_path):
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "a.json").write_text(json.dumps({
        "id": "a", "notes": "n", "open": [{"text": "A", "kind": "observed", "evidence": ["commit:1"], "why": "w"}],
        "optional": [], "must_not": [],
    }))
    (expected / "b.json").write_text(json.dumps({"id": "b", "notes": "n", "open": [], "optional": [], "must_not": []}))
    (expected / "c.json").write_text(json.dumps({"id": "c", "notes": "n", "open": [], "optional": [], "must_not": []}))
    run = tmp_path / "run"
    run.mkdir()
    (run / "a.json").write_text(json.dumps({"status": "ok", "open_items": [
        {"text": "x", "kind": "observed", "evidence": ["commit:1"]}]}))
    (run / "b.json").write_text(json.dumps({"status": "rejected", "detail": "kind inconnu"}))
    # c : pas de résultat dans ce passage → ignoré.

    comparisons = {c.session_id: c for c in compare_run(run, expected)}

    assert set(comparisons) == {"a", "b"}
    assert comparisons["a"].ok
    assert not comparisons["b"].ok and "rejected : kind inconnu" in comparisons["b"].error


# --- Évaluation : vrai tokenizer, pas de poids ; comparaison d'un passage ---


@pytest.fixture(scope="module")
def qwen_tokenizer():
    """Le tokenizer du modèle épinglé, depuis le cache HF, sans les poids
    (~15 s, ~0 Go) : les comptes sont ceux que `MLXProvider` refuserait."""
    pytest.importorskip("transformers")
    from transformers import AutoTokenizer
    from pulse_intelligence.llm.mlx import DEFAULT_MODEL

    try:
        return AutoTokenizer.from_pretrained(DEFAULT_MODEL)
    except Exception as exc:  # cache absent, hors ligne
        pytest.skip(f"tokenizer {DEFAULT_MODEL} indisponible : {exc}")


@pytest.mark.slow
def test_the_referenced_input_of_the_target_sessions_stays_far_under_the_ceiling(
    capture_timezone, qwen_tokenizer
):
    """Le schéma v3 ajoute `open_items` et `ref` aux annexes : mesuré avec le
    vrai tokenizer et le prompt v3 s'il existe (sinon v2), l'entrée des quatre
    sessions cibles reste sous le plafond, et le surcoût des références est
    borné — ce n'est pas ce qui rapprochera une session du plafond."""
    from pulse_intelligence.config import Config
    from pulse_intelligence.llm.mlx import MLXProvider, _count
    from pulse_intelligence.llm.provider import CompletionRequest
    from pulse_intelligence.provider_summarizer import prompt_path_for
    from pulse_intelligence.session_input import serialize_input

    prompt_path = prompt_path_for("v3") if prompt_path_for("v3").exists() else prompt_path_for("v2")
    system = prompt_path.read_text(encoding="utf-8")
    provider = MLXProvider()
    corpus = {e.id: e for e in load_corpus(DEFAULT_CORPUS)}
    for session_id in sorted(TARGETS):
        entry = corpus[session_id]
        legacy = serialize_input(build_model_input(entry.view, entry.context))
        referenced = serialize_input(build_model_input(entry.view, entry.context, references=True))
        counts = [
            _count(qwen_tokenizer, provider._render_prompt(
                qwen_tokenizer, CompletionRequest(system=system, prompt=text, max_tokens=1)))
            for text in (legacy, referenced)
        ]
        assert None not in counts, session_id
        before, after = counts
        print(f"{session_id} {prompt_path.name}: {before} → {after} tokens (+{after - before})")
        assert after < Config().llm_max_input_tokens // 2, (session_id, after)
        assert 0 <= after - before <= 400, (session_id, before, after)


@pytest.mark.slow
def test_an_eval_run_is_compared_to_the_annotated_expectations(capture_timezone, capsys):
    """Passage réel (`pulse-intel eval`, prompt v3) désigné par PULSE_EVAL_RUN :
    l'écart par session est imprimé, et le test échoue sur tout point attendu
    manquant ou motif interdit. Sans passage désigné, rien à comparer."""
    import os
    from pathlib import Path

    run = os.environ.get("PULSE_EVAL_RUN")
    if not run:
        pytest.skip("PULSE_EVAL_RUN non renseigné : désigne le dossier d'un passage eval")
    comparisons = compare_run(Path(run))
    assert {c.session_id for c in comparisons} == TARGETS, "le passage ne couvre pas les quatre sessions"
    with capsys.disabled():
        print()
        for comparison in comparisons:
            print(format_comparison(comparison))
    failed = [c.session_id for c in comparisons if not c.ok]
    assert not failed, f"écart sur {', '.join(failed)} (détail ci-dessus)"
