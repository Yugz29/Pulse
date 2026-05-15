from daemon.core.work_evidence_resolver import WorkEvidenceInput, resolve_work_evidence


def test_resolver_active_project_alone_gives_strong_project():
    resolution = resolve_work_evidence(WorkEvidenceInput(active_project="AlphaApp"))

    assert resolution.project == "AlphaApp"
    assert resolution.project_confidence >= 0.8
    assert resolution.project_source == "active_project"
    assert "Projet explicite détecté" in resolution.evidence


def test_resolver_basename_only_files_do_not_attribute_project():
    resolution = resolve_work_evidence(WorkEvidenceInput(file_paths=("service.py", "test_service.py")))

    assert resolution.project is None
    assert resolution.project_confidence == 0.0
    assert "basename_only_insufficient" in resolution.warnings


def test_resolver_window_title_alone_does_not_attribute_project():
    resolution = resolve_work_evidence(WorkEvidenceInput(window_title="AlphaApp — service.py — Code"))

    assert resolution.project is None
    assert resolution.project_confidence == 0.0
    assert "window_title_only" in resolution.warnings


def test_resolver_ai_app_alone_does_not_attribute_project():
    resolution = resolve_work_evidence(WorkEvidenceInput(active_app="ChatGPT", recent_apps=("Codex",)))

    assert resolution.project is None
    assert resolution.project_confidence == 0.0
    assert resolution.support_apps == ("Codex", "ChatGPT")
    assert "ai_app_only" in resolution.warnings


def test_resolver_ai_apps_are_support_when_terminal_and_intent_correlate():
    resolution = resolve_work_evidence(
        WorkEvidenceInput(
            terminal_cwd="/tmp/workspace/AlphaApp",
            terminal_command_category="testing",
            work_intent_project="AlphaApp",
            active_app="ChatGPT",
            recent_apps=("Codex", "Code"),
        )
    )

    assert resolution.project == "AlphaApp"
    assert resolution.project_confidence >= 0.8
    assert resolution.project_source == "terminal_cwd"
    assert resolution.support_apps == ("Codex", "ChatGPT")
    assert "Intention de travail cohérente avec le terminal" in resolution.evidence
    assert "Apps IA utilisées comme support" in resolution.evidence
