from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daemon.core.app_classifier import classify_app
from daemon.core.workspace_context import extract_project_name


@dataclass(frozen=True)
class WorkEvidenceInput:
    active_project: str | None = None
    project_hint: str | None = None
    file_paths: tuple[str, ...] = ()
    repo_roots: tuple[str, ...] = ()
    terminal_cwd: str | None = None
    terminal_project: str | None = None
    terminal_command_category: str | None = None
    active_app: str | None = None
    active_app_bundle_id: str | None = None
    window_title: str | None = None
    recent_apps: tuple[str, ...] = ()
    recent_app_bundle_ids: tuple[str | None, ...] = ()
    work_intent_project: str | None = None
    commit_repo_root: str | None = None
    commit_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkEvidenceResolution:
    project: str | None
    project_confidence: float
    project_source: str | None
    task_confidence_adjustment: float
    support_apps: tuple[str, ...]
    evidence: tuple[str, ...]
    warnings: tuple[str, ...]


def resolve_work_evidence(input: WorkEvidenceInput) -> WorkEvidenceResolution:
    evidence: list[str] = []
    warnings: list[str] = []
    support_apps = _support_apps(
        input.recent_apps,
        input.active_app,
        recent_app_bundle_ids=input.recent_app_bundle_ids,
        active_app_bundle_id=input.active_app_bundle_id,
    )

    active_project = _clean(input.active_project)
    if active_project:
        evidence.append("Projet explicite détecté")
        if _work_intent_matches(input.work_intent_project, active_project):
            evidence.append("Intention de travail cohérente avec le projet")
        if support_apps:
            evidence.append("Apps IA utilisées comme support")
        return _resolution(active_project, 0.9, "active_project", support_apps, evidence, warnings)

    commit_project = _project_from_root(input.commit_repo_root)
    if commit_project:
        evidence.append("Commit rattaché à un dépôt local")
        if support_apps:
            evidence.append("Apps IA utilisées comme support")
        return _resolution(commit_project, 0.9, "commit_repo_root", support_apps, evidence, warnings)

    root_project = _majority_project_from_roots(input.repo_roots)
    if root_project:
        evidence.append("Racine projet locale détectée")
        if _work_intent_matches(input.work_intent_project, root_project):
            evidence.append("Intention de travail cohérente avec le projet")
        if support_apps:
            evidence.append("Apps IA utilisées comme support")
        return _resolution(root_project, 0.86, "repo_root", support_apps, evidence, warnings)

    terminal_project = _clean(input.terminal_project) or _project_from_path(input.terminal_cwd)
    if terminal_project:
        evidence.append("Terminal rattaché à un projet local")
        if input.terminal_command_category:
            evidence.append(f"Action terminal : {input.terminal_command_category}")
        if _work_intent_matches(input.work_intent_project, terminal_project):
            evidence.append("Intention de travail cohérente avec le terminal")
        if support_apps:
            evidence.append("Apps IA utilisées comme support")
        return _resolution(terminal_project, 0.84, "terminal_cwd", support_apps, evidence, warnings)

    file_project = _majority_project_from_paths(input.file_paths)
    if file_project:
        evidence.append("Fichiers récents sous une même racine projet")
        if _work_intent_matches(input.work_intent_project, file_project):
            evidence.append("Intention de travail cohérente avec les fichiers")
        if support_apps:
            evidence.append("Apps IA utilisées comme support")
        return _resolution(file_project, 0.8, "file_paths", support_apps, evidence, warnings)

    if _has_basename_only(input.file_paths) or _has_basename_only(input.commit_files):
        warnings.append("basename_only_insufficient")
    if _clean(input.window_title):
        warnings.append("window_title_only")
    if support_apps:
        warnings.append("ai_app_only")

    hinted_project = _clean(input.project_hint)
    intent_project = _clean(input.work_intent_project)
    if hinted_project:
        warnings.append("project_hint_uncorroborated")
    if intent_project:
        warnings.append("work_intent_uncorroborated")

    return _resolution(None, 0.0, None, support_apps, evidence, warnings)


def _resolution(
    project: str | None,
    confidence: float,
    source: str | None,
    support_apps: tuple[str, ...],
    evidence: list[str],
    warnings: list[str],
) -> WorkEvidenceResolution:
    task_adjustment = 0.0
    if project and confidence >= 0.8:
        task_adjustment = 0.1
    return WorkEvidenceResolution(
        project=project,
        project_confidence=round(max(0.0, min(confidence, 1.0)), 2),
        project_source=source,
        task_confidence_adjustment=task_adjustment,
        support_apps=support_apps,
        evidence=tuple(_dedupe(evidence)),
        warnings=tuple(_dedupe(warnings)),
    )


def _project_from_path(value: Any) -> str | None:
    text = _clean(value)
    if not text or "/" not in text:
        return None
    return extract_project_name(text)


def _project_from_root(value: Any) -> str | None:
    text = _clean(value)
    if not text or "/" not in text:
        return None
    return Path(text).name.strip() or None


def _majority_project_from_roots(values: tuple[str, ...]) -> str | None:
    projects = [_project_from_root(value) for value in values if _clean(value)]
    return _majority(project for project in projects if project)


def _majority_project_from_paths(values: tuple[str, ...]) -> str | None:
    projects = [_project_from_path(value) for value in values if _clean(value)]
    return _majority(project for project in projects if project)


def _majority(values: Any) -> str | None:
    items = [str(value) for value in values if value]
    if not items:
        return None
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    project, count = max(counts.items(), key=lambda item: item[1])
    return project if count > len(items) / 2 else None


def _support_apps(
    recent_apps: tuple[str, ...],
    active_app: str | None,
    *,
    recent_app_bundle_ids: tuple[str | None, ...] = (),
    active_app_bundle_id: str | None = None,
) -> tuple[str, ...]:
    apps: list[tuple[str, str | None]] = [
        (app, recent_app_bundle_ids[index] if index < len(recent_app_bundle_ids) else None)
        for index, app in enumerate(recent_apps)
    ]
    if active_app:
        apps.append((active_app, active_app_bundle_id))
    return tuple(
        _dedupe(
            app
            for app, bundle_id in apps
            if classify_app(app, bundle_id=bundle_id).role == "ai_assistant"
        )
    )


def _work_intent_matches(work_intent_project: str | None, project: str | None) -> bool:
    return bool(_clean(work_intent_project) and _clean(project) and _clean(work_intent_project) == _clean(project))


def _has_basename_only(values: tuple[str, ...]) -> bool:
    return any(_clean(value) and "/" not in str(value) for value in values)


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _dedupe(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
