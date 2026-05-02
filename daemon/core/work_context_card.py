"""Work context card builder.

This module does not observe, persist, decide, or ask for context.
It only turns the already available runtime/current context into a compact,
explainable card describing what Pulse currently believes about the user's work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class WorkContextCard:
    """Explainable summary of the current work context."""

    project: Optional[str]
    project_hint: Optional[str]
    project_hint_confidence: float
    project_hint_source: Optional[str]
    activity_level: str
    probable_task: str
    confidence: float
    evidence: tuple[str, ...] = field(default_factory=tuple)
    missing_context: tuple[str, ...] = field(default_factory=tuple)
    safe_next_probes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "project": self.project,
            "project_hint": self.project_hint,
            "project_hint_confidence": self.project_hint_confidence,
            "project_hint_source": self.project_hint_source,
            "activity_level": self.activity_level,
            "probable_task": self.probable_task,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "missing_context": list(self.missing_context),
            "safe_next_probes": list(self.safe_next_probes),
        }


def build_work_context_card(
    current_context: Any,
    *,
    present: Any = None,
    signals: Any = None,
    decision: Any = None,
) -> WorkContextCard:
    """Build a passive work context card from existing runtime objects.

    The builder is intentionally conservative. It does not trigger probes,
    store preferences, or infer autonomy. It only explains what is already
    available.
    """
    project = _first_non_empty(
        getattr(current_context, "active_project", None),
        getattr(present, "active_project", None),
    )
    # Insert project_hint computation
    project_hint, project_hint_confidence, project_hint_source = _build_project_hint(
        project=project,
        signals=signals,
        current_context=current_context,
    )
    activity_level = _first_non_empty(
        getattr(current_context, "activity_level", None),
        getattr(present, "activity_level", None),
        "unknown",
    ) or "unknown"
    probable_task = _first_non_empty(
        getattr(current_context, "probable_task", None),
        getattr(present, "probable_task", None),
        "general",
    ) or "general"

    confidence = _clamp_confidence(
        _first_number(
            getattr(current_context, "task_confidence", None),
            getattr(signals, "task_confidence", None),
            getattr(present, "task_confidence", None),
        )
    )

    evidence = _build_evidence(
        project=project,
        activity_level=activity_level,
        probable_task=probable_task,
        current_context=current_context,
        present=present,
        signals=signals,
        decision=decision,
    )
    missing_context = _build_missing_context(
        project=project,
        activity_level=activity_level,
        probable_task=probable_task,
        current_context=current_context,
        signals=signals,
    )
    safe_next_probes = _build_safe_next_probes(
        project=project,
        activity_level=activity_level,
        probable_task=probable_task,
        present=present,
        signals=signals,
        current_context=current_context,
    )

    return WorkContextCard(
        project=project,
        project_hint=project_hint,
        project_hint_confidence=project_hint_confidence,
        project_hint_source=project_hint_source,
        activity_level=activity_level,
        probable_task=probable_task,
        confidence=confidence,
        evidence=tuple(evidence),
        missing_context=tuple(missing_context),
        safe_next_probes=tuple(safe_next_probes),
    )


def _build_evidence(
    *,
    project: Optional[str],
    activity_level: str,
    probable_task: str,
    current_context: Any,
    present: Any,
    signals: Any,
    decision: Any,
) -> list[str]:
    evidence: list[str] = []

    if project:
        evidence.append(f"Projet actif détecté : {project}")
    if activity_level and activity_level != "unknown":
        evidence.append(f"Niveau d'activité : {activity_level}")
    if probable_task and probable_task != "general":
        evidence.append(f"Tâche probable : {probable_task}")

    active_app = _first_non_empty(
        getattr(current_context, "active_app", None),
        getattr(present, "active_app", None),
        getattr(signals, "active_app", None),
    )
    if active_app:
        evidence.append(f"Application active : {active_app}")

    if _has_window_title(signals=signals, current_context=current_context):
        evidence.append("Titre de fenêtre disponible")

    edited_count = _first_number(getattr(signals, "edited_file_count_10m", None))
    if edited_count and edited_count > 0:
        evidence.append(f"Fichiers modifiés récemment : {int(edited_count)}")

    recent_apps = getattr(signals, "recent_apps", None)
    if isinstance(recent_apps, Iterable) and not isinstance(recent_apps, (str, bytes)):
        apps = [str(app) for app in recent_apps if str(app).strip()]
        if apps:
            evidence.append("Applications récentes : " + ", ".join(apps[:3]))

    decision_label = _first_non_empty(
        getattr(decision, "action", None),
        getattr(decision, "type", None),
        getattr(decision, "name", None),
    )
    if decision_label:
        evidence.append(f"Décision runtime récente : {decision_label}")

    return _dedupe(evidence)


def _build_missing_context(
    *,
    project: Optional[str],
    activity_level: str,
    probable_task: str,
    current_context: Any,
    signals: Any,
) -> list[str]:
    missing: list[str] = []

    if not project:
        missing.append("Projet actif non identifié")
    if not probable_task or probable_task == "general":
        missing.append("Tâche utilisateur encore générale")
    if not activity_level or activity_level == "unknown":
        missing.append("Niveau d'activité incertain")

    if not _has_window_title(signals=signals, current_context=current_context):
        missing.append("Titre de fenêtre non disponible")

    terminal_active = bool(getattr(signals, "terminal_active", False))
    recent_commands = getattr(current_context, "recent_terminal_commands", None)
    if terminal_active and not recent_commands:
        missing.append("Terminal actif sans commande récente lisible")

    return _dedupe(missing)


def _build_safe_next_probes(
    *,
    project: Optional[str],
    activity_level: str,
    probable_task: str,
    present: Any,
    signals: Any,
    current_context: Any,
) -> list[str]:
    probes: list[str] = []

    active_app = _first_non_empty(
        getattr(current_context, "active_app", None),
        getattr(present, "active_app", None),
        getattr(signals, "active_app", None),
    )
    if (
        not active_app
        or not project
        or not activity_level
        or activity_level == "unknown"
        or not probable_task
        or probable_task == "general"
    ):
        probes.append("app_context")

    if not _has_window_title(signals=signals, current_context=current_context):
        probes.append("window_title")

    return probes



def _has_window_title(*, signals: Any, current_context: Any) -> bool:
    return bool(
        _first_non_empty(
            getattr(signals, "window_title", None),
            getattr(current_context, "window_title", None),
        )
    )


# --- Project hint logic ---
def _build_project_hint(
    *,
    project: Optional[str],
    signals: Any,
    current_context: Any,
) -> tuple[Optional[str], float, Optional[str]]:
    """Return a weak project hint without promoting it to active project."""
    if project:
        return None, 0.0, None

    title = _first_non_empty(
        getattr(signals, "window_title", None),
        getattr(current_context, "window_title", None),
    )
    if not title:
        return None, 0.0, None

    hint = _project_hint_from_window_title(title)
    if not hint:
        return None, 0.0, None

    return hint, 0.35, "window_title"


def _project_hint_from_window_title(title: str) -> Optional[str]:
    separators = (" — ", " – ", " - ")
    segments = [title]
    for separator in separators:
        if separator in title:
            segments = title.split(separator)
            break

    for segment in segments:
        candidate = segment.strip()
        if _is_project_hint_candidate(candidate):
            return candidate
    return None


def _is_project_hint_candidate(value: str) -> bool:
    if not value or len(value) < 2 or len(value) > 48:
        return False
    lowered = value.lower()
    blocked = {
        "visual studio code",
        "code",
        "cursor",
        "xcode",
        "safari",
        "terminal",
        "chatgpt",
        "claude",
        "finder",
        "nouvel onglet",
        "new tab",
        "untitled",
        "sans titre",
    }
    if lowered in blocked:
        return False
    if "/" in value or "\\" in value:
        return False
    if "." in value and " " not in value:
        return False
    return any(char.isalpha() for char in value)


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _clamp_confidence(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, round(value, 2)))


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
