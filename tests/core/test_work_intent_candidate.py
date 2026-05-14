from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from daemon.core.work_intent_candidate import WorkIntentCandidateStore, WorkIntentCandidateStatus
from daemon.runtime_state import WorkIntent


def _probe(request_id="probe-1", kind="manual_context_note", metadata=None):
    return SimpleNamespace(
        request_id=request_id,
        kind=SimpleNamespace(value=kind),
        metadata=metadata or {},
    )


def _result(source="manual_context_note", value="réduire les coûts cachés du modèle local"):
    return {
        "kind": "manual_context_note",
        "data": {
            "source": source,
            "redacted_value": value,
        },
    }


def test_manual_context_note_creates_candidate_without_raw_secret():
    store = WorkIntentCandidateStore()

    candidate = store.maybe_create_from_probe_result(
        probe_request=_probe(),
        result=_result(value="objectif avec [REDACTED_TOKEN]"),
        project="Pulse",
        active_work_intent=None,
    )

    assert candidate is not None
    assert candidate.source == "manual_context_note"
    assert candidate.confidence == 0.9
    assert candidate.project == "Pulse"
    assert candidate.evidence_refs == ("context_probe:probe-1",)
    assert "sk-" not in str(candidate.to_dict())


def test_candidate_uses_request_metadata_project_when_present_project_missing():
    store = WorkIntentCandidateStore()

    candidate = store.maybe_create_from_probe_result(
        probe_request=_probe(metadata={"project": "Pulse"}),
        result=_result(),
        project=None,
        active_work_intent=None,
    )

    assert candidate is not None
    assert candidate.project == "Pulse"


def test_candidate_project_remains_none_without_present_or_metadata_project():
    store = WorkIntentCandidateStore()

    candidate = store.maybe_create_from_probe_result(
        probe_request=_probe(),
        result=_result(),
        project=None,
        active_work_intent=None,
    )

    assert candidate is not None
    assert candidate.project is None


def test_clipboard_sample_creates_medium_confidence_candidate():
    store = WorkIntentCandidateStore()

    candidate = store.maybe_create_from_probe_result(
        probe_request=_probe("clipboard-1", "clipboard_sample"),
        result=_result(source="next_clipboard_text", value="corriger l'annulation du prochain copier"),
        project="Pulse",
        active_work_intent=None,
    )

    assert candidate is not None
    assert candidate.source == "clipboard_sample"
    assert candidate.confidence == 0.65


def test_focused_element_text_does_not_create_candidate():
    store = WorkIntentCandidateStore()

    candidate = store.maybe_create_from_probe_result(
        probe_request=_probe("focused-1", "focused_element_text"),
        result=_result(source="focused_element_text", value="texte actif"),
        project="Pulse",
        active_work_intent=None,
    )

    assert candidate is None


def test_active_work_intent_prevents_candidate_creation():
    store = WorkIntentCandidateStore()
    active = WorkIntent(
        summary="objectif actif",
        source="manual",
        expires_at=datetime.now() + timedelta(minutes=30),
    )

    candidate = store.maybe_create_from_probe_result(
        probe_request=_probe(),
        result=_result(),
        project="Pulse",
        active_work_intent=active,
    )

    assert candidate is None


def test_refused_candidate_cannot_be_accepted_or_recreated_from_same_evidence():
    store = WorkIntentCandidateStore()
    candidate = store.maybe_create_from_probe_result(
        probe_request=_probe(),
        result=_result(),
        project="Pulse",
        active_work_intent=None,
    )

    refused = store.refuse(candidate.candidate_id)

    assert refused.status is WorkIntentCandidateStatus.REFUSED
    with pytest.raises(ValueError):
        store.accept(candidate.candidate_id)
    recreated = store.maybe_create_from_probe_result(
        probe_request=_probe(),
        result=_result(value="nouvelle valeur même evidence"),
        project="Pulse",
        active_work_intent=None,
    )
    assert recreated is None


def test_expired_candidate_cannot_be_accepted():
    store = WorkIntentCandidateStore()
    now = datetime(2026, 5, 14, 12, 0, 0)
    candidate = store.maybe_create_from_probe_result(
        probe_request=_probe(),
        result=_result(),
        project="Pulse",
        active_work_intent=None,
        now=now,
    )

    store.expire_due(now=now + timedelta(hours=3))

    with pytest.raises(ValueError):
        store.accept(candidate.candidate_id)
