import pytest

from daemon_v2.analysis.terminal import (
    is_pasted_prompt_command,
    is_pulse_inspection_command,
    is_test_command,
    parse_git_command,
    pasted_prompt_placeholder,
    terminal_labels,
    useful_command_lines,
)


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest",
        "python3 -m pytest tests_v2",
        ".venv/bin/python -m pytest tests_v2/test_routes.py",
        "pytest",
        "npm test",
        "swift test",
        "make test",
    ],
)
def test_recognizes_supported_test_commands(command):
    assert is_test_command(command)


@pytest.mark.parametrize(
    "command",
    ["echo pytest", "npm testSomething", "make tester"],
)
def test_rejects_test_command_false_positives(command):
    assert not is_test_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "curl http://127.0.0.1:5000/trace/today",
        "curl http://127.0.0.1:5000/trace/today.md | head",
        "curl http://127.0.0.1:5000/trace/days | python -m json.tool",
        "curl http://127.0.0.1:5000/days",
        "curl http://127.0.0.1:5000/day/2026-07-05 | rg Session",
    ],
)
def test_recognizes_pulse_inspection_commands(command):
    assert is_pulse_inspection_command(command)


def test_recognizes_pasted_prompt_but_keeps_legitimate_single_marker():
    prompt = (
        "Pulse_V2 — extraction terminal\n"
        "Contexte : conserver le comportement actuel.\n"
        "Objectif : déplacer les fonctions pures.\n"
        "À faire : adapter les imports.\n"
        "Validation attendue : tous les tests passent."
    )

    assert is_pasted_prompt_command(prompt)
    assert not is_pasted_prompt_command("echo 'Contexte : build local'")


def test_pasted_prompt_placeholder_reports_size_and_stays_excluded():
    prompt = (
        "Pulse_V2 — extraction terminal\n"
        "Contexte : conserver le comportement actuel.\n"
        "Objectif : déplacer les fonctions pures."
    )

    placeholder = pasted_prompt_placeholder(prompt)

    assert placeholder == f"[prompt collé : 3 lignes, {len(prompt)} caractères]"
    # A stored placeholder must stay out of rendering and labels exactly
    # like the full prompt it replaced.
    assert is_pasted_prompt_command(placeholder)
    assert useful_command_lines(placeholder) == []


def test_pasted_prompt_placeholder_uses_singular_forms():
    assert pasted_prompt_placeholder("x") == "[prompt collé : 1 ligne, 1 caractère]"


def test_singular_placeholder_is_recognized_and_stays_excluded():
    # The singular stored form must round-trip exactly like the plural one:
    # recognized as a placeholder and kept out of rendering.
    placeholder = "[prompt collé : 1 ligne, 1 caractère]"

    assert is_pasted_prompt_command(placeholder)
    assert useful_command_lines(placeholder) == []


@pytest.mark.parametrize(
    "command",
    [
        "echo '[prompt collé : 3 lignes, 120 caractères]'",
        "[prompt collé : 3 lignes, 120 caractères]\nmake test",
        "[prompt collé : quelques lignes]",
    ],
)
def test_placeholder_recognition_requires_exact_single_line(command):
    assert not is_pasted_prompt_command(command)


def test_keeps_useful_lines_from_multiline_inspection_command():
    command = (
        "curl http://127.0.0.1:5000/trace/today.md | head\n"
        "make test\n"
        "curl http://127.0.0.1:5000/days"
    )

    assert useful_command_lines(command) == ["make test"]


def test_terminal_labels_have_stable_order():
    activity = {
        "details": {
            "command": (
                "python -m daemon_v2.main\n"
                "git status\n"
                "make test"
            ),
            "exit_code": 1,
        }
    }

    assert terminal_labels(activity) == ["test", "git", "pulse", "erreur"]


@pytest.mark.parametrize(
    ("exit_code", "has_error"),
    [
        (0, False),
        (1, True),
        (None, False),
        (False, False),
        (True, False),
        ("1", False),
    ],
)
def test_terminal_error_label_preserves_exit_code_contract(exit_code, has_error):
    labels = terminal_labels(
        {"details": {"command": "echo useful", "exit_code": exit_code}}
    )

    assert ("erreur" in labels) is has_error


@pytest.mark.parametrize(
    ("command", "is_git", "action", "commit_message"),
    [
        ('git commit -m "message cité"', True, "commit", "message cité"),
        ("git commit -m message", True, "commit", "message"),
        ("git commit", True, "commit", None),
        ("git push", True, "push", None),
        ("git pull", True, "pull", None),
        ("git status", True, "status", None),
        ("echo git status", False, None, None),
        # Global Git options are intentionally not interpreted yet.
        ("git -C repo status", True, "other", None),
        # Only the separate `-m` form is extracted today.
        ("git commit -am message", True, "commit", None),
    ],
)
def test_parses_observed_git_commands(
    command, is_git, action, commit_message
):
    parsed = parse_git_command(command)

    assert parsed.is_git is is_git
    assert parsed.action == action
    assert parsed.commit_message == commit_message


def test_git_command_parser_preserves_invalid_quoting_fallback():
    parsed = parse_git_command('git commit -m "unfinished')

    assert parsed.is_git
    assert parsed.action == "commit"
    assert parsed.commit_message == '"unfinished'


def test_failed_git_command_remains_an_observed_command():
    activity = {
        "details": {
            "command": 'git commit -m "observed failure"',
            "exit_code": 1,
        }
    }

    parsed = parse_git_command(activity["details"]["command"])
    assert parsed.action == "commit"
    assert parsed.commit_message == "observed failure"
    assert terminal_labels(activity) == ["git", "erreur"]


def test_ctrl_c_interruption_is_not_an_error_label():
    from daemon_v2.analysis.terminal import is_interrupted_exit

    # Ctrl-C (130 = 128+SIGINT) est un geste volontaire, pas un échec —
    # retour utilisateur du 2026-08-30 : 5/8 commandes du jour en 130.
    assert is_interrupted_exit(130)
    assert not is_interrupted_exit(1)
    assert not is_interrupted_exit(0)
    assert not is_interrupted_exit(True)
    assert not is_interrupted_exit(None)

    interrupted = {"details": {"command": "make dev", "exit_code": 130}}
    failed = {"details": {"command": "make dev", "exit_code": 1}}
    assert "erreur" not in terminal_labels(interrupted)
    assert "erreur" in terminal_labels(failed)
