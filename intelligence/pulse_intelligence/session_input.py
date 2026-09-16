"""Model-visible work observations; exhaustive provenance stays with Pulse.

Core owns the ordered projection. Intelligence selects the visible fields and
separates previous interpretations and agent requests from observations. Old
aggregate snapshots remain readable with explicit missing chronology; they
cannot be upgraded by guessing the order of their lists.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import posixpath
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .selection import SessionView
from .resumption import command_outcomes


# Les prompts dont `open` est une chaîne libre (contrat d'origine). Tout
# autre prompt attend la liste d'objets du schéma v3 et reçoit une entrée
# référencée.
LEGACY_OPEN_PROMPT_VERSIONS = frozenset({"v1", "v2"})


def uses_open_items(prompt_version: str) -> bool:
    """Le prompt attend-il des points ouverts référencés (schéma v3) ?"""
    return prompt_version not in LEGACY_OPEN_PROMPT_VERSIONS


# v6 : même contrat de sortie que v5, entrée sans annexes. Sous v5 les annexes
# étaient lisibles mais jamais citables (`_resumption_items`), et le modèle
# recopiait `doing` / `stopped_at` du résumé précédent (dogfooding, jour 5).
# Rejeu `open` du 2026-09-11 (adjudication, synthèse §3.2) : trois variantes
# de v6 à entrée constante, sans la phrase « [] est préférable à un reste
# hypothétique », sans l'exemple `"open": []`, ou sans les deux. Même entrée
# que v6, sinon la comparaison ne dit rien.
# v7 : la variante complète du rejeu (sans la phrase ni l'exemple `[]`),
# enregistrée le 2026-09-11 pour la mesure sur les 14 sessions du corpus.
# Pas le défaut : `Config.prompt_version` reste v6 tant que la mesure n'est
# pas jugée.
PROMPT_VERSIONS_WITHOUT_ANNEXES = frozenset({
    "v6", "v6-sans-phrase", "v6-sans-exemple", "v6-sans-phrase-ni-exemple", "v7", "v8",
})


# v8 (chantier expérimental du 2026-09-16, branche exp/intelligence-compact-input) :
# le texte de v7 plus la description d'une entrée compacte, `input_version`
# 4. Mêmes faits, mêmes `ref`, moins d'octets : workspace omis quand il est
# celui de la session, dates arrondies à la seconde, hash de commit abrégé à
# 12 caractères, faits `file` en tableau à colonnes déclarées une fois. Les
# messages de commit restent entiers. L'entrée compacte n'est construite que
# pour ce prompt : v7 reste octet pour octet ce qu'il était.
COMPACT_INPUT_PROMPT_VERSIONS = frozenset({"v8"})
COMPACT_INPUT_VERSION = 4
# Colonnes du tableau des faits `file`, dans cet ordre ; une clé imprévue
# d'un fait s'ajoute en colonne à la suite, rien n'est perdu. `kind` n'est
# pas une colonne : tout le tableau est du genre `file`.
FILE_COLUMNS = ("ref", "at", "path", "changes", "workspace")
CHANGE_COLUMNS = ("event", "first_at", "last_at", "count")
COMMIT_HASH_LENGTH = 12
# Les versions d'entrée fondées sur les observations ordonnées de Core (v3 et
# sa forme compacte v4) : mêmes références, même validation `open`.
OBSERVATION_INPUT_VERSIONS = frozenset({3, COMPACT_INPUT_VERSION})


# Genres de faits que Core observe mais qu'aucune version de prompt ne décrit :
# ils restent dans la trace et le journal, pas dans l'entrée du modèle. Les
# faits `window` (Core 0.7.0.0) sont entrés sans description ; le lot du
# 2026-09-13 a refusé une session de 126 min à 174 548 tokens, dont 85 % de
# faits `window` (titres de Terminal au spinner alterné). Ils reviendront avec
# une version de prompt qui les décrit (décision contexte de fenêtre,
# addendum du 2026-09-13).
FACT_KINDS_HIDDEN_FROM_MODEL = frozenset({"window"})


def _hidden_refs(observations: Any) -> set[str]:
    if not isinstance(observations, dict):
        return set()
    return {
        fact["ref"]
        for fact in observations.get("timeline", [])
        if fact.get("kind") in FACT_KINDS_HIDDEN_FROM_MODEL
    }


def uses_annexes(prompt_version: str) -> bool:
    """Le prompt reçoit-il `previous_summary` et `agent_session` ?"""
    return prompt_version not in PROMPT_VERSIONS_WITHOUT_ANNEXES


def uses_compact_input(prompt_version: str) -> bool:
    """Le prompt décrit-il l'entrée compacte (`input_version` 4) ?"""
    return prompt_version in COMPACT_INPUT_PROMPT_VERSIONS


# Un point par phrase : fin de phrase suivie d'un blanc, ou point-virgule.
_OPEN_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\s*;\s+")


def split_open_text(text: Any) -> list[str]:
    """Les points d'un ``open`` servi par Core (une chaîne), dans l'ordre.

    Déterministe, sans jugement : c'est le seul découpage que le validateur
    et l'annexe partagent. Une liste (aucun résumé émis à ce jour n'en porte)
    est reprise telle quelle, chaîne par chaîne."""
    if isinstance(text, list):
        return [item.strip() for item in text if isinstance(item, str) and item.strip()]
    if not isinstance(text, str):
        return []
    return [part.strip() for part in _OPEN_BOUNDARY.split(text) if part.strip()]


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def previous_summary_annex(
    context: dict[str, Any], session: SessionView, *, references: bool = False
) -> dict[str, Any] | None:
    """Earlier interpretation in the same day, never independent evidence.

    Own, future and known foreign-workspace summaries are excluded. The
    single optional reference audits the context received, not its truth.
    """
    previous = context.get("last_session_summary")
    if not isinstance(previous, dict):
        return None
    if previous.get("id") == session.id:
        return None
    ended = _instant(previous.get("session_ended_at"))
    if ended is None or ended.astimezone().date() != session.day or ended > session.started_at:
        return None
    workspace = session.raw.get("workspace")
    previous_workspace = previous.get("workspace")
    if workspace and previous_workspace and posixpath.normpath(workspace) != posixpath.normpath(previous_workspace):
        return None
    annex: dict[str, Any] = {
        "origin": "previous_model_interpretation",
        "evidence_eligible": False,
        "as_of": previous.get("session_ended_at"),
        "current_state": "unknown",
        "workspace_attribution": "same_workspace" if workspace and previous_workspace else "unknown",
        "id": previous.get("id"),
        "label": previous.get("label"),
        "reprise": previous.get("reprise"),
    }
    if references:
        # One source for the interpretation, not evidence tokens for each
        # generated claim. No autonomous carry-over chain is created.
        annex["ref"] = "previous_summary:0"
    return annex


def agent_session_annex(
    context: dict[str, Any], session: SessionView, *, references: bool = False
) -> dict[str, Any] | None:
    """Le dernier agent_session s'il chevauche la session, sinon rien."""
    agent = context.get("last_agent_session")
    if not isinstance(agent, dict):
        return None
    started = _instant(agent.get("started_at"))
    ended = _instant(agent.get("ended_at"))
    if started is None or ended is None:
        return None
    if started > session.ended_at or ended < session.started_at:
        return None
    workspace = session.raw.get("workspace")
    agent_workspace = agent.get("workspace")
    if workspace and agent_workspace and posixpath.normpath(workspace) != posixpath.normpath(agent_workspace):
        return None
    annex: dict[str, Any] = {
        "origin": "initial_agent_request",
        "evidence_eligible": False,
        "completion_state": "unknown",
        "workspace_attribution": "same_workspace" if workspace and agent_workspace else "unknown",
        "workspace": agent_workspace,
        "agent": agent.get("agent"),
        "started_at": agent.get("started_at"),
        "ended_at": agent.get("ended_at"),
        "summary": agent.get("summary"),
    }
    if references:
        annex["ref"] = "agent_request:0"
    return annex


def build_model_input(
    session: SessionView,
    context: dict[str, Any],
    *,
    references: bool = False,
    annexes: bool = True,
    compact: bool = False,
) -> dict[str, Any]:
    """Only useful observations reach the model; never event UUIDs.

    Les faits de `FACT_KINDS_HIDDEN_FROM_MODEL` sont retirés de la ligne de
    temps visible ; les autres gardent leur `ref` d'origine, sans
    renumérotation (la provenance du résumé s'y rattache).

    ``annexes=False`` (prompt v6) : les deux clés restent présentes et valent
    None, comme quand Core n'a rien — aucun cas spécial en aval.

    ``compact=True`` (prompt v8) : mêmes faits et mêmes `ref`, sous la forme
    compacte de `input_version` 4 (`compact_observations`). Sans ce drapeau,
    l'entrée est celle de v7, octet pour octet.
    """
    raw = session.raw
    visible = {key: copy.deepcopy(raw.get(key)) for key in (
        "id", "started_at", "last_activity_at", "duration_minutes", "projects", "workspace"
    )}
    observations = raw.get("observations")
    if isinstance(observations, dict):
        visible["observations"] = {key: copy.deepcopy(value) for key, value in observations.items() if key != "sources"}
        visible["observations"]["timeline"] = [
            fact for fact in visible["observations"].get("timeline", [])
            if fact.get("kind") not in FACT_KINDS_HIDDEN_FROM_MODEL
        ]
        if compact:
            visible["observations"] = compact_observations(visible["observations"], visible.get("workspace"))
    else:
        # Targeted read compatibility for frozen corpus / older Core. These
        # lists cannot establish a last result, a file state, or chronology.
        visible["legacy_aggregates"] = {key: copy.deepcopy(raw.get(key)) for key in ("files", "git", "terminal", "apps", "signals")}
        visible["chronology"] = "unavailable_in_legacy_snapshot"
    return {
        "input_version": COMPACT_INPUT_VERSION if compact else 3,
        "session": visible,
        "resumption": {
            "as_of": raw.get("last_activity_at"),
            "current_state": "unknown",
            "command_outcomes": command_outcomes((observations or {}).get("timeline", [])),
        },
        "previous_summary": previous_summary_annex(context, session, references=references) if annexes else None,
        "agent_session": agent_session_annex(context, session, references=references) if annexes else None,
    }


def _second(value: Any) -> Any:
    """Une date en secondes depuis `time_origin`, arrondie à la seconde entière."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return int(round(value))


def _columns(records: list[dict[str, Any]], preferred: tuple[str, ...]) -> list[str]:
    """Les colonnes réellement portées par ces enregistrements : celles de
    `preferred` qui apparaissent, dans cet ordre, puis toute clé imprévue."""
    present = {key for record in records for key in record}
    columns = [key for key in preferred if key in present]
    columns.extend(sorted(present - set(preferred)))
    return columns


def compact_observations(observations: dict[str, Any], workspace: str | None) -> dict[str, Any]:
    """La forme compacte (`input_version` 4) d'observations déjà filtrées.

    Quatre transformations, rien d'autre : le `workspace` d'un fait est omis
    quand il est celui de la session ; les dates sont arrondies à la seconde ;
    le hash d'un commit est abrégé à `COMMIT_HASH_LENGTH` ; les faits `file`
    quittent `timeline` pour le tableau `files` (colonnes déclarées une fois,
    une ligne par fait, dans l'ordre de la chronologie). Les `ref` ne sont
    pas renumérotées, les messages de commit restent entiers, aucun fait
    n'est retiré. `observations` est déjà une copie : modifiée en place.
    """
    files: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    for fact in observations.get("timeline", []):
        fact = dict(fact)
        for key in ("at", "started_at"):
            if key in fact:
                fact[key] = _second(fact[key])
        if workspace and fact.get("workspace") == workspace:
            del fact["workspace"]
        if fact.get("kind") == "commit" and isinstance(fact.get("hash"), str):
            fact["hash"] = fact["hash"][:COMMIT_HASH_LENGTH]
        if fact.get("kind") == "file":
            del fact["kind"]
            files.append(fact)
        else:
            timeline.append(fact)
    change_columns = _columns(
        [change for fact in files for change in fact.get("changes") or [] if isinstance(change, dict)],
        CHANGE_COLUMNS,
    )
    for fact in files:
        if isinstance(fact.get("changes"), list):
            fact["changes"] = [
                [_second(change.get(column)) if column in ("first_at", "last_at") else change.get(column)
                 for column in change_columns]
                if isinstance(change, dict) else change
                for change in fact["changes"]
            ]
    columns = _columns(files, FILE_COLUMNS)
    observations["timeline"] = timeline
    # Sans fait `file`, pas de tableau : rien à déclarer pour rien. Le prompt
    # v8 décrit l'absence. (Ce n'est pas ce qui fait monter les sessions sans
    # fichier : c'est le prompt v8, 104 tokens de plus que v7 ; mesure du
    # 2026-09-16, docs/audits/2026-09-16-entree-compacte.)
    if files:
        observations["files"] = {
            "columns": columns,
            "change_columns": change_columns,
            "rows": [[fact.get(column) for column in columns] for fact in files],
        }
    else:
        observations.pop("files", None)
    observations["applications"] = [
        {key: _second(value) if key in ("first_at", "last_at") else value for key, value in app.items()}
        if isinstance(app, dict) else app
        for app in observations.get("applications", [])
    ]
    return observations


def expand_file_table(observations: dict[str, Any]) -> list[dict[str, Any]]:
    """Les faits `file` d'une entrée compacte, redevenus des objets (`kind`
    compris), pour que la validation les énumère comme ceux de la timeline."""
    table = observations.get("files")
    if not isinstance(table, dict):
        return []
    columns = table.get("columns") or []
    return [
        {"kind": "file", **dict(zip(columns, row))}
        for row in table.get("rows") or []
        if isinstance(row, list)
    ]


def serialize_input(model_input: dict[str, Any]) -> str:
    return json.dumps(
        model_input,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def input_hash(serialized: str) -> str:
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def input_paths(session: SessionView) -> set[str]:
    """Les chemins que le modèle a le droit de citer : ceux de la vue, rien d'autre."""
    observations = session.raw.get("observations")
    if isinstance(observations, dict):
        return {fact["path"] for fact in observations.get("timeline", []) if fact.get("kind") == "file"}
    files = session.raw.get("files", {})
    paths: set[str] = set()
    if isinstance(files, dict):
        for category in ("created", "modified", "deleted"):
            for path in files.get(category, []) or []:
                if isinstance(path, str) and path:
                    paths.add(path)
    return paths


@dataclass(frozen=True)
class InputReferences:
    """Visible references and annex roles; membership is not proof of truth."""

    refs: frozenset[str]
    paths: frozenset[str]
    previous_open: tuple[str, ...]
    agent_requests: tuple[str, ...]
    # None denotes an archived input contract. Current validation uses the
    # actual observation types and bounded relations, never prose matching.
    observations: dict[str, dict[str, Any]] | None = None
    outcomes: tuple[dict[str, Any], ...] = ()

    def __contains__(self, ref: object) -> bool:
        return ref in self.refs


def _strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str) and value]


def input_references(model_input: dict[str, Any]) -> InputReferences:
    """Toutes les références valides pour cette entrée, et rien d'autre.

    Même principe que ``input_paths`` pour ``central_files`` : une référence
    qui n'est pas ici n'existe pas, quel que soit son air de vraisemblance.
    L'énumération ne dépend pas de ``references=True`` : les clés viennent de
    la vue Core, les annexes ne font que les rendre visibles au modèle.
    """
    session = model_input.get("session") or {}
    observations = session.get("observations") or {}
    facts = (
        observations.get("timeline", [])
        + expand_file_table(observations)
        + observations.get("applications", [])
    )
    refs: set[str] = {fact["ref"] for fact in facts}
    paths: set[str] = {fact["path"] for fact in facts if fact.get("kind") == "file"}
    # Old reference names remain readable for historical evaluations only.
    session = session.get("legacy_aggregates", session)
    files = session.get("files") if isinstance(session, dict) else None
    if isinstance(files, dict):
        for category in ("created", "modified", "deleted"):
            paths.update(_strings(files.get(category)))
    if not observations:
        refs.update(f"path:{path}" for path in paths)
    git = session.get("git") if isinstance(session, dict) else None
    commits: list[str] = [fact["ref"] for fact in facts if fact.get("kind") == "commit"]
    if isinstance(git, dict):
        for commit in git.get("commits") or []:
            if isinstance(commit, dict) and isinstance(commit.get("hash"), str) and commit["hash"]:
                commits.append(f"commit:{commit['hash']}")
    refs.update(commits)
    if isinstance(session, dict):
        refs.update(f"event:{event_id}" for event_id in _strings(session.get("source_event_ids")))
        refs.update(f"signal:{name}" for name in _strings(session.get("signals")))
        for app in session.get("apps") or []:
            if isinstance(app, dict) and isinstance(app.get("name"), str) and app["name"]:
                refs.add(f"app:{app['name']}")
        terminal = session.get("terminal")
        if isinstance(terminal, dict):
            refs.update(f"test_passed:{command}" for command in _strings(terminal.get("tests_passed")))
            refs.update(f"test_failed:{command}" for command in _strings(terminal.get("tests_failed")))
            refs.update(f"error:{text}" for text in _strings(terminal.get("errors")))

    previous = model_input.get("previous_summary")
    previous_open: tuple[str, ...] = ()
    if isinstance(previous, dict):
        if model_input.get("input_version") in OBSERVATION_INPUT_VERSIONS:
            if previous.get("ref"):
                refs.add(previous["ref"])
        else:
            reprise = previous.get("reprise")
            received = reprise.get("open") if isinstance(reprise, dict) else None
            previous_open = tuple(split_open_text(received))
            refs.update(f"previous_summary:{index}" for index in range(len(previous_open)))

    agent_requests: tuple[str, ...] = ()
    if isinstance(model_input.get("agent_session"), dict):
        agent_requests = ("agent_request:0",)
        refs.update(agent_requests)

    return InputReferences(
        refs=frozenset(refs),
        paths=frozenset(paths),
        previous_open=previous_open,
        agent_requests=agent_requests,
        observations={fact["ref"]: fact for fact in facts} if model_input.get("input_version") in OBSERVATION_INPUT_VERSIONS else None,
        outcomes=tuple(model_input.get("resumption", {}).get("command_outcomes", [])),
    )


def input_provenance(session: SessionView, context: dict[str, Any], model_input: dict[str, Any]) -> dict[str, list[str]]:
    """Source ids for exactly the observations and annexes made visible."""
    observations = session.raw.get("observations") or {}
    hidden = _hidden_refs(observations)
    sources = {
        ref: copy.deepcopy(ids)
        for ref, ids in observations.get("sources", {}).items()
        if ref not in hidden
    }
    for key, context_key in (("agent_session", "last_agent_session"), ("previous_summary", "last_session_summary")):
        annex = model_input.get(key)
        source = context.get(context_key)
        if not isinstance(annex, dict) or not isinstance(source, dict):
            continue
        source_id = source.get("event_id")
        if not isinstance(source_id, str):
            continue
        refs = [annex["ref"]] if "ref" in annex else [item["ref"] for item in annex.get("open_items", [])]
        for ref in refs:
            sources[ref] = [source_id]
    return sources
