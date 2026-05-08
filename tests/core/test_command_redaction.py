from daemon.core.command_redaction import redact_sensitive_command


def test_redact_sensitive_command_masks_required_secret_patterns():
    command = (
        "curl -H 'Authorization: Bearer bearer-secret' "
        "API_KEY=api-secret TOKEN=token-secret SECRET=secret-value "
        "PASSWORD=password-value password=lowercase-password "
        "--token flag-token --password flag-password "
        "postgres://user:pass@localhost/db mysql://user:pass@localhost/db"
    )

    redacted = redact_sensitive_command(command)

    assert "Authorization: Bearer [REDACTED_TOKEN]" in redacted
    assert "API_KEY=[REDACTED_SECRET]" in redacted
    assert "TOKEN=[REDACTED_SECRET]" in redacted
    assert "SECRET=[REDACTED_SECRET]" in redacted
    assert "PASSWORD=[REDACTED_SECRET]" in redacted
    assert "password=[REDACTED_SECRET]" in redacted
    assert "--token [REDACTED_SECRET]" in redacted
    assert "--password [REDACTED_SECRET]" in redacted
    assert "postgres://user:[REDACTED_PASSWORD]@localhost/db" in redacted
    assert "mysql://user:[REDACTED_PASSWORD]@localhost/db" in redacted
    assert "api-secret" not in redacted
    assert "flag-token" not in redacted
    assert "pass@localhost" not in redacted


def test_redact_sensitive_command_keeps_safe_commands_readable():
    command = "python -m pytest tests/test_runtime_lifecycle.py"

    assert redact_sensitive_command(command) == command


def test_redact_sensitive_command_truncates_long_commands():
    redacted = redact_sensitive_command("echo " + "x" * 40, max_chars=12)

    assert redacted == "echo xxxxxxx…"
