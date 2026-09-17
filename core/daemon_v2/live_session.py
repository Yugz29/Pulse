"""La session de travail en cours, rangée pour la page : aucun modèle, aucun stockage.

Étape 1 de ``docs/decisions/2026-09-17-resumes-en-continu.md``. Le bloc
« Session en cours » range les faits de la session ouverte, tels que
``project_work_observations`` les numérote (les mêmes oN que ``/context``) :
commits, fichiers les plus touchés, dernier test, commandes en échec,
sessions d'agent terminées. Calculé à chaque rendu depuis la trace du jour ;
rien n'est écrit, aucun contrat n'est touché.

Les échecs sont **bruts** : code et heure, jamais « résolu » ni « dépassé ».
L'état net des commandes vit côté Intelligence (``resumption.py``) ; Core ne
le recalcule pas (décision du 2026-09-17).

L'identité d'une session ouverte change à chaque événement : ce module ne
s'y rattache pas, il ne renvoie que ce qu'il voit à l'instant du rendu.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .analysis.timeline import _displayed_sessions
from .daily_trace import agent_session_views
from .work_observations import project_work_observations

# Au-delà, le reste est compté, pas listé : le bloc range, il ne déroule pas
# la chronologie (elle est plus bas dans la page, en entier).
MAX_FILES = 8
MAX_FAILURES = 8


def build_live_session(trace: dict[str, Any]) -> dict[str, Any] | None:
    """Les faits rangés de la session ouverte, ou ``None`` s'il n'y en a pas.

    La session en cours est la dernière session affichée quand sa fin est
    ``open`` : la même que le titre « en cours » de la page.
    """
    sessions = _displayed_sessions(trace)
    if not sessions or sessions[-1].get("end_reason") != "open":
        return None
    session = sessions[-1]
    observations = project_work_observations(session["activities"])
    origin = observations["time_origin"]
    timeline = observations["timeline"]

    def instant(offset: Any) -> str | None:
        if origin is None or not isinstance(offset, (int, float)):
            return None
        moment = datetime.fromisoformat(origin) + timedelta(seconds=float(offset))
        return moment.astimezone(timezone.utc).isoformat()

    commits = [
        {
            "ref": fact["ref"],
            "kind": "commit",
            "at": instant(fact["at"]),
            "hash": fact.get("hash"),
            "branch": fact.get("branch"),
            "message": fact.get("message"),
        }
        for fact in timeline
        if fact["kind"] == "commit"
    ]
    commands = [
        {
            "ref": fact["ref"],
            "kind": "command",
            "at": instant(fact["at"]),
            "command": fact.get("command") or "",
            "exit_code": fact.get("exit_code") if type(fact.get("exit_code")) is int else None,
            "cwd": fact.get("cwd"),
            "test_command": bool(fact.get("test_command")),
        }
        for fact in timeline
        if fact["kind"] == "command"
    ]
    tests = [command for command in commands if command["test_command"]]
    # 130 est une interruption volontaire, pas un échec (comme ``/context``).
    failures = [
        command for command in commands if command["exit_code"] not in (None, 0, 130)
    ]
    files = _files(timeline, instant)
    started = _utc(session["started_at"])
    ended = _utc(session["ended_at"])
    return {
        "session_index": len(sessions),
        "started_at": started.isoformat(),
        "last_activity_at": ended.isoformat(),
        "duration_minutes": max(0, int((ended - started).total_seconds() // 60)),
        "activity_count": len(session["activities"]),
        "fact_count": len(timeline),
        "commits": commits,
        "files": files[:MAX_FILES],
        "file_count": len(files),
        "last_test": tests[-1] if tests else None,
        "test_count": len(tests),
        "failed_test_count": sum(test in failures for test in tests),
        "failures": list(reversed(failures))[:MAX_FAILURES],
        "failure_count": len(failures),
        "agent_sessions": _agent_sessions(trace, started),
    }


def _files(timeline: list[dict[str, Any]], instant: Any) -> list[dict[str, Any]]:
    """Un fichier par chemin, du plus touché au moins touché.

    Un même chemin a un fait par intervalle entre deux commandes ou commits :
    ses faits sont réunis, leurs références gardées.
    """
    by_path: dict[tuple[Any, str], dict[str, Any]] = {}
    for fact in timeline:
        if fact["kind"] != "file":
            continue
        entry = by_path.setdefault(
            (fact.get("workspace"), fact["path"]),
            {"path": fact["path"], "refs": [], "changes": {}, "count": 0, "last_at": None},
        )
        entry["refs"].append(fact["ref"])
        for change in fact.get("changes", []):
            entry["changes"][change["event"]] = (
                entry["changes"].get(change["event"], 0) + change["count"]
            )
            entry["count"] += change["count"]
            last = instant(change.get("last_at"))
            if last and (entry["last_at"] is None or last > entry["last_at"]):
                entry["last_at"] = last
    return sorted(
        by_path.values(),
        key=lambda entry: (-entry["count"], entry["path"]),
    )


def _agent_sessions(trace: dict[str, Any], started: datetime) -> list[dict[str, Any]]:
    """Sessions d'agent terminées depuis le début de la session en cours.

    Elles ne composent pas la session de travail (décision du 2026-09-03) :
    elles sont seulement rapprochées par le temps, et listées comme telles.
    """
    found = []
    for view in agent_session_views(trace):
        ended_at = view["ended_at"] or view["occurred_at"]
        if _utc(ended_at) >= started:
            found.append({**view, "ended_at": _utc(ended_at).isoformat()})
    return found


def _utc(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
