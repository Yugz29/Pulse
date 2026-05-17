from datetime import datetime, timedelta

from daemon.memory.work_episode_builder import build_work_episodes


BASE = datetime(2026, 5, 17, 10, 0, 0)
PULSE_SPECIFIC_SCOPES = {
    "daemon_python",
    "app_swift",
    "extractor",
    "work_episode",
    "routes",
    "memory",
}


def event(path: str, minute: int = 0):
    return {
        "type": "file_modified",
        "payload": {
            "path": path,
            "is_meaningful": True,
        },
        "timestamp": BASE + timedelta(minutes=minute),
    }


def event_with_payload(path: str, payload: dict, minute: int = 0):
    event_item = event(path, minute)
    event_item["payload"].update(payload)
    return event_item


def test_unknown_repo_does_not_emit_pulse_specific_scopes():
    episodes = build_work_episodes(
        [
            event("/tmp/acme-api/src/handler.py", 0),
            event("/tmp/acme-api/tests/test_handler.py", 4),
            event("/tmp/acme-api/config/settings.yml", 8),
        ]
    )

    assert episodes
    assert all(episode.dominant_scope not in PULSE_SPECIFIC_SCOPES for episode in episodes)


def test_source_and_tests_are_compatible_without_pulse_paths():
    episodes = build_work_episodes(
        [
            event("/tmp/acme-api/src/handler.py", 0),
            event("/tmp/acme-api/tests/test_handler.py", 4),
        ]
    )

    assert len(episodes) == 1
    assert episodes[0].evidence_count == 2
    assert episodes[0].dominant_scope in {"source", "tests"}
    assert episodes[0].dominant_scope not in PULSE_SPECIFIC_SCOPES


def test_docs_create_scope_shift_from_source_when_gap_is_significant():
    episodes = build_work_episodes(
        [
            event("/tmp/acme-api/src/handler.py", 0),
            event("/tmp/acme-api/docs/api.md", 18),
        ]
    )

    assert len(episodes) == 2
    assert episodes[0].boundary_reason == "scope_change"
    assert episodes[0].dominant_scope == "source"
    assert episodes[0].next_scope == "docs"
    assert episodes[1].dominant_scope == "docs"


def test_project_detection_does_not_require_projects_folder():
    episodes = build_work_episodes([event("/tmp/acme-api/src/handler.py")])

    assert len(episodes) == 1
    assert episodes[0].project == "acme-api"


def test_project_detection_uses_git_or_workspace_root_when_available(tmp_path):
    repo = tmp_path / "client-api"
    (repo / ".git").mkdir(parents=True)
    source = repo / "src" / "handler.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('ok')\n")

    episodes = build_work_episodes([event(str(source))])

    assert len(episodes) == 1
    assert episodes[0].project == "client-api"


def test_explicit_project_payload_still_has_priority():
    episodes = build_work_episodes(
        [
            event_with_payload(
                "/tmp/acme-api/src/handler.py",
                {"project": "ExplicitProject"},
            )
        ]
    )

    assert len(episodes) == 1
    assert episodes[0].project == "ExplicitProject"


def test_unknown_project_penalizes_confidence():
    known_project = build_work_episodes(
        [
            event("/tmp/acme-api/src/handler.py", 0),
            event("/tmp/acme-api/tests/test_handler.py", 4),
        ]
    )
    unknown_project = build_work_episodes(
        [
            event("/tmp/handler.py", 0),
            event("/tmp/test_handler.py", 4),
        ]
    )

    assert len(known_project) == 1
    assert len(unknown_project) == 1
    assert known_project[0].project == "acme-api"
    assert unknown_project[0].project is None
    assert unknown_project[0].confidence < known_project[0].confidence
