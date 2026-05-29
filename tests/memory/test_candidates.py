from __future__ import annotations

import inspect

import pytest

from daemon.memory.candidates import (
    DEFAULT_REJECTION_POLICY,
    FORBIDDEN_MEMORY_TYPES,
    MemoryCandidateError,
    MemoryCandidateStore,
)
import daemon.memory.candidates as candidates_module


def _store(tmp_path):
    return MemoryCandidateStore(db_path=tmp_path / "candidates.sqlite")


def test_manual_candidate_starts_pending(tmp_path):
    candidate = _store(tmp_path).create_manual_candidate(
        memory_type="project_pattern",
        claim="Pulse semble etre un projet de travail recurrent.",
        confidence=0.4,
        sensitivity={"level": "low", "reason": "non_sensitive_project_pattern"},
        evidence=[{"source_type": "manual_review_seed", "summary": "Seed explicite de test."}],
    )

    assert candidate["status"] == "pending"
    assert candidate["human_review"]["required"] is True
    assert candidate["human_review"]["decision"] is None
    assert candidate["rejection_policy"] == DEFAULT_REJECTION_POLICY


def test_accept_does_not_create_product_memory_or_llm_injection(tmp_path):
    store = _store(tmp_path)
    candidate = store.create_manual_candidate(
        memory_type="workflow_pattern",
        claim="Les tests Python sont souvent l'etape de verification.",
    )

    accepted = store.accept(candidate["id"])

    assert accepted["status"] == "accepted"
    assert accepted["human_review"]["decision"] == "accepted"
    assert "llm" not in accepted
    assert "canonical_memory" not in accepted
    assert not hasattr(store, "promote_to_memory")
    assert not hasattr(store, "render_for_context")


def test_reject_keeps_explicit_rejection_policy(tmp_path):
    store = _store(tmp_path)
    candidate = store.create_manual_candidate(
        memory_type="caution",
        claim="Ne pas apprendre depuis curl seul.",
    )

    rejected = store.reject(candidate["id"], reason="insufficient_evidence")

    assert rejected["status"] == "rejected"
    assert rejected["rejection_policy"] == DEFAULT_REJECTION_POLICY
    assert rejected["human_review"]["trace"][-1]["reason"] == "insufficient_evidence"


def test_edit_keeps_human_trace(tmp_path):
    store = _store(tmp_path)
    candidate = store.create_manual_candidate(
        memory_type="tool_usage",
        claim="pytest est utilise.",
    )

    edited = store.edit(candidate["id"], claim="pytest est utilise pour verifier les patchs.")

    assert edited["status"] == "edited"
    assert edited["claim"] == "pytest est utilise pour verifier les patchs."
    assert edited["human_review"]["decision"] == "edited"
    assert edited["human_review"]["edited_claim"] == edited["claim"]
    assert edited["human_review"]["trace"][-1]["reviewer"] == "human"


def test_delete_removes_candidate(tmp_path):
    store = _store(tmp_path)
    candidate = store.create_manual_candidate(
        memory_type="tool_usage",
        claim="pytest est utilise.",
    )

    assert store.delete(candidate["id"]) is True
    assert store.get_candidate(candidate["id"]) is None


@pytest.mark.parametrize("memory_type", sorted(FORBIDDEN_MEMORY_TYPES))
def test_forbidden_memory_types_are_refused(tmp_path, memory_type):
    with pytest.raises(MemoryCandidateError, match="forbidden_memory_type"):
        _store(tmp_path).create_manual_candidate(
            memory_type=memory_type,
            claim="Claim sensible interdite.",
        )


def test_sensitive_candidate_is_refused(tmp_path):
    with pytest.raises(MemoryCandidateError, match="sensitive_candidate_refused"):
        _store(tmp_path).create_manual_candidate(
            memory_type="project_pattern",
            claim="Claim a refuser par sensibilite.",
            sensitivity={"level": "credential", "reason": "secret-like"},
        )


def test_unknown_sensitivity_level_is_refused(tmp_path):
    with pytest.raises(MemoryCandidateError, match="invalid_sensitivity"):
        _store(tmp_path).create_manual_candidate(
            memory_type="project_pattern",
            claim="Claim avec sensibilite inconnue.",
            sensitivity={"level": "unknown"},
        )


def test_non_dict_sensitivity_is_refused(tmp_path):
    with pytest.raises(MemoryCandidateError, match="invalid_sensitivity"):
        _store(tmp_path).create_manual_candidate(
            memory_type="project_pattern",
            claim="Claim avec sensibilite invalide.",
            sensitivity="low",
        )


def test_evidence_items_must_be_objects(tmp_path):
    with pytest.raises(MemoryCandidateError, match="invalid_evidence_item"):
        _store(tmp_path).create_manual_candidate(
            memory_type="project_pattern",
            claim="Claim avec preuve invalide.",
            evidence=["bad"],
        )


def test_no_generation_api_from_forbidden_sources(tmp_path):
    store = _store(tmp_path)

    forbidden_generation_methods = {
        "create_from_state",
        "create_from_curl",
        "create_from_debug_state",
        "create_from_insights",
        "create_from_llm_summary",
        "create_from_user_presence",
        "create_from_stale_repair",
        "create_from_daydream",
        "create_from_facts",
        "generate_candidates",
        "scan_sessions",
    }

    for method_name in forbidden_generation_methods:
        assert not hasattr(store, method_name)


def test_candidate_module_has_no_runtime_or_lab_dependencies():
    source = inspect.getsource(candidates_module)

    assert "RuntimeOrchestrator" not in source
    assert "from daemon.memory.store" not in source
    assert "memory_store" not in source
    assert "DayDream" not in source
    assert "daydream" not in source
    assert "FactEngine" not in source
    assert "facts" not in source
    assert "LLM" not in source
    assert "llm" not in source
    assert "/state" not in source
