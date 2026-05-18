from daemon.core.app_classifier import classify_app


def test_classify_app_prefers_bundle_id_over_name():
    classification = classify_app(
        "RandomIDE",
        bundle_id="dev.pulse.test.UnknownIDE",
    )

    assert classification.role == "dev_tool"
    assert classification.role_source == "bootstrap_bundle"
    assert classification.confidence == 0.95


def test_classify_app_falls_back_to_bootstrap_name():
    classification = classify_app("Cursor")

    assert classification.role == "dev_tool"
    assert classification.role_source == "bootstrap_name"
    assert classification.confidence == 0.80


def test_classify_app_unknown_when_no_match():
    classification = classify_app("RandomApp", bundle_id="com.example.random")

    assert classification.role == "unknown"
    assert classification.role_source == "unknown"
    assert classification.confidence == 0.0


def test_bundle_id_has_priority_over_app_name():
    classification = classify_app(
        "Safari",
        bundle_id="dev.pulse.test.UnknownIDE",
    )

    assert classification.role == "dev_tool"
    assert classification.role_source == "bootstrap_bundle"
