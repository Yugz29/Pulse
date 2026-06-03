from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from daemon.routes.runtime_state_payloads import (
    build_debug_state_payload,
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
    active_file_source = "file_event"
    active_project = "Pulse"
    session_duration_min = 42

    def to_dict(self):
        return {
            "active_file": self.active_file,
            "active_file_source": self.active_file_source,
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
            active_file_source=getattr(signals, "active_file_source", None),
            probable_task="coding",
            activity_level="editing",
            focus_level="deep",
            session_duration_min=42,
            clipboard_context="code",
            signal_summary=SimpleNamespace(
                recent_apps=["Xcode"],
                recent_files=getattr(signals, "recent_files", []),
                edited_file_count_10m=2,
                file_type_mix_10m={"source": 2},
                rename_delete_ratio_10m=0.0,
                dominant_file_mode="few_files",
                work_pattern_candidate="feature_candidate",
            ),
            task_confidence=getattr(signals, "task_confidence", None),
        )


def _snapshot(
    *,
    signals=None,
    decision=None,
    present=None,
    paused=False,
    lock_marker_active=False,
    last_screen_locked_at=None,
):
    return SimpleNamespace(
        present=present or PresentStub(),
        signals=signals,
        decision=decision,
        paused=paused,
        memory_synced_at=datetime(2026, 5, 6, 10, 0, 0),
        latest_active_app="Xcode",
        latest_active_app_bundle_id="com.apple.dt.Xcode",
        latest_active_app_system_category="public.app-category.developer-tools",
        lock_marker_active=lock_marker_active,
        last_screen_locked_at=last_screen_locked_at,
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
        active_file_source="file_event",
        recent_files=["main.py", "test_main.py"],
        terminal_action_category="testing",
        terminal_project="Pulse",
        terminal_cwd="/tmp/Pulse",
        terminal_command="pytest",
        terminal_success=True,
        terminal_exit_code=0,
        terminal_duration_ms=1234,
        terminal_summary="✓ pytest",
    )


def _session_fsm(
    *,
    state="active",
    session_started_at=datetime(2026, 5, 6, 9, 0, 0),
    last_meaningful_activity_at=datetime(2026, 5, 6, 9, 30, 0),
    last_screen_locked_at=None,
):
    return SimpleNamespace(
        state=state,
        session_started_at=session_started_at,
        last_meaningful_activity_at=last_meaningful_activity_at,
        last_screen_locked_at=last_screen_locked_at,
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
        active_file_source="file_event",
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
        active_file_source="file_event",
        probable_task="testing",
        activity_level="executing",
        user_presence_state="active",
        user_idle_seconds=12,
        user_presence_source="iokit",
    )

    payload = present.to_dict()

    assert payload["user_idle_seconds"] == 12
    assert payload["user_presence_source"] == "iokit"
    assert payload["active_file_source"] == "file_event"
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
        active_file_source="file_event",
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
    assert payload["active_file_source"] == "file_event"
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
    assert payload["signals"]["active_file_source"] == "file_event"
    assert payload["signals"]["recent_files"] == ["main.py", "test_main.py"]
    assert payload["signals"]["task_confidence"] == 0.82
    assert payload["signals"]["terminal_command"] == "pytest"
    assert payload["signals"]["last_session_context"] == "last session for Pulse"


def test_build_state_payload_keeps_present_task_confidence_nullable_without_value():
    present = PresentState(
        active_project="Pulse",
        active_file="/tmp/pulse.py",
        probable_task="debug",
        activity_level="executing",
        focus_level="normal",
        session_duration_min=12,
    )

    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_signals(), present=present),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
    )

    assert payload["present"]["probable_task"] == "debug"
    assert payload["present"]["active_file_source"] == "unknown"
    assert payload["present"]["task_confidence"] is None
    assert payload["signals"]["task_confidence"] == 0.82


def test_build_state_payload_present_exposes_task_confidence_from_signals():
    present = PresentState(
        active_project="Pulse",
        active_file="/tmp/pulse.py",
        probable_task="coding",
        task_confidence=0.82,
        activity_level="editing",
        focus_level="normal",
        session_duration_min=12,
    )

    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_signals(), present=present),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
    )

    assert payload["present"]["probable_task"] == "coding"
    assert payload["present"]["task_confidence"] == 0.82


def test_build_state_payload_documents_legacy_signals_exposed_by_default():
    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_signals()),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
    )

    assert "debug" not in payload
    assert "signals" in payload
    assert payload["signals"]["terminal_command"] == "pytest"
    assert payload["signals"]["task_confidence"] == 0.82


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


def test_state_present_contract_rejects_raw_debug_lab_and_terminal_fields():
    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_sensitive_signals()),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
    )

    forbidden_present_fields = {
        "command",
        "terminal_command",
        "terminal_cwd",
        "terminal_summary",
        "mcp_command",
        "window_title",
        "git_context",
        "repo_root",
        "raw",
        "raw_output",
        "stdout",
        "stderr",
        "facts",
        "profile",
        "daydream",
        "vector_store",
        "embeddings",
        "llm_summary",
        "memory_candidate",
        "memory_candidates",
    }

    assert forbidden_present_fields.isdisjoint(payload["present"].keys())
    assert payload["signals"]["terminal_command"] == _sensitive_signals().terminal_command
    assert "signals" in payload  # legacy compatibility surface remains intentionally broad.


def test_build_state_payload_omits_debug_by_default_but_keeps_product_fields(monkeypatch):
    monkeypatch.delenv("PULSE_MODE", raising=False)

    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_signals()),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
    )

    assert "debug" not in payload
    assert payload["signals"]["active_project"] == "Pulse"
    assert payload["pulse_mode"] == "core"
    assert payload["experimental_enabled"] is False


def test_build_state_payload_exposes_lab_mode(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "lab")

    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(),
    )

    assert payload["pulse_mode"] == "lab"
    assert payload["experimental_enabled"] is True


def test_build_state_payload_can_include_legacy_debug_when_requested(monkeypatch):
    monkeypatch.delenv("PULSE_MODE", raising=False)

    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_signals()),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
        include_debug=True,
    )

    assert payload["debug"]["store"]["last_event_type"] == "file_modified"
    assert payload["debug"]["surface"] == "debug_state"
    assert payload["debug"]["legacy_in_state"] is True
    assert payload["debug"]["pulse_mode"] == "core"
    assert payload["debug"]["experimental_enabled"] is False
    assert payload["debug"]["runtime"]["latest_active_app"] == "Xcode"
    assert payload["debug"]["runtime"]["latest_active_app_bundle_id"] == "com.apple.dt.Xcode"
    assert (
        payload["debug"]["runtime"]["latest_active_app_system_category"]
        == "public.app-category.developer-tools"
    )
    assert payload["debug"]["runtime"]["memory_synced_at"] == "2026-05-06T10:00:00"
    assert payload["debug"]["signals"]["active_project"] == "Pulse"


def test_build_state_payload_keeps_debug_surface_out_by_default_but_not_legacy_signals(monkeypatch):
    monkeypatch.delenv("PULSE_MODE", raising=False)

    payload = build_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_signals()),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
        include_debug=False,
    )

    assert "debug" not in payload
    assert "store" not in payload
    assert "runtime" not in payload
    assert "signals" in payload


def test_build_debug_state_payload_returns_debug_surface_without_legacy_marker(monkeypatch):
    monkeypatch.delenv("PULSE_MODE", raising=False)

    payload = build_debug_state_payload(
        store_state=StoreStub().to_dict(),
        runtime_snapshot=_snapshot(signals=_signals()),
        current_context_builder=CurrentContextBuilderStub(),
        get_session_fsm=lambda: _session_fsm(),
        get_current_context=lambda: SimpleNamespace(
            id="ctx-1",
            session_id="session-1",
            active_project="Pulse",
            active_file="/tmp/pulse.py",
            probable_task="coding",
            activity_level="editing",
            task_confidence=0.8,
        ),
        get_recent_sessions=lambda limit: [{"id": "session-1", "active_project": "Pulse"}],
        last_session_context_fn=lambda project: None,
    )

    assert payload["surface"] == "debug_state"
    assert payload["legacy_in_state"] is False
    assert payload["pulse_mode"] == "core"
    assert payload["experimental_enabled"] is False
    assert payload["store"]["last_event_type"] == "file_modified"
    assert payload["runtime"]["latest_active_app"] == "Xcode"
    assert payload["session_fsm"]["state"] == "active"
    assert payload["current_context"]["active_project"] == "Pulse"
    assert payload["signals"]["active_project"] == "Pulse"
    assert payload["recent_sessions"][0]["id"] == "session-1"


def test_state_session_payload_keeps_runtime_pause_out_of_fsm_state(monkeypatch):
    monkeypatch.delenv("PULSE_MODE", raising=False)
    present = PresentState(
        session_status="active",
        awake=True,
        locked=False,
        active_project="Pulse",
        probable_task="coding",
        activity_level="editing",
        session_duration_min=18,
    )

    payload = build_state_payload(
        store_state={"session_duration_min": 999},
        runtime_snapshot=_snapshot(
            signals=_signals(),
            present=present,
            paused=True,
        ),
        get_session_fsm=lambda: _session_fsm(state="active"),
        current_context_builder=CurrentContextBuilderStub(),
        last_session_context_fn=lambda project: None,
    )

    assert payload["runtime_paused"] is True
    assert payload["present"]["session_status"] == "active"
    assert payload["present"]["locked"] is False
    assert payload["session_fsm"]["state"] == "active"
    assert payload["session_duration_min"] == 18
    assert payload["present"]["session_duration_min"] == 18


def test_debug_state_session_payload_distinguishes_locked_from_runtime_pause(monkeypatch):
    monkeypatch.delenv("PULSE_MODE", raising=False)
    locked_at = datetime(2026, 5, 6, 9, 45, 0)
    present = PresentState(
        session_status="locked",
        awake=False,
        locked=True,
        active_project="Pulse",
        activity_level="idle",
        session_duration_min=22,
    )

    payload = build_debug_state_payload(
        store_state={},
        runtime_snapshot=_snapshot(
            present=present,
            paused=False,
            lock_marker_active=True,
            last_screen_locked_at=locked_at,
        ),
        get_session_fsm=lambda: _session_fsm(
            state="locked",
            last_screen_locked_at=locked_at,
        ),
    )

    assert payload["runtime"]["lock_marker_active"] is True
    assert payload["runtime"]["last_screen_locked_at"] == "2026-05-06T09:45:00"
    assert payload["session_fsm"]["state"] == "locked"
    assert payload["session_fsm"]["last_screen_locked_at"] == "2026-05-06T09:45:00"


def test_state_closed_persisted_session_does_not_override_idle_runtime_session(monkeypatch):
    monkeypatch.delenv("PULSE_MODE", raising=False)
    present = PresentState(
        session_status="idle",
        awake=True,
        locked=False,
        active_project=None,
        probable_task="general",
        activity_level="idle",
        session_duration_min=0,
    )

    payload = build_state_payload(
        store_state={},
        runtime_snapshot=_snapshot(present=present),
        get_session_fsm=lambda: _session_fsm(
            state="idle",
            last_meaningful_activity_at=None,
        ),
        get_recent_sessions=lambda limit: [
            {
                "id": "closed-session",
                "started_at": "2026-05-06T08:00:00",
                "ended_at": "2026-05-06T08:45:00",
                "boundary_reason": "screen_lock",
                "active_project": "Pulse",
                "activity_level": "editing",
            }
        ],
    )

    assert payload["present"]["session_status"] == "idle"
    assert payload["session_fsm"]["state"] == "idle"
    assert payload["session_duration_min"] == 0
    assert payload["recent_sessions"][0]["ended_at"] == "2026-05-06T08:45:00"
    assert payload["recent_sessions"][0]["boundary_reason"] == "screen_lock"


def test_state_session_boundary_does_not_require_markdown_session_context(monkeypatch):
    monkeypatch.delenv("PULSE_MODE", raising=False)
    present = PresentState(
        session_status="idle",
        awake=True,
        locked=False,
        active_project="Pulse",
        probable_task="general",
        activity_level="idle",
    )

    payload = build_state_payload(
        store_state={},
        runtime_snapshot=_snapshot(present=present, signals=None),
        get_session_fsm=lambda: _session_fsm(state="idle"),
        last_session_context_fn=lambda project: (_ for _ in ()).throw(
            AssertionError("Markdown session context must not be needed for session state")
        ),
    )

    assert payload["present"]["session_status"] == "idle"
    assert payload["session_fsm"]["state"] == "idle"
    assert "signals" not in payload


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
    assert "debug" not in payload
