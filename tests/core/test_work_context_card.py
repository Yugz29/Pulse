from types import SimpleNamespace

from daemon.core.work_context_card import WorkContextCard, build_work_context_card


def test_build_work_context_card_from_current_context_and_signals():
    current_context = SimpleNamespace(
        active_project="Pulse",
        activity_level="editing",
        probable_task="debug",
        task_confidence=0.78,
        active_app="Code",
    )
    signals = SimpleNamespace(
        window_title="Pulse — work_context_card.py — Visual Studio Code",
        edited_file_count_10m=3,
        recent_apps=["Code", "Terminal", "ChatGPT"],
    )

    card = build_work_context_card(current_context, signals=signals)

    assert card.project == "Pulse"
    assert card.project_hint is None
    assert card.project_hint_confidence == 0.0
    assert card.project_hint_source is None
    assert card.activity_level == "editing"
    assert card.probable_task == "debug"
    assert card.confidence == 0.78
    assert card.project_status == "observed"
    assert card.task_status == "probable"
    assert card.evidence == (
        "Projet actif observé : Pulse",
        "Niveau d'activité : editing",
        "Tâche probable : debug",
        "Application active : Code",
        "Titre de fenêtre disponible",
        "Fichiers modifiés récemment : 3",
        "Applications récentes : Code, Terminal, ChatGPT",
    )
    assert card.missing_context == ()
    assert card.safe_next_probes == ()


def test_build_work_context_card_exposes_work_intent_separately_from_probable_task():
    current_context = SimpleNamespace(
        active_project="Pulse",
        activity_level="editing",
        probable_task="coding",
        task_confidence=0.7,
        work_intent={
            "summary": "réduire les coûts cachés du modèle local",
            "source": "manual",
            "confidence": 0.9,
            "project": "Pulse",
            "evidence_refs": ["commit_message"],
        },
    )

    card = build_work_context_card(current_context)

    assert card.probable_task == "coding"
    assert card.work_intent["summary"] == "réduire les coûts cachés du modèle local"
    assert "Objectif de travail : réduire les coûts cachés du modèle local" in card.evidence
    payload = card.to_dict()
    assert payload["work_intent"]["source"] == "manual"
    assert "window_title" not in payload["work_intent"]
    assert "clipboard" not in payload["work_intent"]
    assert "conversation" not in payload["work_intent"]


def test_build_work_context_card_falls_back_to_present():
    current_context = SimpleNamespace(
        active_project=None,
        activity_level=None,
        probable_task=None,
        task_confidence=None,
    )
    present = SimpleNamespace(
        active_project="DevNote",
        activity_level="reading",
        probable_task="review",
        task_confidence=0.63,
        active_app="Safari",
    )
    signals = SimpleNamespace(window_title=None, recent_apps=[])

    card = build_work_context_card(current_context, present=present, signals=signals)

    assert card.project == "DevNote"
    assert card.activity_level == "reading"
    assert card.probable_task == "review"
    assert card.confidence == 0.63
    assert card.project_status == "observed"
    assert card.task_status == "inferred"
    assert "Projet actif observé : DevNote" in card.evidence
    assert "Tâche inférée : review" in card.evidence
    assert "Application active : Safari" in card.evidence
    assert "Titre de fenêtre non disponible" in card.missing_context
    assert card.safe_next_probes == ("window_title",)


def test_build_work_context_card_reports_missing_context_when_uncertain():
    current_context = SimpleNamespace(
        active_project=None,
        activity_level="unknown",
        probable_task="general",
        active_app=None,
    )
    signals = SimpleNamespace(
        window_title=None,
        terminal_active=True,
        recent_apps=[],
    )

    card = build_work_context_card(current_context, signals=signals)

    assert card.project is None
    assert card.activity_level == "unknown"
    assert card.probable_task == "general"
    assert card.confidence == 0.0
    assert card.project_status == "unknown"
    assert card.task_status == "unknown"
    assert card.evidence == ()
    assert card.missing_context == (
        "Projet actif non identifié",
        "Tâche utilisateur encore générale",
        "Niveau d'activité incertain",
        "Titre de fenêtre non disponible",
        "Terminal actif sans commande récente lisible",
    )
    assert card.safe_next_probes == ("app_context", "window_title")


def test_build_work_context_card_does_not_report_terminal_missing_when_commands_are_known():
    current_context = SimpleNamespace(
        active_project="Pulse",
        activity_level="executing",
        probable_task="test",
        recent_terminal_commands=["python -m pytest"],
    )
    signals = SimpleNamespace(
        window_title=None,
        terminal_active=True,
    )

    card = build_work_context_card(current_context, signals=signals)

    assert "Terminal actif sans commande récente lisible" not in card.missing_context
    assert "Titre de fenêtre non disponible" in card.missing_context


def test_build_work_context_card_uses_current_context_window_title_for_probe_availability():
    current_context = SimpleNamespace(
        active_project="Pulse",
        activity_level="editing",
        probable_task="debug",
        active_app="Code",
        window_title="Pulse — DashboardRootView.swift — Visual Studio Code",
    )
    signals = SimpleNamespace(window_title=None)

    card = build_work_context_card(current_context, signals=signals)

    assert "Titre de fenêtre disponible" in card.evidence
    assert "Titre de fenêtre non disponible" not in card.missing_context
    assert "window_title" not in card.safe_next_probes


def test_build_work_context_card_suggests_app_context_only_when_base_context_is_incomplete():
    current_context = SimpleNamespace(
        active_project="Pulse",
        activity_level="editing",
        probable_task="general",
        active_app="Code",
        window_title="Pulse",
    )

    card = build_work_context_card(current_context)

    assert card.safe_next_probes == ("app_context",)


def test_build_work_context_card_clamps_confidence():
    high = build_work_context_card(SimpleNamespace(task_confidence=1.8))
    low = build_work_context_card(SimpleNamespace(task_confidence=-0.4))
    rounded = build_work_context_card(SimpleNamespace(task_confidence=0.756))

    assert high.confidence == 1.0
    assert low.confidence == 0.0
    assert rounded.confidence == 0.76


def test_build_work_context_card_uses_signal_confidence_when_context_missing():
    current_context = SimpleNamespace(task_confidence=None)
    signals = SimpleNamespace(task_confidence=0.42, window_title="Pulse")

    card = build_work_context_card(current_context, signals=signals)

    assert card.confidence == 0.42


def test_build_work_context_card_adds_runtime_decision_evidence():
    current_context = SimpleNamespace(
        active_project="Pulse",
        activity_level="editing",
        probable_task="coding",
        task_confidence=0.7,
    )
    decision = SimpleNamespace(action="context_ready")

    card = build_work_context_card(current_context, decision=decision)

    assert "Décision runtime récente : context_ready" in card.evidence


def test_build_work_context_card_deduplicates_evidence_and_missing_context():
    current_context = SimpleNamespace(
        active_project="Pulse",
        activity_level="editing",
        probable_task="debug",
        active_app="Code",
    )
    present = SimpleNamespace(
        active_project="Pulse",
        activity_level="editing",
        probable_task="debug",
        active_app="Code",
    )
    signals = SimpleNamespace(
        active_app="Code",
        window_title=None,
        recent_apps=["Code", "Code"],
    )

    card = build_work_context_card(current_context, present=present, signals=signals)

    assert card.evidence.count("Application active : Code") == 1
    assert card.missing_context.count("Titre de fenêtre non disponible") == 1


def test_work_context_card_to_dict_is_json_ready():
    card = WorkContextCard(
        project="Pulse",
        project_hint=None,
        project_hint_confidence=0.0,
        project_hint_source=None,
        activity_level="editing",
        probable_task="debug",
        confidence=0.8,
        work_intent=None,
        evidence=("Projet actif observé : Pulse",),
        missing_context=("Objectif utilisateur non explicite",),
        safe_next_probes=("app_context", "window_title"),
    )

    assert card.to_dict() == {
        "project": "Pulse",
        "project_hint": None,
        "project_hint_confidence": 0.0,
        "project_hint_source": None,
        "activity_level": "editing",
        "probable_task": "debug",
        "work_intent": None,
        "confidence": 0.8,
        "project_confidence": 0.0,
        "project_status": "unknown",
        "task_status": "unknown",
        "project_source": None,
        "project_evidence": [],
        "project_warnings": [],
        "support_apps": [],
        "evidence": ["Projet actif observé : Pulse"],
        "missing_context": ["Objectif utilisateur non explicite"],
        "safe_next_probes": ["app_context", "window_title"],
    }


def test_build_work_context_card_exposes_project_confidence_separately_from_task_confidence():
    current_context = SimpleNamespace(
        active_project=None,
        project_root="/tmp/workspace/AlphaApp",
        activity_level="executing",
        probable_task="general",
        task_confidence=0.32,
        active_app="ChatGPT",
        terminal_cwd="/tmp/workspace/AlphaApp",
        terminal_action_category="testing",
        work_intent={
            "summary": "stabiliser les tests locaux",
            "source": "manual_context_note",
            "confidence": 0.9,
            "project": "AlphaApp",
        },
    )
    signals = SimpleNamespace(recent_apps=["Codex", "Code"], window_title=None)

    card = build_work_context_card(current_context, signals=signals)

    assert card.project == "AlphaApp"
    assert card.probable_task == "general"
    assert card.confidence == 0.32
    assert card.project_confidence >= 0.8
    assert card.project_status == "observed"
    assert card.task_status == "unknown"
    assert card.project_source == "repo_root"
    assert card.support_apps == ("Codex", "ChatGPT")
    assert "Apps IA utilisées comme support" in card.project_evidence
    assert str(card.to_dict()).find("/tmp/workspace/AlphaApp") == -1


# Additional tests for project_hint logic

def test_build_work_context_card_adds_weak_project_hint_from_window_title_when_project_unknown():
    current_context = SimpleNamespace(
        active_project=None,
        activity_level="reading",
        probable_task="general",
        active_app="Code",
        window_title="Pulse — DashboardRootView.swift — Visual Studio Code",
    )

    card = build_work_context_card(current_context)

    assert card.project is None
    assert card.project_hint == "Pulse"
    assert card.project_hint_confidence == 0.35
    assert card.project_hint_source == "window_title"
    assert "Projet actif détecté : Pulse" not in card.evidence
    assert all("détecté" not in item for item in card.evidence)
    assert card.project_status == "unknown"
    assert "project_hint_uncorroborated" in card.project_warnings


def test_build_work_context_card_does_not_promote_project_hint_when_project_is_known():
    current_context = SimpleNamespace(
        active_project="Pulse",
        activity_level="reading",
        probable_task="general",
        active_app="Code",
        window_title="DevNote — README.md — Visual Studio Code",
    )

    card = build_work_context_card(current_context)

    assert card.project == "Pulse"
    assert card.project_hint is None
    assert card.project_hint_confidence == 0.0
    assert card.project_hint_source is None


def test_build_work_context_card_ignores_weak_project_hint_for_app_or_file_segments():
    current_context = SimpleNamespace(
        active_project=None,
        activity_level="reading",
        probable_task="general",
        active_app="Code",
        window_title="work_context_card.py — Visual Studio Code",
    )

    card = build_work_context_card(current_context)

    assert card.project is None
    assert card.project_hint is None
    assert card.project_hint_confidence == 0.0
    assert card.project_hint_source is None


def test_project_hint_is_not_rendered_as_detected_when_confidence_is_low():
    current_context = SimpleNamespace(
        active_project=None,
        activity_level="reading",
        probable_task="general",
        active_app="Code",
        window_title="Pulse — DashboardRootView.swift — Visual Studio Code",
        task_confidence=0.35,
    )

    card = build_work_context_card(current_context)

    assert card.project is None
    assert card.project_hint == "Pulse"
    assert card.project_hint_confidence == 0.35
    assert card.project_status == "unknown"
    assert "project_hint_uncorroborated" in card.project_warnings
    assert all("Projet actif détecté" not in item for item in card.evidence)


def test_high_confidence_project_can_be_rendered_as_active_or_observed():
    current_context = SimpleNamespace(
        active_project="Pulse",
        activity_level="editing",
        probable_task="coding",
        task_confidence=0.82,
    )

    card = build_work_context_card(current_context)

    assert card.project == "Pulse"
    assert card.project_confidence >= 0.75
    assert card.project_status == "observed"
    assert "Projet actif observé : Pulse" in card.evidence


def test_unknown_project_keeps_uncertainty_visible():
    current_context = SimpleNamespace(
        active_project=None,
        activity_level="unknown",
        probable_task="general",
        task_confidence=0.0,
    )

    card = build_work_context_card(current_context)

    assert card.project is None
    assert card.project_status == "unknown"
    assert "Projet actif non identifié" in card.missing_context
    assert card.evidence == ()


def test_context_card_exposes_evidence_or_uncertainty_flags():
    current_context = SimpleNamespace(
        active_project=None,
        activity_level="reading",
        probable_task="general",
        active_app="Code",
        window_title="Pulse — DashboardRootView.swift — Visual Studio Code",
    )

    card = build_work_context_card(current_context)

    assert card.project is None
    assert card.project_hint == "Pulse"
    assert card.project_warnings
    assert "project_hint_uncorroborated" in card.project_warnings
    assert card.project_status == "unknown"
