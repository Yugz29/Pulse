"""Rendu HTML du bloc « Session en cours » (``live_session.build_live_session``).

Chaque ligne est un fait observé, ancré (``id="fait-live-oN"``) et affiché
comme les faits cités par un résumé (``summaries.render_fact``). Tout texte
passe par ``html.escape``. Aucun script : la page se recharge à la main.
"""

from datetime import datetime, tzinfo
from html import escape
from typing import Any

from ..summary_references import RESOLVED
from .summaries import render_fact


NAVIGATION = '<a class="nav-main" href="#session-en-cours">Session en cours</a>'

CSS = """
.live-session{border-top:3px solid #6fa287}
.live-session h3{font-size:.95rem;margin:1rem 0 .3rem;color:#a9d3b8}
.live-session .live-empty{margin:.2rem 0;color:var(--muted);font-size:.88rem}
.live-session .live-more{margin:.3rem 0 0;color:var(--muted);font-size:.84rem}
.live-session .summary-facts{margin:.2rem 0 0;border-left-color:#35503f}
"""

_CHANGE_LABELS = {"created": "créé", "modified": "modifié", "deleted": "supprimé"}


def render_live_session(live: dict[str, Any], zone: tzinfo) -> str:
    started = _local(live["started_at"], zone)
    last = _local(live["last_activity_at"], zone)
    parts = [
        '<section class="current live-session" id="session-en-cours">',
        "<h2>Session en cours</h2>",
        '<p class="meta">'
        f"Depuis {escape(started.strftime('%H:%M'))} · {live['duration_minutes']} min · "
        f"{live['activity_count']} activité(s), {live['fact_count']} fait(s) · "
        f"dernier fait à {escape(last.strftime('%H:%M:%S'))} · "
        f'<a href="#session-{live["session_index"]}">chronologie complète</a>. '
        "Faits observés par Core, rangés sans modèle ; les références oN sont "
        "celles de cet instant, elles peuvent encore bouger tant que la session "
        "est ouverte.</p>",
    ]
    parts.append(_commits(live, zone))
    parts.append(_files(live, zone))
    parts.append(_last_test(live, zone))
    parts.append(_failures(live, zone))
    parts.append(_agent_sessions(live, zone))
    parts.append("</section>")
    return "".join(parts)


def _fact(fact: dict[str, Any], zone: tzinfo, *, scope: str = "") -> str:
    """``scope`` garde les ancres uniques : le dernier test, s'il a échoué,
    est aussi dans les échecs."""
    if fact["at"] is None:
        return ""
    return render_fact(
        {**fact, "status": RESOLVED},
        zone,
        anchor=escape(f"fait-live-{scope}{fact['ref']}", quote=True),
    )


def _facts(items: list[str]) -> str:
    return f'<div class="summary-facts">{"".join(items)}</div>'


def _commits(live: dict[str, Any], zone: tzinfo) -> str:
    commits = live["commits"]
    if not commits:
        return '<h3>Commits</h3><p class="live-empty">Aucun commit dans cette session.</p>'
    return f"<h3>Commits ({len(commits)})</h3>" + _facts(
        [_fact(commit, zone) for commit in commits]
    )


def _files(live: dict[str, Any], zone: tzinfo) -> str:
    if not live["files"]:
        return (
            '<h3>Fichiers les plus touchés</h3>'
            '<p class="live-empty">Aucun fichier modifié dans cette session.</p>'
        )
    items = []
    for entry in live["files"]:
        refs = ", ".join(f"<code>{escape(ref)}</code>" for ref in entry["refs"])
        changes = ", ".join(
            f"{_CHANGE_LABELS.get(event, event)} ×{count}"
            for event, count in entry["changes"].items()
        )
        last = (
            f" · dernier changement à {escape(_local(entry['last_at'], zone).strftime('%H:%M:%S'))}"
            if entry["last_at"]
            else ""
        )
        anchor = escape(f"fait-live-{entry['refs'][0]}", quote=True)
        items.append(
            f'<div class="summary-fact" id="{anchor}">{refs} · fichier · '
            f"<code>{escape(entry['path'])}</code> · {escape(changes)}{last}</div>"
        )
    more = live["file_count"] - len(live["files"])
    tail = (
        f'<p class="live-more">et {more} autre(s) fichier(s), moins touché(s).</p>'
        if more > 0
        else ""
    )
    return f"<h3>Fichiers les plus touchés ({live['file_count']})</h3>" + _facts(items) + tail


def _last_test(live: dict[str, Any], zone: tzinfo) -> str:
    test = live["last_test"]
    if test is None:
        return '<h3>Dernier test</h3><p class="live-empty">Aucune commande de test observée.</p>'
    counts = (
        f'<p class="live-more">{live["test_count"]} commande(s) de test dans la session, '
        f'dont {live["failed_test_count"]} en échec.</p>'
    )
    return "<h3>Dernier test</h3>" + _facts([_fact(test, zone, scope="test-")]) + counts


def _failures(live: dict[str, Any], zone: tzinfo) -> str:
    failures = live["failures"]
    if not failures:
        return (
            '<h3>Commandes en échec</h3>'
            '<p class="live-empty">Aucune commande en échec observée.</p>'
        )
    more = live["failure_count"] - len(failures)
    tail = f'<p class="live-more">et {more} échec(s) plus ancien(s).</p>' if more > 0 else ""
    note = (
        '<p class="live-more">Échecs bruts, du plus récent au plus ancien : code et heure '
        "observés. Core ne dit pas si un échec a été corrigé depuis.</p>"
    )
    return (
        f"<h3>Commandes en échec ({live['failure_count']})</h3>"
        + _facts([_fact(failure, zone) for failure in failures])
        + tail
        + note
    )


def _agent_sessions(live: dict[str, Any], zone: tzinfo) -> str:
    sessions = live["agent_sessions"]
    if not sessions:
        return (
            '<h3>Sessions d’agent terminées</h3>'
            '<p class="live-empty">Aucune session d’agent terminée depuis le début '
            "de la session.</p>"
        )
    items = []
    for index, view in enumerate(sessions, start=1):
        bounds = _local(view["ended_at"], zone).strftime("%H:%M")
        if view["started_at"]:
            bounds = f"{_local(view['started_at'], zone).strftime('%H:%M')}–{bounds}"
        items.append(
            f'<div class="summary-fact" id="fait-live-agent-{index}">session d’agent · '
            f"{escape(bounds)} · {escape(str(view['summary']))}</div>"
        )
    return (
        f"<h3>Sessions d’agent terminées ({len(sessions)})</h3>"
        + _facts(items)
        + '<p class="live-more">Rapprochées par le temps : elles ne composent pas la '
        'session de travail. Liste du jour : <a href="#sessions-agent">Sessions d’agent</a>.</p>'
    )


def _local(value: str, zone: tzinfo) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(zone)
