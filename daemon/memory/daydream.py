"""
daydream.py -- Consolidation nocturne de Pulse.

DayDream est declenche une fois par jour, au premier screen_lock apres 23:59.
Il lit le journal du jour, les titres de fenetres accumules, et produit :
  1. Un fichier Markdown lisible : ~/.pulse/memory/daydreams/YYYY-MM-DD.md
  2. Une entree vectorisee dans vectors.db (kind="daydream")
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("pulse.daydream")

DAYDREAM_DIR = Path.home() / ".pulse" / "memory" / "daydreams"
_JOURNAL_DATA_START = "<!-- pulse-journal-data:start"
_JOURNAL_DATA_END = "pulse-journal-data:end -->"

_daydream_pending = False
_daydream_lock = threading.Lock()
_daydream_done_for_date: Optional[date] = None
_daydream_target_date: Optional[date] = None
_daydream_status = "idle"
_daydream_last_reason: Optional[str] = None
_daydream_last_error: Optional[str] = None
_daydream_last_attempt_at: Optional[datetime] = None
_daydream_last_completed_at: Optional[datetime] = None
_daydream_last_output_path: Optional[str] = None


def mark_daydream_pending(ref_date: Optional[date] = None) -> bool:
    global _daydream_pending, _daydream_target_date, _daydream_status, _daydream_last_reason
    with _daydream_lock:
        target_date = ref_date or date.today()
        if _daydream_status == "running" and _daydream_target_date == target_date:
            log.info("DayDream : execution deja en cours pour %s.", target_date)
            return False
        if _daydream_pending and _daydream_target_date == target_date:
            log.info("DayDream : deja en attente pour %s.", target_date)
            return False
        _daydream_pending = True
        _daydream_target_date = target_date
        _daydream_status = "pending"
        _daydream_last_reason = "awaiting_screen_lock"
    log.info("DayDream : en attente du prochain screen_lock pour %s.", target_date)
    return True


def should_trigger_daydream() -> bool:
    with _daydream_lock:
        if not _daydream_pending:
            return False
        if _daydream_status == "running":
            return False
        target_date = _daydream_target_date or date.today()
        if _daydream_done_for_date == target_date:
            return False
        return True


def get_daydream_status() -> dict[str, Any]:
    with _daydream_lock:
        return {
            "status": _daydream_status,
            "pending": _daydream_pending,
            "target_date": _daydream_target_date.isoformat() if _daydream_target_date else None,
            "done_for_date": _daydream_done_for_date.isoformat() if _daydream_done_for_date else None,
            "last_reason": _daydream_last_reason,
            "last_error": _daydream_last_error,
            "last_attempt_at": _daydream_last_attempt_at.isoformat() if _daydream_last_attempt_at else None,
            "last_completed_at": _daydream_last_completed_at.isoformat() if _daydream_last_completed_at else None,
            "last_output_path": _daydream_last_output_path,
        }


def claim_daydream_run(today: Optional[date] = None) -> Optional[date]:
    global _daydream_pending
    global _daydream_status
    global _daydream_target_date
    global _daydream_done_for_date
    global _daydream_last_reason
    global _daydream_last_attempt_at
    global _daydream_last_completed_at
    global _daydream_last_output_path
    global _daydream_last_error

    with _daydream_lock:
        ref_date = _daydream_target_date or today or date.today()
        if not _daydream_pending:
            return None
        if _daydream_status == "running":
            log.info("DayDream : execution deja en cours pour %s.", ref_date)
            return None
        if _daydream_done_for_date == ref_date:
            _daydream_pending = False
            _daydream_status = "skipped"
            _daydream_last_reason = "already_completed_for_date"
            return None

        existing_path = _daydream_output_path(ref_date)
        if existing_path.exists():
            _daydream_pending = False
            _daydream_done_for_date = ref_date
            _daydream_status = "generated"
            _daydream_last_reason = "already_exists"
            _daydream_last_completed_at = datetime.now()
            _daydream_last_output_path = str(existing_path)
            _daydream_last_error = None
            log.info("DayDream : fichier deja present pour %s (%s).", ref_date, existing_path)
            return None

        _daydream_pending = False
        _daydream_status = "running"
        _daydream_target_date = ref_date
        _daydream_last_reason = "running"
        _daydream_last_attempt_at = datetime.now()
        _daydream_last_error = None
        return ref_date


def trigger_daydream(
    llm: Optional[Any] = None,
    window_titles: Optional[list[str]] = None,
    today: Optional[date] = None,
    ref_date: Optional[date] = None,
) -> Optional[Path]:
    global _daydream_done_for_date
    global _daydream_target_date
    global _daydream_status
    global _daydream_last_reason
    global _daydream_last_error
    global _daydream_last_completed_at
    global _daydream_last_output_path

    try:
        claimed_ref_date = ref_date or claim_daydream_run(today=today)
        if claimed_ref_date is None:
            return None

        journal_entries = _load_journal_entries_for_date(claimed_ref_date)
        if not journal_entries:
            log.info("DayDream : aucune entree journal pour %s -- ignore.", claimed_ref_date)
            with _daydream_lock:
                _daydream_done_for_date = claimed_ref_date
                _daydream_target_date = None
                _daydream_status = "skipped"
                _daydream_last_reason = "no_journal_entries"
                _daydream_last_completed_at = datetime.now()
                _daydream_last_output_path = None
            return None

        content = _generate_daydream(
            entries=journal_entries,
            window_titles=window_titles or [],
            ref_date=claimed_ref_date,
            llm=llm,
        )

        output_path = _write_daydream(content, claimed_ref_date)
        _vectorize_daydream(content, claimed_ref_date)

        with _daydream_lock:
            _daydream_done_for_date = claimed_ref_date
            _daydream_target_date = None
            _daydream_status = "generated"
            _daydream_last_reason = "generated"
            _daydream_last_completed_at = datetime.now()
            _daydream_last_output_path = str(output_path)
            _daydream_last_error = None

        log.info("DayDream genere : %s", output_path)
        return output_path

    except Exception as exc:
        log.warning("DayDream : erreur inattendue : %s", exc)
        with _daydream_lock:
            _daydream_target_date = ref_date or _daydream_target_date
            _daydream_status = "failed"
            _daydream_last_reason = "unexpected_error"
            _daydream_last_error = str(exc)
            _daydream_last_completed_at = datetime.now()
        return None


def _load_journal_entries_for_date(ref_date: date) -> list[dict]:
    from daemon.memory.extractor import MEMORY_DIR
    journal_path = MEMORY_DIR / "sessions" / f"{ref_date}.md"
    if not journal_path.exists():
        return []

    content = journal_path.read_text(encoding="utf-8")
    start = content.find(_JOURNAL_DATA_START)
    end = content.find(_JOURNAL_DATA_END)
    if start == -1 or end == -1:
        return []

    raw = content[start + len(_JOURNAL_DATA_START):end].strip()
    try:
        entries = json.loads(raw)
        return [e for e in entries if isinstance(e, dict)]
    except Exception as exc:
        log.warning("DayDream : erreur lecture journal %s : %s", journal_path, exc)
        return []


def _generate_daydream(
    entries: list[dict],
    window_titles: list[str],
    ref_date: date,
    llm: Optional[Any],
) -> dict:
    projects = _extract_projects(entries)
    tasks = _extract_tasks(entries)
    top_files = _extract_top_files(entries)
    commits = _extract_commits(entries)
    total_min = sum(int(e.get("duration_min") or 0) for e in entries)
    cleaned_titles = _filter_window_titles(window_titles)

    if llm is not None:
        try:
            narrative = _llm_narrative(llm, entries, commits, top_files, cleaned_titles, total_min)
        except Exception as exc:
            log.warning("DayDream : LLM echoue, fallback deterministe : %s", exc)
            narrative = _deterministic_narrative(entries, commits, total_min)
    else:
        narrative = _deterministic_narrative(entries, commits, total_min)

    return {
        "date": str(ref_date),
        "narrative": narrative,
        "projects": projects,
        "tasks": tasks,
        "top_files": top_files,
        "commits": commits,
        "window_titles": cleaned_titles[:20],
        "total_min": total_min,
        "entry_count": len(entries),
    }


def _llm_narrative(
    llm: Any,
    entries: list[dict],
    commits: list[str],
    top_files: list[str],
    window_titles: list[str],
    total_min: int,
) -> str:
    entries_text = "\n".join(
        "- " + e.get("started_at", "")[:16] + " -> " + e.get("probable_task", "general") +
        " (" + str(e.get("duration_min", 0)) + " min) : " + e.get("body", "")[:100]
        for e in entries
        if not _is_noise_entry(e)
    )
    commits_text = "\n".join("- " + c for c in commits[:8])
    titles_text = "\n".join("- " + t for t in window_titles[:10])

    prompt = (
        "Tu es Pulse, un assistant de developpement qui observe le travail.\n"
        "Voici les donnees de la journee :\n\n"
        "Sessions de travail :\n" + (entries_text or "Aucune session notable.") + "\n\n"
        "Commits :\n" + (commits_text or "Aucun commit.") + "\n\n"
        "Pages consultees :\n" + (titles_text or "Non capturees.") + "\n\n"
        "Duree totale : " + str(total_min) + " minutes.\n\n"
        "Ecris une synthese narrative de 3-4 phrases en francais, factuelle et concise. "
        "Commence directement par la synthese."
    )

    if hasattr(llm, "complete"):
        return llm.complete(prompt, max_tokens=200).strip()
    return _deterministic_narrative(entries, commits, total_min)


def _deterministic_narrative(entries: list[dict], commits: list[str], total_min: int) -> str:
    real_entries = [e for e in entries if not _is_noise_entry(e)]
    if not real_entries:
        return "Journee legere -- " + str(total_min) + " min d'activite sans session notable."

    projects = list(dict.fromkeys(
        e.get("active_project") for e in real_entries
        if e.get("active_project")
    ))
    tasks = list(dict.fromkeys(
        e.get("probable_task") for e in real_entries
        if e.get("probable_task")
    ))
    task_labels = {
        "coding": "developpement", "debug": "debogage",
        "writing": "redaction", "exploration": "exploration",
    }
    tasks_fr = [task_labels.get(t, t) for t in tasks]

    parts = []
    if projects:
        parts.append("Travail sur " + ", ".join(projects))
    if tasks_fr:
        parts.append("activites principales : " + ", ".join(tasks_fr))
    if commits:
        parts.append(str(len(commits)) + " commit(s) effectue(s)")
    parts.append(str(total_min) + " min de travail total")

    return ". ".join(parts) + "."


def _write_daydream(content: dict, ref_date: date) -> Path:
    DAYDREAM_DIR.mkdir(parents=True, exist_ok=True)
    path = _daydream_output_path(ref_date)

    try:
        date_fr = ref_date.strftime("%-d %B %Y")
    except Exception:
        date_fr = str(ref_date)

    lines = [
        "# DayDream -- " + date_fr,
        "",
        "## Synthese",
        content["narrative"],
        "",
    ]

    if content["projects"]:
        lines += ["## Projets", ", ".join(content["projects"]), ""]

    if content["commits"]:
        lines += ["## Commits"]
        for c in content["commits"]:
            lines.append("- " + c)
        lines.append("")

    if content["top_files"]:
        lines += ["## Fichiers centraux"]
        for f in content["top_files"][:8]:
            lines.append("- " + f)
        lines.append("")

    if content["window_titles"]:
        lines += ["## Ressources consultees"]
        for t in content["window_titles"]:
            lines.append("- " + t)
        lines.append("")

    lines += [
        "---",
        "*" + str(content["entry_count"]) + " sessions - " + str(content["total_min"]) + " min*",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _daydream_output_path(ref_date: date) -> Path:
    return DAYDREAM_DIR / f"{ref_date}.md"


def _vectorize_daydream(content: dict, ref_date: date) -> None:
    try:
        from daemon.memory.vector_store import VectorStore
        store = VectorStore()

        parts = [content["narrative"]]
        if content["commits"]:
            parts.append("Commits : " + " | ".join(content["commits"][:5]))
        if content["top_files"]:
            parts.append("Fichiers : " + ", ".join(content["top_files"][:5]))
        if content["window_titles"]:
            parts.append("Contexte : " + " | ".join(content["window_titles"][:5]))

        text = "\n".join(parts)
        mid = store.index_text(
            text=text,
            kind="daydream",
            project=content["projects"][0] if content["projects"] else None,
            metadata={
                "date": content["date"],
                "total_min": content["total_min"],
                "projects": content["projects"],
                "commits_count": len(content["commits"]),
            },
        )
        if mid:
            log.info("DayDream vectorise : id=%d", mid)
    except Exception as exc:
        log.warning("DayDream : vectorisation echouee : %s", exc)


def _extract_projects(entries: list[dict]) -> list[str]:
    seen: dict[str, int] = {}
    for e in entries:
        p = e.get("active_project")
        if p and p not in {"inconnu", "unknown", ""}:
            seen[p] = seen.get(p, 0) + int(e.get("duration_min") or 0)
    return sorted(seen, key=lambda p: seen[p], reverse=True)


def _extract_tasks(entries: list[dict]) -> list[str]:
    return list(dict.fromkeys(
        e.get("probable_task") for e in entries
        if e.get("probable_task") and e.get("probable_task") != "general"
    ))


def _extract_top_files(entries: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for e in entries:
        for f in (e.get("top_files") or []):
            counts[f] = counts.get(f, 0) + 1
    return sorted(counts, key=lambda f: counts[f], reverse=True)[:10]


def _extract_commits(entries: list[dict]) -> list[str]:
    seen: set[str] = set()
    result = []
    for e in entries:
        for c in (e.get("commit_messages") or []):
            if c and c not in seen:
                seen.add(c)
                result.append(c)
        if e.get("commit_message") and e["commit_message"] not in seen:
            seen.add(e["commit_message"])
            result.append(e["commit_message"])
    return result


def _filter_window_titles(titles: list[str]) -> list[str]:
    trivial = {
        "New Tab", "Nouvel onglet", "Safari", "Google Chrome",
        "Claude", "ChatGPT", "Firefox", "Arc",
    }
    result = []
    seen: set[str] = set()
    for title in titles:
        if not title or len(title) < 15:
            continue
        if title in trivial:
            continue
        if title in seen:
            continue
        seen.add(title)
        result.append(title)
    return result


def _is_noise_entry(entry: dict) -> bool:
    return (
        entry.get("activity_level") == "idle"
        and entry.get("probable_task") == "general"
        and not entry.get("commit_message")
        and not entry.get("top_files")
    )
