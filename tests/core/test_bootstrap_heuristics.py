from daemon.core.bootstrap_heuristics import (
    BOOTSTRAP_AI_APPS,
    BOOTSTRAP_DEV_APPS,
    BOOTSTRAP_NON_WORK_TITLE_HINTS,
    BOOTSTRAP_SELF_APPS,
    BOOTSTRAP_WORK_APPS,
    BOOTSTRAP_WRITING_APPS,
)
from daemon.core.signal_scorer import SignalScorer
from daemon.core.work_evidence_resolver import WorkEvidenceInput, resolve_work_evidence
from daemon.memory.work_heartbeat import (
    AI_APPS,
    NON_WORK_TITLE_HINTS,
    WORK_APPS,
    classify_work_heartbeat,
)


def test_bootstrap_ai_apps_are_shared_by_consumers():
    assert {"ChatGPT", "Claude", "Claude Desktop", "Codex"}.issubset(BOOTSTRAP_AI_APPS)
    assert AI_APPS is BOOTSTRAP_AI_APPS
    assert SignalScorer.AI_APPS is BOOTSTRAP_AI_APPS

    resolution = resolve_work_evidence(WorkEvidenceInput(active_app="Claude Desktop", recent_apps=("Codex",)))

    assert resolution.support_apps == ("Codex", "Claude Desktop")


def test_bootstrap_work_dev_and_writing_apps_are_available_to_scorer_and_heartbeat():
    assert {"Code", "Visual Studio Code", "Xcode", "Cursor", "Terminal", "iTerm2"}.issubset(
        BOOTSTRAP_WORK_APPS
    )
    assert {"Xcode", "VSCode", "WebStorm", "PyCharm", "Warp"}.issubset(BOOTSTRAP_DEV_APPS)
    assert {"Notion", "Obsidian", "Bear", "Notes", "Pages"}.issubset(BOOTSTRAP_WRITING_APPS)
    assert WORK_APPS is BOOTSTRAP_WORK_APPS
    assert SignalScorer.DEV_APPS is BOOTSTRAP_DEV_APPS
    assert SignalScorer.WRITING_APPS is BOOTSTRAP_WRITING_APPS


def test_bootstrap_self_apps_are_centralized_for_signal_scorer():
    assert {"Pulse", "PulseApp"}.issubset(BOOTSTRAP_SELF_APPS)
    assert SignalScorer.SELF_APPS is BOOTSTRAP_SELF_APPS


def test_bootstrap_non_work_title_hints_are_shared_with_work_heartbeat():
    assert {"youtube", "netflix", "spotify"}.issubset(BOOTSTRAP_NON_WORK_TITLE_HINTS)
    assert NON_WORK_TITLE_HINTS is BOOTSTRAP_NON_WORK_TITLE_HINTS


def test_bootstrap_catalog_preserves_heartbeat_app_behaviors():
    ai_heartbeat = classify_work_heartbeat({"type": "app_activated", "payload": {"app_name": "ChatGPT"}})
    work_heartbeat = classify_work_heartbeat({"type": "app_activated", "payload": {"app_name": "Xcode"}})
    non_work_heartbeat = classify_work_heartbeat(
        {
            "type": "window_title_poll",
            "payload": {"app_name": "Google Chrome", "title": "Demo - YouTube"},
        }
    )

    assert ai_heartbeat.strength == "weak"
    assert ai_heartbeat.reason == "ai_app_active"
    assert work_heartbeat.strength == "weak"
    assert work_heartbeat.reason == "work_app_active"
    assert non_work_heartbeat.strength == "none"
