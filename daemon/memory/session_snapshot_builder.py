from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from daemon.core.contracts import SessionSnapshot
from daemon.core.file_classifier import file_signal_significance


def build_session_snapshot(
    *,
    session: Mapping[str, Any],
    recent_events: Sequence[Mapping[str, Any]],
    duration_fallback_min: int,
) -> SessionSnapshot:
    """
    Construit un SessionSnapshot structuré à partir de la session SQLite
    courante et de ses events récents.

    Le calcul reste strictement aligné sur l'ancien export_session_data().
    """

    apps: list[str] = []
    seen_apps: set[str] = set()
    file_counts: dict[str, int] = {}
    max_friction = float(session.get("friction_score") or 0.0)

    for event in recent_events:
        payload = event["payload"]

        if event["type"] in {"app_activated", "app_switch"}:
            app_name = payload.get("app_name")
            if app_name and app_name not in seen_apps:
                seen_apps.add(app_name)
                apps.append(app_name)

        if event["type"] in {
            "file_created", "file_modified", "file_renamed", "file_deleted", "file_change"
        }:
            path = payload.get("path")
            if path and file_signal_significance(path) != "technical_noise":
                file_counts[path] = file_counts.get(path, 0) + 1

    top_files = sorted(file_counts.items(), key=lambda item: item[1], reverse=True)[:8]
    top_file_names = [Path(path).name for path, _ in top_files]

    return SessionSnapshot(
        session_id=session.get("id"),
        started_at=session.get("started_at"),
        updated_at=session.get("updated_at"),
        ended_at=session.get("ended_at"),
        active_project=session.get("active_project"),
        active_file=session.get("active_file"),
        probable_task=session.get("probable_task"),
        focus_level=session.get("focus_level"),
        duration_min=session.get("session_duration_min") or duration_fallback_min,
        recent_apps=apps[-10:],
        files_changed=len(file_counts),
        top_files=top_file_names,
        event_count=len(recent_events),
        max_friction=max_friction,
    )


def session_snapshot_to_legacy_dict(snapshot: SessionSnapshot) -> dict[str, Any]:
    """
    Adaptateur legacy : conserve exactement le contrat dict attendu par
    export_session_data() et ses consommateurs existants.
    """

    return {
        "session_id": snapshot.session_id,
        "started_at": snapshot.started_at,
        "updated_at": snapshot.updated_at,
        "ended_at": snapshot.ended_at,
        "active_project": snapshot.active_project,
        "active_file": snapshot.active_file,
        "probable_task": snapshot.probable_task,
        "focus_level": snapshot.focus_level,
        "duration_min": snapshot.duration_min,
        "recent_apps": list(snapshot.recent_apps),
        "files_changed": snapshot.files_changed,
        "top_files": list(snapshot.top_files),
        "event_count": snapshot.event_count,
        "max_friction": snapshot.max_friction,
    }
