

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
    assert card.activity_level == "editing"
    assert card.probable_task == "debug"
    assert card.confidence == 0.78
    assert card.evidence == (
        "Projet actif détecté : Pulse",
        "Niveau d'activité : editing",
        "Tâche probable : debug",
        "Application active : Code",
        "Titre de fenêtre disponible",
        "Fichiers modifiés récemment : 3",
        "Applications récentes : Code, Terminal, ChatGPT",
    )
    assert card.missing_context == ()
    assert card.safe_next_probes == ("app_context",)


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
    assert "Projet actif détecté : DevNote" in card.evidence
    assert "Application active : Safari" in card.evidence
    assert "Titre de fenêtre non disponible" in card.missing_context
    assert card.safe_next_probes == ("app_context", "window_title")


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
        activity_level="editing",
        probable_task="debug",
        confidence=0.8,
        evidence=("Projet actif détecté : Pulse",),
        missing_context=("Objectif utilisateur non explicite",),
        safe_next_probes=("app_context", "window_title"),
    )

    assert card.to_dict() == {
        "project": "Pulse",
        "activity_level": "editing",
        "probable_task": "debug",
        "confidence": 0.8,
        "evidence": ["Projet actif détecté : Pulse"],
        "missing_context": ["Objectif utilisateur non explicite"],
        "safe_next_probes": ["app_context", "window_title"],
    }