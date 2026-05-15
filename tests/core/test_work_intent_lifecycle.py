from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from daemon.core.work_intent_lifecycle import evaluate_work_intent_lifecycle
from daemon.runtime_state import PresentState, WorkIntent


def _intent(**overrides):
    payload = {
        "summary": "réduire les coûts cachés du modèle local",
        "source": "manual_context_note",
        "confidence": 0.9,
        "project": "Pulse",
        "expires_at": datetime.now() + timedelta(hours=1),
    }
    payload.update(overrides)
    return WorkIntent(**payload)


def test_no_active_work_intent_is_noop():
    present = PresentState(active_project="Pulse", activity_level="editing", work_intent=None)

    decision = evaluate_work_intent_lifecycle(present=present)

    assert decision.action == "keep"
    assert decision.reason == "noop"


def test_same_project_coding_editing_keeps_intent():
    present = PresentState(
        active_project="Pulse",
        probable_task="coding",
        activity_level="editing",
        work_intent=_intent(),
    )

    decision = evaluate_work_intent_lifecycle(present=present)

    assert decision.action == "keep"


def test_same_project_debug_executing_keeps_intent():
    present = PresentState(
        active_project="Pulse",
        probable_task="debug",
        activity_level="executing",
        work_intent=_intent(),
    )

    decision = evaluate_work_intent_lifecycle(present=present)

    assert decision.action == "keep"


def test_clear_on_clear_project_change():
    present = PresentState(
        active_project="OtherProject",
        probable_task="coding",
        activity_level="editing",
        work_intent=_intent(project="Pulse"),
    )

    decision = evaluate_work_intent_lifecycle(present=present)

    assert decision.action == "clear"
    assert decision.reason == "project_changed"


def test_clear_on_prolonged_idle_when_duration_available():
    present = PresentState(
        active_project="Pulse",
        activity_level="idle",
        user_idle_seconds=31 * 60,
        work_intent=_intent(),
    )

    decision = evaluate_work_intent_lifecycle(present=present)

    assert decision.action == "clear"
    assert decision.reason == "idle_timeout"


def test_clear_on_strong_session_boundary():
    present = PresentState(
        active_project="Pulse",
        activity_level="editing",
        work_intent=_intent(),
    )
    transition = SimpleNamespace(
        should_start_new_session=True,
        boundary_reason="screen_lock",
    )

    decision = evaluate_work_intent_lifecycle(present=present, session_state=transition)

    assert decision.action == "clear"
    assert decision.reason == "session_boundary"


def test_expired_intent_clears_but_runtime_state_remains_canonical():
    now = datetime(2026, 5, 15, 10, 0, 0)
    present = PresentState(
        active_project="Pulse",
        activity_level="editing",
        work_intent=_intent(expires_at=now - timedelta(seconds=1)),
    )

    decision = evaluate_work_intent_lifecycle(present=present, now=now)

    assert decision.action == "clear"
    assert decision.reason == "expired"
