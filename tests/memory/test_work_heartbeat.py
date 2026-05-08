from daemon.memory.work_heartbeat import (
    classify_work_heartbeat,
    is_work_heartbeat,
    work_heartbeat_strength,
)


def test_meaningful_file_event_is_strong_work_heartbeat():
    event = {
        "type": "file_modified",
        "payload": {
            "path": "/Users/yugz/Projets/Pulse/Pulse/daemon/core/signal_scorer.py",
            "is_meaningful": True,
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "strong"
    assert heartbeat.reason == "meaningful_file_event"
    assert is_work_heartbeat(event) is True


def test_technical_file_event_is_not_work_heartbeat():
    event = {
        "type": "file_modified",
        "payload": {
            "path": "/Users/yugz/Projets/Pulse/Pulse/models_cache.json",
            "is_meaningful": True,
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "none"
    assert heartbeat.reason == "no_work_evidence"
    assert is_work_heartbeat(event) is False


def test_xcode_xcresult_tmp_file_event_is_not_work_heartbeat():
    paths = [
        (
            "/Users/yugz/Projets/Pulse/Pulse/.derivedData/Logs/Test/"
            "Test-App-2026.05.05_19-56-24-+0200.xcresult/Data/_tmp.abc123"
        ),
        (
            "/Users/yugz/Projets/Pulse/Pulse/DerivedData/Logs/Test/"
            "Test-App-2026.05.05_19-56-24-+0200.xcresult/Staging/1_Test/Diagnostics.json"
        ),
        (
            "/Users/yugz/Projets/Pulse/Pulse/.derivedData/Logs/Test/"
            "Test-App-2026.05.05_19-56-24-+0200.xcresult/Data/refs.0~abc"
        ),
        (
            "/Users/yugz/Projets/Pulse/Pulse/.derivedData/Logs/Test/"
            "Test-App-2026.05.05_19-56-24-+0200.xcresult/1_Test/StandardOutputAndStandardError.txt"
        ),
    ]

    for path in paths:
        event = {
            "type": "file_modified",
            "payload": {
                "path": path,
                "is_meaningful": True,
            },
        }

        heartbeat = classify_work_heartbeat(event)

        assert heartbeat.strength == "none"
        assert heartbeat.reason == "no_work_evidence"
        assert is_work_heartbeat(event) is False


def test_xcode_artifact_file_event_types_are_not_work_heartbeats():
    cases = [
        (
            "file_renamed",
            "/Users/yugz/Projets/Pulse/Pulse/.derivedData/Build/Intermediates.noindex/Pulse.build/tmp",
        ),
        (
            "file_renamed",
            "/Users/yugz/Projets/Pulse/Pulse/.derivedData/Logs/Test/Test-App.xcresult/Data/refs.0~abc",
        ),
        (
            "file_deleted",
            "/Users/yugz/Projets/Pulse/Pulse/.derivedData/Logs/Test/Test-App.xcresult/Staging/1_Test/out.txt",
        ),
        (
            "file_created",
            "/Users/yugz/Projets/Pulse/Pulse/.derivedData/Build/Products/Debug/App.app",
        ),
    ]

    for event_type, path in cases:
        event = {
            "type": event_type,
            "payload": {
                "path": path,
                "is_meaningful": True,
            },
        }

        heartbeat = classify_work_heartbeat(event)

        assert heartbeat.strength == "none"
        assert heartbeat.reason == "no_work_evidence"
        assert is_work_heartbeat(event) is False


def test_real_file_renamed_event_remains_work_heartbeat():
    event = {
        "type": "file_renamed",
        "payload": {
            "path": "/Users/yugz/Projets/Pulse/Pulse/daemon/memory/work_episode_builder.py",
            "is_meaningful": True,
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "strong"
    assert heartbeat.reason == "meaningful_file_event"
    assert is_work_heartbeat(event) is True


def test_global_dev_tool_artifacts_are_not_work_heartbeats():
    cases = [
        (
            "file_modified",
            "/Users/yugz/.vscode/extensions/extensions.json",
        ),
        (
            "file_created",
            "/Users/yugz/.vscode/extensions/continue.continue-1.0.0/package.json",
        ),
        (
            "file_modified",
            "/Users/yugz/.continue/index/globalContext.json",
        ),
        (
            "file_renamed",
            "/Users/yugz/.ollama/cache/model-recommendations.json",
        ),
    ]

    for event_type, path in cases:
        event = {
            "type": event_type,
            "payload": {
                "path": path,
                "is_meaningful": True,
            },
        }

        heartbeat = classify_work_heartbeat(event)

        assert heartbeat.strength == "none"
        assert heartbeat.reason == "no_work_evidence"
        assert is_work_heartbeat(event) is False


def test_project_vscode_settings_is_not_filtered_as_global_dev_tool_artifact():
    event = {
        "type": "file_modified",
        "payload": {
            "path": "/Users/yugz/Projets/Pulse/Pulse/.vscode/settings.json",
            "is_meaningful": True,
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "strong"
    assert heartbeat.reason == "meaningful_file_event"
    assert is_work_heartbeat(event) is True


def test_terminal_testing_command_is_strong_work_heartbeat():
    event = {
        "type": "terminal_command_finished",
        "payload": {
            "terminal_action_category": "testing",
            "terminal_command": "python -m pytest tests/core/test_signal_scorer.py",
            "terminal_project": "Pulse",
            "terminal_success": True,
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "strong"
    assert heartbeat.reason == "terminal_testing"
    assert work_heartbeat_strength(event) == "strong"


def test_terminal_project_command_without_category_is_strong_work_heartbeat():
    event = {
        "type": "terminal_command_finished",
        "payload": {
            "terminal_command": "curl -s http://127.0.0.1:8765/state",
            "terminal_project": "Pulse",
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "strong"
    assert heartbeat.reason == "terminal_project_command"


def test_git_status_is_weak_work_heartbeat():
    event = {
        "type": "terminal_command_finished",
        "payload": {
            "terminal_command": "git status",
            "terminal_command_base": "git",
            "terminal_project": "Pulse",
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "weak"
    assert heartbeat.reason == "terminal_git_status"


def test_read_only_git_variants_are_weak_work_heartbeats():
    commands = [
        "git -C repo status",
        "git diff --stat",
        "git show HEAD",
    ]

    for command in commands:
        heartbeat = classify_work_heartbeat({
            "type": "terminal_command_finished",
            "payload": {
                "terminal_command": command,
                "terminal_command_base": "git",
                "terminal_project": "Pulse",
            },
        })

        assert heartbeat.strength == "weak"


def test_git_commit_is_strong_work_heartbeat():
    event = {
        "type": "terminal_command_finished",
        "payload": {
            "terminal_command": "git commit -m 'fix: persist session activity level'",
            "terminal_command_base": "git",
            "terminal_project": "Pulse",
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "strong"
    assert heartbeat.reason == "terminal_git_commit"


def test_youtube_window_title_is_not_work_heartbeat_even_in_browser():
    event = {
        "type": "window_title_poll",
        "payload": {
            "app_name": "Google Chrome",
            "title": "Some Video - YouTube",
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "none"
    assert heartbeat.reason == "no_work_evidence"


def test_ai_app_activation_is_weak_work_heartbeat():
    event = {
        "type": "app_activated",
        "payload": {
            "app_name": "ChatGPT",
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "weak"
    assert heartbeat.reason == "ai_app_active"


def test_recent_user_presence_is_not_work_heartbeat_by_itself():
    event = {
        "type": "user_presence",
        "payload": {
            "presence_state": "active",
            "idle_seconds": "10",
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "none"
    assert heartbeat.reason == "no_work_evidence"


def test_passive_user_presence_is_not_work_heartbeat():
    event = {
        "type": "user_presence",
        "payload": {
            "presence_state": "passive",
            "idle_seconds": "300",
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "none"
    assert heartbeat.reason == "no_work_evidence"


def test_unknown_app_does_not_become_work_without_corrobation():
    event = {
        "type": "app_activated",
        "payload": {
            "app_name": "Unknown Notes App",
            "title": "Random window",
        },
    }

    heartbeat = classify_work_heartbeat(event)

    assert heartbeat.strength == "none"
    assert heartbeat.reason == "no_work_evidence"
