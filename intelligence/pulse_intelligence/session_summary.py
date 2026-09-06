"""Résumer une session : parsing, validation, événement, émission (spec v2 §6–§7).

Une seule fonction fait le travail, ``summarize_session`` ; la CLI et,
plus tard, le job périodique n'appellent rien d'autre. Tout ce que le
modèle écrit est non fiable : validé par schéma ici, rédigé par Core à
l'ingestion, et un chemin cité qui n'existe pas dans l'entrée invalide le
résumé. Rien n'atteint ``trace.db`` avant validation.
"""

from __future__ import annotations

import json
import sys
import re
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any

from . import PRODUCER_NAME, __version__
from .config import Config
from .core_client import CoreClient, CoreError, CoreUnavailable
from .selection import SessionView, select_candidates
from .session_input import (
    InputReferences,
    build_model_input,
    input_hash,
    input_paths,
    input_references,
    serialize_input,
    uses_open_items,
)
from .state import JobState
from .summarizer import (
    Summarizer,
    SummarizerError,
    SummarizerInputRefused,
    SummarizerUnavailable,
)


CONFIDENCE_LEVELS = ("high", "medium", "low")
MAX_INTENTS = 3
MAX_CENTRAL_FILES = 5
MAX_BLOCKERS = 3
MAX_STRING_LENGTH = 300
# Schéma `open` v3 : une liste de points, chacun d'une nature déclarée et
# étayé par des références de l'entrée (`session_input.input_references`).
MAX_OPEN_ITEMS = 5
OPEN_KINDS = ("observed", "carried_over", "requested")
OPEN_ITEM_KEYS = frozenset({"text", "kind", "evidence", "carried_from", "reason_kept"})
EMPTY_OPEN_TEXT = "Aucun point ouvert étayé par les faits de la session."


class InvalidModelOutput(ValueError):
    """La sortie du modèle ne respecte pas le schéma : on n'écrit rien."""


# --- Parsing et validation ----------------------------------------------------


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


@dataclass(frozen=True)
class ParsedSummary:
    reprise: dict[str, str]
    structured: dict[str, Any]
    # Schéma v3 : les points ouverts tels que validés (texte, nature,
    # preuves). `reprise["open"]` en est le rendu texte, seul format que Core
    # accepte ; `None` pour une sortie au schéma d'origine.
    open_items: list[dict[str, Any]] | None = None


def _bounded_string(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidModelOutput(f"{name} absente ou vide")
    cleaned = value.strip()
    if len(cleaned) > MAX_STRING_LENGTH:
        raise InvalidModelOutput(
            f"{name}: {len(cleaned)} caractères, max {MAX_STRING_LENGTH}"
        )
    return cleaned


def _string_list(value: Any, *, name: str, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidModelOutput(f"structured.{name} doit être une liste")
    cleaned = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise InvalidModelOutput(f"structured.{name}[{index}] doit être une chaîne")
        if item.strip():
            cleaned.append(_bounded_string(item, name=f"structured.{name}[{index}]"))
    if len(cleaned) > limit:
        raise InvalidModelOutput(f"structured.{name}: {len(cleaned)} entrées, max {limit}")
    return cleaned


# --- `open` v3 : points référencés -------------------------------------------


_TRAILING_CARRY_NOTE = re.compile(r"\s*\(repris\s*:[^()]*\)\s*$")
# D5 : le push n'est pas observable par Core (`push_observed` n'est jamais
# vrai, aucun événement `git_push`). Un point qui affirme qu'il n'a pas eu
# lieu transforme un silence en fait ; « non observé » reste permis.
_PUSH = re.compile(r"push|pouss", re.IGNORECASE)
_ASSERTED_NOT_DONE = re.compile(
    r"(?:pas|non|jamais)\s+(?:encore\s+)?(?:été\s+)?(?:effectué|fait|réalisé|poussé)"
    r"|ne\s+sont\s+pas\s+pouss|n['’]est\s+pas\s+pouss|non\s+pouss",
    re.IGNORECASE,
)


def normalize_open_text(text: str) -> str:
    """La forme sous laquelle deux points se comparent (règle D1) : sans la
    note de reprise du rendu, sans ponctuation finale, sans casse."""
    cleaned = " ".join(text.split()).rstrip(" .;!?")
    cleaned = _TRAILING_CARRY_NOTE.sub("", cleaned).rstrip(" .;!?")
    return cleaned.casefold()


def asserts_unobservable_push(text: str) -> bool:
    """« Le push n'a pas été effectué » : un fait affirmé sur un événement
    que la vue ne peut pas montrer. « Aucun push observé » n'en est pas un."""
    return bool(_PUSH.search(text)) and bool(_ASSERTED_NOT_DONE.search(text))


def render_open_items(items: list[dict[str, Any]]) -> str:
    """Le `open` que Core reçoit : une phrase par point, dans l'ordre.

    Inverse de `split_open_text` sur les textes ordinaires : chaque phrase se
    termine par un point, un point repris porte sa raison entre parenthèses.
    Aucune liste vide n'atteint Core (`reprise.open` doit être non vide) : la
    phrase de vide est fixe, jamais rédigée par le modèle."""
    if not items:
        return EMPTY_OPEN_TEXT
    sentences = []
    for item in items:
        body = item["text"].strip().rstrip(" .;")
        if item["kind"] == "carried_over":
            body += f" (repris : {item['reason_kept'].strip().rstrip(' .;')})"
        sentences.append(body + ".")
    return " ".join(sentences)


def _references(value: Any, *, name: str, references: InputReferences) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidModelOutput(f"{name} doit être une liste de références")
    cleaned = []
    for index, ref in enumerate(value):
        if not isinstance(ref, str) or not ref.strip():
            raise InvalidModelOutput(f"{name}[{index}] doit être une référence non vide")
        ref = ref.strip()
        if ref not in references:
            raise InvalidModelOutput(f"{name}: référence {ref} absente de l'entrée")
        cleaned.append(ref)
    return cleaned


def _open_items(value: Any, references: InputReferences) -> list[dict[str, Any]]:
    """Le schéma v3 de `open`, règle par règle. Tout écart est un rejet."""
    if not isinstance(value, list):
        raise InvalidModelOutput("reprise.open doit être une liste de points (schéma v3)")
    if len(value) > MAX_OPEN_ITEMS:
        raise InvalidModelOutput(f"reprise.open: {len(value)} points, max {MAX_OPEN_ITEMS}")
    previous = {normalize_open_text(text): index for index, text in enumerate(references.previous_open)}
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        name = f"reprise.open[{index}]"
        if not isinstance(raw, dict):
            raise InvalidModelOutput(f"{name} doit être un objet")
        unknown = sorted(set(raw) - OPEN_ITEM_KEYS)
        if unknown:
            raise InvalidModelOutput(f"{name}: clés inconnues {', '.join(unknown)}")
        text = _bounded_string(raw.get("text"), name=f"{name}.text")
        kind = raw.get("kind")
        if kind not in OPEN_KINDS:
            raise InvalidModelOutput(
                f"{name}.kind doit être {', '.join(OPEN_KINDS)}, reçu {kind!r}"
            )
        evidence = _references(raw.get("evidence"), name=f"{name}.evidence", references=references)
        item: dict[str, Any] = {"text": text, "kind": kind, "evidence": evidence}

        if kind == "carried_over":
            carried_from = raw.get("carried_from")
            if not isinstance(carried_from, str) or not carried_from.startswith("previous_summary:"):
                raise InvalidModelOutput(
                    f"{name}.carried_from doit désigner un point previous_summary:<i>"
                )
            if carried_from not in references:
                raise InvalidModelOutput(
                    f"{name}.carried_from: {carried_from} absent de l'annexe previous_summary"
                )
            item["carried_from"] = carried_from
            item["reason_kept"] = _bounded_string(raw.get("reason_kept"), name=f"{name}.reason_kept")
        else:
            for forbidden in ("carried_from", "reason_kept"):
                if forbidden in raw:
                    raise InvalidModelOutput(
                        f"{name}.{forbidden} n'a de sens que pour kind carried_over"
                    )
            if kind == "observed":
                if not evidence:
                    raise InvalidModelOutput(f"{name}: un point observed exige evidence non vide")
                # Une annexe n'est pas un fait de la session : la demande de
                # l'agent étaye un point requested, le résumé précédent un
                # point carried_over, jamais une observation.
                annexed = [ref for ref in evidence if ref.split(":", 1)[0] in ("agent_request", "previous_summary")]
                if annexed:
                    raise InvalidModelOutput(
                        f"{name}: un point observed ne s'étaye pas sur une annexe ({', '.join(annexed)})"
                    )
                if asserts_unobservable_push(text):
                    raise InvalidModelOutput(
                        f"{name}: affirme un push non effectué, que la vue ne peut pas montrer "
                        "(formuler « non observé »)"
                    )
            else:  # requested
                if not evidence or any(ref not in references.agent_requests for ref in evidence):
                    raise InvalidModelOutput(
                        f"{name}: un point requested cite l'annexe d'agent (agent_request:<i>) et rien d'autre"
                    )
            # D1 : un point du résumé précédent repris mot pour mot sans être
            # déclaré comme tel n'a pas été réévalué.
            match = previous.get(normalize_open_text(text))
            if match is not None:
                raise InvalidModelOutput(
                    f"{name}: texte identique à previous_summary:{match} sans kind carried_over"
                )
        items.append(item)
    return items


def parse_model_output(
    text: str,
    allowed_paths: set[str],
    *,
    references: InputReferences | None = None,
) -> ParsedSummary:
    """Valide le JSON du modèle. Tout écart est un rejet, jamais un rafistolage.

    Sans ``references``, `open` est la chaîne libre du contrat d'origine
    (prompts v1, v2). Avec, c'est la liste de points du schéma v3, dont chaque
    référence doit exister dans l'entrée — même mécanisme que `central_files`.
    """
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    if fenced:
        stripped = fenced.group(1)
    try:
        payload = json.loads(stripped)
    except ValueError as exc:
        raise InvalidModelOutput(f"sortie non JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidModelOutput("la sortie doit être un objet JSON")

    reprise = payload.get("reprise")
    if not isinstance(reprise, dict):
        raise InvalidModelOutput("reprise absente ou non objet")
    cleaned_reprise = {
        key: _bounded_string(reprise.get(key), name=f"reprise.{key}")
        for key in ("doing", "stopped_at")
    }
    open_items: list[dict[str, Any]] | None = None
    if references is None:
        cleaned_reprise["open"] = _bounded_string(reprise.get("open"), name="reprise.open")
    else:
        open_items = _open_items(reprise.get("open"), references)
        cleaned_reprise["open"] = render_open_items(open_items)

    structured = payload.get("structured")
    if not isinstance(structured, dict):
        raise InvalidModelOutput("structured absent ou non objet")
    project = structured.get("project")
    if project is not None:
        project = _bounded_string(project, name="structured.project")
    confidence = structured.get("confidence")
    if confidence not in CONFIDENCE_LEVELS:
        raise InvalidModelOutput(
            f"structured.confidence doit être {', '.join(CONFIDENCE_LEVELS)}"
        )
    central_files = _string_list(
        structured.get("central_files"), name="central_files", limit=MAX_CENTRAL_FILES
    )
    # Garde-fou anti-hallucination : un fichier central doit être un chemin
    # de l'entrée. Le modèle ne peut pas en inventer.
    for path in central_files:
        if path not in allowed_paths:
            raise InvalidModelOutput(
                f"structured.central_files: {path} absent de l'entrée"
            )
    return ParsedSummary(
        reprise=cleaned_reprise,
        structured={
            "project": project,
            "intents": _string_list(
                structured.get("intents"), name="intents", limit=MAX_INTENTS
            ),
            "central_files": central_files,
            "blockers": _string_list(
                structured.get("blockers"), name="blockers", limit=MAX_BLOCKERS
            ),
            "confidence": confidence,
        },
        open_items=open_items,
    )


def open_items_for_core(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ce que l'événement emporte des points v3 : nature et preuves, alignées
    sur les phrases de `reprise.open`, sans texte libre.

    Core rédige `reprise.open` (champ connu de son schéma) mais recopierait
    tel quel un champ libre inconnu de `details` : `text` et `reason_kept`
    ne voyagent donc que rendus dans `reprise.open`, jamais à côté
    (décision 2026-09-06, rédaction des champs libres)."""
    exported = []
    for item in items:
        entry: dict[str, Any] = {"kind": item["kind"], "evidence": list(item["evidence"])}
        if item["kind"] == "carried_over":
            entry["carried_from"] = item["carried_from"]
        exported.append(entry)
    return exported


# --- Événement -----------------------------------------------------------------


def summary_event_id(session_id: str, prompt_version: str, model_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"pulse-session-summary:{session_id}:{prompt_version}:{model_id}",
        )
    )


def build_event(
    session: SessionView,
    parsed: ParsedSummary,
    *,
    prompt_version: str,
    model_id: str,
    generated_at: datetime,
    generation_ms: int,
    context_hash: str,
    workspace: str | None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "session_id": session.id,
        "session_label": session.label,
        "session_date": session.day.isoformat(),
        "session_started_at": session.started_at.isoformat(),
        "session_ended_at": session.ended_at.isoformat(),
        # Redondance voulue : le champ dit explicitement ce qu'est l'id.
        "source_event_ids_hash": session.id,
        "source_event_count": len(session.source_event_ids),
        "reconstruction_version": session.reconstruction_version,
        "prompt_version": prompt_version,
        "model_id": model_id,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "generation_ms": generation_ms,
        "input_hash": context_hash,
        "reprise": dict(parsed.reprise),
        "structured": dict(parsed.structured),
    }
    if parsed.open_items is not None:
        details["open_items"] = open_items_for_core(parsed.open_items)
    if workspace:
        details["workspace"] = workspace
    return {
        "event_id": summary_event_id(session.id, prompt_version, model_id),
        "schema_version": 1,
        "type": "session_summary",
        "producer": {"name": PRODUCER_NAME, "version": __version__},
        # À sa place dans la journée : la fin de la session, pas la génération.
        "occurred_at": session.ended_at.isoformat(),
        "details": details,
    }


# --- Une session ------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    session_id: str
    status: str  # dry_run | created | duplicate | already_known | failed | given_up
    event_id: str
    event: dict[str, Any] | None = None
    detail: str | None = None


def _emit(
    session: SessionView,
    event_id: str,
    event: dict[str, Any],
    *,
    client: CoreClient,
    config: Config,
    model_id: str,
    state: JobState,
) -> Outcome:
    """POST du payload gelé, puis passage de ``pending`` à ``emitted``.

    Un Core injoignable lève CoreUnavailable : le payload reste ``pending``
    et sera renvoyé tel quel au tick suivant.
    """
    result = client.post_activity(event)
    if not result.accepted:
        if result.status_code == 409:
            # Core détient déjà un événement sous cet identifiant, avec un
            # autre contenu : un `pending` d'avant une perte d'état ou d'une
            # sauvegarde restaurée (relecture 2026-09-06, sonde B). Ce que
            # Core a accepté est la référence : repris tel quel, `pending`
            # retiré, zéro budget. Un 409 sans événement lisible (404) est
            # un refus ordinaire et compte comme avant.
            recovered = _recover_after_conflict(
                session, event_id, client=client, config=config, model_id=model_id, state=state,
            )
            if recovered is not None:
                return recovered
        count = state.record_failure(
            session.id, f"Core {result.status_code}: {result.error}", event_id=event_id
        )
        status = "given_up" if state.is_failed(session.id, event_id) else "failed"
        return Outcome(
            session.id, status, event_id, detail=f"tentative {count}: Core {result.status_code}"
        )
    # Copie de référence = l'événement accepté par Core, après sa
    # normalisation (rédaction, enveloppe), relu par GET /activities. Jamais
    # la sortie du modèle avant normalisation (décision 2026-09-06, rédaction
    # des champs libres). Si la relecture échoue, l'entrée est enregistrée
    # sans `event` : `show <id>` passera par Core.
    accepted: dict[str, Any] | None = None
    try:
        stored = client.get_activity(event_id)
        problem = None if stored is not None else "Core ne connaît pas encore l'événement"
    except (CoreUnavailable, CoreError) as exc:
        stored, problem = None, str(exc)
    if stored is not None:
        accepted = _recovered_event(stored)
    else:
        print(
            f"⚠ relecture impossible après acceptation ({event_id}) : {problem} — "
            "entrée enregistrée sans copie locale, `show` lira Core",
            file=sys.stderr,
        )
    state.record_emitted(
        event_id,
        session_id=session.id,
        prompt_version=config.prompt_version,
        model_id=model_id,
        at=event["details"]["generated_at"],
        event=accepted,
        origin="core",
    )
    # `event` est la copie de Core ou rien : la sortie du modèle avant
    # rédaction ne sort jamais d'ici, ni vers l'état ni vers l'affichage.
    return Outcome(
        session.id, "duplicate" if result.duplicate else "created", event_id,
        event=accepted,
    )


def _recover_after_conflict(
    session: SessionView,
    event_id: str,
    *,
    client: CoreClient,
    config: Config,
    model_id: str,
    state: JobState,
) -> Outcome | None:
    """Après un 409 : l'événement que Core détient, enregistré comme
    référence (`origin: "core"`), ou ``None`` si Core n'en a pas (404).
    Core injoignable remonte en ``CoreUnavailable`` : le `pending` reste."""
    stored = client.get_activity(event_id)
    if stored is None:
        return None
    recovered = _recovered_event(stored)
    details = recovered["details"]
    state.record_emitted(
        event_id,
        session_id=session.id,
        prompt_version=config.prompt_version,
        model_id=model_id,
        at=str(details.get("generated_at") or recovered["occurred_at"]),
        event=recovered,
        origin="core",
    )
    return Outcome(
        session.id, "already_known", event_id, event=recovered,
        detail="récupéré depuis Core après conflit : Core détenait déjà un résumé "
        "pour cette identité, repris tel quel, budget intact",
    )


def _recovered_event(stored: dict[str, Any]) -> dict[str, Any]:
    """L'événement stocké par Core, remis dans la forme canonique d'émission.

    C'est ce que Core a accepté après sa normalisation (rédaction,
    enveloppe retirée), pas ce que le modèle avait produit : la copie
    locale d'une entrée récupérée diffère de celle d'une émission.
    """
    details = stored.get("details")
    return {
        "event_id": stored["event_id"],
        "schema_version": stored.get("schema_version", 1),
        "type": stored["type"],
        "producer": dict(stored.get("producer") or {}),
        "occurred_at": stored["occurred_at"],
        "details": dict(details) if isinstance(details, dict) else {},
    }


def summarize_session(
    session: SessionView,
    *,
    client: CoreClient,
    summarizer: Summarizer,
    config: Config,
    state: JobState,
    dry_run: bool = False,
    now: datetime | None = None,
) -> Outcome:
    """Construit l'entrée, appelle le modèle, valide, gèle, émet. Idempotent.

    Le payload validé est persisté dans l'état local *avant* le POST : un
    envoi qui échoue ou dont la confirmation se perd est rejoué octet pour
    octet, sans rappeler le modèle ni recalculer ``generated_at``.
    ``dry_run`` fait tout sauf l'émission et ne touche pas à l'état local.
    """
    model_id = summarizer.model_id
    event_id = summary_event_id(session.id, config.prompt_version, model_id)
    if not dry_run:
        if state.knows(event_id):
            return Outcome(session.id, "already_known", event_id)
        if state.is_failed(session.id, event_id):
            return Outcome(
                session.id, "given_up", event_id, detail=state.failure_reason(session.id, event_id)
            )
        pending = state.pending_event(event_id)
        if pending is not None:
            return _emit(
                session, event_id, pending,
                client=client, config=config, model_id=model_id, state=state,
            )
        # État local muet sur cette identité : avant de rappeler le modèle,
        # demander à Core ce qu'il a déjà accepté. Après une perte d'état,
        # régénérer produirait un contenu différent (generated_at,
        # generation_ms) sous le même event_id, que Core refuse à raison
        # (409). Core injoignable lève CoreUnavailable ici comme sur
        # get_context : jamais un `failed`. (audit 2026-09-06, défaut 3)
        stored = client.get_activity(event_id)
        if stored is not None:
            recovered = _recovered_event(stored)
            details = recovered["details"]
            state.record_emitted(
                event_id,
                session_id=session.id,
                prompt_version=config.prompt_version,
                model_id=model_id,
                at=str(details.get("generated_at") or recovered["occurred_at"]),
                event=recovered,
                origin="core",
            )
            return Outcome(
                session.id, "already_known", event_id, event=recovered,
                detail="récupéré depuis Core : résumé déjà accepté pour cette "
                "identité, repris tel quel, sans régénération",
            )

    context = client.get_context(at=session.ended_at)
    referenced = uses_open_items(config.prompt_version)
    model_input = build_model_input(session, context, references=referenced)
    serialized = serialize_input(model_input)
    workspace = context.get("workspace") or {}
    workspace_path = workspace.get("path") if isinstance(workspace, dict) else None

    started = datetime.now(timezone.utc)
    try:
        output = summarizer.summarize(serialized)
        parsed = parse_model_output(
            output, input_paths(session),
            references=input_references(model_input) if referenced else None,
        )
    except SummarizerUnavailable:
        # Modèle injoignable : la même erreur pour toute candidate. Remonte
        # à run_pass, qui arrête le passage comme sur un Core injoignable.
        raise
    except (SummarizerInputRefused, InvalidModelOutput) as exc:
        # Déterministe pour cette entrée : consomme le budget de l'identité.
        if dry_run:
            return Outcome(session.id, "failed", event_id, detail=str(exc))
        count = state.record_failure(session.id, str(exc), event_id=event_id)
        status = "given_up" if state.is_failed(session.id, event_id) else "failed"
        return Outcome(session.id, status, event_id, detail=f"tentative {count}: {exc}")
    except SummarizerError as exc:
        # Transitoire (délai, 5xx, génération) : réessayé au passage suivant,
        # sans consommer le budget — une panne n'empoisonne pas une session.
        return Outcome(session.id, "failed", event_id, detail=f"modèle indisponible (transitoire) : {exc}")
    generation_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    generated_at = now or datetime.now(timezone.utc)

    event = build_event(
        session,
        parsed,
        prompt_version=config.prompt_version,
        model_id=model_id,
        generated_at=generated_at,
        generation_ms=generation_ms,
        context_hash=input_hash(serialized),
        workspace=workspace_path,
    )
    if dry_run:
        return Outcome(session.id, "dry_run", event_id, event=event)

    state.record_pending(
        event_id,
        session_id=session.id,
        prompt_version=config.prompt_version,
        model_id=model_id,
        at=event["details"]["generated_at"],
        event=event,
        previous_summary=model_input["previous_summary"],
    )
    return _emit(
        session, event_id, event,
        client=client, config=config, model_id=model_id, state=state,
    )


# --- Un passage : toutes les candidates ------------------------------------------


@dataclass(frozen=True)
class PassReport:
    candidates: int
    outcomes: list[Outcome]
    error: str | None = None
    # Payloads `pending` rejoués par le vidage de la file, avant la sélection
    # (défaut 4 de l'audit, issue #62). Leurs Outcome sont dans `outcomes`.
    replayed: int = 0

    def count(self, status: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)


def run_pass(
    client: CoreClient,
    summarizer: Summarizer,
    config: Config,
    state: JobState,
    *,
    now: datetime | None = None,
) -> PassReport:
    """Toutes les candidates, une session à la fois, séquentiellement.

    Une session déjà résumée ou abandonnée n'est plus candidate (état local),
    donc le modèle n'est jamais recontacté pour elle. Un Core qui tombe en
    cours de passage arrête le passage proprement, le suivant reprendra.
    """
    moment = now or datetime.now(timezone.utc)
    # Vidage de la file d'abord, indépendant de la fenêtre de sélection : un
    # payload gelé pendant une panne repart tel quel même si sa session est
    # sortie de `lookback_days` (défaut 4, issue #62). Distinct du rattrapage
    # des sessions jamais traitées, qui n'existe pas ici.
    outcomes: list[Outcome] = []
    replayed = 0
    # Une identité traitée par le vidage ne l'est pas une seconde fois par la
    # sélection du même passage : un rejeu refusé garde son unique tentative,
    # un rejeu accepté la rend connue, donc non candidate. La clé est
    # l'identité (event_id), pas la session : un `pending` abandonné sous un
    # ancien prompt ou modèle ne cache pas la session à une identité neuve
    # (relecture 2026-09-06, sonde A).
    drained: set[str] = set()
    for entry in list(state.pending.values()):
        session_id = str(entry.get("session_id", ""))
        event = entry.get("event")
        if not session_id or not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id", ""))
        drained.add(event_id)
        if state.is_failed(session_id, event_id):
            # Abandonnée : le pending reste sur disque jusqu'à une reprise
            # explicite ; il n'est ni rejoué ni oublié.
            outcomes.append(
                Outcome(session_id, "given_up", event_id, detail=state.failure_reason(session_id, event_id))
            )
            continue
        try:
            outcome = _replay_pending(entry, client=client, config=config, state=state)
        except CoreUnavailable as exc:
            return PassReport(candidates=0, outcomes=outcomes, error=str(exc), replayed=replayed)
        replayed += 1
        outcomes.append(outcome)
    try:
        candidates = select_candidates(
            client, now=moment, config=config, model_id=summarizer.model_id, state=state
        )
    except CoreUnavailable as exc:
        return PassReport(candidates=0, outcomes=outcomes, error=str(exc), replayed=replayed)
    for session in candidates:
        event_id = summary_event_id(session.id, config.prompt_version, summarizer.model_id)
        if event_id in drained:
            continue
        if state.is_failed(session.id, event_id):
            outcomes.append(
                Outcome(
                    session.id, "given_up", event_id,
                    detail=state.failure_reason(session.id, event_id),
                )
            )
            continue
        try:
            outcomes.append(
                summarize_session(
                    session, client=client, summarizer=summarizer, config=config,
                    state=state, now=moment,
                )
            )
        except SummarizerUnavailable as exc:
            return PassReport(
                candidates=len(candidates), outcomes=outcomes,
                error=f"modèle indisponible : {exc}", replayed=replayed,
            )
        except CoreUnavailable as exc:
            return PassReport(
                candidates=len(candidates), outcomes=outcomes, error=str(exc), replayed=replayed
            )
    return PassReport(candidates=len(candidates), outcomes=outcomes, replayed=replayed)


def _replay_pending(
    entry: dict[str, Any],
    *,
    client: CoreClient,
    config: Config,
    state: JobState,
) -> Outcome:
    """POST d'un payload `pending` exactement tel que figé (issue #62).

    Rien n'est recalculé : ni `generated_at`, ni `generation_ms`, ni
    `input_hash`, ni `producer`. Les versions enregistrées avec l'entrée
    servent à l'inscription dans `emitted`, pas celles de la configuration
    courante, qui a pu changer depuis le gel.
    """
    event: dict[str, Any] = entry["event"]
    details = event.get("details") or {}
    session_id = str(entry["session_id"])
    day_text = details.get("session_date") or str(event.get("occurred_at", ""))[:10]
    session = SessionView(
        raw={"id": session_id, "label": details.get("session_label", "")},
        day=date.fromisoformat(day_text),
    )
    frozen_config = replace(
        config, prompt_version=str(entry.get("prompt_version") or config.prompt_version)
    )
    outcome = _emit(
        session, str(event["event_id"]), event,
        client=client, config=frozen_config,
        model_id=str(entry.get("model_id") or details.get("model_id") or ""),
        state=state,
    )
    detail = "rejeu pending" if outcome.detail is None else f"rejeu pending · {outcome.detail}"
    return replace(outcome, detail=detail)
