"""État net des commandes : un échec suivi d'une commande similaire qui réussit
dans le même cwd est « dépassé » (superseded_observed), plus éligible à `open`.

Décision du 2026-09-11 (instruction T1, session 03 du corpus) : similaire =
même cwd connu + même tête (premier jeton shlex de la première ligne utile) ;
pour git, tête + sous-verbe, avec une tolérance Levenshtein ≤ 2 sur le
sous-verbe ; une chaîne n'est jamais dépassée par similarité ; un dernier
événement en échec et une relance qui échoue encore restent unresolved."""

from __future__ import annotations

from conftest import REFERENCE, session_view, valid_output
from pulse_intelligence.resumption import command_outcomes
from pulse_intelligence.selection import SessionView
from pulse_intelligence.session_input import build_model_input, input_paths, input_references
from pulse_intelligence.session_summary import InvalidModelOutput, parse_model_output

import json
import pytest

CWD = "/Users/Yugz/holbertonschool-agentic_ai/front_end-frameworks"


def cmd(ref, command, code, at, *, start=None, cwd=CWD):
    return {"kind": "command", "ref": ref, "command": command, "cwd": cwd,
            "exit_code": code, "at": float(at), "started_at": float(at if start is None else start),
            "exit_scope": "whole_command"}


def by_last(rows):
    return {row["last"]: row for row in rows}


# Extrait réel de la session 03 (6a4166356dbab6ec, eval/observed) : trois
# échecs corrigés à la commande suivante, jamais résolus par la clé exacte.
SESSION_03 = [
    cmd("o15", "cd ..", 0, 2476, cwd="/Users/Yugz/holbertonschool-agentic_ai/front_end-frameworks/vue"),
    cmd("o16", "git statuys", 1, 2478),
    cmd("o17", "git status", 0, 2480),
    cmd("o18", "git add .", 0, 2509),
    cmd("o19", 'git commit -m "Add Vue.js project setup"', 0, 2521),
    cmd("o20", "git add vue/ .gitignore", 128, 2897),
    cmd("o21", "git push", 0, 3199, start=3197),
    cmd("o22", "git add front_end-frameworks/{react,vue}/{vite.config.js,package.json}", 128, 4119),
    cmd("o23", "git add {react,vue}/{vite.config.js,package.json}", 0, 4157),
    cmd("o24", 'git commit -m "fix: deploy react & vue into separate gh-pages subfolders"', 0, 4162),
]


def test_session_03_typo_and_corrected_adds_are_superseded():
    rows = by_last(command_outcomes(SESSION_03))
    assert rows["o16"]["status"] == "superseded_observed" and rows["o16"]["superseded_by"] == "o17"
    assert rows["o20"]["status"] == "superseded_observed" and rows["o20"]["superseded_by"] == "o23"
    assert rows["o22"]["status"] == "superseded_observed" and rows["o22"]["superseded_by"] == "o23"
    assert all(row["resolved_by"] is None for row in rows.values())


def test_a_different_git_verb_does_not_supersede():
    # git push en échec, puis git status réussi : le push n'est pas dépassé.
    rows = by_last(command_outcomes([cmd("o1", "git push", 1, 10), cmd("o2", "git status", 0, 20)]))
    assert rows["o1"]["status"] == "unresolved_observed" and rows["o1"].get("superseded_by") is None


def test_same_head_supersedes_only_in_the_same_known_cwd():
    rows = by_last(command_outcomes([cmd("o1", "bash check-setup.sh", 127, 10), cmd("o2", "bash check-setup.sh", 0, 20, cwd="/other")]))
    assert rows["o1"]["status"] == "unresolved_observed"
    rows = by_last(command_outcomes([cmd("o1", "bash check-setup.s", 127, 10), cmd("o2", "bash check-setup.sh", 0, 20)]))
    assert rows["o1"]["status"] == "superseded_observed" and rows["o1"]["superseded_by"] == "o2"
    # cwd inconnu : pas d'identité entre exécutions, jamais dépassé.
    rows = by_last(command_outcomes([cmd("o1", "bash x.sh", 1, 10, cwd=None), cmd("o2", "bash y.sh", 0, 20, cwd=None)]))
    assert rows["o1"]["status"] == "unresolved_observed"


def test_git_subverb_typo_within_two_edits_counts_as_the_same_verb():
    rows = by_last(command_outcomes([cmd("o1", "git sattus", 1, 10), cmd("o2", "git status", 0, 20)]))
    assert rows["o1"]["status"] == "superseded_observed"
    rows = by_last(command_outcomes([cmd("o1", "git checkout x", 1, 10), cmd("o2", "git commit", 0, 20)]))
    assert rows["o1"]["status"] == "unresolved_observed"


def test_a_chain_is_never_superseded_by_similarity_only_by_the_exact_chain():
    chain = 'git add . && git commit -m "x" && git push'
    rows = by_last(command_outcomes([cmd("o1", chain, 128, 10), cmd("o2", 'git add . && git commit -m "y" && git push', 0, 20)]))
    assert rows["o1"]["status"] == "unresolved_observed"
    rows = by_last(command_outcomes([cmd("o1", chain, 128, 10), cmd("o2", "git add .", 0, 20)]))
    assert rows["o1"]["status"] == "unresolved_observed"
    rows = by_last(command_outcomes([cmd("o1", chain, 128, 10), cmd("o2", chain, 0, 20)]))
    assert rows["o2"]["status"] == "resolved_observed" and rows["o2"]["resolved_by"] == "o2"
    # Un bloc multi-lignes est une chaîne au même titre (exit_scope = whole_command).
    rows = by_last(command_outcomes([cmd("o1", "git add x\ngit commit -m y", 1, 10), cmd("o2", "git add x", 0, 20)]))
    assert rows["o1"]["status"] == "unresolved_observed"


def test_last_failure_and_failing_relaunch_stay_unresolved():
    rows = by_last(command_outcomes([cmd("o1", "manage.py migrate", 127, 10), cmd("o2", "manage.py migrate", 127, 20)]))
    assert rows["o2"]["status"] == "unresolved_observed" and rows["o2"]["failures"] == ["o1", "o2"]
    # succès similaire entre deux échecs de la même clé : le dernier échec n'est pas dépassé
    rows = by_last(command_outcomes([cmd("o1", "git add a", 1, 10), cmd("o2", "git add b", 0, 20), cmd("o3", "git add a", 1, 30)]))
    assert rows["o3"]["status"] == "unresolved_observed"
    # succès similaire avant l'échec : sans effet
    rows = by_last(command_outcomes([cmd("o1", "git add b", 0, 10), cmd("o2", "git add a", 1, 20)]))
    assert rows["o2"]["status"] == "unresolved_observed"


def test_the_validator_refuses_a_superseded_failure_in_open():
    raw = session_view("cccccccccccccccc")
    raw["observations"] = {"timeline": SESSION_03, "last_observed": {}}
    session = SessionView(raw, REFERENCE.date())
    model_input = build_model_input(session, {}, references=True, annexes=False)
    statuses = {o["last"]: o["status"] for o in model_input["resumption"]["command_outcomes"]}
    assert statuses == {"o16": "superseded_observed", "o20": "superseded_observed", "o22": "superseded_observed"}
    output = json.loads(valid_output())
    output["reprise"]["open"] = [{"text": "git statuys a échoué", "kind": "command_failure", "evidence": ["o16"]}]
    with pytest.raises(InvalidModelOutput, match="dernier échec sans résolution observée"):
        parse_model_output(json.dumps(output), input_paths(session), references=input_references(model_input))
