from __future__ import annotations

import inspect
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from flask import Flask

from daemon.memory.candidates import MemoryCandidateError, MemoryCandidateStore
from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.routes.memory_candidates import register_memory_candidate_routes
from daemon.routes.runtime_status_routes import register_status_routes
from daemon.runtime_state import RuntimeState
import daemon.routes.memory_candidates as memory_candidate_routes


def _candidate_app(store: MemoryCandidateStore) -> Flask:
    app = Flask(__name__)
    register_memory_candidate_routes(app, candidate_store=store)
    return app


def _seed(store: MemoryCandidateStore) -> dict:
    return store.create_manual_candidate(
        memory_type="project_pattern",
        claim="Pulse semble etre un projet de travail recurrent.",
        confidence=0.4,
        sensitivity={"level": "low", "reason": "non_sensitive_project_pattern"},
        evidence=[{"source_type": "manual_review_seed", "summary": "Seed explicite de test."}],
    )


def _manual_payload(**overrides) -> dict:
    payload = {
        "memory_type": "project_pattern",
        "claim": "Pulse est un projet de travail recurrent.",
        "evidence": [
            {
                "source_type": "human_manual",
                "summary": "Cree explicitement par l'utilisateur pour tester le cycle de review.",
            }
        ],
        "sensitivity": {
            "level": "low",
            "reason": "non-sensitive project pattern",
        },
    }
    payload.update(overrides)
    return payload


def test_routes_are_dedicated_review_surface_only(tmp_path):
    app = _candidate_app(MemoryCandidateStore(tmp_path / "candidates.sqlite"))
    routes = {rule.rule: rule.methods for rule in app.url_map.iter_rules() if rule.endpoint != "static"}

    assert "/memory/candidates/manual" in routes
    assert "/memory/candidates" in routes
    assert "/memory/candidates/<candidate_id>" in routes
    assert "/memory/candidates/<candidate_id>/accept" in routes
    assert "/memory/candidates/<candidate_id>/edit" in routes
    assert "/memory/candidates/<candidate_id>/reject" in routes
    assert "/memory/candidates/<candidate_id>/archive" in routes
    assert "POST" not in routes["/memory/candidates"]


def test_manual_create_route_creates_pending_candidate(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=_manual_payload())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["surface"] == "memory_candidates"
    assert payload["canonical_memory_created"] is False
    assert payload["llm_injected"] is False
    assert payload["candidate"]["status"] == "pending"
    assert payload["candidate"]["memory_type"] == "project_pattern"
    assert store.list_candidates()[0]["id"] == payload["candidate"]["id"]


def test_manual_create_refuses_non_object_payload(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=["bad"])

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_payload"
    assert store.list_candidates() == []


def test_manual_create_refuses_missing_claim(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()
    payload = _manual_payload()
    payload.pop("claim")

    response = client.post("/memory/candidates/manual", json=payload)

    assert response.status_code == 400
    assert response.get_json()["error"] == "claim_required"
    assert store.list_candidates() == []


def test_manual_create_refuses_empty_claim(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=_manual_payload(claim="  "))

    assert response.status_code == 400
    assert response.get_json()["error"] == "claim_required"
    assert store.list_candidates() == []


def test_manual_create_refuses_non_string_claim(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=_manual_payload(claim=123))

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_claim"
    assert store.list_candidates() == []


def test_manual_create_refuses_missing_memory_type(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()
    payload = _manual_payload()
    payload.pop("memory_type")

    response = client.post("/memory/candidates/manual", json=payload)

    assert response.status_code == 400
    assert response.get_json()["error"] == "memory_type_required"
    assert store.list_candidates() == []


def test_manual_create_refuses_forbidden_memory_type(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=_manual_payload(memory_type="credential"))

    assert response.status_code == 400
    assert response.get_json()["error"] == "forbidden_memory_type"
    assert store.list_candidates() == []


def test_manual_create_redacts_unexpected_store_error():
    store = MagicMock()
    store.create_manual_candidate.side_effect = MemoryCandidateError(
        "secret path /Users/yugz/.pulse/token"
    )
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=_manual_payload())

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "invalid_request"
    assert "secret path" not in str(payload)


def test_manual_create_refuses_missing_evidence(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()
    payload = _manual_payload()
    payload.pop("evidence")

    response = client.post("/memory/candidates/manual", json=payload)

    assert response.status_code == 400
    assert response.get_json()["error"] == "evidence_required"
    assert store.list_candidates() == []


def test_manual_create_refuses_empty_evidence(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=_manual_payload(evidence=[]))

    assert response.status_code == 400
    assert response.get_json()["error"] == "evidence_required"
    assert store.list_candidates() == []


def test_manual_create_refuses_non_list_evidence(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=_manual_payload(evidence={"bad": True}))

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_evidence"
    assert store.list_candidates() == []


def test_manual_create_refuses_non_object_evidence_item(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=_manual_payload(evidence=["bad"]))

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_evidence_item"
    assert store.list_candidates() == []


def test_manual_create_refuses_missing_sensitivity(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()
    payload = _manual_payload()
    payload.pop("sensitivity")

    response = client.post("/memory/candidates/manual", json=payload)

    assert response.status_code == 400
    assert response.get_json()["error"] == "sensitivity_required"
    assert store.list_candidates() == []


def test_manual_create_refuses_non_object_sensitivity(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post("/memory/candidates/manual", json=_manual_payload(sensitivity="low"))

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_sensitivity"
    assert store.list_candidates() == []


def test_manual_create_refuses_unknown_sensitivity_level(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post(
        "/memory/candidates/manual",
        json=_manual_payload(sensitivity={"level": "unknown", "reason": "bad"}),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_sensitivity"
    assert store.list_candidates() == []


def test_manual_create_refuses_sensitive_sensitivity_level(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post(
        "/memory/candidates/manual",
        json=_manual_payload(sensitivity={"level": "credential", "reason": "secret-like"}),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "sensitive_candidate_refused"
    assert store.list_candidates() == []


def test_manual_create_refuses_sensitive_claim(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    client = _candidate_app(store).test_client()

    response = client.post(
        "/memory/candidates/manual",
        json=_manual_payload(claim="Le token secret est stocke dans le projet."),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "sensitive_claim_refused"
    assert store.list_candidates() == []


def test_accept_route_does_not_call_llm_or_create_product_memory(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    candidate = _seed(store)
    client = _candidate_app(store).test_client()

    response = client.post(f"/memory/candidates/{candidate['id']}/accept", json={"reviewer": "human"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["candidate"]["status"] == "accepted"
    assert payload["canonical_memory_created"] is False
    assert payload["llm_injected"] is False


def test_reject_edit_delete_routes_review_candidate_without_promotion(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    candidate = _seed(store)
    client = _candidate_app(store).test_client()

    edit_response = client.post(
        f"/memory/candidates/{candidate['id']}/edit",
        json={"claim": "Pulse est un projet recurrent verifie manuellement."},
    )
    edited = edit_response.get_json()["candidate"]
    assert edit_response.status_code == 200
    assert edited["status"] == "edited"
    assert edited["human_review"]["trace"][-1]["decision"] == "edited"

    reject_response = client.post(
        f"/memory/candidates/{candidate['id']}/reject",
        json={"reason": "human_changed_mind"},
    )
    rejected = reject_response.get_json()["candidate"]
    assert reject_response.status_code == 200
    assert rejected["status"] == "rejected"
    assert rejected["rejection_policy"] == "do_not_repropose_without_new_stronger_evidence"

    delete_response = client.delete(f"/memory/candidates/{candidate['id']}")
    assert delete_response.status_code == 200
    assert store.get_candidate(candidate["id"]) is None


def test_routes_do_not_call_daydream_facts_llm_or_memory_store(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    candidate = _seed(store)
    client = _candidate_app(store).test_client()
    llm = MagicMock()
    daydream = MagicMock()
    facts = MagicMock()
    memory_store = MagicMock()

    response = client.post(f"/memory/candidates/{candidate['id']}/accept")

    assert response.status_code == 200
    llm.assert_not_called()
    daydream.assert_not_called()
    facts.assert_not_called()
    memory_store.assert_not_called()


def test_list_route_falls_back_on_invalid_limit(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    _seed(store)
    client = _candidate_app(store).test_client()

    response = client.get("/memory/candidates?limit=abc")

    assert response.status_code == 200
    assert response.get_json()["count"] == 1


def test_review_routes_ignore_non_object_json_payload(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    candidate = _seed(store)
    client = _candidate_app(store).test_client()

    response = client.post(f"/memory/candidates/{candidate['id']}/accept", json=["bad"])

    assert response.status_code == 200
    reviewed = response.get_json()["candidate"]["human_review"]
    assert reviewed["reviewer"] == "human"
    assert reviewed["trace"][-1]["reviewer"] == "human"


def test_reject_route_falls_back_when_reason_is_not_string(tmp_path):
    store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    candidate = _seed(store)
    client = _candidate_app(store).test_client()

    response = client.post(
        f"/memory/candidates/{candidate['id']}/reject",
        json={"reason": {"bad": True}},
    )

    assert response.status_code == 200
    rejected = response.get_json()["candidate"]
    assert rejected["human_review"]["trace"][-1]["reason"] == "human_rejected"


def test_routes_module_has_no_lab_or_state_dependencies():
    source = inspect.getsource(memory_candidate_routes)

    assert "MemoryStore" not in source
    assert "RuntimeOrchestrator" not in source
    assert "memory_store" not in source
    assert "DayDream" not in source
    assert "daydream" not in source
    assert "FactEngine" not in source
    assert "facts" not in source
    assert "daemon.llm" not in source
    assert "summary_llm" not in source
    assert ".complete(" not in source
    assert "/state" not in source


def test_state_debug_state_and_insights_do_not_create_candidates(tmp_path):
    candidate_store = MemoryCandidateStore(tmp_path / "candidates.sqlite")
    app = Flask(__name__)
    register_memory_candidate_routes(app, candidate_store=candidate_store)
    runtime_state = RuntimeState()
    store = MagicMock()
    store.to_dict.return_value = {"last_event_type": "curl"}
    bus = MagicMock()
    bus.recent.return_value = [
        SimpleNamespace(type="terminal_command_finished", payload={"command": "curl /state"}, timestamp=datetime(2026, 5, 29, 12, 0, 0))
    ]
    register_status_routes(
        app,
        bus=bus,
        store=store,
        runtime_state=runtime_state,
        current_context_builder=CurrentContextBuilder(),
    )
    client = app.test_client()

    assert client.get("/state").status_code == 200
    assert client.get("/debug/state").status_code == 200
    assert client.get("/insights").status_code == 200
    assert candidate_store.list_candidates() == []


def test_candidate_routes_do_not_expose_forbidden_generation_endpoints(tmp_path):
    app = _candidate_app(MemoryCandidateStore(tmp_path / "candidates.sqlite"))
    client = app.test_client()

    assert client.post("/memory/candidates", json={"source": "state"}).status_code == 405
    assert client.post("/memory/candidates/generate", json={"source": "llm_summary"}).status_code in {404, 405}
    assert client.post("/memory/candidates/from-daydream", json={}).status_code in {404, 405}
    assert client.post("/memory/candidates/from-facts", json={}).status_code in {404, 405}
