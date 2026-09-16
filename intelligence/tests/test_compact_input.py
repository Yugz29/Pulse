"""Entrée compacte (`input_version` 4) derrière le prompt v8, chantier
expérimental du 2026-09-16 : v7 ne bouge pas d'un octet, v8 reçoit les mêmes
faits et les mêmes références sous une forme plus courte."""

from __future__ import annotations

import json

import pytest

from pulse_intelligence.config import Config
from pulse_intelligence.evaluation import DEFAULT_CORPUS, load_corpus
from pulse_intelligence.provider_summarizer import prompt_path_for
from pulse_intelligence.session_input import (
    COMMIT_HASH_LENGTH,
    build_model_input,
    compact_observations,
    input_hash,
    input_paths,
    input_references,
    serialize_input,
    uses_annexes,
    uses_compact_input,
    uses_open_items,
)
from pulse_intelligence.session_summary import parse_model_output


# Empreintes SHA-256 de l'entrée v7 sérialisée (`references=True`,
# `annexes=False`) des 14 sessions d'`eval/observed`, relevées sur main au
# commit 131a6dd, avant l'entrée compacte. Si l'une change, v7 a changé.
V7_INPUT_HASHES = {
    "071bbd62a95fb6cb": "30419b10352be4b32217e863070ad76b6183f9166f286c3ee9d9074844deab3f",
    "1e420dda8b6eee77": "5907f9248fba75810a6198acf1e06c56527ae24015c0fc9cb42b52365cc9ab34",
    "247f2062410ca5a9": "ba9cdf37895d64524c14face52b924cd3f2c69b6c1d49d3fbea87cbb2375162d",
    "2ce344566f7e85dc": "e3567c53ae2fd4198ab7d1d0a28e33e5a46ad1f5a6f3f4562c357c4b3393d91e",
    "3cabaefb759dae36": "068b3a284626a3dda7985d1b5846d391ed17bb2aef13e3ec0fa991193cf16920",
    "6a4166356dbab6ec": "b70aed70431be00ccff38801d0a3fd60f4d0e9d4a81161ffbd6675e940b6982a",
    "7bbaca7882c3d766": "65c3f4c77de1091d8158755664ff7d11d556675fb2bc941f82cde90539f35156",
    "8af930d9ef437d2a": "1b71e445997d65769103391f2e88504250d631077fe2ab0008fe0fcca3cee8a4",
    "8faf4569fe2723b1": "4c559bb8caf4b110c4efcd96223980e1ab048dfa1ffa5ce248d53987e967c8dc",
    "cda6ccce898d3e88": "b2cfffbfd74d32ab96582c30eae8d31f0000558112e4953822115dd774f8f657",
    "d047b37b4511d37c": "698f1b84c17ef129f6a9ad80c08d6ac4e5a3199a66a8b02930f6f1bfc5306c03",
    "d98778994319cd07": "3a7ab4a4f2ea04a1ebb3d3815844d72a0f8ecc901e7526f445d02e2ad34cb864",
    "eb652ce9f04c4b37": "c617429807c68201a8abf390ef5b11621e437892d51ba0a547c8c1825530e4ab",
    "eef4956b36dd37ce": "b478d40ac74d5a5991dd854dea9ba29518fd2117da2900c4560afa6d49381e4f",
}


def _inputs(entry):
    v7 = build_model_input(entry.view, entry.context, references=True, annexes=False)
    v8 = build_model_input(entry.view, entry.context, references=True, annexes=False, compact=True)
    return v7, v8


def test_v8_is_the_only_prompt_with_the_compact_input_and_is_not_the_default():
    assert uses_compact_input("v8")
    assert uses_open_items("v8") and not uses_annexes("v8")
    for version in ("v5", "v6", "v7"):
        assert not uses_compact_input(version), version
    assert Config().prompt_version == "v6"


def test_v8_prompt_is_v7_plus_the_input_description_only():
    v7 = prompt_path_for("v7").read_text(encoding="utf-8").splitlines()
    v8 = prompt_path_for("v8").read_text(encoding="utf-8").splitlines()
    assert len(v7) == len(v8)
    changed = [index for index, (a, b) in enumerate(zip(v7, v8)) if a != b]
    # Deux lignes : le titre « L'entrée vN contient : » et le point sur
    # session.observations, qui décrit la forme. Rien d'autre ne bouge.
    assert changed == [4, 5], changed
    assert v7[4] == "L'entrée v3 contient :" and v8[4] == "L'entrée v4 contient :"
    assert v8[5].startswith("- session.observations :")
    for word in ("files", "columns", "rows", "change_columns", "files est absent", "12 caractères", "secondes entières", "sans workspace"):
        assert word in v8[5], word


def test_v7_input_is_byte_identical_to_its_reference(capture_timezone):
    corpus = {entry.id: entry for entry in load_corpus(DEFAULT_CORPUS)}
    assert set(corpus) == set(V7_INPUT_HASHES)
    for session_id, expected in V7_INPUT_HASHES.items():
        entry = corpus[session_id]
        serialized = serialize_input(build_model_input(entry.view, entry.context, references=True, annexes=False))
        assert input_hash(serialized) == expected, session_id
        assert json.loads(serialized)["input_version"] == 3


def test_compact_input_keeps_every_fact_and_ref_under_a_shorter_form(capture_timezone):
    corpus = {entry.id: entry for entry in load_corpus(DEFAULT_CORPUS)}
    entry = corpus["247f2062410ca5a9"]  # 16 faits file, 3 commandes, 1 commit
    v7, v8 = _inputs(entry)
    assert v8["input_version"] == 4
    workspace = v8["session"]["workspace"]
    before = v7["session"]["observations"]
    after = v8["session"]["observations"]

    # d. Les faits `file` sont en tableau, dans l'ordre, refs conservées.
    files_before = [fact for fact in before["timeline"] if fact["kind"] == "file"]
    table = after["files"]
    assert table["columns"] == ["ref", "at", "path", "changes"]
    assert table["change_columns"] == ["event", "first_at", "last_at", "count"]
    assert [row[0] for row in table["rows"]] == [fact["ref"] for fact in files_before]
    assert [row[2] for row in table["rows"]] == [fact["path"] for fact in files_before]
    assert all(fact["kind"] != "file" for fact in after["timeline"])
    assert [fact["ref"] for fact in after["timeline"]] == [
        fact["ref"] for fact in before["timeline"] if fact["kind"] != "file"
    ]
    # a. Le workspace de la session n'est plus répété fait par fait.
    assert all(fact["workspace"] == workspace for fact in files_before)
    assert "workspace" not in table["columns"]
    assert all("workspace" not in fact for fact in after["timeline"])
    # b. Dates entières, à la seconde.
    for row in table["rows"]:
        assert isinstance(row[1], int)
        for change in row[3]:
            assert isinstance(change[1], int) and isinstance(change[2], int)
    for fact in after["timeline"]:
        assert isinstance(fact["at"], int)
        if "started_at" in fact:
            assert fact["started_at"] is None or isinstance(fact["started_at"], int)
    for app in after["applications"]:
        assert isinstance(app["first_at"], int) and isinstance(app["last_at"], int)
    # c. Hash abrégé, message entier.
    commit_before = next(fact for fact in before["timeline"] if fact["kind"] == "commit")
    commit_after = next(fact for fact in after["timeline"] if fact["kind"] == "commit")
    assert len(commit_before["hash"]) == 40
    assert commit_after["hash"] == commit_before["hash"][:COMMIT_HASH_LENGTH]
    assert commit_after["message"] == commit_before["message"]
    # Le reste des observations est inchangé.
    for key in ("version", "time_origin", "time_unit", "last_observed", "coverage"):
        assert after[key] == before[key], key
    assert "sources" not in after
    assert len(serialize_input(v8)) < len(serialize_input(v7))


def test_a_foreign_workspace_stays_on_its_fact():
    observations = {
        "timeline": [
            {"ref": "o1", "kind": "file", "at": 1.6, "path": "a.py", "workspace": "/w",
             "changes": [{"event": "modified", "first_at": 1.6, "last_at": 2.4, "count": 2}]},
            {"ref": "o2", "kind": "file", "at": 3.2, "path": "b.py", "workspace": "/other",
             "changes": [{"event": "created", "first_at": 3.2, "last_at": 3.2, "count": 1}]},
            {"ref": "o3", "kind": "commit", "at": 4.5, "hash": "0123456789abcdef0123", "message": "m", "workspace": "/w", "branch": "main"},
            {"ref": "o4", "kind": "command", "at": 5.49, "started_at": None, "command": "ls", "cwd": "/w", "exit_code": 0},
        ],
        "applications": [{"ref": "app:1", "name": "Terminal", "first_at": 0.4, "last_at": 9.5, "activations": 1}],
    }
    compact = compact_observations(json.loads(json.dumps(observations)), "/w")
    assert compact["files"] == {
        "columns": ["ref", "at", "path", "changes", "workspace"],
        "change_columns": ["event", "first_at", "last_at", "count"],
        "rows": [
            ["o1", 2, "a.py", [["modified", 2, 2, 2]], None],
            ["o2", 3, "b.py", [["created", 3, 3, 1]], "/other"],
        ],
    }
    assert compact["timeline"] == [
        {"ref": "o3", "kind": "commit", "at": 4, "hash": "0123456789ab", "message": "m", "branch": "main"},
        {"ref": "o4", "kind": "command", "at": 5, "started_at": None, "command": "ls", "cwd": "/w", "exit_code": 0},
    ]
    assert compact["applications"] == [{"ref": "app:1", "name": "Terminal", "first_at": 0, "last_at": 10, "activations": 1}]
    # Sans workspace de session, rien n'est retiré.
    kept = compact_observations(observations, None)
    assert kept["files"]["rows"][0][4] == "/w"
    assert kept["timeline"][0]["workspace"] == "/w"


def test_no_file_table_without_file_facts(capture_timezone):
    corpus = {entry.id: entry for entry in load_corpus(DEFAULT_CORPUS)}
    for session_id in ("8af930d9ef437d2a", "2ce344566f7e85dc", "d98778994319cd07"):
        v7, v8 = _inputs(corpus[session_id])
        assert not any(fact["kind"] == "file" for fact in v7["session"]["observations"]["timeline"])
        assert "files" not in v8["session"]["observations"], session_id
        assert input_references(v7).refs == input_references(v8).refs
        assert len(serialize_input(v8)) < len(serialize_input(v7)), session_id


def test_no_compact_input_without_the_flag_on_a_legacy_view():
    from conftest import REFERENCE, session_view
    from pulse_intelligence.selection import SessionView

    legacy = SessionView(session_view("aaaaaaaaaaaaaaaa"), REFERENCE.date())
    value = build_model_input(legacy, {}, references=True, annexes=False, compact=True)
    assert value["input_version"] == 4
    assert value["session"]["chronology"] == "unavailable_in_legacy_snapshot"
    assert "observations" not in value["session"]
    assert input_references(value).paths == {"core/daemon_v2/routes.py"}


def test_v7_and_v8_accept_exactly_the_same_references_and_paths(capture_timezone):
    """Sur les 14 sessions : mêmes refs, mêmes chemins, mêmes relations de
    commandes, mêmes faits énumérés — le validateur ne distingue pas les deux."""
    for entry in load_corpus(DEFAULT_CORPUS):
        v7, v8 = _inputs(entry)
        r7, r8 = input_references(v7), input_references(v8)
        assert r7.refs == r8.refs, entry.id
        assert r7.paths == r8.paths == frozenset(input_paths(entry.view)), entry.id
        assert r7.outcomes == r8.outcomes, entry.id
        assert set(r7.observations) == set(r8.observations), entry.id
        for ref, fact in r7.observations.items():
            assert r8.observations[ref].get("kind") == fact.get("kind"), (entry.id, ref)
            if fact.get("kind") == "commit":
                assert r8.observations[ref]["message"] == fact["message"], (entry.id, ref)
            if fact.get("kind") == "command":
                assert r8.observations[ref]["command"] == fact["command"], (entry.id, ref)
        assert r7.previous_open == r8.previous_open == ()
        assert r7.agent_requests == r8.agent_requests == ()


def _output(reprise: dict, structured: dict) -> str:
    return json.dumps({"reprise": reprise, "structured": structured}, ensure_ascii=False)


def test_the_v7_outputs_of_the_benchmark_validate_identically_under_v8(capture_timezone):
    """Les 14 sorties Qwen du 2026-09-15 (prompt v7, preuves versionnées avec
    la décision) sont rejouées au validateur sous les références v7 et v8."""
    from pathlib import Path

    out = (Path(__file__).parent.parent.parent / "docs" / "decisions"
           / "2026-09-14-benchmark-modeles-en-local" / "out" / "qwen3.8-27b"
           / "mlx-mlx-community-Qwen3.8-27B-4bit")
    if not out.is_dir():
        pytest.skip(f"preuves du benchmark absentes : {out}")
    corpus = {entry.id: entry for entry in load_corpus(DEFAULT_CORPUS)}
    replayed = 0
    for path in sorted(out.glob("*.json")):
        if path.name == "meta.json":
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["status"] != "ok":
            continue
        entry = corpus[result["id"]]
        text = _output(
            {"doing": result["reprise"]["doing"], "stopped_at": result["reprise"]["stopped_at"],
             "open": result["open_items"]},
            result["structured"],
        )
        v7, v8 = _inputs(entry)
        parsed7 = parse_model_output(text, input_paths(entry.view), references=input_references(v7))
        parsed8 = parse_model_output(text, input_paths(entry.view), references=input_references(v8))
        assert parsed7 == parsed8, entry.id
        replayed += 1
    assert replayed == 14


def test_a_stopped_at_citing_a_short_hash_is_valid_under_both(capture_timezone):
    corpus = {entry.id: entry for entry in load_corpus(DEFAULT_CORPUS)}
    entry = corpus["1e420dda8b6eee77"]  # sept commits
    v7, v8 = _inputs(entry)
    commit = next(fact for fact in v8["session"]["observations"]["timeline"] if fact["kind"] == "commit")
    assert len(commit["hash"]) == COMMIT_HASH_LENGTH
    text = _output(
        {"doing": "Spécification de la couche LLMProvider.",
         "stopped_at": f"Après le commit {commit['hash']} ({commit['ref']}).",
         "open": [{"text": "Divergence list/run consignée.", "kind": "recorded_statement",
                   "evidence": ["o20"], "quote": "consigner la divergence list/run sur le modèle"}]},
        {"project": "Pulse", "intents": [], "central_files": [], "blockers": [], "confidence": "medium"},
    )
    for model_input in (v7, v8):
        parsed = parse_model_output(text, input_paths(entry.view), references=input_references(model_input))
        assert commit["hash"] in parsed.reprise["stopped_at"]
        assert parsed.open_items[0]["evidence"] == ["o20"]


def test_eval_and_summarize_build_the_compact_input_only_for_v8(tmp_path, capture_timezone):
    from pulse_intelligence.evaluation import evaluate
    from pulse_intelligence.llm.fake import FakeProvider
    from pulse_intelligence.provider_summarizer import ProviderSummarizer

    seen: dict[str, int] = {}
    for version in ("v7", "v8"):
        provider = FakeProvider()
        summarizer = ProviderSummarizer(provider=provider, model_id="fake/model", prompt_path=prompt_path_for(version))
        evaluate(summarizer, provider_name="fake", out_dir=tmp_path / version)
        versions = {json.loads(call.prompt)["input_version"] for call in provider.calls}
        assert len(versions) == 1, version
        seen[version] = versions.pop()
    assert seen == {"v7": 3, "v8": 4}
