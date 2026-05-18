from datetime import datetime, timedelta
from types import SimpleNamespace

from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.event_bus import Event, EventBus
from daemon.core.signal_scorer import SignalScorer
from daemon.core.work_context_card import build_work_context_card
from daemon.core.workspace_context import extract_project_name
from daemon.memory.work_episode_builder import build_work_episodes
from daemon.runtime_state import PresentState


BASE = datetime(2026, 5, 18, 10, 0, 0)
PULSE_SPECIFIC_SCOPES = {
    "memory",
    "routes",
    "daemon_python",
    "app_swift",
    "extractor",
    "work_episode",
}
GENERIC_SCOPES = {"source", "tests", "docs", "config", "assets", "git", "unknown"}


def _score_events(events: list[Event]):
    bus = EventBus(max_size=50)
    bus._queue.extend(events)
    return SignalScorer(bus).compute(observed_now=BASE)


def _event(event_type: str, payload: dict, minute: int = 0) -> Event:
    return Event(
        type=event_type,
        payload=payload,
        timestamp=BASE - timedelta(minutes=minute),
    )


def _episode_event(path: str, minute: int = 0) -> dict:
    return {
        "type": "file_modified",
        "payload": {
            "path": path,
            "is_meaningful": True,
        },
        "timestamp": BASE + timedelta(minutes=minute),
    }


def test_unknown_app_with_source_edits_still_infers_coding():
    signals = _score_events(
        [
            _event("app_activated", {"app_name": "Helix"}),
            _event("file_modified", {"path": "/tmp/acme-api/src/handler.py"}),
            _event("file_modified", {"path": "/tmp/acme-api/src/router.py"}),
            _event("file_modified", {"path": "/tmp/acme-api/tests/test_handler.py"}),
        ]
    )

    assert signals.active_project == "acme-api"
    assert signals.edited_file_count_10m == 3
    assert signals.probable_task == "coding"


def test_unknown_app_without_work_evidence_stays_general_or_unknown():
    signals = _score_events([_event("app_activated", {"app_name": "Helix"})])

    assert signals.probable_task in {"general", "unknown"}
    assert signals.probable_task != "coding"
    assert signals.active_project is None
    assert signals.active_file is None


def test_unknown_git_repo_project_detected_from_git_root(tmp_path):
    repo = tmp_path / "client-api"
    source = repo / "src" / "handler.py"
    (repo / ".git").mkdir(parents=True)
    source.parent.mkdir(parents=True)
    source.write_text("print('ok')\n")

    assert extract_project_name(str(source)) == "client-api"


def test_unknown_unstructured_path_does_not_invent_project():
    for path in ("/tmp/random.py", "/tmp/scratch/notes.txt", "handler.py"):
        assert extract_project_name(path) is None


def test_empty_work_context_card_uses_unknown_statuses():
    card = build_work_context_card(
        SimpleNamespace(
            active_project=None,
            activity_level="unknown",
            probable_task="general",
            task_confidence=None,
            active_app=None,
        ),
        signals=SimpleNamespace(window_title=None, recent_apps=[]),
    )

    assert card.project is None
    assert card.project_status == "unknown"
    assert card.task_status == "unknown"
    assert all("détecté" not in text.lower() for text in card.evidence)
    assert "Projet actif non identifié" in card.missing_context
    assert "Tâche utilisateur encore générale" in card.missing_context


def test_current_context_builder_propagates_app_bundle_ids():
    signals = SimpleNamespace(
        active_app_bundle_id="dev.pulse.test.UnknownIDE",
        active_app_system_category="public.app-category.developer-tools",
        recent_apps=["RandomIDE", "RandomAssistant"],
        recent_app_bundle_ids=["dev.pulse.test.UnknownIDE", "dev.pulse.test.UnknownAI"],
        recent_app_system_categories=[
            "public.app-category.developer-tools",
            "public.app-category.productivity",
        ],
    )

    context = CurrentContextBuilder().build(
        present=PresentState(active_project="acme-api", active_file="/tmp/acme-api/src/handler.py"),
        active_app="RandomIDE",
        signals=signals,
        find_git_root_fn=lambda path: None,
        find_workspace_root_fn=lambda path: None,
    )

    assert context.active_app_bundle_id == "dev.pulse.test.UnknownIDE"
    assert context.active_app_system_category == "public.app-category.developer-tools"
    assert context.signal_summary.recent_apps == ["RandomIDE", "RandomAssistant"]
    assert context.signal_summary.recent_app_bundle_ids == [
        "dev.pulse.test.UnknownIDE",
        "dev.pulse.test.UnknownAI",
    ]
    assert context.signal_summary.recent_app_system_categories == [
        "public.app-category.developer-tools",
        "public.app-category.productivity",
    ]


def test_bundle_id_flows_from_scorer_to_context_card_for_unknown_ai_support_app():
    signals = _score_events(
        [
            _event(
                "app_activated",
                {
                    "app_name": "RandomAssistant",
                    "bundle_id": "dev.pulse.test.UnknownAI",
                },
            ),
            _event("file_modified", {"path": "/tmp/acme-api/src/handler.py"}),
        ]
    )
    present = PresentState(
        active_project=signals.active_project,
        active_file=signals.active_file,
        probable_task=signals.probable_task,
        activity_level=signals.activity_level,
        focus_level=signals.focus_level,
        clipboard_context=signals.clipboard_context,
    )
    context = CurrentContextBuilder().build(
        present=present,
        active_app="RandomAssistant",
        signals=signals,
        find_git_root_fn=lambda path: None,
        find_workspace_root_fn=lambda path: None,
    )

    card = build_work_context_card(context, signals=signals)

    assert signals.active_app_bundle_id == "dev.pulse.test.UnknownAI"
    assert context.active_app_bundle_id == "dev.pulse.test.UnknownAI"
    assert card.support_apps == ("RandomAssistant",)


def test_work_episode_on_unknown_repo_uses_generic_scopes():
    episodes = build_work_episodes(
        [
            _episode_event("/tmp/acme-api/src/handler.py", 0),
            _episode_event("/tmp/acme-api/tests/test_handler.py", 4),
        ]
    )

    assert episodes
    assert all(episode.dominant_scope in GENERIC_SCOPES for episode in episodes)
    assert all(episode.dominant_scope not in PULSE_SPECIFIC_SCOPES for episode in episodes)
