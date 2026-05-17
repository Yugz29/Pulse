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
