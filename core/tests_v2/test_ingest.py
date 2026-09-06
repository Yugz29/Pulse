import pytest

from daemon_v2.ingest import (
    IgnoredActivity,
    InvalidActivity,
    command_has_secret,
    filter_terminal_command,
    normalize_activity,
    normalize_event,
    redact_command,
)


def test_command_has_secret_ignores_continuation_folding():
    # Une commande multiligne innocente (continuations \) n'est PAS un secret :
    # seul le repli de normalisation la distingue de sa forme rédigée.
    innocent = "git add a.py \\\n  b.py \\\n  c.py"
    assert not command_has_secret(innocent)
    assert command_has_secret("mysql --password \\\n  hunter2secret")
    assert command_has_secret("export API_TOKEN=abc123")
    assert not command_has_secret("git status")


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "mysql -u root -psup3rSecret -h localhost",
            "mysql -u root -p[REDACTED] -h localhost",
        ),
        (
            'curl -H "Authorization: Bearer sk-abc123XYZ789abcd" https://api.example.com',
            'curl -H "Authorization: Bearer [REDACTED]" https://api.example.com',
        ),
        (
            "psql postgres://user:hunter2@localhost/db",
            "psql postgres://user:[REDACTED]@localhost/db",
        ),
        (
            "git remote add origin https://user:ghp_abcdefghij1234567890@github.com/x/y.git",
            "git remote add origin https://user:[REDACTED]@github.com/x/y.git",
        ),
        (
            "aws configure set aws_secret_access_key AKIAIOSFODNN7EXAMPLE",
            "aws configure set aws_secret_access_key [REDACTED]",
        ),
        (
            "DATABASE_URL=postgres://u:p@h/db python app.py",
            "DATABASE_URL=postgres://u:[REDACTED]@h/db python app.py",
        ),
        (
            "openssl rsa -in key.pem -passin pass:secretpw",
            "openssl rsa -in key.pem -passin=[REDACTED]",
        ),
        (
            "curl -u admin:hunter2 http://localhost:8765/x",
            "curl -u [REDACTED] http://localhost:8765/x",
        ),
        # Secret entre guillemets avec espaces : masqué EN ENTIER (pas de
        # rédaction partielle qui laisserait fuir la fin du secret).
        (
            'export API_TOKEN="alpha bravo charlie"',
            "export API_TOKEN=[REDACTED]",
        ),
        (
            'tool --password "my secret phrase"',
            "tool --password=[REDACTED]",
        ),
        # Continuation de ligne : le repli \<newline> empêche le contournement.
        (
            "mysql --password \\\n  hunter2secret",
            "mysql --password=[REDACTED]",
        ),
        # Variante CRLF : sans le \r? du repli, le backslash seul serait
        # masqué et le secret resterait en clair sur la ligne suivante.
        (
            "mysql --password \\\r\n  hunter2secret",
            "mysql --password=[REDACTED]",
        ),
        # Invocations enveloppées (docker/ssh) : l'ancre (^|\s) les couvre.
        (
            "docker exec -it db mysql -u root -psup3rSecret",
            "docker exec -it db mysql -u root -p[REDACTED]",
        ),
        (
            "gpg --passphrase secret file.gpg",
            "gpg --passphrase=[REDACTED] file.gpg",
        ),
        (
            "sshpass -p hunter2 ssh host",
            "sshpass -p [REDACTED] ssh host",
        ),
        (
            'curl -H "X-Api-Key: abcd1234efgh" https://api.example.com',
            'curl -H "X-Api-Key: [REDACTED]" https://api.example.com',
        ),
        # Mot de passe contenant @ : masqué jusqu'au dernier @ avant l'hôte.
        (
            "psql postgres://user:p@ss@host/db",
            "psql postgres://user:[REDACTED]@host/db",
        ),
        (
            "export MY_PASSWD=abc && run",
            "export MY_PASSWD=[REDACTED] && run",
        ),
        (
            "slack-cli --token xoxb-1234567890-abcdef post",
            "slack-cli --token=[REDACTED] post",
        ),
    ],
)
def test_redacts_common_secret_shapes(command, expected):
    assert redact_command(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "fix passing tests"',
        "grep -p pattern file.txt",
        "python -m pytest tests_v2 -p no:cacheprovider",
        "curl http://127.0.0.1:8765/trace/today",
        "git push origin main",
        "mysql -u root -p",
        # Prose contenant basic/bearer/pass: — jamais touchée (faux positifs
        # attrapés par la revue : corrompaient l'historique ET faisaient
        # sortir l'audit en code 1 sur des lignes innocentes).
        'git commit -m "add basic logging support"',
        "echo pass:through",
        "echo bearer results.txt",
        # -u ailleurs que sur une commande à credentials : intouché.
        "rsync -u remote:path .",
        "docker run -u 1000:1000 image",
        "sudo -u www:data cmd",
        # mysql -P majuscule = PORT, pas mot de passe.
        "mysql -u root -P3306 -h host",
        # Chemin de fichier après un nom de clé : pas un secret.
        "grep aws_secret_access_key ~/.aws/credentials",
        # Sentinelles openssl non secrètes.
        "openssl req -passout stdin",
        "openssl rsa -passin env:MYPASS",
        "openssl rsa -passin file:/tmp/key.txt",
    ],
)
def test_redaction_leaves_ordinary_commands_untouched(command):
    assert redact_command(command) == command


def test_git_commit_message_is_redacted_at_ingest():
    activity = normalize_activity(
        {
            "type": "git_commit",
            "occurred_at": "2026-07-03T10:00:00+02:00",
            "commit_hash": "abc1234def",
            "repository": "Pulse",
            "git_root": "/project/Pulse",
            "branch": "main",
            "message": "rotate key: old was AKIAIOSFODNN7EXAMPLE",
        }
    )
    assert activity.details["message"] == "rotate key: old was [REDACTED]"
    assert "AKIA" not in activity.summary


def test_internal_pulse_curl_is_ignored_only_on_pulse_ports():
    # Ports Pulse : configuré + défaut 8765 + historique 5000.
    for port in (5000, 8765):
        multiline = (
            f"curl -X POST http://127.0.0.1:{port}/activities \\\n"
            '  -H "Content-Type: application/json" \\\n'
            '  -d \'{"type": "app_activated"}\''
        )
        assert filter_terminal_command(multiline) is None
    assert filter_terminal_command(
        "curl -X POST http://localhost:8765/activities -d '{}'"
    ) is None
    # Un dev qui teste SA propre API /activities garde sa commande.
    assert filter_terminal_command(
        "curl -X POST http://localhost:3000/activities -d '{}'"
    ) is not None
    # Chemin non exact : jamais filtré.
    assert filter_terminal_command(
        "curl http://127.0.0.1:8765/activities/123"
    ) is not None
    assert filter_terminal_command(
        "curl -X POST http://example.com/activities -d '{}'"
    ) is not None


def test_internal_pulse_curl_does_not_hide_following_command():
    command = "curl http://127.0.0.1:8765/activities\npytest -q"

    assert filter_terminal_command(command) == "pytest -q"


def test_internal_pulse_curl_preserves_useful_lines_on_both_sides():
    command = (
        "echo before\n"
        "curl http://127.0.0.1:8765/activities\n"
        "echo after"
    )

    assert filter_terminal_command(command) == "echo before\necho after"


def test_normalizes_and_redacts_terminal_activity():
    activity = normalize_activity(
        {
            "type": "terminal_finished",
            "occurred_at": "2026-07-03T10:00:00+02:00",
            "command": "deploy --token very-secret",
            "exit_code": 0,
            "cwd": "~/project",
            "started_at": "2026-07-03T09:59:58+02:00",
            "finished_at": "2026-07-03T10:00:00+02:00",
        }
    )

    assert activity.source == "terminal"
    assert activity.details["command"] == "deploy --token=[REDACTED]"
    assert activity.details["started_at"] == "2026-07-03T09:59:58+02:00"
    assert activity.details["finished_at"] == "2026-07-03T10:00:00+02:00"
    assert activity.summary == "Command succeeded: deploy --token=[REDACTED]"


_PASTED_PROMPT = (
    "Pulse_V2 — refonte ingestion\n"
    "Contexte : conserver le comportement actuel.\n"
    "Objectif : déplacer les fonctions pures.\n"
    "À faire : adapter les imports."
)


def test_failed_pasted_prompt_is_stored_as_placeholder_only():
    activity = normalize_activity(
        {
            "type": "terminal_finished",
            "occurred_at": "2026-07-03T10:00:00+02:00",
            "command": _PASTED_PROMPT,
            "exit_code": 127,
            "cwd": "~/project",
        }
    )

    expected = f"[prompt collé : 4 lignes, {len(_PASTED_PROMPT)} caractères]"
    assert activity.details["command"] == expected
    assert "Contexte" not in activity.summary
    assert activity.summary == f"Command failed (127): {expected}"


def test_interrupted_pasted_prompt_is_also_stored_as_placeholder_only():
    # Ctrl-C on a mis-paste ends with a signal exit (130): any non-zero
    # exit code — not just command-not-found — must trigger the policy.
    activity = normalize_activity(
        {
            "type": "terminal_finished",
            "occurred_at": "2026-07-03T12:00:00+02:00",
            "command": _PASTED_PROMPT,
            "exit_code": 130,
            "cwd": "~/project",
        }
    )

    assert activity.details["command"] == (
        f"[prompt collé : 4 lignes, {len(_PASTED_PROMPT)} caractères]"
    )
    assert "Contexte" not in activity.summary


def test_placeholder_from_producer_is_not_replaced_again():
    # The producer applies the policy before enqueueing; delivery then runs
    # the same command through normalize_activity with the same failed
    # exit_code. Without idempotence the real counts would be destroyed
    # ("[prompt collé : 4 lignes, 120 caractères]" → "… 1 ligne, 41 …").
    placeholder = "[prompt collé : 4 lignes, 120 caractères]"
    activity = normalize_activity(
        {
            "type": "terminal_finished",
            "occurred_at": "2026-07-03T10:00:00+02:00",
            "command": placeholder,
            "exit_code": 127,
            "cwd": "~/project",
        }
    )

    assert activity.details["command"] == placeholder


def test_successful_prompt_shaped_command_keeps_full_text():
    # A prompt-shaped command that succeeded (e.g. a heredoc feeding a tool)
    # is real work, not a mis-paste: its text must be preserved.
    activity = normalize_activity(
        {
            "type": "terminal_finished",
            "occurred_at": "2026-07-03T10:00:00+02:00",
            "command": _PASTED_PROMPT,
            "exit_code": 0,
            "cwd": "~/project",
        }
    )

    assert activity.details["command"] == _PASTED_PROMPT


def test_normalizes_agent_session_and_redacts_first_prompt():
    activity = normalize_activity(
        {
            "type": "agent_session",
            "occurred_at": "2026-07-03T09:00:00+00:00",
            "source_tool": "claude-code",
            "session_id": "abc-123",
            "transcript_path": "/Users/dev/.claude/projects/x/abc-123.jsonl",
            "summary_version": 1,
            "started_at": "2026-07-03T09:00:00+00:00",
            "ended_at": "2026-07-03T09:30:00+00:00",
            "user_messages": 4,
            "assistant_messages": 9,
            "git_branch": "main",
            "first_prompt": "déploie avec le token sk-abcdef1234567890XYZ",
            "workspace": "/Users/dev/Projets/Pulse",
        }
    )

    assert activity.source == "agent"
    assert activity.details["summary_version"] == 1
    assert activity.details["workspace"] == "/Users/dev/Projets/Pulse"
    # Défense en profondeur : rédigé à l'ingestion même si le producteur rédige.
    assert activity.details["first_prompt"] == "déploie avec le token [REDACTED]"
    assert activity.summary == (
        "Agent session (claude-code): déploie avec le token [REDACTED]"
    )


@pytest.mark.parametrize("bad_version", [0, -1, True, "1", None])
def test_agent_session_requires_a_positive_summary_version(bad_version):
    payload = {
        "type": "agent_session",
        "occurred_at": "2026-07-03T09:00:00+00:00",
        "source_tool": "codex",
        "session_id": "s",
        "transcript_path": "/tmp/s.jsonl",
        "summary_version": bad_version,
    }
    with pytest.raises(InvalidActivity):
        normalize_activity(payload)


def test_rejects_unknown_activity_type():
    with pytest.raises(InvalidActivity):
        normalize_activity({"type": "browser_opened"})


def test_normalizes_git_commit_activity():
    activity = normalize_activity(
        {
            "type": "git_commit",
            "occurred_at": "2026-07-03T10:00:00+02:00",
            "commit_hash": "abc1234def5678",
            "repository": "Pulse_Core",
            "git_root": "/Users/yugz/Projets/Pulse/Pulse_Core",
            "branch": "main",
            "message": "Add git commit events\n\nCloses the VS Code gap.",
            "files_changed": 3,
            "insertions": 42,
            "deletions": 5,
        }
    )

    assert activity.source == "git"
    assert activity.details == {
        "commit_hash": "abc1234def5678",
        "repository": "Pulse_Core",
        "git_root": "/Users/yugz/Projets/Pulse/Pulse_Core",
        "branch": "main",
        "message": "Add git commit events\n\nCloses the VS Code gap.",
        "files_changed": 3,
        "insertions": 42,
        "deletions": 5,
    }
    assert activity.summary == "Commit abc1234 on main: Add git commit events"


def test_normalizes_git_commit_activity_without_optional_stats():
    activity = normalize_activity(
        {
            "type": "git_commit",
            "commit_hash": "abc1234def5678",
            "repository": "Pulse_Core",
            "git_root": "/Users/yugz/Projets/Pulse/Pulse_Core",
            "branch": "main",
            "message": "Fix typo",
        }
    )

    assert "files_changed" not in activity.details
    assert "insertions" not in activity.details
    assert "deletions" not in activity.details


@pytest.mark.parametrize("missing_field", ["commit_hash", "repository", "git_root", "branch", "message"])
def test_rejects_git_commit_missing_required_field(missing_field):
    payload = {
        "type": "git_commit",
        "commit_hash": "abc1234def5678",
        "repository": "Pulse_Core",
        "git_root": "/Users/yugz/Projets/Pulse/Pulse_Core",
        "branch": "main",
        "message": "Fix typo",
    }
    del payload[missing_field]

    with pytest.raises(InvalidActivity):
        normalize_activity(payload)


@pytest.mark.parametrize("field", ["files_changed", "insertions", "deletions"])
def test_rejects_git_commit_negative_optional_stats(field):
    payload = {
        "type": "git_commit",
        "commit_hash": "abc1234def5678",
        "repository": "Pulse_Core",
        "git_root": "/Users/yugz/Projets/Pulse/Pulse_Core",
        "branch": "main",
        "message": "Fix typo",
        field: -1,
    }

    with pytest.raises(InvalidActivity):
        normalize_activity(payload)


def test_normalizes_app_activated_activity():
    activity = normalize_activity(
        {
            "type": "app_activated",
            "app": "Visual Studio Code",
        }
    )

    assert activity.source == "application"
    assert activity.details == {"app": "Visual Studio Code"}
    assert activity.summary == "Activated Visual Studio Code"


@pytest.mark.parametrize("event", ["modified", "created", "deleted"])
def test_normalizes_file_changed_activity(event):
    activity = normalize_activity(
        {
            "type": "file_changed",
            "path": "/project/daemon_v2/daily_trace.py",
            "event": event,
            "workspace": "/project",
        }
    )

    assert activity.source == "filesystem"
    assert activity.details == {
        "path": "/project/daemon_v2/daily_trace.py",
        "event": event,
        "workspace": "/project",
    }
    assert activity.summary == f"{event.capitalize()} /project/daemon_v2/daily_trace.py"


@pytest.mark.parametrize(
    "command",
    [
        "",
        "   ",
        "source ~/.zshrc",
    ],
)
def test_ignores_noisy_terminal_commands(command):
    with pytest.raises(IgnoredActivity):
        normalize_activity(
            {
                "type": "terminal_finished",
                "command": command,
                "exit_code": 0,
                "cwd": "/project",
            }
        )


@pytest.mark.parametrize(
    "command",
    [
        "curl http://127.0.0.1:5000/trace/today",
        "curl http://127.0.0.1:5000/trace/today.md",
        "curl -s http://127.0.0.1:5000/trace/days | python -m json.tool",
    ],
)
def test_keeps_pulse_inspection_commands_in_raw_activity(command):
    activity = normalize_activity(
        {
            "type": "terminal_finished",
            "command": command,
            "exit_code": 0,
            "cwd": "/project",
        }
    )

    assert activity.details["command"] == command


def test_removes_ignored_lines_from_multiline_command():
    activity = normalize_activity(
        {
            "type": "terminal_finished",
            "command": "clear\ngit status",
            "exit_code": 0,
            "cwd": "/project",
        }
    )

    assert activity.details["command"] == "git status"


def test_keeps_useful_lines_before_multiline_internal_curl():
    activity = normalize_activity(
        {
            "type": "terminal_finished",
            "command": (
                "git status\n"
                "curl -X POST http://127.0.0.1:5000/activities \\\n"
                "  -H 'Content-Type: application/json' \\\n"
                "  -d '{\n"
                '    \"type\": \"file_changed\"\n'
                "  }'"
            ),
            "exit_code": 0,
            "cwd": "/project",
        }
    )

    assert activity.details["command"] == "git status"


def canonical_payload(**overrides):
    payload = {
        "event_id": "019c-valid",
        "schema_version": 1,
        "type": "file_changed",
        "producer": {
            "name": "pulse-test",
            "version": "1.0",
            "instance_id": "test-instance",
        },
        "occurred_at": "2026-07-23T14:32:10.123+02:00",
        "details": {
            "path": "/project/main.py",
            "event": "modified",
        },
    }
    payload.update(overrides)
    return payload


def test_normalizes_complete_canonical_event():
    ingested = normalize_event(canonical_payload(unused_top_level="ignored"))

    assert ingested.event.event_id == "019c-valid"
    assert ingested.event.schema_version == 1
    assert ingested.event.producer_name == "pulse-test"
    assert ingested.event.occurred_at.isoformat() == "2026-07-23T14:32:10.123000+02:00"
    assert ingested.activity.details == {
        "path": "/project/main.py",
        "event": "modified",
    }
    assert "unused_top_level" not in ingested.activity.details


def test_preserves_enriched_terminal_context_sent_by_producer():
    workspace = {
        "project_name": "Pulse_Core",
        "workspace_root": "/project/Pulse_Core",
        "git_root": "/project/Pulse_Core",
        "resolution_method": "git",
        "resolution_confidence": "high",
    }
    git = {
        "repository": "Pulse_Core",
        "git_root": "/project/Pulse_Core",
        "branch": "main",
        "head": "1234567",
        "dirty": False,
        "staged": 0,
        "unstaged": 0,
        "untracked": 0,
    }
    ingested = normalize_event(
        canonical_payload(
            type="terminal_finished",
            details={
                "command": "git status",
                "exit_code": 0,
                "cwd": "/project/Pulse_Core",
                "workspace": workspace,
                "git": git,
            },
        )
    )

    assert ingested.activity.details["workspace"] == workspace
    assert ingested.activity.details["git"] == git


def test_preserves_object_workspace_for_file_event():
    workspace = {
        "project_name": "Pulse_Core",
        "workspace_root": "/project/Pulse_Core",
    }
    ingested = normalize_event(
        canonical_payload(
            details={
                "path": "/project/Pulse_Core/main.py",
                "event": "modified",
                "workspace": workspace,
            }
        )
    )

    assert ingested.activity.details["workspace"] == workspace


def test_preserves_historical_direct_git_root():
    ingested = normalize_event(
        canonical_payload(
            details={
                "path": "/project/Pulse_Core/main.py",
                "event": "modified",
                "git_root": "/project/Pulse_Core",
            }
        )
    )

    assert ingested.activity.details["git_root"] == "/project/Pulse_Core"


def test_preserves_application_bundle_identifier():
    ingested = normalize_event(
        canonical_payload(
            type="app_activated",
            details={
                "app": "Visual Studio Code",
                "bundle_id": "com.microsoft.VSCode",
            },
        )
    )

    assert ingested.activity.details == {
        "app": "Visual Studio Code",
        "bundle_id": "com.microsoft.VSCode",
    }


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"event_id": None}, "event_id"),
        ({"event_id": ""}, "event_id"),
        ({"schema_version": 0}, "schema_version"),
        ({"schema_version": -1}, "schema_version"),
        ({"type": ""}, "type"),
        ({"producer": None}, "producer"),
        ({"producer": {"name": ""}}, "producer.name"),
        ({"occurred_at": "2026-07-23T14:32:10"}, "occurred_at"),
        ({"occurred_at": "not-a-date"}, "occurred_at"),
        ({"details": []}, "details"),
    ],
)
def test_rejects_invalid_canonical_fields(change, field):
    with pytest.raises(InvalidActivity) as raised:
        normalize_event(canonical_payload(**change))

    assert raised.value.field == field


def test_rejects_missing_event_id_on_otherwise_canonical_payload():
    payload = canonical_payload()
    del payload["event_id"]

    with pytest.raises(InvalidActivity) as raised:
        normalize_event(payload)

    assert raised.value.field == "event_id"


def test_legacy_timestamp_becomes_occurred_at_and_gets_explicit_producer():
    ingested = normalize_event(
        {
            "type": "app_activated",
            "timestamp": "2026-07-23T12:00:00+02:00",
            "app": "Terminal",
        }
    )

    assert ingested.legacy is True
    assert ingested.event.event_id
    assert ingested.event.schema_version == 1
    assert ingested.event.producer_name == "pulse-legacy"
    assert ingested.event.occurred_at.isoformat() == "2026-07-23T12:00:00+02:00"


def test_identical_legacy_requests_receive_different_event_ids():
    payload = {"type": "app_activated", "app": "Terminal"}

    first = normalize_event(payload)
    second = normalize_event(payload)

    assert first.event.event_id != second.event.event_id


def test_rejects_nan_in_canonical_details():
    with pytest.raises(InvalidActivity) as raised:
        normalize_event(
            canonical_payload(
                details={
                    "path": "/project/main.py",
                    "event": "modified",
                    "invalid_number": float("nan"),
                }
            )
        )

    assert raised.value.field == "details"
    assert "strictly valid JSON" in str(raised.value)


def session_summary_payload(**overrides):
    payload = {
        "type": "session_summary",
        "occurred_at": "2026-09-02T15:55:00+00:00",
        "session_id": "0123456789abcdef",
        "source_event_ids_hash": "0123456789abcdef",
        "session_label": "work-3",
        "session_started_at": "2026-09-02T13:02:00+00:00",
        "session_ended_at": "2026-09-02T15:55:00+00:00",
        "prompt_version": "v1",
        "model_id": "mlx-community/test-model",
        "generated_at": "2026-09-02T16:30:00+00:00",
        "generation_ms": 4210,
        "input_context_hash": "abc123",
        "reprise": {
            "doing": "Tu implémentais le Context API de Core.\nDeuxième ligne.",
            "stopped_at": "Tu venais de pousser la branche ship/context-api.",
            "open": "La PR attend ta relecture.",
        },
        "structured": {
            "project": "Pulse",
            "intents": ["livrer le pas 2"],
            "central_files": ["core/daemon_v2/context_snapshot.py"],
            "blockers": [],
            "confidence": "high",
        },
        "workspace": "/Users/dev/Projets/Pulse",
    }
    payload.update(overrides)
    return payload


def test_normalizes_session_summary_and_keeps_the_rest_as_is():
    activity = normalize_activity(session_summary_payload())

    assert activity.source == "intelligence"
    # Le summary de l'Activity est la première ligne de la reprise.
    assert activity.summary == "Tu implémentais le Context API de Core."
    assert activity.details["session_id"] == "0123456789abcdef"
    assert activity.details["source_event_ids_hash"] == "0123456789abcdef"
    assert activity.details["session_label"] == "work-3"
    assert activity.details["prompt_version"] == "v1"
    assert activity.details["model_id"] == "mlx-community/test-model"
    assert activity.details["workspace"] == "/Users/dev/Projets/Pulse"
    assert activity.details["reprise"]["open"] == "La PR attend ta relecture."
    assert activity.details["structured"]["confidence"] == "high"
    # Le reste passe tel quel.
    assert activity.details["generation_ms"] == 4210
    assert activity.details["input_context_hash"] == "abc123"
    assert activity.details["session_ended_at"] == "2026-09-02T15:55:00+00:00"
    assert "type" not in activity.details and "occurred_at" not in activity.details


def test_session_summary_reprise_is_redacted_in_depth():
    activity = normalize_activity(
        session_summary_payload(
            reprise={
                "doing": "Tu testais l'API avec le jeton sk-abcdef1234567890XYZ.",
                "stopped_at": "—",
                "open": "—",
            }
        )
    )

    assert activity.details["reprise"]["doing"] == (
        "Tu testais l'API avec le jeton [REDACTED]."
    )
    assert activity.summary == "Tu testais l'API avec le jeton [REDACTED]."


def test_session_summary_structured_lists_are_redacted_element_by_element():
    activity = normalize_activity(
        session_summary_payload(
            structured={
                "project": "Pulse",
                "intents": ["déployer avec le jeton sk-abcdef1234567890XYZ", "tester"],
                "central_files": ["core/daemon_v2/ingest.py", "docs/VISION.md"],
                "blockers": ["export API_TOKEN=abc123 refusé par la CI"],
                "confidence": "medium",
            }
        )
    )

    structured = activity.details["structured"]
    assert structured["intents"] == ["déployer avec le jeton [REDACTED]", "tester"]
    assert structured["blockers"] == ["export API_TOKEN=[REDACTED] refusé par la CI"]
    # Un chemin normal reste intact.
    assert structured["central_files"] == ["core/daemon_v2/ingest.py", "docs/VISION.md"]
    assert structured["project"] == "Pulse" and structured["confidence"] == "medium"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"session_id": ""}, "session_id"),
        ({"session_id": "2026-09-02/work-3"}, "details.session_id"),
        ({"session_id": "0123456789ABCDEF"}, "details.session_id"),
        ({"source_event_ids_hash": None}, "source_event_ids_hash"),
        ({"source_event_ids_hash": "fedcba9876543210"}, "details.source_event_ids_hash"),
        ({"session_label": ""}, "details.session_label"),
        ({"prompt_version": None}, "prompt_version"),
        ({"model_id": "  "}, "model_id"),
        ({"reprise": "texte"}, "details.reprise"),
        (
            {"reprise": {"doing": "x", "stopped_at": "y"}},
            "details.reprise.open",
        ),
        (
            {"reprise": {"doing": "", "stopped_at": "y", "open": "z"}},
            "details.reprise.doing",
        ),
        ({"structured": None}, "details.structured"),
        ({"structured": {"project": 3, "confidence": "high"}}, "details.structured.project"),
        ({"structured": {"project": None, "confidence": "sure"}}, "details.structured.confidence"),
        ({"structured": {"project": "Pulse"}}, "details.structured.confidence"),
    ],
)
def test_session_summary_rejects_incomplete_contract(overrides, field):
    with pytest.raises(InvalidActivity) as raised:
        normalize_activity(session_summary_payload(**overrides))

    assert raised.value.field == field


def test_unknown_schema_version_is_rejected_not_read_as_version_one():
    with pytest.raises(InvalidActivity) as raised:
        normalize_event(canonical_payload(schema_version=2))

    assert raised.value.field == "schema_version"
    assert "one of: 1" in str(raised.value)

    accepted = normalize_event(canonical_payload(schema_version=1))
    assert accepted.event.schema_version == 1

    legacy = normalize_event(
        {
            "type": "file_changed",
            "occurred_at": "2026-07-03T09:00:00+00:00",
            "path": "/project/main.py",
        }
    )
    assert legacy.legacy is True and legacy.event.schema_version == 1


# --- champs réservés de l'enveloppe dans details (audit 2026-09-06, défaut 8) ---


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        # Scénario de l'audit : le type de l'enveloppe est invalide, mais
        # details.type le remplaçait silencieusement.
        (
            {"type": "unsupported", "details": {"app": "Synthetic App", "type": "app_activated"}},
            "details.type",
        ),
        # Enveloppe valide : la collision est refusée pour elle-même.
        (
            {
                "details": {
                    "path": "/project/main.py",
                    "event": "modified",
                    "occurred_at": "2020-01-01T00:00:00+00:00",
                }
            },
            "details.occurred_at",
        ),
    ],
)
def test_reserved_envelope_fields_inside_details_are_refused(overrides, field):
    """Un `details.type` ne doit jamais remplacer le `type` de l'enveloppe :
    la collision est refusée avant la fusion, avec le champ nommé."""
    with pytest.raises(InvalidActivity) as raised:
        normalize_event(canonical_payload(**overrides))

    assert raised.value.field == field
    assert field.split(".")[1] in str(raised.value)
