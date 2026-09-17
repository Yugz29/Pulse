"""Les résumés de session stockés, lus pour le journal : aucun modèle, aucune écriture.

Un ``session_summary`` est une interprétation produite par la couche
Intelligence et acceptée par Core (spec du 2026-09-03, §6). Ce module les
relit tels que stockés et les range pour la page d'accueil :

- ``reprise`` : le résumé que ``GET /context`` expose comme
  ``last_session_summary``, même requête, même ordre (fin de session la plus
  récente avant l'instant de référence, puis la génération la plus récente) ;
  les deux surfaces ne peuvent pas diverger ;
- ``unsummarized_sessions`` : les sessions de travail closes d'aujourd'hui et
  d'hier qu'aucun résumé ne couvre, qu'elles précèdent ou suivent le résumé
  affiché : une session refusée avant une session résumée le même jour doit
  rester visible. Chacune porte ce que cette absence veut dire (``status``,
  voir ``_absence_status``). Core ne connaît pas l'état local d'Intelligence :
  d'une session éligible, il ne sait pas si elle a été refusée ou pas encore
  traitée, seulement qu'aucun résumé n'existe pour elle ;
- ``days`` : tous les résumés, par jour de session puis par session, chaque
  version coexistante conservée, la plus récemment générée en tête. Aucune
  version ne fait foi ici : chaque fiche porte sa ``prompt_version``.

Pur : un store, un instant de référence et un fuseau en entrée, un dict en
sortie. Même base, même instant → même dict.
"""

from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from .daily_trace import build_daily_trace
from .models import StoredActivity
from .runtime_config import reconstruction_timezone
from .summary_references import resolve_references
from .trace_store import TraceStore


SUMMARY_TYPE = "session_summary"
# Au-delà, la reprise en tête le dit explicitement : elle ne décrit plus la
# veille. L'âge se compte depuis la fin de la session résumée, comme
# ``age_minutes`` dans ``GET /context``.
STALE_AFTER = timedelta(hours=24)
# Jours locaux relus pour les sessions closes sans résumé : aujourd'hui et
# hier. Chaque jour coûte une reconstruction complète au rendu.
UNSUMMARIZED_LOOKBACK_DAYS = 2
# Seuils de candidature d'Intelligence, repris de la spec du 2026-09-03 (§7) :
# une session close est candidate au résumé si elle dure au moins 10 minutes
# ou compte au moins 30 activités ; sous les deux, jamais, sauf si elle porte
# au moins un ``git_commit`` (exception d'Intelligence depuis #98, 2026-09-16).
# Core ne lit pas la configuration d'Intelligence : ce sont les défauts de la
# spec, que la page affiche avec le compte des sessions qu'ils écartent.
CANDIDATE_MIN_MINUTES = 10
CANDIDATE_MIN_ACTIVITIES = 30


def build_summary_board(
    store: TraceStore,
    *,
    reference_at: datetime,
    local_timezone: tzinfo | None = None,
    traces_by_day: dict[date, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tout ce que les zones « Reprise » et « Résumés » du journal affichent.

    ``traces_by_day`` évite de reconstruire une journée que l'appelant a déjà
    reconstruite au même instant (la page d'accueil a celle du jour).
    """
    if reference_at.tzinfo is None:
        raise ValueError("reference_at must include a timezone")
    zone = local_timezone or reconstruction_timezone()
    reference_utc = reference_at.astimezone(timezone.utc)

    views = [
        _summary_view(stored, store=store, zone=zone, reference_at=reference_utc)
        for stored in store.activities_of_type(SUMMARY_TYPE, before=reference_utc)
    ]
    reprise = views[0] if views else None
    return {
        "reference_at": reference_utc.isoformat(),
        "summary_count": len(views),
        "session_count": len({view["session_id"] for view in views}),
        "reprise": reprise,
        "unsummarized_sessions": _unsummarized_sessions(
            store,
            views,
            reference_at=reference_utc,
            zone=zone,
            traces_by_day=traces_by_day or {},
        ),
        "unsummarized_days": [
            day.isoformat() for day in _lookback_days(reference_utc, zone)
        ],
        "candidate_thresholds": {
            "minutes": CANDIDATE_MIN_MINUTES,
            "activities": CANDIDATE_MIN_ACTIVITIES,
        },
        "days": _group_by_day(views),
    }


# --- Une fiche ---------------------------------------------------------------


def _summary_view(
    stored: StoredActivity,
    *,
    store: TraceStore,
    zone: tzinfo,
    reference_at: datetime,
) -> dict[str, Any]:
    details = stored.details
    reprise = details.get("reprise") if isinstance(details.get("reprise"), dict) else {}
    structured = (
        details.get("structured") if isinstance(details.get("structured"), dict) else {}
    )
    ended = _optional_instant(details.get("session_ended_at")) or stored.occurred_at
    started = _optional_instant(details.get("session_started_at"))
    workspace = details.get("workspace")
    if isinstance(workspace, dict):
        workspace = workspace.get("workspace_root")
    age_seconds = (reference_at - ended.astimezone(timezone.utc)).total_seconds()
    doing = _text(reprise.get("doing"))
    stopped_at = _text(reprise.get("stopped_at"))
    open_text = _text(reprise.get("open"))
    open_items = _open_items(details.get("open_items"))
    return {
        "event_id": stored.event_id,
        "session_id": str(details.get("session_id") or ""),
        "label": _text(details.get("session_label")),
        "session_date": _session_date(details.get("session_date"), started or ended, zone),
        "session_started_at": started.astimezone(timezone.utc).isoformat() if started else None,
        "session_ended_at": ended.astimezone(timezone.utc).isoformat(),
        "workspace": workspace if isinstance(workspace, str) and workspace else None,
        "project": _text(structured.get("project")),
        "prompt_version": _text(details.get("prompt_version")),
        "model_id": _text(details.get("model_id")),
        "generated_at": _text(details.get("generated_at")),
        "origin": "model_interpretation",
        "doing": doing,
        "stopped_at": stopped_at,
        "open": open_text,
        "open_items": open_items,
        # Références oN citées, résolues par la table ``observation_sources``
        # du résumé lui-même ; les bornes sont celles que le résumé déclare,
        # jamais ``occurred_at`` en repli : sans elles, rien ne se vérifie.
        "references": resolve_references(
            store,
            details,
            texts=[doing, stopped_at, open_text],
            open_items=open_items,
            started_at=started,
            ended_at=_optional_instant(details.get("session_ended_at")),
        ),
        "confidence": _text(structured.get("confidence")),
        "central_files": _texts(structured.get("central_files")),
        "age_minutes": max(0, int(age_seconds // 60)),
        "is_stale": age_seconds > STALE_AFTER.total_seconds(),
    }


def _open_items(value: Any) -> list[dict[str, Any]]:
    """Nature et preuves des points ouverts (prompts v3 et suivants).

    Le texte de chaque point voyage seulement dans ``reprise.open``, rédigé
    par Core : l'événement n'en porte que la nature et les références.

    « Rédigé » est ici le terme du dépôt pour le masquage des secrets
    (``redact_command``, appliqué à ``reprise.open`` à l'ingestion), pas pour
    l'écriture du texte : c'est Intelligence qui le compose
    (``render_open_items``), et Core qui le masque avant de le stocker.
    """
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("kind"), str):
            items.append(
                {"kind": item["kind"], "evidence": _texts(item.get("evidence"))}
            )
    return items


# --- Sessions closes sans résumé ----------------------------------------------


def _lookback_days(reference_at: datetime, zone: tzinfo) -> list[date]:
    today = reference_at.astimezone(zone).date()
    return [today - timedelta(days=offset) for offset in range(UNSUMMARIZED_LOOKBACK_DAYS)]


def _unsummarized_sessions(
    store: TraceStore,
    views: list[dict[str, Any]],
    *,
    reference_at: datetime,
    zone: tzinfo,
    traces_by_day: dict[date, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sessions closes des journées relues qu'aucun résumé ne couvre.

    Aucune borne relative au résumé affiché : une session refusée plus tôt
    dans la journée qu'une session résumée est exactement ce qu'il faut voir.

    Couverte : un résumé porte son identifiant, ou ses bornes chevauchent
    celles d'un résumé. Le second cas est une session dont l'identité a
    changé avec la reconstruction depuis que le résumé a été produit ; elle
    n'est pas silencieuse, un résumé existe pour ce temps-là.

    Toutes les sessions non couvertes sont rendues, chacune avec son
    ``status`` : durée et nombre d'activités sont calculés comme dans
    ``/context/sessions``, la vue qu'Intelligence classe.
    """
    summarized_ids = {view["session_id"] for view in views}
    summarized_bounds = [
        (_instant(view["session_started_at"]), _instant(view["session_ended_at"]))
        for view in views
        if view["session_started_at"]
    ]
    days = _lookback_days(reference_at, zone)
    today = days[0]
    found = []
    for day in reversed(days):
        trace = traces_by_day.get(day) or build_daily_trace(
            store, day, zone, now=reference_at
        )
        for session in trace["work_sessions"]:
            if session.get("activity_kind") != "work" or session.get("end_reason") == "open":
                continue
            started = _instant(session["started_at"])
            ended = _instant(session["ended_at"])
            if session["id"] in summarized_ids:
                continue
            if any(started < end and start < ended for start, end in summarized_bounds):
                continue
            duration_minutes = max(0, int((ended - started).total_seconds() // 60))
            activity_count = len(session["activities"])
            has_commit = any(
                activity["type"] == "git_commit" for activity in session["activities"]
            )
            found.append(
                {
                    "id": session["id"],
                    "label": session["label"],
                    "date": day.isoformat(),
                    "started_at": started.astimezone(timezone.utc).isoformat(),
                    "ended_at": ended.astimezone(timezone.utc).isoformat(),
                    "duration_minutes": duration_minutes,
                    "activity_count": activity_count,
                    "project": session.get("project_name"),
                    "status": _absence_status(
                        duration_minutes,
                        activity_count,
                        has_commit=has_commit,
                        day=day,
                        today=today,
                    ),
                }
            )
    found.sort(key=lambda item: (item["ended_at"], item["id"]), reverse=True)
    return found


def _absence_status(
    duration_minutes: int,
    activity_count: int,
    *,
    has_commit: bool,
    day: date,
    today: date,
) -> str:
    """Ce que l'absence de résumé veut dire pour une session close.

    - ``below_threshold`` : sous les deux seuils de candidature et sans
      commit, Intelligence ne la résumera jamais ; une session qui porte un
      ``git_commit`` est candidate quelle que soit sa durée ;
    - ``pending`` : éligible et d'aujourd'hui, elle attend le lot du matin,
      qui résume la veille ;
    - ``missing`` : éligible et d'un jour passé, le lot aurait dû la résumer.
      Refus, abandon, ou lot pas encore passé entre minuit et sa fin : Core
      ne sait pas lequel.
    """
    if (
        not has_commit
        and duration_minutes < CANDIDATE_MIN_MINUTES
        and activity_count < CANDIDATE_MIN_ACTIVITIES
    ):
        return "below_threshold"
    return "pending" if day == today else "missing"


# --- Regroupement -------------------------------------------------------------


def _group_by_day(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Jours du plus récent au plus ancien, sessions par fin décroissante.

    ``views`` arrive déjà trié (fin de session puis ligne, décroissants) : la
    première fiche rencontrée pour une session est sa génération la plus
    récente, et l'ordre d'insertion des dicts suffit.
    """
    sessions: dict[str, dict[str, Any]] = {}
    for view in views:
        key = view["session_id"] or view["event_id"]
        group = sessions.get(key)
        if group is None:
            group = sessions[key] = {
                "session_id": view["session_id"],
                "label": view["label"],
                "date": view["session_date"],
                "session_started_at": view["session_started_at"],
                "session_ended_at": view["session_ended_at"],
                "project": view["project"],
                "workspace": view["workspace"],
                "summaries": [],
            }
        group["summaries"].append(view)
    days: dict[str, list[dict[str, Any]]] = {}
    for group in sessions.values():
        days.setdefault(group["date"], []).append(group)
    return [
        {"date": day, "sessions": days[day]}
        for day in sorted(days, reverse=True)
    ]


# --- Lecture défensive ---------------------------------------------------------


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = _instant(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _session_date(value: Any, fallback: datetime, zone: tzinfo) -> str:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    return fallback.astimezone(zone).date().isoformat()


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
