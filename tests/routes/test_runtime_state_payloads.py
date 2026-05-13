from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from daemon.routes.runtime_state_payloads import (
    build_state_payload,
    serialize_current_context,
)
from daemon.runtime_state import PresentState, WorkIntent


class StoreStub:
    def to_dict(self):
        return {
            "last_event_type": "file_modified",
            "active_project": "OldProject",
        }


class PresentStub:
    active_file = "/tmp/pulse.py"
    active_project = "Pulse"
    session_duration_min = 42

    def to_dict(self):
        return {
            "active_file": self.active_file,
            "active_project": self.active_project,
            "session_duration_min": self.session_duration_min,
            "session_status": "active",
        }


class CurrentContextBuilderStub:
    def build(self, **kwargs):
        signals = kwargs["signals"]
        return SimpleNamespace(
            active_project="Pulse",
            active_file="/tmp/pulse.py",
            probable_task="coding",
            activity_level="editing",
            focus_level="deep",
            session_duration_min=42,
            clipboard_context="code",
            signal_summary=SimpleNamespace(
                recent_apps=["Xcode"],
                edited_file_count_10m=2,
                file_type_mix_10m={"source": 2},
                rename_delete_ratio_10m=0.0,
                dominant_file_mode="few_files",
                work_pattern_candidate="feature_candidate",
            ),
            task_confidence=getattr(signals, "task_confidence", None),
        )


def _snapshot(*, signals=None, decision=None, present=None):
    return SimpleNamespace(
        present=present or PresentStub(),
        signals=signals,
        decision=decision,
        paused=False,
        memory_synced_at=datetime(2026, 5, 6, 10, 0, 0),
        latest_active_app="Xcode",
        lock_marker_active=False,
        last_screen_locked_at=None,
    )


def _signals():
    return SimpleNamespace(
        task_confidence=0.82,
        friction_score=0.14,
        user_presence_state="active",
        user_idle_seconds=3,
        active_app_duration_sec=120,
        active_window_title_duration_sec=90,
        app_switch_count_10m=1,
        ai_app_switch_count_10m=0,
        terminal_action_category="testing",
        terminal_project="Pulse",
        terminal_cwd="/tmp/Pulse",
        terminal_command="pytest",
        terminal_success=True,
        terminal_exit_code=0,
        terminal_duration_ms=1234,
        terminal_summary="✓ pytest",
    )


def _sensitive_signals():
    return SimpleNamespace(
        task_confidence=0.82,
        friction_score=0.14,
        user_presence_state="active",
        user_idle_seconds=3,
        active_app_duration_sec=120,
        active_window_title_duration_sec=90,
        app_switch_count_10m=1,
        ai_app_switch_count_10m=0,
        terminal_action_category="testing",
        terminal_project="Pulse",
        terminal_cwd="/Users/yugz/Projets/Pulse/Pulse",
        terminal_command="curl -H 'Authorization: Bearer SECRET_TOKEN' https://example.test",
        terminal_success=False,
        terminal_exit_code=1,
        terminal_duration_ms=1234,
        terminal_summary="pytest failed",
        window_title="Pulse notes yugz@example.com /Users/yugz/private",
        git_context={
            "repo_root": "/Users/yugz/Projets/Pulse/Pulse",
            "repo_name": "Pulse",
            "branch": "main",
        },
        raw_output="SECRET stdout",
        stdout="SECRET stdout",
        stderr="SECRET stderr",
    )


def test_present_state_product_projection_stays_minimal():
    present = PresentState(
        active_project="Pulse",
        active_file="/Users/yugz/Projets/Pulse/Pulse/daemon/main.py",
        probable_task="testing",
        activity_level="executing",
        user_presence_state="active",
        user_idle_seconds=12,
        user_presence_source="iokit",
    )

    payload = present.to_dict()

    assert payload["user_idle_seconds"] == 12
    assert payload["user_presence_source"] == "iokit"
    assert "terminal_command" not in payload
    assert "command" not in payload
    assert "mcp_command" not in payload
    assert "window_title" not in payload
    assert "git_context" not in payload
    assert "repo_root" not in payload
    assert "stdout" not in payload
    assert "stderr" not in payload
    assert "raw_output" not in payload


def test_present_state_exposes_optional_work_intent_without_raw_context():
    present = PresentState(
        active_project="Pulse",
        probable_task="coding",
        work_intent=WorkIntent(
            summary="réduire les coûts cachés du modèle local",
            source="manual",
            confidence=0.9,
            project="Pulse",
            evidence_refs=("commit_message",),
        ),
    )

    payload = present.to_dict()

    assert payload["probable_task"] == "coding"
    assert payload["work_intent"]["summary"] == "réduire les coûts cachés du modèle local"
    assert payload["work_intent"]["source"] == "manual"
    assert payload["work_intent"]["evidence_refs"] == ["commit_message"]
    assert "window_title" not in payload["work_intent"]
    assert "clipboard" not in payload["work_intent"]
    assert "conversation" not in payload["work_intent"]


def test_serialize_current_context_returns_expected_top_level_keys():
    context = SimpleNamespace(
        id="ctx-1",
        session_id="session-1",
        started_at="2026-05-06T09:00:00",
        active_project="Pulse",
        active_file="/tmp/pulse.py",
        probable_task="coding",
        activity_level="editing",
        focus_level="deep",
        task_confidence=0.8,
        work_intent={
            "summary": "stabiliser le résumé journal",
            "source": "manual",
            "confidence": 0.8,
        },
    )

    payload = serialize_current_context(context)

    assert payload["id"] == "ctx-1"
    assert payload["session_id"] == "session-1"
    assert payload["active_project"] == "Pulse"
    assert payload["active_file"] == "/tmp/pulse.py"
    assert payload["probable_task"] == "coding"
    assert payload["task_confidence"] == 0.8
    assert payload["work_intent"]["summary"] == "stabiliser le résumé journal"
    assert payload["app_switch_count_10m"] == 0


def test_build_state_payload_legacy_signals_contains_expected_fields():
    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_signals()),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: f"last session for {project}",
    )

    assert payload["active_project"] == "Pulse"
    assert payload["signals"]["active_project"] == "Pulse"
    assert payload["signals"]["active_file"] == "/tmp/pulse.py"
    assert payload["signals"]["task_confidence"] == 0.82
    assert payload["signals"]["terminal_command"] == "pytest"
    assert payload["signals"]["last_session_context"] == "last session for Pulse"


def test_build_state_payload_keeps_present_minimal_when_state_signals_are_enriched():
    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_sensitive_signals()),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
    )

    serialized = str(payload)

    assert payload["present"]["active_project"] == "Pulse"
    assert "terminal_command" not in payload["present"]
    assert "window_title" not in payload["present"]
    assert "git_context" not in payload["present"]
    assert "raw_output" not in payload["present"]

    assert payload["signals"]["terminal_command"] == _sensitive_signals().terminal_command
    assert "window_title" not in payload["signals"]
    assert "git_context" not in payload["signals"]
    assert "raw_output" not in payload["signals"]
    assert "SECRET_TOKEN" in serialized
    assert "Pulse notes yugz@example.com" not in serialized
    assert "SECRET stdout" not in serialized


def test_build_state_payload_debug_contains_expected_fields():
    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_signals()),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
    )

    assert payload["debug"]["store"]["last_event_type"] == "file_modified"
    assert payload["debug"]["runtime"]["latest_active_app"] == "Xcode"
    assert payload["debug"]["runtime"]["memory_synced_at"] == "2026-05-06T10:00:00"
    assert payload["debug"]["signals"]["active_project"] == "Pulse"


def test_build_state_payload_missing_optional_fields_uses_safe_defaults():
    payload = build_state_payload(
        store_state={},
        runtime_snapshot=_snapshot(
            present=SimpleNamespace(
                active_file=None,
                active_project=None,
                session_duration_min=0,
                to_dict=lambda: {},
            )
        ),
    )

    assert payload["active_app"] == "Xcode"
    assert payload["active_file"] is None
    assert payload["last_event_type"] is None
    assert payload["runtime_paused"] is False
    assert payload["present"] == {}
    assert payload["debug"]["store"] == {}
