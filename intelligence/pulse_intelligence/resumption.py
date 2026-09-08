"""Bounded temporal relations, never a model of the current worktree.

Only identical command text in the same known cwd identifies a retry. A later
successful process must start after the failed one ended. This says nothing
about individual subcommands, the cause, or the health of the application.
"""
from __future__ import annotations

from typing import Any


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
        if latest in failures:
            status = "unresolved_observed"
        elif (type(latest.get("exit_code")) is int and latest["exit_code"] == 0
              and latest.get("cwd") and latest.get("started_at") is not None
              and latest["started_at"] >= failures[-1]["at"]):
            status = "resolved_observed"
            resolved_by = latest["ref"]
        outcomes.append({
            "last": latest["ref"], "failures": [f["ref"] for f in failures],
            "status": status, "resolved_by": resolved_by,
        })
    return outcomes
