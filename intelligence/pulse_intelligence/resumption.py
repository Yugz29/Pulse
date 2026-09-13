"""Bounded temporal relations, never a model of the current worktree.

Only identical command text in the same known cwd identifies a retry. A later
successful process must start after the failed one ended. This says nothing
about individual subcommands, the cause, or the health of the application.

État net des commandes (décision du 2026-09-11, cas « échec dépassé », PR #89 ;
ratifiée au merge par docs/decisions/2026-09-12-prompt-v7.md, « Règle de la
PR #89 ») : un
dernier échec d'une clé exacte est ``superseded_observed`` quand une commande
*similaire* réussit ensuite dans le même cwd connu. Similaire = même tête
(premier jeton shlex de la première ligne utile) ; pour git, tête + sous-verbe,
un sous-verbe à distance de Levenshtein ≤ 2 comptant comme le même (faute de
frappe). Une chaîne (``&&``, ``;``, ``|``, retour à la ligne…) n'est jamais
dépassée par similarité, seulement résolue par la même chaîne exacte :
``exit_scope = whole_command`` ne dit pas quel maillon a échoué. Un échec
dépassé n'est plus éligible à ``open``.
"""
from __future__ import annotations

import shlex
from typing import Any


# Même critère que `_simple_command` de Core : un opérateur, même cité, fait
# une chaîne (un faux « composé » vaut mieux qu'un faux « dépassé »).
_CHAIN_CHARS = "\n;&|<>`$()"
_GIT_TYPO_DISTANCE = 2


def _is_chain(command: str) -> bool:
    return any(c in command for c in _CHAIN_CHARS)


def _head(command: str) -> tuple[str, ...] | None:
    """La tête d'une commande simple : premier jeton, plus le sous-verbe pour git."""
    try:
        parts = shlex.split(command.strip().splitlines()[0]) if command.strip() else []
    except ValueError:
        return None
    if not parts:
        return None
    if parts[0] == "git":
        return ("git", parts[1]) if len(parts) >= 2 else ("git",)
    return (parts[0],)


def _levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _similar(failed: tuple[str, ...], succeeded: tuple[str, ...]) -> bool:
    if failed == succeeded:
        return True
    if failed[0] == "git" == succeeded[0] and len(failed) == len(succeeded) == 2:
        return _levenshtein(failed[1], succeeded[1]) <= _GIT_TYPO_DISTANCE
    return False


def _superseding_success(failure: dict[str, Any], facts: list[dict[str, Any]]) -> str | None:
    """La première commande simple similaire réussie après l'échec, même cwd connu."""
    command = failure["command"]
    if not failure.get("cwd") or _is_chain(command):
        return None
    head = _head(command)
    if head is None:
        return None
    for fact in facts:
        if fact.get("kind") != "command" or fact.get("cwd") != failure["cwd"]:
            continue
        if not (type(fact.get("exit_code")) is int and fact["exit_code"] == 0):
            continue
        if fact.get("started_at") is None or fact["started_at"] < failure["at"]:
            continue
        if _is_chain(fact["command"]):
            continue
        other = _head(fact["command"])
        if other is not None and _similar(head, other):
            return fact["ref"]
    return None


def command_outcomes(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fact in facts:
        if fact.get("kind") != "command":
            continue
        # Unknown cwd cannot establish identity across separate executions.
        key = (fact["command"], fact.get("cwd") or fact["ref"])
        groups.setdefault(key, []).append(fact)
    outcomes = []
    for executions in groups.values():
        failures = [f for f in executions if type(f.get("exit_code")) is int
                    and f["exit_code"] > 0 and f["exit_code"] != 130]
        if not failures:
            continue
        latest = executions[-1]
        status = "unknown"
        resolved_by = None
        superseded_by = None
        if latest in failures:
            status = "unresolved_observed"
            superseded_by = _superseding_success(failures[-1], facts)
            if superseded_by is not None:
                status = "superseded_observed"
        elif (type(latest.get("exit_code")) is int and latest["exit_code"] == 0
              and latest.get("cwd") and latest.get("started_at") is not None
              and latest["started_at"] >= failures[-1]["at"]):
            status = "resolved_observed"
            resolved_by = latest["ref"]
        outcomes.append({
            "last": latest["ref"], "failures": [f["ref"] for f in failures],
            "status": status, "resolved_by": resolved_by,
            "superseded_by": superseded_by,
        })
    return outcomes
