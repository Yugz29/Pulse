from daemon.core.context_probe_redaction import (
    ContextProbeRedactionFlag,
    redact_context_probe_value,
    redact_context_probe_values,
)


def test_redact_empty_value():
    result = redact_context_probe_value(None)

    assert result.redacted_value == ""
    assert result.original_length == 0
    assert result.redacted_length == 0
    assert result.flags == (ContextProbeRedactionFlag.EMPTY,)
    assert result.was_redacted is True


def test_redact_email_url_and_home_path():
    result = redact_context_probe_value(
        "Contact yugz@example.com at https://example.com/private from /Users/yugz/Projects/Pulse"
    )

    assert result.redacted_value == "Contact [REDACTED_EMAIL] at [REDACTED_URL] from /Users/[REDACTED_USER]/Projects/Pulse"
    assert result.flags == (
        ContextProbeRedactionFlag.EMAIL,
        ContextProbeRedactionFlag.URL,
        ContextProbeRedactionFlag.HOME_PATH,
    )
    assert "yugz@example.com" not in result.redacted_value
    assert "https://example.com/private" not in result.redacted_value
    assert "/Users/yugz" not in result.redacted_value


def test_redact_common_tokens():
    result = redact_context_probe_value(
        "token sk-abcdefghijklmnopqrstuvwxyz123456 and ghp_abcdefghijklmnopqrstuvwxyz123456"
    )

    assert result.redacted_value == "token [REDACTED_TOKEN] and [REDACTED_TOKEN]"
    assert result.flags == (ContextProbeRedactionFlag.TOKEN,)
    assert "sk-" not in result.redacted_value
    assert "ghp_" not in result.redacted_value


def test_redact_env_secret():
    result = redact_context_probe_value("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456")

    assert result.redacted_value == "OPENAI_API_KEY=[REDACTED_SECRET]"
    assert result.flags == (ContextProbeRedactionFlag.ENV_SECRET,)
    assert "sk-" not in result.redacted_value


def test_redact_openssh_private_key():
    raw = """-----BEGIN OPENSSH PRIVATE KEY-----
secret-key-content
-----END OPENSSH PRIVATE KEY-----"""

    result = redact_context_probe_value(raw)

    assert result.redacted_value == "[REDACTED_SSH_PRIVATE_KEY]"
    assert result.flags == (ContextProbeRedactionFlag.SSH_KEY,)
    assert "secret-key-content" not in result.redacted_value


def test_redact_pkcs8_private_key_without_algorithm_prefix():
    raw = """-----BEGIN PRIVATE KEY-----
secret-key-content
-----END PRIVATE KEY-----"""

    result = redact_context_probe_value(raw)

    assert result.redacted_value == "[REDACTED_SSH_PRIVATE_KEY]"
    assert result.flags == (ContextProbeRedactionFlag.SSH_KEY,)
    assert "secret-key-content" not in result.redacted_value


def test_redact_private_key_inside_untrusted_long_value_without_regex_backtracking():
    raw = (
        "before "
        "-----BEGIN RSA PRIVATE KEY-----\n"
        + ("secret-key-content\n" * 200)
        + "-----END RSA PRIVATE KEY-----"
        " after"
    )

    result = redact_context_probe_value(raw, max_chars=1000)

    assert result.redacted_value == "before [REDACTED_SSH_PRIVATE_KEY] after"
    assert result.flags == (ContextProbeRedactionFlag.SSH_KEY,)
    assert "secret-key-content" not in result.redacted_value


def test_unclosed_private_key_marker_on_long_value_is_truncated_without_ssh_flag():
    raw = "-----BEGIN PRIVATE KEY-----\n" + ("x " * 2500)

    result = redact_context_probe_value(raw, max_chars=80)

    assert result.redacted_value.startswith("-----BEGIN PRIVATE KEY-----")
    assert result.redacted_value.endswith("…")
    assert result.flags == (ContextProbeRedactionFlag.TRUNCATED,)


def test_long_untrusted_value_is_bounded_before_regex_scan():
    raw = ("safe " * 900) + "TOKEN=secret-after-limit"

    result = redact_context_probe_value(raw, max_chars=-1)

    assert result.redacted_value.endswith("…")
    assert "secret-after-limit" not in result.redacted_value
    assert result.flags == (ContextProbeRedactionFlag.TRUNCATED,)


def test_long_untrusted_value_still_redacts_secret_before_bound():
    raw = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456 " + ("safe " * 900)

    result = redact_context_probe_value(raw, max_chars=120)

    assert "sk-" not in result.redacted_value
    assert result.redacted_value.startswith("OPENAI_API_KEY=[REDACTED_SECRET]")
    assert result.flags == (
        ContextProbeRedactionFlag.ENV_SECRET,
        ContextProbeRedactionFlag.TRUNCATED,
    )


def test_redact_truncates_long_value_after_redaction():
    result = redact_context_probe_value("hello " + "x" * 20, max_chars=10)

    assert result.redacted_value == "hello xxxx…"
    assert result.flags == (ContextProbeRedactionFlag.TRUNCATED,)
    assert result.was_redacted is True
    assert result.original_length == 26
    assert result.redacted_length == 11


def test_redact_preserves_safe_short_value_without_flags():
    result = redact_context_probe_value("normal window title", max_chars=100)

    assert result.redacted_value == "normal window title"
    assert result.flags == ()
    assert result.was_redacted is False


def test_redaction_result_to_dict_is_json_ready():
    result = redact_context_probe_value("hello yugz@example.com")

    assert result.to_dict() == {
        "redacted_value": "hello [REDACTED_EMAIL]",
        "original_length": 22,
        "redacted_length": 22,
        "flags": ["email"],
        "was_redacted": True,
    }


def test_redact_context_probe_values_batch():
    results = redact_context_probe_values(
        ["yugz@example.com", "https://example.com", "safe"],
        max_chars=100,
    )

    assert [result.redacted_value for result in results] == [
        "[REDACTED_EMAIL]",
        "[REDACTED_URL]",
        "safe",
    ]
    assert [result.flags for result in results] == [
        (ContextProbeRedactionFlag.EMAIL,),
        (ContextProbeRedactionFlag.URL,),
        (),
    ]


def test_redaction_flags_are_deduplicated_in_order():
    result = redact_context_probe_value("a@example.com b@example.com https://a.test https://b.test")

    assert result.flags == (
        ContextProbeRedactionFlag.EMAIL,
        ContextProbeRedactionFlag.URL,
    )
