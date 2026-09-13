"""Deterministic work-session reconstruction and timeline presentation helpers.

Only reconstruct_session_views owns work-session boundaries, composition,
identity and closure. It takes stored events, never historical session groups.
"""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
import hashlib
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import WEAK_CONTEXT_TYPES
from .projects import (
    WorkspaceIdentity,
    activity_project_root,
    activity_workspace,
    is_generic_workspace_path,
    is_weak_workspace,
    persisted_workspace_identity,
)


IGNORED_APP_NAMES_FOR_RENDERING = {"CleanMyMac Menu", "Finder", "loginwindow"}
WORK_SESSION_GAP = timedelta(minutes=30)
WEAK_CONTEXT_WINDOW = timedelta(minutes=15)
WORKSPACE_PROMOTION_WINDOW = timedelta(minutes=5)

# Fermeture monotone (décision 2026-09-03) : un verrouillage ou une mise en
# veille ferme la session ouverte sur-le-champ et ne se défait jamais ; la
# reprise attendue prouve seulement que l'utilisateur est de retour.
LOCK_RESUME_TYPES = {
    "screen_locked": "screen_unlocked",
    "system_sleep": "system_wake",
}
RESUME_LOCK_TYPES = {resume: lock for lock, resume in LOCK_RESUME_TYPES.items()}

# Incrémenter à chaque changement des règles de sessionnisation (gap,
# promotion de workspace, rétrogradation en isolé…) : un consommateur qui a
# mémorisé une session sait alors que sa composition peut avoir changé.
# 2 (2026-09-03) : fermeture monotone sur verrouillage/veille, activité forte
# pendant un verrouillage rangée en arrière-plan hors session de travail.
# 3 depuis le 2026-09-06 : fuseau de reconstruction explicite (ZoneInfo) à la
# place du décalage fixe du moment ; les sessions proches de minuit peuvent
# changer d'identifiant au premier replay, variation prévue par la décision.
# 4 : seuil avant split (décision du 2026-09-12) — un fragment d'un autre
# workspace ne ferme la session en cours que s'il dure SPLIT_MIN_DURATION et
# compte SPLIT_MIN_STRONG activités fortes ; sinon il est absorbé, avec son
# workspace.
RECONSTRUCTION_VERSION = 4
SPLIT_MIN_DURATION = timedelta(minutes=2)
SPLIT_MIN_STRONG = 2
SESSION_IDENTITY_HEX_LENGTH = 16


def session_identity(activities: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Identité stable d'une session : sha256 tronqué des event_id triés.

    Déterministe et sans état : deux reconstructions qui regroupent les mêmes
    événements donnent le même id, quel que soit l'ordre des lignes ou ce qui
    s'est passé ailleurs dans la journée. Si la composition change (un
    événement tardif rejoint la session), c'est une autre session — c'est
    correct par construction. Le label ordinal ``work-N``, lui, bouge dès
    qu'un événement tardif s'insère plus tôt dans la journée : il sert à
    l'affichage, jamais comme clé.
    """
    keys = sorted(activity["event_id"] for activity in activities)
    digest = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()
    return digest[:SESSION_IDENTITY_HEX_LENGTH], keys

# Temporary aliases preserve the renderer-facing timeline API.
_activity_workspace = activity_workspace
_is_weak_workspace = is_weak_workspace
_is_generic_workspace_path = is_generic_workspace_path
_persisted_workspace = persisted_workspace_identity


def _trace_timezone(trace: dict[str, Any]) -> tzinfo:
    name = str(trace["timezone"])
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "UTC":
            return timezone.utc
        try:
            return datetime.fromisoformat(
                f"2000-01-01T00:00:00{name}"
            ).tzinfo or timezone.utc
        except ValueError as exc:
            raise ValueError(f"invalid trace timezone: {name}") from exc


def _display_time(value: str, zone: tzinfo) -> str:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise ValueError("timeline timestamps must include a timezone")
    return instant.astimezone(zone).strftime("%H:%M")


def _session_observed_bounds(session: dict[str, Any]) -> tuple[str, str]:
    if "end_reason" in session:
        return session["started_at"], session["ended_at"]
    strong_activities = [
        activity
        for activity in session["activities"]
        if is_strong_work_activity(activity)
    ]
    if strong_activities:
        return (
            strong_activities[0]["occurred_at"],
            strong_activities[-1]["occurred_at"],
        )

    file_change_groups = _file_change_groups(session)
    activation_counts = app_activation_counts(session)
    rendered_app_activations = False
    rendered_activities = []
    for activity in session["activities"]:
        details = activity.get("details", {})
        if activity["type"] == "app_activated":
            if details.get("app") not in activation_counts:
                continue
            if rendered_app_activations:
                continue
            rendered_app_activations = True
        elif (
            activity["type"] == "file_changed"
            and details.get("event", details.get("change"))
            and details.get("path")
            and id(activity) not in file_change_groups
        ):
            continue
        rendered_activities.append(activity)

    if not rendered_activities:
        return session["started_at"], session["ended_at"]
    return (
        rendered_activities[0]["occurred_at"],
        rendered_activities[-1]["occurred_at"],
    )


def _session_duration(session: dict[str, Any]) -> str:
    started_at, ended_at = _session_observed_bounds(session)
    duration = (
        datetime.fromisoformat(ended_at)
        - datetime.fromisoformat(started_at)
    )
    minutes = max(0, int(duration.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{hours}h{remaining_minutes:02d}"


def _session_duration_seconds(session: dict[str, Any]) -> float:
    started_at, ended_at = _session_observed_bounds(session)
    return max(
        0,
        (
            datetime.fromisoformat(ended_at)
            - datetime.fromisoformat(started_at)
        ).total_seconds(),
    )


def display_file_path(path: str, workspace: Any) -> str:
    display_path = Path(path)
    if isinstance(workspace, dict):
        workspace = workspace.get("workspace_root")
    if workspace:
        try:
            display_path = display_path.relative_to(Path(workspace))
        except ValueError:
            pass
    return str(display_path)


def app_activation_counts(session: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for activity in session["activities"]:
        if activity["type"] == "app_activated":
            app = activity.get("details", {}).get("app")
            if app and app not in IGNORED_APP_NAMES_FOR_RENDERING:
                counts[app] = counts.get(app, 0) + 1
    return counts


def _ranked_apps(counts: dict[str, int], limit: int = 5) -> list[tuple[str, int]]:
    return sorted(counts.items(), key=lambda item: -item[1])[:limit]


def unresolved_app_names(session: dict[str, Any]) -> list[str]:
    """Applications d'un groupe non attribué : les activations classées,
    sinon celles des fenêtres observées, dans l'ordre d'apparition."""
    ranked = [app for app, _count in _ranked_apps(app_activation_counts(session))]
    if ranked:
        return ranked
    names: list[str] = []
    for activity in session["activities"]:
        if activity["type"] != "window_focused":
            continue
        app = activity.get("details", {}).get("app")
        if app and app not in IGNORED_APP_NAMES_FOR_RENDERING and app not in names:
            names.append(app)
    return names


def is_strong_work_activity(activity: dict[str, Any]) -> bool:
    # A git_commit event is verified evidence (the commit object itself),
    # not an inference, so it counts as strong work signal like the others.
    # An agent_session is derived from a real transcript too, but it is
    # emitted after the fact (SessionEnd hook, hourly launchd pass) with an
    # occurred_at that lands inside an already reconstructed session: letting
    # it join would change the session's identity and bounds after a summary
    # may have been attached (decision 2026-09-03-agent-session-hors-identite).
    # It stays reachable through /context.last_agent_session, never here.
    return activity["type"] in {
        "terminal_finished",
        "file_changed",
        "git_commit",
    }


# Deprecated aliases (2026-09-03): display_file_path, app_activation_counts
# and is_strong_work_activity are imported by several consumers
# (daily_trace, context_snapshot, the renderers) — use the public names.
# Kept until every import has migrated; no new caller should use them.
_display_file_path = display_file_path
_app_activation_counts = app_activation_counts
_is_strong_work_activity = is_strong_work_activity


def _session_metadata(
    activities: list[dict[str, Any]],
    *,
    started_at: datetime,
    ended_at: datetime,
    workspace_root: str | None,
    project_name: str | None,
    end_reason: str,
    zone: tzinfo,
) -> dict[str, Any]:
    files: set[str] = set()
    commands_executed = 0
    applications: list[str] = []
    for activity in activities:
        details = activity.get("details", {})
        if activity["type"] == "file_changed":
            path = details.get("path")
            if isinstance(path, str) and path:
                files.add(path)
        elif activity["type"] == "terminal_finished":
            commands_executed += 1
        elif activity["type"] == "app_activated":
            app = details.get("app")
            if (
                isinstance(app, str)
                and app
                and app not in IGNORED_APP_NAMES_FOR_RENDERING
                and app not in applications
            ):
                applications.append(app)

    calendar_duration = max(0, int((ended_at - started_at).total_seconds()))

    return {
        "started_at": started_at.astimezone(zone).isoformat(),
        "ended_at": ended_at.astimezone(zone).isoformat(),
        "duration_seconds": calendar_duration,
        # Depuis la fermeture monotone (reconstruction 2), une session ne
        # contient plus d'interruption : les deux champs restent pour la
        # forme JSON, toujours vide et égal à la durée calendaire.
        "active_duration_seconds": calendar_duration,
        "project_name": project_name,
        "workspace_root": workspace_root,
        "event_count": len(activities),
        "activity_count": len(activities),
        "files_changed": len(files),
        "commands_executed": commands_executed,
        "applications": applications,
        "interruptions": [],
        "end_reason": end_reason,
        "activities": activities,
    }


def _session_from_activities(
    activities: list[dict[str, Any]],
    session_id: str,
    zone: tzinfo,
) -> dict[str, Any]:
    started_at = datetime.fromisoformat(activities[0]["occurred_at"]).astimezone(
        zone
    )
    ended_at = datetime.fromisoformat(activities[-1]["occurred_at"]).astimezone(
        zone
    )
    applications: list[str] = []
    for activity in activities:
        app = activity.get("details", {}).get("app")
        if (
            isinstance(app, str)
            and app
            and app not in IGNORED_APP_NAMES_FOR_RENDERING
            and app not in applications
        ):
            applications.append(app)
    return {
        "id": session_id,
        "activity_kind": "user_presence",
        "workspace_attribution": "unresolved",
        "project_name": None,
        "workspace_root": None,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": max(
            0,
            int((ended_at - started_at).total_seconds()),
        ),
        "applications": applications,
        "event_count": len(activities),
        "activity_count": len(activities),
        "activities": activities,
    }


def _workspace_relation(
    current_root: str | None,
    current_confidence: str | None,
    current_observed_at: datetime,
    incoming: WorkspaceIdentity,
    occurred_at: datetime,
) -> str:
    """same, promote ou split entre un workspace tenu (session en cours ou
    fragment en attente) et un événement entrant. Mêmes règles pour les
    deux : une commande à faible confiance ne quitte jamais un dépôt sûr."""
    if incoming.root is None:
        return "same"
    if current_root is None:
        return "promote"
    if incoming.root == current_root:
        return (
            "promote"
            if current_confidence == "low"
            and incoming.confidence in {"medium", "high"}
            else "same"
        )
    if current_confidence == "high" and incoming.confidence == "low":
        return "same"
    if (
        current_confidence == "low"
        and incoming.confidence in {"medium", "high"}
        and occurred_at - current_observed_at <= WORKSPACE_PROMOTION_WINDOW
    ):
        current_path = Path(current_root).expanduser()
        incoming_path = Path(incoming.root).expanduser()
        if (
            current_path in incoming_path.parents
            or incoming_path in current_path.parents
        ):
            return "promote"
    return "split"


def reconstruct_session_views(
    activities: list[dict[str, Any]],
    *,
    day: date,
    zone: tzinfo,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sessions de travail (et vues « isolated » / « background ») du jour.

    Fermeture monotone : ``screen_locked`` et ``system_sleep`` ferment la
    session ouverte immédiatement, avec ce motif, et rien ne la rouvre.
    Tant que la reprise correspondante n'a pas été vue, toute activité forte
    tombe dans une vue ``activity_kind == "background"`` — des faits observés
    pendant un verrouillage (un agent qui tourne seul), jamais une reprise
    humaine — qui ne compose ni identité ni bornes de session de travail.
    """
    trace_zone = zone
    activities = sorted(
        activities,
        key=lambda activity: (
            datetime.fromisoformat(activity["occurred_at"]),
            activity.get("id", 0),
        ),
    )
    work_sessions: list[dict[str, Any]] = []
    assigned_ids: set[int] = set()
    current: dict[str, Any] | None = None
    # Fragment d'un autre workspace en attente de qualification (seuil avant
    # split) : ses événements ne sont ni dans `current` ni dans une session.
    pending_split: dict[str, Any] | None = None
    work_label_count = 0
    # Verrouillages / mises en veille sans reprise vue : type → instant.
    open_locks: dict[str, datetime] = {}
    background: dict[str, Any] | None = None
    background_count = 0

    def sorted_activities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            rows,
            key=lambda activity: (
                datetime.fromisoformat(activity["occurred_at"]),
                activity.get("id", 0),
            ),
        )

    def close_current(ended_at: datetime, reason: str) -> None:
        nonlocal current, work_label_count
        assert current is not None
        session_activities = sorted_activities(
            [
                activity
                for activity in current["activities"]
                if current["started_at"]
                <= datetime.fromisoformat(activity["occurred_at"])
                <= ended_at
            ]
        )
        identity, source_event_ids = session_identity(session_activities)
        work_label_count += 1
        session_view = {
            "id": identity,
            "label": f"work-{work_label_count}",
            "source_event_ids": source_event_ids,
            "reconstruction_version": RECONSTRUCTION_VERSION,
            "activity_kind": "work",
            "workspace_attribution": (
                "assigned"
                if current["workspace_root"] is not None
                else "unknown"
            ),
            **_session_metadata(
                session_activities,
                started_at=current["started_at"],
                ended_at=ended_at,
                workspace_root=current["workspace_root"],
                project_name=current["project_name"],
                end_reason=reason,
                zone=trace_zone,
            ),
        }
        # Un événement fort isolé (un cd nu, un commit seul) n'est pas une
        # session de travail : ne pas le promouvoir en bloc « Session ».
        # Une session encore ouverte n'est jamais rétrogradée — elle vient
        # peut-être de commencer.
        strong_count = sum(
            1
            for activity in session_activities
            if is_strong_work_activity(activity)
        )
        if (
            reason != "open"
            and strong_count < 2
            and current["started_at"] == ended_at
        ):
            session_view["activity_kind"] = "isolated"
        work_sessions.append(session_view)
        assigned_ids.update(id(activity) for activity in session_activities)
        current = None

    def close_background(resumed_at: datetime | None) -> None:
        nonlocal background, background_count
        assert background is not None
        rows = sorted_activities(background["activities"])
        identity, source_event_ids = session_identity(rows)
        workspace = _persisted_workspace(rows[0])
        background_count += 1
        first_at = datetime.fromisoformat(rows[0]["occurred_at"])
        last_at = datetime.fromisoformat(rows[-1]["occurred_at"])
        view = {
            "id": identity,
            "label": f"background-{background_count}",
            "source_event_ids": source_event_ids,
            "reconstruction_version": RECONSTRUCTION_VERSION,
            "activity_kind": "background",
            "workspace_attribution": (
                "assigned" if workspace.root is not None else "unknown"
            ),
            "lock_type": background["lock_type"],
            "locked_at": background["locked_at"].astimezone(trace_zone).isoformat(),
            "resumed_at": (
                resumed_at.astimezone(trace_zone).isoformat()
                if resumed_at is not None
                else None
            ),
            **_session_metadata(
                rows,
                started_at=first_at,
                ended_at=last_at,
                workspace_root=workspace.root,
                project_name=workspace.project_name,
                end_reason="resumed" if resumed_at is not None else "still_locked",
                zone=trace_zone,
            ),
        }
        work_sessions.append(view)
        assigned_ids.update(id(activity) for activity in rows)
        background = None

    def start_session(activity: dict[str, Any], occurred_at: datetime) -> None:
        nonlocal current
        workspace = _persisted_workspace(activity)
        current = {
            "started_at": occurred_at,
            "last_work_at": occurred_at,
            "workspace_root": workspace.root,
            "project_name": workspace.project_name,
            "workspace_method": workspace.method,
            "workspace_confidence": workspace.confidence,
            "workspace_observed_at": occurred_at,
            "activities": [activity],
            "pending_unresolved": [],
        }

    def workspace_transition(
        incoming: WorkspaceIdentity,
        occurred_at: datetime,
    ) -> str:
        """Return same, promote, or split for the active session."""
        assert current is not None
        return _workspace_relation(
            current["workspace_root"],
            current["workspace_confidence"],
            current["workspace_observed_at"],
            incoming,
            occurred_at,
        )

    def promote_workspace(
        incoming: WorkspaceIdentity,
        occurred_at: datetime,
    ) -> None:
        assert current is not None
        current["workspace_root"] = incoming.root
        current["project_name"] = incoming.project_name
        current["workspace_method"] = incoming.method
        current["workspace_confidence"] = incoming.confidence
        current["workspace_observed_at"] = occurred_at

    def confirm_pending_unresolved() -> None:
        assert current is not None
        current["activities"].extend(current["pending_unresolved"])
        current["pending_unresolved"] = []

    def last_work_at() -> datetime:
        """Dernier travail observé, fragment en attente compris."""
        assert current is not None
        if pending_split is not None:
            return max(current["last_work_at"], pending_split["last_at"])
        return current["last_work_at"]

    def open_pending_split(
        activity: dict[str, Any],
        workspace: WorkspaceIdentity,
        occurred_at: datetime,
    ) -> None:
        nonlocal pending_split
        pending_split = {
            "workspace": workspace,
            "activities": [activity],
            "first_at": occurred_at,
            "last_at": occurred_at,
        }

    def pending_split_qualifies() -> bool:
        assert pending_split is not None
        # M est la condition première : un fragment de 0 minute n'est jamais
        # une session, quel que soit le nombre d'activités fortes.
        return (
            pending_split["last_at"] - pending_split["first_at"]
            >= SPLIT_MIN_DURATION
            and len(pending_split["activities"]) >= SPLIT_MIN_STRONG
        )

    def absorb_pending_split() -> None:
        """Le fragment n'est pas une session : ses événements rejoignent la
        session en cours, chacun avec son propre workspace (rendu et
        observations le gardent)."""
        nonlocal pending_split
        assert current is not None and pending_split is not None
        confirm_pending_unresolved()
        current["activities"].extend(pending_split["activities"])
        current["last_work_at"] = max(
            current["last_work_at"], pending_split["last_at"]
        )
        pending_split = None

    def confirm_pending_split() -> None:
        """Le fragment est une session : la précédente se ferme à l'instant
        de son premier événement, comme avant le seuil."""
        nonlocal pending_split, current
        assert current is not None and pending_split is not None
        fragment = pending_split
        pending_split = None
        carried = [
            weak
            for weak in current["pending_unresolved"]
            if datetime.fromisoformat(weak["occurred_at"]) >= fragment["first_at"]
        ]
        current["pending_unresolved"] = [
            weak for weak in current["pending_unresolved"] if weak not in carried
        ]
        close_current(fragment["first_at"], "workspace_changed")
        start_session(fragment["activities"][0], fragment["first_at"])
        assert current is not None
        if fragment["workspace"].root != current["workspace_root"]:
            promote_workspace(fragment["workspace"], fragment["first_at"])
        current["activities"].extend(fragment["activities"][1:])
        current["last_work_at"] = fragment["last_at"]
        current["pending_unresolved"] = carried

    def resolve_pending_split() -> None:
        if pending_split is None:
            return
        if pending_split_qualifies():
            confirm_pending_split()
        else:
            absorb_pending_split()

    for activity in activities:
        occurred_at = datetime.fromisoformat(activity["occurred_at"])
        activity_type = activity["type"]
        is_work = is_strong_work_activity(activity)

        if (
            current is not None
            and occurred_at - last_work_at() > WORK_SESSION_GAP
        ):
            resolve_pending_split()
            close_current(current["last_work_at"], "inactivity")

        if activity_type in LOCK_RESUME_TYPES:
            # Frontière dure : la session se ferme maintenant, sur son dernier
            # travail observé, et ne rouvrira jamais. Un second verrouillage
            # du même type (doublon) garde l'instant du premier.
            if current is not None:
                resolve_pending_split()
                close_current(current["last_work_at"], activity_type)
            open_locks.setdefault(activity_type, occurred_at)
            continue

        if activity_type in RESUME_LOCK_TYPES:
            # Seule la reprise du bon type lève son verrouillage ; une reprise
            # orpheline ou du mauvais type est ignorée en silence. Elle ne
            # rouvre rien : la prochaine activité forte démarrera une session.
            lock_type = RESUME_LOCK_TYPES[activity_type]
            if lock_type in open_locks:
                del open_locks[lock_type]
                if not open_locks and background is not None:
                    close_background(occurred_at)
            continue

        if is_work:
            if open_locks:
                # Entre un verrouillage et sa reprise : des faits, pas une
                # reprise humaine. Visibles à part, hors session de travail.
                if background is None:
                    lock_type, locked_at = min(
                        open_locks.items(), key=lambda item: item[1]
                    )
                    background = {
                        "lock_type": lock_type,
                        "locked_at": locked_at,
                        "activities": [],
                    }
                background["activities"].append(activity)
                continue
            workspace = _persisted_workspace(activity)
            if current is None:
                start_session(activity, occurred_at)
                continue
            if pending_split is not None:
                fragment = pending_split["workspace"]
                relation = _workspace_relation(
                    fragment.root,
                    fragment.confidence,
                    pending_split["first_at"],
                    workspace,
                    occurred_at,
                )
                if relation != "split":
                    # Le fragment continue ; dès qu'il dure et pèse assez,
                    # c'est une session et la précédente se ferme.
                    if relation == "promote":
                        pending_split["workspace"] = workspace
                    pending_split["activities"].append(activity)
                    pending_split["last_at"] = occurred_at
                    if pending_split_qualifies():
                        confirm_pending_split()
                    continue
                # Retour à la session en cours, ou troisième workspace : le
                # fragment n'a pas atteint le seuil, il est absorbé.
                absorb_pending_split()
            transition = workspace_transition(workspace, occurred_at)
            if transition == "split":
                open_pending_split(activity, workspace, occurred_at)
                if pending_split_qualifies():
                    confirm_pending_split()
                continue
            confirm_pending_unresolved()
            if transition == "promote":
                promote_workspace(workspace, occurred_at)
            current["activities"].append(activity)
            current["last_work_at"] = occurred_at
            continue

        if activity_type in WEAK_CONTEXT_TYPES:
            if (
                current is not None
                and occurred_at - last_work_at() <= WEAK_CONTEXT_WINDOW
            ):
                current["pending_unresolved"].append(activity)

    if current is not None:
        resolve_pending_split()
        current_day = now.astimezone(zone).date()
        if day != current_day:
            reason = "day_boundary"
        elif now - current["last_work_at"] <= WORK_SESSION_GAP:
            reason = "open"
        else:
            reason = "inactivity"
        close_current(current["last_work_at"], reason)
    if background is not None:
        close_background(None)

    unresolved_activities = [
        activity
        for activity in activities
        if id(activity) not in assigned_ids
        and activity["type"]
        not in {
            "screen_locked",
            "screen_unlocked",
            "system_sleep",
            "system_wake",
            # Résumé dérivé (couche Intelligence) : stocké et exposé par
            # /context, rendu à part par le journal (session_summaries) —
            # ni session, ni activité non attribuée.
            "session_summary",
            # Événement dérivé émis après coup : hors identité des sessions
            # (voir is_strong_work_activity), exposé par /context seulement.
            "agent_session",
        }
        and not (
            activity["type"] in WEAK_CONTEXT_TYPES
            and activity.get("details", {}).get("app")
            in IGNORED_APP_NAMES_FOR_RENDERING
        )
    ]
    unresolved_groups: list[list[dict[str, Any]]] = []
    for activity in unresolved_activities:
        if not unresolved_groups:
            unresolved_groups.append([activity])
            continue
        previous_at = datetime.fromisoformat(
            unresolved_groups[-1][-1]["occurred_at"]
        )
        current_at = datetime.fromisoformat(activity["occurred_at"])
        if current_at - previous_at <= WORK_SESSION_GAP:
            unresolved_groups[-1].append(activity)
        else:
            unresolved_groups.append([activity])
    unresolved_sessions = [
        _session_from_activities(group, f"unresolved-{index}", trace_zone)
        for index, group in enumerate(unresolved_groups, start=1)
    ]
    return work_sessions, unresolved_sessions


def _displayed_sessions(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        session
        for session in trace["work_sessions"]
        if session.get("activity_kind") not in {"isolated", "background"}
    ]


def background_sessions(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Activité forte observée pendant un verrouillage, rendue à part."""
    return [
        session
        for session in trace["work_sessions"]
        if session.get("activity_kind") == "background"
    ]


def isolated_sessions(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Événements forts isolés, rendus en une ligne hors blocs Session."""
    return [
        session
        for session in trace["work_sessions"]
        if session.get("activity_kind") == "isolated"
    ]


def _file_change_groups(
    session: dict[str, Any],
) -> dict[int, list[tuple[str, str, str | None, int]]]:
    activities_by_minute: dict[
        tuple[datetime, str | None],
        list[dict[str, Any]],
    ] = {}
    for activity in session["activities"]:
        if activity["type"] != "file_changed":
            continue
        details = activity.get("details", {})
        path = details.get("path")
        event = details.get("event", details.get("change"))
        if path and event:
            minute = datetime.fromisoformat(activity["occurred_at"]).replace(
                second=0, microsecond=0
            )
            workspace = _activity_workspace(activity)
            activities_by_minute.setdefault(
                (minute, workspace), []
            ).append(activity)

    groups = {}
    for activities in activities_by_minute.values():
        counts: OrderedDict[str, int] = OrderedDict()
        first_activities = {}
        for activity in activities:
            path = activity["details"]["path"]
            counts[path] = counts.get(path, 0) + 1
            first_activities.setdefault(path, activity)
        group = [
            (
                path,
                first_activities[path]["details"].get(
                    "event", first_activities[path]["details"].get("change")
                ),
                first_activities[path]["details"].get("workspace"),
                count,
            )
            for path, count in counts.items()
        ]
        first_activity = next(iter(first_activities.values()))
        groups[id(first_activity)] = group
    return groups


def _session_project_sequence(
    session: dict[str, Any],
    project_workspaces: set[str],
) -> list[str]:
    file_change_groups = _file_change_groups(session)
    sequence = []
    current_workspace = None
    for activity in session["activities"]:
        details = activity.get("details", {})
        duplicate_file = (
            activity["type"] == "file_changed"
            and bool(
                details.get("event", details.get("change"))
                and details.get("path")
            )
            and id(activity) not in file_change_groups
        )
        workspace = activity_project_root(activity)
        if (
            not duplicate_file
            and workspace in project_workspaces
            and workspace != current_workspace
        ):
            current_workspace = workspace
            sequence.append(workspace)
    return sequence
