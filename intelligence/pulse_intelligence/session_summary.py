"""Résumer une session : parsing, validation, événement, émission (spec v2 §6–§7).

Une seule fonction fait le travail, ``summarize_session`` ; la CLI et,
plus tard, le job périodique n'appellent rien d'autre. Tout ce que le
modèle écrit est non fiable : validé par schéma ici, rédigé par Core à
l'ingestion, et un chemin cité qui n'existe pas dans l'entrée invalide le
résumé. Rien n'atteint ``trace.db`` avant validation.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import PRODUCER_NAME, __version__
from .config import Config
from .core_client import CoreClient, CoreUnavailable
from .selection import SessionView, select_candidates
from .session_input import (
    build_model_input,
    input_hash,
    input_paths,
    serialize_input,
)
from .state import JobState
from .summarizer import Summarizer, SummarizerError


CONFIDENCE_LEVELS = ("high", "medium", "low")
MAX_INTENTS = 3
MAX_CENTRAL_FILES = 5
MAX_BLOCKERS = 3
MAX_STRING_LENGTH = 300


class InvalidModelOutput(ValueError):
    """La sortie du modèle ne respecte pas le schéma : on n'écrit rien."""


# --- Parsing et validation ----------------------------------------------------


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


@dataclass(frozen=True)
class ParsedSummary:
    reprise: dict[str, str]
    structured: dict[str, Any]


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


def parse_model_output(text: str, allowed_paths: set[str]) -> ParsedSummary:
    """Valide le JSON du modèle. Tout écart est un rejet, jamais un rafistolage."""
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
        for key in ("doing", "stopped_at", "open")
    }

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
    )


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
        count = state.record_failure(session.id, f"Core {result.status_code}: {result.error}")
        status = "given_up" if state.is_failed(session.id) else "failed"
        return Outcome(
            session.id, status, event_id, detail=f"tentative {count}: Core {result.status_code}"
        )
    state.record_emitted(
        event_id,
        session_id=session.id,
        prompt_version=config.prompt_version,
        model_id=model_id,
        at=event["details"]["generated_at"],
        event=event,
    )
    return Outcome(
        session.id, "duplicate" if result.duplicate else "created", event_id, event=event
    )


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
        if state.is_failed(session.id):
            return Outcome(session.id, "given_up", event_id, detail=state.failed[session.id])
        pending = state.pending_event(event_id)
        if pending is not None:
            return _emit(
                session, event_id, pending,
                client=client, config=config, model_id=model_id, state=state,
            )

    context = client.get_context(at=session.ended_at)
    model_input = build_model_input(session, context)
    serialized = serialize_input(model_input)
    workspace = context.get("workspace") or {}
    workspace_path = workspace.get("path") if isinstance(workspace, dict) else None

    started = datetime.now(timezone.utc)
    try:
        output = summarizer.summarize(serialized)
        parsed = parse_model_output(output, input_paths(session))
    except (SummarizerError, InvalidModelOutput) as exc:
        if dry_run:
            return Outcome(session.id, "failed", event_id, detail=str(exc))
        count = state.record_failure(session.id, str(exc))
        status = "given_up" if state.is_failed(session.id) else "failed"
        return Outcome(session.id, status, event_id, detail=f"tentative {count}: {exc}")
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
    try:
        candidates = select_candidates(
            client, now=moment, config=config, model_id=summarizer.model_id, state=state
        )
    except CoreUnavailable as exc:
        return PassReport(candidates=0, outcomes=[], error=str(exc))
    outcomes: list[Outcome] = []
    for session in candidates:
        if state.is_failed(session.id):
            outcomes.append(
                Outcome(
                    session.id,
                    "given_up",
                    summary_event_id(session.id, config.prompt_version, summarizer.model_id),
                    detail=state.failed[session.id],
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
        except CoreUnavailable as exc:
            return PassReport(candidates=len(candidates), outcomes=outcomes, error=str(exc))
    return PassReport(candidates=len(candidates), outcomes=outcomes)
