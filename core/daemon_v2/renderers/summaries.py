"""Rendu HTML des zones « Reprise » et « Résumés » de la page d'accueil.

Entrée : le dict de ``session_summaries.build_summary_board``. Tout texte
passe par ``html.escape`` ; les résumés sont marqués comme interprétation du
modèle, jamais présentés comme des faits observés.
"""

from datetime import datetime, tzinfo
from html import escape
from typing import Any


NAVIGATION = (
    '<a class="nav-main" href="#reprise">Reprise</a>',
    '<a class="nav-main" href="#resumes">Résumés</a>',
)
LEAD_LENGTH = 110

CSS = """
.model-reprise,.model-summaries{background:var(--panel);border:1px solid var(--border);
border-radius:12px;padding:1.25rem 1.5rem;margin:1.25rem 0;box-shadow:0 8px 24px #0003}
.model-reprise{border-top:3px solid #c9a15f}.model-summaries{border-top:3px solid #a88d5f}
.model-reprise h2,.model-summaries h2{font-size:1.2rem;margin:0 0 1rem}
.summary-reprise{display:grid;grid-template-columns:10rem minmax(0,1fr);gap:.45rem 1rem;margin:0}
.summary-reprise dt{font-weight:650;color:#d6bd8f}.summary-reprise dd{margin:0;min-width:0;
overflow-wrap:anywhere;color:#dde3ea}
.summary-card{padding:.2rem 0}.summary-card+.summary-card{margin-top:1rem;padding-top:1rem;
border-top:1px dashed var(--border)}
.summary-meta{margin:.8rem 0 0;color:var(--muted);font-size:.84rem;overflow-wrap:anywhere}
.summary-meta code,.summary-extra code{background:#222a33;color:#c3ccd6;padding:.05rem .3rem;
border:1px solid #303b47;border-radius:5px;font-size:.8rem}
.summary-extra{margin:.5rem 0 0;color:#b8c2cd;font-size:.88rem;overflow-wrap:anywhere}
.prompt-version{display:inline-block;background:#3a2f1c;border:1px solid #6b5630;color:#f0cf95;
border-radius:999px;padding:0 .45rem;font-size:.76rem;font-weight:700;margin-right:.2rem;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.summary-alert{margin:0 0 1rem;padding:.7rem .9rem;border-radius:8px;background:#3a2023;
border:1px solid #6d363d;color:#f0c2c6}.summary-alert h3{margin:0 0 .35rem;font-size:.95rem;
color:#f3cdd1}.summary-alert ul{margin:.2rem 0;padding-left:1.2rem}
.summary-alert p{margin:.35rem 0 0;font-size:.84rem;color:#d9a9ae}
.summary-stale{margin:0 0 1rem;padding:.55rem .9rem;border-radius:8px;background:#3a331c;
border:1px solid #6b5f30;color:#efdca6;font-weight:600}
.summary-day{font-size:.95rem;color:#aebdcb;margin:1.2rem 0 .4rem;
font-variant-numeric:tabular-nums}.summary-day:first-of-type{margin-top:.2rem}
.summary-session{border-top:1px solid var(--border)}.summary-session>summary{cursor:pointer;
padding:.5rem .2rem;color:#cbd5e1;overflow-wrap:anywhere}
.summary-session>summary .time{color:var(--muted);font-variant-numeric:tabular-nums;
margin-right:.35rem}.summary-session>summary .lead{color:#9aa6b4}
.summary-session[open]>summary{color:#e4eaf1}
.summary-session>div{padding:.4rem .2rem 1rem 1.1rem}
.versions-note{margin:0 0 .6rem;color:var(--muted);font-size:.84rem}
@media(max-width:850px){.summary-reprise{grid-template-columns:1fr;gap:.1rem}
.summary-reprise dd{margin-bottom:.45rem}.model-reprise,.model-summaries{padding:1rem}}
"""


def render_summary_zones(board: dict[str, Any], zone: tzinfo) -> list[str]:
    """Les deux sections, dans l'ordre de la page."""
    return [_render_reprise(board, zone), _render_summaries(board, zone)]


# --- Zone 1 : Reprise ------------------------------------------------------------


def _render_reprise(board: dict[str, Any], zone: tzinfo) -> str:
    reprise = board["reprise"]
    parts = ['<section class="model-reprise" id="reprise">', "<h2>Reprise</h2>"]
    parts.append(_render_unsummarized(board, zone))
    if reprise is None:
        parts.append("<p>Aucun résumé de session stocké.</p>")
    else:
        if reprise["is_stale"]:
            parts.append(
                '<p class="summary-stale">Résumé de plus de 24 h : la session '
                f"résumée s’est terminée {escape(_age_label(reprise['age_minutes']))}."
                "</p>"
            )
        parts.append(_render_card(reprise, zone))
    parts.append("</section>")
    return "".join(parts)


def _render_unsummarized(board: dict[str, Any], zone: tzinfo) -> str:
    sessions = board["unsummarized_sessions"]
    if not sessions:
        return ""
    scope = " et ".join(board["unsummarized_days"])
    heading = f"{len(sessions)} session(s) close(s) sans résumé"
    items = []
    for session in sessions:
        project = f" · {escape(session['project'])}" if session["project"] else ""
        items.append(
            "<li>"
            f"{escape(_bounds_label(session['started_at'], session['ended_at'], zone))}"
            f" · {escape(session['label'])} · <code>{escape(session['id'])}</code>"
            f" · {session['duration_minutes']} min · {session['activity_count']} activité(s)"
            f"{project}</li>"
        )
    return (
        '<div class="summary-alert">'
        f"<h3>{escape(heading)}</h3>"
        f"<ul>{''.join(items)}</ul>"
        f"<p>Journées relues : {escape(scope)}. Core ne sait pas si Intelligence "
        "a refusé ces sessions, les a écartées ou ne les a pas encore "
        "traitées : seulement qu’aucun résumé ne les couvre.</p>"
        "</div>"
    )


# --- Zone 2 : Résumés ------------------------------------------------------------


def _render_summaries(board: dict[str, Any], zone: tzinfo) -> str:
    parts = ['<section class="model-summaries" id="resumes">', "<h2>Résumés</h2>"]
    days = board["days"]
    if not days:
        parts.append("<p>Aucun résumé de session stocké.</p></section>")
        return "".join(parts)
    multi = sum(
        len(session["summaries"]) > 1 for day in days for session in day["sessions"]
    )
    parts.append(
        f'<p class="meta">{board["summary_count"]} résumé(s) · '
        f'{board["session_count"]} session(s) · '
        f"{multi} session(s) à plusieurs versions · repliés, le plus récent en haut</p>"
    )
    for day in days:
        parts.append(f'<h3 class="summary-day">{escape(day["date"])}</h3>')
        for session in day["sessions"]:
            parts.append(_render_session(session, zone))
    parts.append("</section>")
    return "".join(parts)


def _render_session(session: dict[str, Any], zone: tzinfo) -> str:
    summaries = session["summaries"]
    latest = summaries[0]
    bounds = (
        _time_range(session["session_started_at"], session["session_ended_at"], zone)
        if session["session_started_at"]
        else _local(session["session_ended_at"], zone).strftime("%H:%M")
    )
    versions = "".join(_prompt_badge(view["prompt_version"]) for view in summaries)
    label = escape(session["label"] or session["session_id"])
    project = f" · {escape(session['project'])}" if session["project"] else ""
    lead = f' · <span class="lead">{escape(_lead(latest["doing"]))}</span>' if latest["doing"] else ""
    note = (
        f'<p class="versions-note">{len(summaries)} versions coexistantes, la plus '
        "récemment générée en premier. Aucune ne fait foi ici.</p>"
        if len(summaries) > 1
        else ""
    )
    anchor = f' id="resume-session-{escape(session["session_id"])}"' if session["session_id"] else ""
    return (
        f'<details class="summary-session"{anchor}>'
        f'<summary><span class="time">{escape(bounds)}</span>{label}{project} · '
        f"{versions}{lead}</summary>"
        f"<div>{note}{''.join(_render_card(view, zone) for view in summaries)}</div>"
        "</details>"
    )


# --- Une fiche ---------------------------------------------------------------------


def _render_card(view: dict[str, Any], zone: tzinfo) -> str:
    rows = [
        ("En cours", view["doing"]),
        ("Arrêté à", view["stopped_at"]),
        ("Reste ouvert", view["open"]),
    ]
    reprise = "".join(
        f"<dt>{label}</dt><dd>{escape(value) if value else '—'}</dd>"
        for label, value in rows
    )
    extras = []
    if view["open_items"]:
        natures = ", ".join(
            f"<code>{escape(item['kind'])}</code>"
            + (f" ({escape(', '.join(item['evidence']))})" if item["evidence"] else "")
            for item in view["open_items"]
        )
        extras.append(f'<p class="summary-extra">Nature des points ouverts : {natures}</p>')
    if view["central_files"]:
        files = ", ".join(f"<code>{escape(path)}</code>" for path in view["central_files"])
        extras.append(f'<p class="summary-extra">Fichiers centraux : {files}</p>')
    return (
        '<article class="summary-card">'
        f'<dl class="summary-reprise">{reprise}</dl>'
        f"{''.join(extras)}"
        f'<p class="summary-meta">{_meta(view, zone)}</p>'
        "</article>"
    )


def _meta(view: dict[str, Any], zone: tzinfo) -> str:
    bounds = (
        _bounds_label(view["session_started_at"], view["session_ended_at"], zone)
        if view["session_started_at"]
        else f"fin {_local(view['session_ended_at'], zone).strftime('%Y-%m-%d %H:%M')}"
    )
    pieces = [_prompt_badge(view["prompt_version"])]
    if view["label"]:
        pieces.append(escape(view["label"]))
    if view["session_id"]:
        pieces.append(f"<code>{escape(view['session_id'])}</code>")
    pieces.append(escape(bounds))
    if view["project"]:
        pieces.append(escape(view["project"]))
    if view["model_id"]:
        pieces.append(escape(view["model_id"]))
    generated = _optional_local(view["generated_at"], zone)
    if generated is not None:
        pieces.append(f"généré le {generated.strftime('%Y-%m-%d %H:%M')}")
    if view["confidence"]:
        pieces.append(f"confiance {escape(view['confidence'])}")
    pieces.append("interprétation du modèle")
    return " · ".join(pieces)


# --- Formats -------------------------------------------------------------------------


def _prompt_badge(version: str | None) -> str:
    return f'<span class="prompt-version">{escape(version or "version inconnue")}</span>'


def _lead(text: str) -> str:
    first = text.splitlines()[0]
    return first if len(first) <= LEAD_LENGTH else f"{first[:LEAD_LENGTH - 1].rstrip()}…"


def _local(value: str, zone: tzinfo) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(zone)


def _optional_local(value: str | None, zone: tzinfo) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(zone) if parsed.tzinfo is not None else None


def _time_range(started_at: str, ended_at: str, zone: tzinfo) -> str:
    return f"{_local(started_at, zone).strftime('%H:%M')}–{_local(ended_at, zone).strftime('%H:%M')}"


def _bounds_label(started_at: str, ended_at: str, zone: tzinfo) -> str:
    start = _local(started_at, zone)
    end = _local(ended_at, zone)
    end_format = "%H:%M" if start.date() == end.date() else "%Y-%m-%d %H:%M"
    return f"{start.strftime('%Y-%m-%d %H:%M')}–{end.strftime(end_format)}"


def _age_label(minutes: int) -> str:
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days:
        return f"il y a {days} j {hours} h"
    if hours:
        return f"il y a {hours} h {mins:02d} min"
    return f"il y a {mins} min"
