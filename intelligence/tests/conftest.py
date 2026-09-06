"""Faux Core : un Flask de test qui rejoue des fixtures de /context et
/context/sessions et enregistre les POST /activities. Aucun test ne charge MLX.
"""

from __future__ import annotations

import copy
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from pulse_intelligence.config import Config
from pulse_intelligence.core_client import CoreClient
from pulse_intelligence.state import JobState


REFERENCE = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_intelligence_home(monkeypatch, tmp_path):
    """Aucun test ne lit la config du poste (`~/.pulse_intelligence`).

    Vu en réel : dès qu'une `config.toml` de dogfooding a existé avec un modèle
    configuré, deux tests de CLI « sans modèle » sortaient 0 au lieu de 1 en
    local, verts en CI. Même principe que l'isolement de `PULSE_LLM_*` : chaque
    test repart d'un dossier vide et pose explicitement ce dont il a besoin.
    """
    monkeypatch.setenv("PULSE_INTELLIGENCE_HOME", str(tmp_path / "pulse_intelligence_home"))
PULSE = "/Users/dev/Projets/Pulse"
HEX_ID = re.compile(r"[0-9a-f]{16}")


def at(minutes: int) -> datetime:
    return REFERENCE + timedelta(minutes=minutes)


def session_view(
    session_id: str,
    *,
    label: str = "work-1",
    started: int = -120,
    ended: int = -60,
    activity_count: int = 40,
    is_open: bool = False,
    files: dict[str, list[str]] | None = None,
    projects: list[str] | None = None,
    commits: list[dict[str, str]] | None = None,
    summaries: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Une session dans la forme exacte de current_session (Core 0.5.0)."""
    files = files or {"created": [], "modified": ["core/daemon_v2/routes.py"], "deleted": []}
    view = {
        "id": session_id,
        "label": label,
        "source_event_ids": [f"evt-{session_id}-{index}" for index in range(activity_count)],
        "reconstruction_version": 1,
        "started_at": at(started).isoformat(),
        "last_activity_at": at(ended).isoformat(),
        "duration_minutes": ended - started,
        "is_open": is_open,
        "activity_count": activity_count,
        "projects": projects if projects is not None else ["Pulse"],
        "apps": [{"name": "Terminal", "activations": 3}],
        "files": {**files, "truncated": False},
        "git": {"commits": commits or [], "push_observed": False},
        "terminal": {"tests_passed": ["pytest -q"], "tests_failed": [], "errors": [], "truncated": False},
        "signals": ["file_changed", "terminal_finished"],
    }
    if summaries is not None:
        view["summaries"] = summaries
    return view


def context_view(
    *,
    reference_at: datetime,
    current_session: dict[str, Any] | None = None,
    last_session_summary: dict[str, Any] | None = None,
    last_agent_session: dict[str, Any] | None = None,
    workspace_path: str | None = PULSE,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "generated_at": reference_at.isoformat(),
        "reference_at": reference_at.astimezone(timezone.utc).isoformat(),
        "window_minutes": 120,
        "timezone": "UTC",
        "workspace": (
            {"path": workspace_path, "project": "Pulse", "resolution": "session", "git": None}
            if workspace_path
            else None
        ),
        "current_session": current_session,
        "recent_sessions": [],
        "isolated_signals": [],
        "last_agent_session": last_agent_session,
        "last_session_summary": last_session_summary,
    }


def valid_output(**overrides: Any) -> str:
    payload = {
        "reprise": {
            "doing": "Tu implémentais la route /context/sessions dans Core.",
            "stopped_at": "Tu venais de faire passer la suite de tests.",
            "open": "La PR attend ta relecture.",
        },
        "structured": {
            "project": "Pulse",
            "intents": ["livrer le pas 2"],
            "central_files": ["core/daemon_v2/routes.py"],
            "blockers": [],
            "confidence": "high",
        },
    }
    for key, value in overrides.items():
        payload[key] = value
    return json.dumps(payload, ensure_ascii=False)


@dataclass
class FakeCore:
    """Fixtures rejouées par date et par instant ; POST /activities enregistrés."""

    sessions_by_date: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    contexts_by_at: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_context: dict[str, Any] | None = None
    posts: list[dict[str, Any]] = field(default_factory=list)
    # Panne simulée : les N prochains POST /activities répondent 503 sans
    # rien enregistrer ; le payload refusé est gardé pour comparaison.
    fail_posts: int = 0
    refused: list[dict[str, Any]] = field(default_factory=list)
    requested_dates: list[str] = field(default_factory=list)
    seen_event_ids: set[str] = field(default_factory=set)
    # Même contrat que le vrai Core : un event_id connu avec un contenu
    # différent est un conflit (409), pas un doublon. Sans importer ni
    # recopier la formule d'empreinte de Core (principe 1 : rien de Core,
    # tests compris) : le payload complet est mémorisé par event_id et
    # comparé en égalité profonde, tout sauf `event_id` — au moins aussi
    # strict que l'empreinte de Core, qui couvre tout le payload. Le vrai
    # contrat est prouvé par le test d'intégration contre Core réel.
    payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    stored: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Panne simulée de la relecture : les N prochains GET /activities/<id>
    # répondent 503. Le faux Core ne rédige pas : la preuve `[REDACTED]`
    # est portée par le test d'intégration contre le vrai Core.
    fail_readbacks: int = 0
    context_requests: int = 0
    url: str = ""

    def add_sessions(self, day: str, *views: dict[str, Any]) -> None:
        self.sessions_by_date.setdefault(day, []).extend(views)

    def add_context(self, reference_at: datetime, context: dict[str, Any]) -> None:
        self.contexts_by_at[reference_at.astimezone(timezone.utc).isoformat()] = context

    def app(self) -> Flask:
        app = Flask("fake-core")

        @app.get("/status")
        def status():
            return jsonify({"daemon": "running"})

        @app.get("/context")
        def context():
            self.context_requests += 1
            key = request.args.get("at")
            body = self.contexts_by_at.get(key) if key else None
            if body is None:
                body = self.default_context or context_view(
                    reference_at=datetime.fromisoformat(key) if key else REFERENCE
                )
            return jsonify(body)

        @app.get("/context/sessions")
        def sessions():
            day = request.args.get("date")
            if not day or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                return jsonify({"error": "invalid date; expected YYYY-MM-DD"}), 400
            self.requested_dates.append(day)
            return jsonify(
                {
                    "schema_version": 2,
                    "date": day,
                    "reconstruction_version": 1,
                    "sessions": self.sessions_by_date.get(day, []),
                }
            )

        @app.post("/activities")
        def activities():
            payload = request.get_json(silent=True) or {}
            if self.fail_posts > 0:
                self.fail_posts -= 1
                self.refused.append(payload)
                return jsonify({"error": {"code": "unavailable"}}), 503
            details = payload.get("details", {})
            for field_name in ("event_id", "type", "occurred_at"):
                if not payload.get(field_name):
                    return jsonify({"error": {"code": "invalid_event", "field": field_name}}), 400
            # Même refus que le vrai Core (audit 2026-09-06, défaut 8) : un
            # champ réservé de l'enveloppe ne passe pas dans details.
            for reserved in ("type", "occurred_at"):
                if reserved in details:
                    return jsonify({"error": {"code": "invalid_event", "field": f"details.{reserved}"}}), 400
            if payload["type"] == "session_summary":
                session_id = details.get("session_id", "")
                if not HEX_ID.fullmatch(str(session_id)):
                    return jsonify({"error": {"code": "invalid_event", "field": "details.session_id"}}), 400
                if details.get("source_event_ids_hash") != session_id:
                    return jsonify({"error": {"code": "invalid_event", "field": "details.source_event_ids_hash"}}), 400
                reprise = details.get("reprise", {})
                for key in ("doing", "stopped_at", "open"):
                    if not isinstance(reprise.get(key), str) or not reprise[key].strip():
                        return jsonify({"error": {"code": "invalid_event", "field": f"details.reprise.{key}"}}), 400
            event_id = payload["event_id"]
            content = _content(payload)
            duplicate = event_id in self.seen_event_ids
            if duplicate and self.payloads[event_id] != content:
                self.posts.append(payload)
                return (
                    jsonify(
                        {
                            "accepted": False,
                            "event_id": event_id,
                            "error": {"code": "event_id_conflict", "field": "event_id"},
                        }
                    ),
                    409,
                )
            self.seen_event_ids.add(event_id)
            self.payloads[event_id] = content
            self.posts.append(payload)
            if not duplicate:
                self.stored[event_id] = {
                    "id": len(self.stored) + 1,
                    "event_id": event_id,
                    "schema_version": payload.get("schema_version"),
                    "type": payload["type"],
                    "occurred_at": payload["occurred_at"],
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "producer": {
                        "name": payload.get("producer", {}).get("name"),
                        "version": payload.get("producer", {}).get("version"),
                        "instance_id": payload.get("producer", {}).get("instance_id"),
                    },
                    "source": "intelligence",
                    "summary": str(details.get("reprise", {}).get("doing", "")).splitlines()[0]
                    if details.get("reprise") else "",
                    "details": details,
                }
            return (
                jsonify({"accepted": True, "event_id": event_id, "duplicate": duplicate}),
                200 if duplicate else 201,
            )

        @app.get("/activities/<event_id>")
        def activity(event_id: str):
            stored = self.stored.get(event_id)
            # La panne simulée ne touche que la relecture d'un événement
            # accepté : la vérification de récupération (#61) sur un id
            # inconnu répond 404 normalement.
            if stored is not None and self.fail_readbacks > 0:
                self.fail_readbacks -= 1
                return jsonify({"error": {"code": "unavailable"}}), 503
            if stored is None:
                return jsonify({"error": {"code": "unknown_event_id", "event_id": event_id}}), 404
            return jsonify(stored)

        return app


def _content(payload: dict[str, Any]) -> dict[str, Any]:
    """Tout le payload sauf `event_id`, copié : la base de comparaison du 409."""
    return copy.deepcopy({key: value for key, value in payload.items() if key != "event_id"})


@pytest.fixture
def fake_core():
    core = FakeCore()
    server = make_server("127.0.0.1", 0, core.app())
    core.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield core
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def client(fake_core) -> CoreClient:
    return CoreClient(fake_core.url, timeout_s=5.0)


@pytest.fixture
def config() -> Config:
    # Version épinglée : les tests raisonnent sur « v1 connu, v2 = autre version »,
    # indépendamment du défaut courant de `Config` (testé à part).
    return Config(model_id="fake/summarizer", prompt_version="v1")


@pytest.fixture
def state(tmp_path) -> JobState:
    return JobState.load(tmp_path / "state" / "state.json")


@pytest.fixture
def fake_output_file(tmp_path) -> Path:
    path = tmp_path / "output.json"
    path.write_text(valid_output(), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def frozen_cli_clock(monkeypatch):
    """L'horloge de la CLI est gelée sur l'instant des fixtures.

    Les vues rejouées par le faux Core sont ancrées sur ``REFERENCE`` et la
    fenêtre de sélection vaut « aujourd'hui plus la veille » (`lookback_days`
    = 1). Sans gel, la suite passe le jour où elle est écrite puis échoue deux
    jours plus tard : le 2026-09-05, cinq tests de CLI ne trouvaient plus
    aucune session close, sans qu'une ligne de code ait bougé.

    Le gel porte sur l'horloge, pas sur les dates des fixtures : décaler les
    fixtures aurait seulement reporté la panne de quelques mois.
    """
    from pulse_intelligence import cli

    monkeypatch.setattr(cli, "_now", lambda: at(120))
