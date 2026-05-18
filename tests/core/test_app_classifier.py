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


def test_classify_app_supports_ai_assistant_bundle_fixture():
    classification = classify_app(
        "RandomAssistant",
        bundle_id="dev.pulse.test.UnknownAI",
    )

    assert classification.role == "ai_assistant"
    assert classification.role_source == "bootstrap_bundle"


def test_classify_app_supports_tool_assistant_bundle_fixture_as_ai_role():
    classification = classify_app(
        "RandomToolAssistant",
        bundle_id="dev.pulse.test.ToolAssistant",
    )

    assert classification.role == "ai_assistant"
    assert classification.role_source == "bootstrap_bundle"


def test_bundle_id_has_priority_over_app_name():
    classification = classify_app(
        "Safari",
        bundle_id="dev.pulse.test.UnknownIDE",
    )

    assert classification.role == "dev_tool"
    assert classification.role_source == "bootstrap_bundle"


def test_classify_app_uses_system_category_as_fallback_for_developer_tools():
    classification = classify_app(
        "RandomIDE",
        bundle_id="com.example.random",
        system_category="public.app-category.developer-tools",
    )

    assert classification.role == "dev_tool"
    assert classification.role_source == "system_category"
    assert classification.confidence == 0.60
    assert classification.system_category == "public.app-category.developer-tools"


def test_classify_app_name_beats_system_category():
    classification = classify_app(
        "Safari",
        system_category="public.app-category.developer-tools",
    )

    assert classification.role == "browser"
    assert classification.role_source == "bootstrap_name"


def test_classify_app_bundle_beats_system_category():
    classification = classify_app(
        "RandomBrowser",
        bundle_id="com.apple.Safari",
        system_category="public.app-category.developer-tools",
    )

    assert classification.role == "browser"
    assert classification.role_source == "bootstrap_bundle"


def test_classify_app_utilities_category_stays_unknown_without_name_or_bundle():
    classification = classify_app(
        "RandomUtility",
        bundle_id="com.example.random",
        system_category="public.app-category.utilities",
    )

    assert classification.role == "unknown"
    assert classification.role_source == "unknown"


def test_classify_app_productivity_category_stays_unknown_without_name_or_bundle():
    classification = classify_app(
        "RandomProductivity",
        bundle_id="com.example.random",
        system_category="public.app-category.productivity",
    )

    assert classification.role == "unknown"
    assert classification.role_source == "unknown"
