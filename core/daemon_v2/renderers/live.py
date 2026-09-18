"""Rendu HTML du bloc « Session en cours » (``live_session.build_live_session``).

Chaque ligne est un fait observé, ancré (``id="fait-live-oN"``) et affiché
comme les faits cités par un résumé (``summaries.render_fact``). Tout texte
passe par ``html.escape``. Aucun script : la page se recharge à la main.
"""

from datetime import datetime, tzinfo
from html import escape
from typing import Any

from ..agent_transcript import MAX_COMMANDS as MAX_AGENT_COMMANDS
from ..summary_references import RESOLVED
from .summaries import render_fact


NAVIGATION = '<a class="nav-main" href="#session-en-cours">Session en cours</a>'

CSS = """
.live-session{border-top:3px solid #6fa287}
.live-session h3{font-size:.95rem;margin:1rem 0 .3rem;color:#a9d3b8}
.live-session .live-empty{margin:.2rem 0;color:var(--muted);font-size:.88rem}
.live-session .live-more{margin:.3rem 0 0;color:var(--muted);font-size:.84rem}
.live-session .summary-facts{margin:.2rem 0 0;border-left-color:#35503f}
.live-session .live-sub{margin:.4rem 0 .1rem;font-size:.84rem;color:#a9d3b8}
.live-session .live-agent-head{border-bottom:1px solid #35503f;padding-bottom:.2rem}
.live-session .live-fail .live-outcome{color:#e07070;font-weight:600}
.live-session .live-stop .live-outcome{color:var(--muted)}
.live-session .live-ok .live-outcome{color:#6fa287}
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
    parts.append(_live_agents(live, zone))
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


_OUTCOME_LABELS = {"ok": "ok", "échec": "échec", "interrompue": "interrompue"}
_OUTCOME_CLASS = {"ok": "live-ok", "échec": "live-fail", "interrompue": "live-stop"}


def _live_agents(live: dict[str, Any], zone: tzinfo) -> str:
    """Étape 1 bis : les sessions Claude Code vivantes, depuis leur transcript.

    Rien ici ne vient de ``trace.db`` ; rien n'est stocké. Commande et
    description sont déjà passées par ``redact_command`` ; ``stdout``,
    ``stderr``, le prompt et le motif d'un ``Exit code`` ne sont jamais lus.
    Sans dossier d'état (hooks non installés), la clé ``agents`` est vide et
    la sous-section dit seulement qu'aucune session vivante n'est connue.
    """
    agents = live.get("agents") or []
    if not agents:
        return (
            "<h3>Claude Code en cours</h3>"
            '<p class="live-empty">Aucune session Claude Code vivante connue '
            "(hooks d’état d’agent non installés, ou aucune session ouverte).</p>"
        )
    parts = [f"<h3>Claude Code en cours ({len(agents)})</h3>"]
    for index, agent in enumerate(agents, start=1):
        parts.append(_live_agent(agent, index, zone))
    parts.append(
        '<p class="live-more">Lu dans le transcript de chaque session, sans modèle et '
        "hors trace.db : commandes et descriptions masquées comme les commandes du "
        "shell ; jamais la sortie ni le prompt. Les commandes d’un agent n’entrent "
        "pas dans <code>/context</code> ni dans le résumé de nuit.</p>"
    )
    return "".join(parts)


def _live_agent(agent: dict[str, Any], index: int, zone: tzinfo) -> str:
    since = _local(agent["since"], zone).strftime("%H:%M") if agent.get("since") else "?"
    head = (
        f'<div class="summary-fact live-agent-head" id="fait-live-agent-live-{index}">'
        f"<strong>{escape(str(agent.get('project') or '?'))}</strong> · "
        f"{escape(agent['state_label'])} depuis {escape(since)} · "
        f"<code>{escape(str(agent.get('session_id', ''))[:8])}</code>"
        f"{' · ' + escape(str(agent['cwd'])) if agent.get('cwd') else ''}</div>"
    )
    transcript = agent.get("transcript")
    if transcript is None:
        return _facts([head, '<div class="summary-fact live-empty">Transcript introuvable ou illisible.</div>'])
    items = [head]
    items.append(_agent_commands(transcript, index, zone))
    items.append(_agent_last_test(transcript, index, zone))
    items.append(_agent_failures(transcript, index, zone))
    items.append(_agent_files(transcript, index, zone))
    if transcript["skipped_lines"]:
        items.append(
            f'<div class="summary-fact live-empty">{transcript["skipped_lines"]} ligne(s) du transcript ignorée(s) (format inconnu).</div>'
        )
    return _facts(items)


def _agent_command_line(command: dict[str, Any], zone: tzinfo, anchor: str) -> str:
    when = _local(command["at"], zone).strftime("%H:%M:%S") if command.get("at") else "?"
    outcome = command.get("outcome") or "?"
    label = _OUTCOME_LABELS.get(outcome, outcome)
    css = _OUTCOME_CLASS.get(outcome, "")
    description = f"{escape(command['description'])} · " if command.get("description") else ""
    test = " · test" if command.get("test_command") else ""
    return (
        f'<div class="summary-fact {css}" id="{escape(anchor, quote=True)}">'
        f"{escape(when)} · {description}<code>{escape(command['command'])}</code> · "
        f"<span class=\"live-outcome\">{escape(label)}</span>{test}</div>"
    )


def _agent_commands(transcript: dict[str, Any], index: int, zone: tzinfo) -> str:
    commands = transcript["commands"]
    if not commands:
        return '<div class="summary-fact live-empty">Aucune commande dans le transcript.</div>'
    shown = commands[-MAX_AGENT_COMMANDS:]
    lines = [f'<div class="live-sub">Dernières commandes ({len(shown)} sur {transcript["command_count"]})</div>']
    for position, command in enumerate(reversed(shown), start=1):
        lines.append(_agent_command_line(command, zone, f"fait-live-agent-live-{index}-cmd-{position}"))
    return "".join(lines)


def _agent_last_test(transcript: dict[str, Any], index: int, zone: tzinfo) -> str:
    test = transcript["last_test"]
    if test is None:
        return '<div class="summary-fact live-empty">Dernier test : aucune commande de test dans le transcript.</div>'
    return (
        '<div class="live-sub">Dernier test</div>'
        + _agent_command_line(test, zone, f"fait-live-agent-live-{index}-test")
        + f'<div class="summary-fact live-empty">{transcript["test_count"]} commande(s) de test, '
        f'dont {transcript["failed_test_count"]} en échec.</div>'
    )


def _agent_failures(transcript: dict[str, Any], index: int, zone: tzinfo) -> str:
    failures = transcript["failures"]
    if not failures:
        return '<div class="summary-fact live-empty">Aucune commande en échec dans le transcript.</div>'
    lines = [f'<div class="live-sub">Échecs bruts ({transcript["failure_count"]}, du plus récent au plus ancien)</div>']
    for position, failure in enumerate(failures, start=1):
        lines.append(_agent_command_line(failure, zone, f"fait-live-agent-live-{index}-fail-{position}"))
    more = transcript["failure_count"] - len(failures)
    if more > 0:
        lines.append(f'<div class="summary-fact live-empty">et {more} échec(s) plus ancien(s).</div>')
    return "".join(lines)


def _agent_files(transcript: dict[str, Any], index: int, zone: tzinfo) -> str:
    files = transcript["files"]
    if not files:
        return '<div class="summary-fact live-empty">Aucun fichier écrit par l’agent (Edit/Write).</div>'
    lines = [f'<div class="live-sub">Fichiers écrits par l’agent ({transcript["file_count"]})</div>']
    for position, entry in enumerate(files, start=1):
        changes = ", ".join(f"{event} ×{count}" for event, count in entry["changes"].items())
        last = f" · dernier à {escape(_local(entry['last_at'], zone).strftime('%H:%M:%S'))}" if entry.get("last_at") else ""
        lines.append(
            f'<div class="summary-fact" id="fait-live-agent-live-{index}-file-{position}">'
            f"<code>{escape(entry['path'])}</code> · {escape(changes)}{last}</div>"
        )
    more = transcript["file_count"] - len(files)
    if more > 0:
        lines.append(f'<div class="summary-fact live-empty">et {more} autre(s) fichier(s).</div>')
    return "".join(lines)


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
