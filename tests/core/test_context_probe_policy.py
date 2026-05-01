

from daemon.core.context_probe_policy import (
    ContextProbeConsent,
    ContextProbeKind,
    policy_for_probe,
    is_probe_allowed_by_default,
)
from daemon.core.event_envelope import PulsePrivacyClass, PulseRetention


def test_app_context_policy_is_session_metadata():
    policy = policy_for_probe(ContextProbeKind.APP_CONTEXT)

    assert policy.kind is ContextProbeKind.APP_CONTEXT
    assert policy.consent is ContextProbeConsent.IMPLICIT_SESSION
    assert policy.privacy is PulsePrivacyClass.PUBLIC
    assert policy.retention is PulseRetention.SESSION
    assert policy.allow_raw_value is False
    assert policy.allow_persistent_storage is False
    assert policy.requires_user_visible_reason is True
    assert policy.max_chars == 256
    assert is_probe_allowed_by_default(ContextProbeKind.APP_CONTEXT) is True


def test_window_title_policy_is_path_sensitive_session_metadata():
    policy = policy_for_probe("window_title")

    assert policy.kind is ContextProbeKind.WINDOW_TITLE
    assert policy.consent is ContextProbeConsent.IMPLICIT_SESSION
    assert policy.privacy is PulsePrivacyClass.PATH_SENSITIVE
    assert policy.retention is PulseRetention.SESSION
    assert policy.allow_raw_value is False
    assert policy.allow_persistent_storage is False
    assert policy.max_chars == 256
    assert is_probe_allowed_by_default("window_title") is True


def test_selected_text_policy_requires_explicit_each_time_and_is_ephemeral():
    policy = policy_for_probe(ContextProbeKind.SELECTED_TEXT)

    assert policy.kind is ContextProbeKind.SELECTED_TEXT
    assert policy.consent is ContextProbeConsent.EXPLICIT_EACH_TIME
    assert policy.privacy is PulsePrivacyClass.CONTENT_SENSITIVE
    assert policy.retention is PulseRetention.EPHEMERAL
    assert policy.allow_raw_value is False
    assert policy.allow_persistent_storage is False
    assert policy.max_chars == 2_000
    assert is_probe_allowed_by_default(ContextProbeKind.SELECTED_TEXT) is False


def test_clipboard_sample_policy_requires_explicit_each_time_and_is_ephemeral():
    policy = policy_for_probe(ContextProbeKind.CLIPBOARD_SAMPLE)

    assert policy.kind is ContextProbeKind.CLIPBOARD_SAMPLE
    assert policy.consent is ContextProbeConsent.EXPLICIT_EACH_TIME
    assert policy.privacy is PulsePrivacyClass.CONTENT_SENSITIVE
    assert policy.retention is PulseRetention.EPHEMERAL
    assert policy.allow_raw_value is False
    assert policy.allow_persistent_storage is False
    assert policy.max_chars == 1_000
    assert is_probe_allowed_by_default(ContextProbeKind.CLIPBOARD_SAMPLE) is False


def test_screen_snapshot_policy_requires_explicit_each_time_and_is_ephemeral():
    policy = policy_for_probe(ContextProbeKind.SCREEN_SNAPSHOT)

    assert policy.kind is ContextProbeKind.SCREEN_SNAPSHOT
    assert policy.consent is ContextProbeConsent.EXPLICIT_EACH_TIME
    assert policy.privacy is PulsePrivacyClass.CONTENT_SENSITIVE
    assert policy.retention is PulseRetention.EPHEMERAL
    assert policy.allow_raw_value is False
    assert policy.allow_persistent_storage is False
    assert policy.max_chars is None
    assert is_probe_allowed_by_default(ContextProbeKind.SCREEN_SNAPSHOT) is False


def test_unknown_probe_policy_is_blocked_debug_only():
    policy = policy_for_probe("not_a_probe")

    assert policy.kind is ContextProbeKind.UNKNOWN
    assert policy.consent is ContextProbeConsent.BLOCKED
    assert policy.privacy is PulsePrivacyClass.UNKNOWN
    assert policy.retention is PulseRetention.DEBUG_ONLY
    assert policy.allow_raw_value is False
    assert policy.allow_persistent_storage is False
    assert policy.max_chars is None
    assert is_probe_allowed_by_default("not_a_probe") is False


def test_context_probe_policy_to_dict_is_json_ready():
    policy = policy_for_probe(ContextProbeKind.SELECTED_TEXT)

    assert policy.to_dict() == {
        "kind": "selected_text",
        "consent": "explicit_each_time",
        "privacy": "content_sensitive",
        "retention": "ephemeral",
        "allow_raw_value": False,
        "allow_persistent_storage": False,
        "requires_user_visible_reason": True,
        "max_chars": 2000,
    }