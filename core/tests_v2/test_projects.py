from pathlib import Path

from daemon_v2.analysis.projects import (
    WorkspaceIdentity,
    is_generic_workspace_path,
    persisted_workspace_identity,
)


def test_workspace_details_win_and_carry_method_and_confidence():
    identity = persisted_workspace_identity(
        {
            "type": "terminal_finished",
            "details": {
                "workspace": {
                    "workspace_root": "/Users/dev/Projets/Pulse/Pulse_Core",
                    "project_name": "Pulse_Core",
                    "resolution_method": "git",
                    "resolution_confidence": "high",
                },
                "git_root": "/somewhere/else",
            },
        }
    )

    assert identity == WorkspaceIdentity(
        "/Users/dev/Projets/Pulse/Pulse_Core",
        "Pulse_Core",
        "git",
        "high",
    )


def test_git_details_fall_back_when_workspace_is_absent():
    identity = persisted_workspace_identity(
        {
            "type": "terminal_finished",
            "details": {
                "git": {"git_root": "/Users/dev/repo", "repository": "repo"},
                "cwd": "/Users/dev/repo/src",
            },
        }
    )

    assert identity.root == "/Users/dev/repo"
    assert identity.project_name == "repo"
    assert identity.method == "git"
    assert identity.confidence == "high"


def test_generic_cwd_resolves_to_no_identity():
    identity = persisted_workspace_identity(
        {"type": "terminal_finished", "details": {"cwd": "/tmp"}}
    )

    assert identity == WorkspaceIdentity(None, None, "cwd", "low")


def test_activity_without_any_detail_has_empty_identity():
    identity = persisted_workspace_identity({"type": "app_activated", "details": {}})

    assert identity == WorkspaceIdentity(None, None, None, None)


def test_generic_workspace_paths_include_home_and_temp_dirs():
    assert is_generic_workspace_path(str(Path.home()))
    assert is_generic_workspace_path("/tmp")
    assert is_generic_workspace_path("/Users/dev/code/build")
    assert not is_generic_workspace_path("/Users/dev/Projets/Pulse/Pulse_Core")
