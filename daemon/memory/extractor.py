"""
extractor.py — Génération des rapports de session Pulse.

Déclencheurs
────────────
  1. Commit git (signal principal — résumé lightweight côté app, fallback déterministe)
  2. screen_lock / user_idle (fallback déterministe uniquement)
  3. Manuel (fallback déterministe uniquement)

Anti-doublon
────────────
  Curseur par projet dans _CooldownState : un rapport ne se génère pas
  si un autre a été écrit il y a moins de REPORT_COOLDOWN_MIN minutes
  pour le même projet. Le curseur est persisté dans cooldown.json pour
  survivre aux redémarrages du daemon — c'est la cause principale de
  l'explosion de fichiers de session.

Qualité LLM
────────────
  Prompt inspiré de awaySummary.ts (Leak Claude) :
  1-3 phrases, tâche de haut niveau (pas les détails d'implémentation),
  prochaine étape concrète. Le LLM est désactivé pour les triggers
  screen_lock / user_idle — le fallback déterministe est plus honnête.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import hashlib
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.core.command_redaction import redact_sensitive_command
from daemon.core.bootstrap_heuristics import BOOTSTRAP_BROWSER_APPS
from daemon.core.file_cluster import cluster_files_for_display
from daemon.core.git_diff import extract_file_names_from_diff_summary
from daemon.core.work_evidence_resolver import WorkEvidenceInput, resolve_work_evidence
from daemon.llm.lifecycle_policy import is_legacy_journal_repair_enabled, require_heavy_llm
from daemon.memory.facts import FactEngine
from daemon.memory.embedding_policy import embeddings_enabled
from daemon.memory.vector_store import VectorStore

log = logging.getLogger("pulse")

_fact_engine: Optional[FactEngine] = None
_vector_store: Optional[VectorStore] = None


def _get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store


def get_fact_engine() -> FactEngine:
    global _fact_engine
    if _fact_engine is None:
        _fact_engine = FactEngine()
    return _fact_engine


def reset_fact_engine_for_tests() -> None:
    global _fact_engine
    _fact_engine = None


def reset_cooldown_for_tests() -> None:
    _cooldown.reset()


MEMORY_DIR = Path.home() / ".pulse" / "memory"
REPORT_COOLDOWN_MIN = 30
MAX_SESSION_DURATION_MIN = 480
_COOLDOWN_FILE = Path.home() / ".pulse" / "cooldown.json"

# Number of pending journal entries to enrich at once
PENDING_JOURNAL_ENRICH_LIMIT = 10

_NOISE_SUFFIXES = {
    ".tmp", ".swp", ".swo", ".orig", ".bak",
    ".xcuserstate", ".DS_Store", "~",
    ".png", ".jpg", ".jpeg", ".gif", ".tiff", ".heic", ".webp",
    ".mp4", ".mov", ".avi", ".pdf", ".zip", ".tar", ".gz",
}
_NOISE_PATTERNS = {
    "COMMIT_EDITMSG", "MERGE_MSG", "FETCH_HEAD", "ORIG_HEAD",
    "packed-refs", "index",
    "loginwindow", "Desktop", "Downloads", "Documents",
}
_NOISE_SUBSTRINGS = {
    ".sb-", "__pycache__", "DerivedData", "xcuserdata",
    "Capture d\u2019\u00e9cran", "Capture d'\u00e9cran", "Screenshot",
    "globalContext.json", "openai_yaml",
    # Fichiers de config éditeur locaux — jamais du vrai travail
    "settings.local.json",
    # Cache HuggingFace — téléchargé par sentence-transformers, pas du code
    "huggingface", "adapter_config", "video_preprocessor", "preprocessor_config",
}


class _CooldownState:
    def __init__(self) -> None:
        self.last_report_at: Dict[str, datetime] = {}
        self.loaded: bool = False

    def reset(self) -> None:
        self.last_report_at = {}
        self.loaded = False


_cooldown = _CooldownState()
_memory_write_lock = threading.Lock()
_background_writer_shutdown = threading.Event()
_background_writer_lock = threading.Lock()
_background_writer_threads: set[threading.Thread] = set()
_JOURNAL_DATA_START = "<!-- pulse-journal-data:start"
_JOURNAL_DATA_END = "pulse-journal-data:end -->"
_JOURNAL_HIDDEN_RE = re.compile(
    rf"\n?{re.escape(_JOURNAL_DATA_START)}\n(.*?)\n{re.escape(_JOURNAL_DATA_END)}\s*\Z",
    re.DOTALL,
)
_TECHNICAL_FILE_PATTERNS = (
    "cache", ".json", ".sqlite", ".db", ".lock", ".log", ".tmp",
)
_SCOPE_SOURCE_PRIORITY = {
    "commit_diff": 4,
    "commit_files": 3,
    "snapshot": 2,
    "fallback_snapshot": 1,
    "count_only": 0,
    "unknown": -1,
}
_UNKNOWN_PROJECT_NAMES = {"", "inconnu", "unknown", "autre", "none", "null"}
_BROWSER_APPS = BOOTSTRAP_BROWSER_APPS | {"Brave Browser", "Brave"}
_ADMIN_APPS = {
    "Mail", "Gmail", "Outlook", "Calendar", "Calendrier",
    "zoom.us", "Zoom", "Microsoft Teams", "Teams", "Meet", "Slack",
}
_TOOLING_METADATA_FILENAMES = {
    "model-recommendations.json",
    "openai.yaml",
    "plugin.json",
    "skill.md",
}

_CODE_FILE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".java", ".js", ".jsx",
    ".kt", ".m", ".mm", ".php", ".py", ".rb", ".rs", ".swift",
    ".ts", ".tsx",
}


def _load_cooldown() -> None:
    if _cooldown.loaded:
        return
    _cooldown.loaded = True
    try:
        if _COOLDOWN_FILE.exists():
            raw = json.loads(_COOLDOWN_FILE.read_text())
            cutoff = datetime.now() - timedelta(minutes=REPORT_COOLDOWN_MIN)
            for project, iso in raw.items():
                try:
                    dt = datetime.fromisoformat(iso)
                    if dt > cutoff:
                        _cooldown.last_report_at[project] = dt
                except ValueError:
                    pass
    except Exception:
        pass


def _save_cooldown() -> None:
    try:
        _COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {p: dt.isoformat() for p, dt in _cooldown.last_report_at.items()}
        _COOLDOWN_FILE.write_text(json.dumps(data))
    except Exception:
        pass


_COMMIT_PREFIX_TASK: Dict[str, Optional[str]] = {
    "fix": "debug", "feat": "coding", "docs": "writing",
    "refactor": "coding", "test": "coding", "perf": "coding",
    "style": "coding", "chore": None, "build": None, "ci": None,
}
_COMMIT_CORRECTION_FROM: Dict[str, set] = {
    "debug":   {"general", "exploration", "coding"},
    "coding":  {"general", "exploration"},
    "writing": {"general", "exploration"},
}


def _commit_task_correction(commit_message: str, current_task: str) -> str:
    if not commit_message or not current_task:
        return current_task
    match = re.match(r'^(\w+)(?:\([^)]*\))?!?:', commit_message.strip().lower())
    if not match:
        return current_task
    prefix = match.group(1)
    target = _COMMIT_PREFIX_TASK.get(prefix)
    if target is None:
        return current_task
    compatible = _COMMIT_CORRECTION_FROM.get(target, set())
    if current_task in compatible:
        return target
    return current_task


# ── API publique ───────────────────────────────────────────────────────────────

def _start_background_writer(
    *,
    name: str,
    target,
    args: tuple = (),
    kwargs: Optional[dict] = None,
) -> threading.Thread | None:
    if _background_writer_shutdown.is_set():
        return None
    kwargs = kwargs or {}

    def _run() -> None:
        try:
            if _background_writer_shutdown.is_set():
                return
            target(*args, **kwargs)
        finally:
            with _background_writer_lock:
                _background_writer_threads.discard(threading.current_thread())

    thread = threading.Thread(target=_run, daemon=True, name=name)
    with _background_writer_lock:
        if _background_writer_shutdown.is_set():
            return None
        _background_writer_threads.add(thread)
    try:
        thread.start()
    except Exception:
        with _background_writer_lock:
            _background_writer_threads.discard(thread)
        raise
    return thread


def request_background_writer_shutdown() -> None:
    _background_writer_shutdown.set()


def join_background_writers(timeout: float = 1.0) -> None:
    import time as _time

    deadline = _time.monotonic() + max(float(timeout or 0.0), 0.0)
    while True:
        with _background_writer_lock:
            writers = [
                writer
                for writer in _background_writer_threads
                if writer is not threading.current_thread()
            ]
        if not writers:
            return
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            return
        for writer in writers:
            is_alive = getattr(writer, "is_alive", lambda: False)
            if not is_alive():
                with _background_writer_lock:
                    _background_writer_threads.discard(writer)
                continue
            join = getattr(writer, "join", None)
            if join is None:
                with _background_writer_lock:
                    _background_writer_threads.discard(writer)
                continue
            join(timeout=min(0.1, max(remaining, 0.0)))


def reset_background_writers_for_tests() -> None:
    _background_writer_shutdown.clear()
    with _background_writer_lock:
        _background_writer_threads.clear()


def _redact_memory_text(value: Any) -> str:
    return redact_sensitive_command(value, max_chars=-1)


def _redact_optional_memory_text(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    return _redact_memory_text(value)


def _redact_session_free_text(session_data: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(session_data)
    for key in ("body", "terminal_summary"):
        if key in redacted:
            redacted[key] = _redact_memory_text(redacted[key])
    return redacted

def update_memories_from_session(
    session_data: Dict[str, Any],
    llm: Optional[Any] = None,
    memory_dir: Optional[Path] = None,
    commit_message: Optional[str] = None,
    trigger: str = "screen_lock",
    diff_summary: Optional[str] = None,
    defer_llm_enrichment: bool = False,
):
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    _load_cooldown()
    session_data = _redact_session_free_text(session_data)
    commit_message = _redact_optional_memory_text(commit_message)
    diff_summary = _redact_optional_memory_text(diff_summary)

    if "duration_min" in session_data:
        session_data = dict(session_data)
        session_data["duration_min"] = min(session_data["duration_min"], MAX_SESSION_DURATION_MIN)

    if trigger == "commit" and commit_message:
        corrected = _commit_task_correction(commit_message, session_data.get("probable_task", "general"))
        if corrected != session_data.get("probable_task"):
            session_data = dict(session_data)
            session_data["probable_task"] = corrected
            session_data["task_source"] = "commit_correction"

    consolidation = _build_consolidation_frame(
        session_data,
        commit_message=commit_message,
        trigger=trigger,
    )
    _update_projects(base_dir, session_data, consolidation=consolidation)

    try:
        engine = get_fact_engine()
        new_facts = engine.observe_session(session_data)
        engine.clear_runtime_error()
        if new_facts:
            log.info("Facts : %d nouveau(x) fait(s) consolidé(s)", len(new_facts))
    except Exception as exc:
        engine = get_fact_engine()
        info = engine.mark_runtime_error(exc)
        if info["recoverable"]:
            log.warning("Facts : erreur récupérable observe_session : %s", info["reason"])
        else:
            log.error("Facts : erreur structurelle observe_session : %s", info["reason"])

    project  = consolidation["active_project"] or "inconnu"
    duration = consolidation["duration_min"]
    top_files = _clean_files(session_data.get("top_files", []))
    files_count = session_data.get("files_changed", 0)
    substantive_commit = trigger == "commit" and _has_substantive_commit_signal(
        commit_message=commit_message, diff_summary=diff_summary,
        top_files=top_files, files_count=files_count,
    )

    should_write = (duration >= 15 or substantive_commit)
    if not should_write:
        _update_index(base_dir)
        return None

    if trigger != "commit":
        last = _cooldown.last_report_at.get(project)
        if last is not None:
            elapsed = (datetime.now() - last).total_seconds() / 60
            # Buffer de 2 min pour éviter le cas limite où elapsed == REPORT_COOLDOWN_MIN
            # (30 < 30 = False) qui laisse passer une entrée supplémentaire.
            if elapsed < REPORT_COOLDOWN_MIN - 2:
                _update_index(base_dir)
                return None

    effective_llm = (
        llm
        if trigger == "commit" and substantive_commit
        and should_use_llm_for_commit(diff_summary=diff_summary, top_files=top_files, files_count=files_count, commit_message=commit_message)
        and not defer_llm_enrichment
        and is_legacy_journal_repair_enabled()
        else None
    )

    report_ref = _write_session_report(
        base_dir, session_data, consolidation=consolidation,
        llm=effective_llm, commit_message=commit_message, trigger=trigger, diff_summary=diff_summary,
    )

    if (
        trigger == "commit"
        and llm is not None
        and report_ref is not None
        and not defer_llm_enrichment
        and is_legacy_journal_repair_enabled()
    ):
        _, current_entry_id, _ = _report_ref_parts(report_ref)

        def _enrich_pending():
            try:
                result = enrich_pending_journal_summaries(
                    memory_dir=base_dir,
                    llm=llm,
                    limit=PENDING_JOURNAL_ENRICH_LIMIT,
                    exclude_entry_ids={str(current_entry_id)},
                )
                if result.get("enriched") or result.get("failed"):
                    log.debug("Memory : enrichissement différé journal : %s", result)
            except Exception as exc:
                log.debug("Memory : enrichissement différé ignoré : %s", exc)

        _start_background_writer(name="pulse-journal-enrich", target=_enrich_pending)

    _cooldown.last_report_at[project] = datetime.now()
    _save_cooldown()
    _update_index(base_dir)

    # Vectoriser l'entrée dans un thread séparé — ne pas bloquer le pipeline.
    # L'embedding est lent (1-2s au premier appel) mais non critique.
    if report_ref is not None and embeddings_enabled():
        def _vectorize():
            try:
                store = _get_vector_store()
                entry = {
                    "active_project": session_data.get("active_project"),
                    "probable_task":  session_data.get("probable_task"),
                    "body":           session_data.get("body", ""),
                    "commit_message": commit_message or "",
                    "top_files":      _clean_files(session_data.get("top_files", [])),
                    "duration_min":   session_data.get("duration_min"),
                    "activity_level": session_data.get("activity_level"),
                    "started_at":     session_data.get("started_at"),
                    "ended_at":       session_data.get("ended_at"),
                    "recent_apps":    session_data.get("recent_apps", []),
                }
                mid = store.index_journal_entry(entry)
                if mid:
                    log.debug("Vectorisé en mémoire : id=%d projet=%s", mid, entry.get("active_project"))
            except Exception as exc:
                log.debug("Vectorisation ignorée : %s", exc)
        _start_background_writer(name="pulse-vectorize", target=_vectorize)

    return report_ref



def enrich_session_report(
    report_ref, session_data: Dict[str, Any], llm: Any,
    *, commit_message: Optional[str] = None, diff_summary: Optional[str] = None,
) -> bool:
    if report_ref is None or llm is None:
        return False
    session_data = _redact_session_free_text(session_data)
    commit_message = _redact_optional_memory_text(commit_message)
    diff_summary = _redact_optional_memory_text(diff_summary)
    journal_file, entry_id, commit_item_id = _report_ref_parts(report_ref)
    project     = session_data.get("active_project") or "inconnu"
    duration    = session_data.get("duration_min", 0)
    task        = session_data.get("probable_task", "general")
    focus       = session_data.get("focus_level", "normal")
    friction    = float(session_data.get("max_friction", 0.0))
    apps        = session_data.get("recent_apps", [])
    top_files   = _clean_files(session_data.get("top_files", []))
    files_count = session_data.get("files_changed", 0)
    body = _llm_summary(llm, project, duration, task, focus, friction, apps, top_files, files_count, commit_message, diff_summary)
    return _replace_journal_entry(
        journal_file,
        entry_id,
        body,
        commit_item_id=commit_item_id,
        summary_source="llm",
        summary_status="generated",
        summary_error=None,
    )


# -- Opportunistic enrichment of pending journal summaries --

def enrich_pending_journal_summaries(
    *,
    memory_dir: Optional[Path] = None,
    llm: Any,
    journal_date: Optional[str] = None,
    limit: int = PENDING_JOURNAL_ENRICH_LIMIT,
    exclude_entry_ids: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """Retry LLM summaries for fallback journal entries from one day.

    This is intentionally bounded and opportunistic: it repairs older fallback
    commit summaries without blocking the main commit/report path.
    """
    if not require_heavy_llm("legacy_journal_repair", reason="pending_journal_repair"):
        log.info("Memory : réparation legacy LLM du journal désactivée par policy")
        return {
            "journal_date": journal_date or datetime.now().strftime("%Y-%m-%d"),
            "scanned": 0,
            "eligible": 0,
            "enriched": 0,
            "failed": 0,
            "skipped": 0,
            "reason": "legacy_journal_repair_disabled",
        }

    if llm is None:
        return {
            "journal_date": journal_date,
            "scanned": 0,
            "eligible": 0,
            "enriched": 0,
            "failed": 0,
            "skipped": 0,
            "reason": "llm_unavailable",
        }

    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    day = journal_date or datetime.now().strftime("%Y-%m-%d")
    journal_file = base_dir / "sessions" / f"{day}.md"
    exclude = {str(item) for item in (exclude_entry_ids or set())}
    max_items = max(int(limit or 0), 0)

    if max_items <= 0 or not journal_file.exists():
        return {
            "journal_date": day,
            "scanned": 0,
            "eligible": 0,
            "enriched": 0,
            "failed": 0,
            "skipped": 0,
        }

    entries = _load_journal_entries(journal_file)
    result = {
        "journal_date": day,
        "scanned": len(entries),
        "eligible": 0,
        "enriched": 0,
        "failed": 0,
        "skipped": 0,
    }

    for entry in entries:
        if result["eligible"] >= max_items:
            break
        normalized = _normalize_journal_entry(entry)
        entry_id = str(normalized.get("entry_id") or "")
        if entry_id in exclude:
            result["skipped"] += 1
            continue
        if not _is_pending_llm_summary_entry(normalized):
            result["skipped"] += 1
            continue

        result["eligible"] += 1
        commit_message = "\n".join(_compact_strings(normalized.get("commit_messages", [])))
        if not commit_message:
            commit_message = str(normalized.get("commit_message") or "").strip()
        try:
            body = _llm_summary(
                llm,
                normalized.get("active_project") or "inconnu",
                int(normalized.get("duration_min") or 0),
                str(normalized.get("probable_task") or "general"),
                "normal",
                0.0,
                _compact_strings(normalized.get("recent_apps", [])),
                _compact_strings(normalized.get("top_files", [])),
                int(normalized.get("files_count") or 0),
                commit_message,
                None,
                scope_source=str(normalized.get("scope_source") or "unknown"),
            )
            if _replace_journal_entry(
                journal_file,
                entry_id,
                body,
                summary_source="llm",
                summary_status="generated",
                summary_error=None,
            ):
                result["enriched"] += 1
            else:
                result["failed"] += 1
        except Exception as exc:
            _replace_journal_entry(
                journal_file,
                entry_id,
                str(normalized.get("body") or ""),
                summary_source="deterministic_fallback",
                summary_status="failed",
                summary_error=str(exc),
            )
            result["failed"] += 1

    return result


def _is_pending_llm_summary_entry(entry: Dict[str, Any]) -> bool:
    unresolved_commit_items = _entry_has_unresolved_commit_item_summaries(entry)
    if str(entry.get("summary_source") or "") == "llm" and not unresolved_commit_items:
        return False
    if (
        str(entry.get("summary_status") or "unknown") not in {"failed", "llm_unavailable", "unknown", "deferred"}
        and not unresolved_commit_items
    ):
        return False
    commit_messages = _compact_strings([entry.get("commit_message"), *entry.get("commit_messages", [])])
    if not commit_messages:
        return False
    if _is_suppressed_journal_entry(entry) or _is_noise_journal_entry(entry):
        return False
    return True


def _commit_item_body_is_fallback(body: str) -> bool:
    return str(body or "").strip().startswith("Livraison :")


def _entry_has_unresolved_commit_item_summaries(entry: Dict[str, Any]) -> bool:
    commit_items = entry.get("commit_items")
    if not isinstance(commit_items, list):
        return False
    return any(
        isinstance(item, dict) and _commit_item_body_is_fallback(str(item.get("body") or ""))
        for item in commit_items
    )


def last_session_context(project: str, memory_dir: Optional[Path] = None, today: Optional["date"] = None) -> Optional[str]:
    from datetime import date as _date
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    sections = _parse_project_sections(base_dir / "projects.md")
    entry = sections.get(project)
    if not entry or not entry.get("last_session"):
        return None
    try:
        last_date = datetime.strptime(entry["last_session"], "%Y-%m-%d").date()
        ref_today = today if today is not None else datetime.now().date()
        delta = (ref_today - last_date).days
        if delta < 0:
            return None
        elif delta == 0: age = "aujourd'hui"
        elif delta == 1: age = "hier"
        elif delta <= 6: age = f"il y a {delta} jours"
        elif delta <= 13: age = "la semaine dernière"
        else: age = f"il y a {delta // 7} semaine(s)"
        _task_labels = {"coding": "développement", "debug": "débogage", "writing": "rédaction", "exploration": "exploration", "browsing": "exploration"}
        raw_task = entry.get("last_task") or entry.get("task") or "general"
        task = _task_labels.get(raw_task, raw_task)
        duration = int(entry.get("last_duration") or 0)
        return f"Dernière session {project} : {age} ({task}, {duration} min)"
    except (ValueError, TypeError, AttributeError):
        return None


# ── Recent Journal Entries API ────────────────────────────────────────────────

def get_recent_journal_entries(
    limit: int = 5,
    *,
    project: Optional[str] = None,
    memory_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return recent structured journal entries suitable for resume cards.

    This reads the hidden pulse-journal-data blocks already persisted in
    session journals. It does not parse rendered Markdown prose and does not
    mutate memory.
    """
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    sessions_dir = base_dir / "sessions"
    if not sessions_dir.exists():
        return []

    wanted_project = _normalize_project_name(project) if project else None
    entries: List[Dict[str, Any]] = []
    for journal_file in sorted(sessions_dir.glob("*.md"), reverse=True)[:14]:
        for raw_entry in _load_journal_entries(journal_file):
            entry = _normalize_journal_entry(raw_entry)
            if _is_suppressed_journal_entry(entry) or _is_noise_journal_entry(entry):
                continue
            if wanted_project is not None and _normalize_project_name(entry.get("active_project")) != wanted_project:
                continue
            entries.append(_journal_entry_for_resume_card(entry, journal_file))

    entries.sort(key=lambda item: (str(item.get("ended_at") or ""), str(item.get("started_at") or "")), reverse=True)
    return entries[: max(int(limit or 0), 0)]


def _journal_entry_for_resume_card(entry: Dict[str, Any], journal_file: Path) -> Dict[str, Any]:
    commit_messages = _compact_strings(entry.get("commit_messages", []))
    commit_message = str(entry.get("commit_message") or "").strip()
    if commit_message and commit_message not in commit_messages:
        commit_messages.insert(0, commit_message)

    return {
        "date": _journal_date_from_path(journal_file),
        "entry_id": entry.get("entry_id"),
        "active_project": _normalize_project_name(entry.get("active_project")),
        "project": _normalize_project_name(entry.get("active_project")),
        "probable_task": str(entry.get("probable_task") or "general"),
        "task": str(entry.get("probable_task") or "general"),
        "activity_level": str(entry.get("activity_level") or "unknown"),
        "duration_min": int(entry.get("duration_min") or 0),
        "body": str(entry.get("body") or "").strip(),
        "commit_message": commit_message,
        "commit_messages": commit_messages,
        "top_files": _compact_strings(entry.get("top_files", [])),
        "files_count": int(entry.get("files_count") or 0),
        "recent_apps": _compact_strings(entry.get("recent_apps", [])),
        "started_at": entry.get("started_at"),
        "ended_at": entry.get("ended_at"),
        "boundary_reason": entry.get("boundary_reason"),
        "scope_source": entry.get("scope_source"),
        "summary_source": entry.get("summary_source"),
        "summary_status": entry.get("summary_status"),
        "summary_error": entry.get("summary_error"),
    }


def load_memory_context(memory_dir: Optional[Path] = None) -> str:
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    parts = []
    for filename in ("projects.md", "preferences.md"):
        path = base_dir / filename
        if path.exists():
            parts.append(path.read_text())
    return "\n---\n".join(parts)[:2000]


def render_project_memory(memory_dir: Optional[Path] = None) -> str:
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    path = base_dir / "projects.md"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def find_git_root(file_path: str) -> Optional[Path]:
    path = Path(file_path)
    if path.is_file():
        path = path.parent
    for candidate in [path, *path.parents]:
        git = candidate / ".git"
        if git.is_dir() or git.is_file():
            return candidate
    return None


def _resolve_git_dir(git_root: Path) -> Optional[Path]:
    try:
        git_entry = git_root / ".git"
        if git_entry.is_dir():
            return git_entry
        if not git_entry.is_file():
            return None
        content = git_entry.read_text(encoding="utf-8").strip()
        if not content.startswith("gitdir:"):
            return None
        gitdir_text = content[7:].strip()
        if not gitdir_text:
            return None
        gitdir = Path(gitdir_text)
        if not gitdir.is_absolute():
            gitdir = (git_entry.parent / gitdir).resolve()
        return gitdir if gitdir.exists() else None
    except Exception:
        return None


def read_head_sha(git_root: Path) -> Optional[str]:
    try:
        git_dir = _resolve_git_dir(git_root)
        if git_dir is None:
            return None
        head_file = git_dir / "HEAD"
        if not head_file.exists():
            return None
        ref = head_file.read_text().strip()
        if ref.startswith("ref: "):
            ref_path = git_dir / ref[5:]
            if not ref_path.exists():
                return None
            return ref_path.read_text().strip()
        return ref if len(ref) == 40 else None
    except Exception:
        return None


def read_commit_message(git_root: Path) -> Optional[str]:
    try:
        git_dir = _resolve_git_dir(git_root)
        if git_dir is None:
            return None
        commit_msg_file = git_dir / "COMMIT_EDITMSG"
        content = commit_msg_file.read_text(encoding="utf-8").strip()
        lines = [l for l in content.splitlines() if not l.startswith("#")]
        msg = "\n".join(lines).strip()
        return msg if msg else None
    except Exception:
        return None


def read_commit_file_names(git_root: Path, limit: int = 8) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "show", "--name-only", "--format=format:", "--diff-filter=ACDMRTUXB", "HEAD"],
            cwd=str(git_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return []
        files: list[str] = []
        seen: set[str] = set()
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            name = Path(line).name
            if not name or name in seen:
                continue
            seen.add(name)
            files.append(name)
            if len(files) >= limit:
                break
        return files
    except Exception:
        return []


# ── Rapport de session ────────────────────────────────────────────────────────

def _write_session_report(
    base_dir: Path, session: Dict[str, Any], *, consolidation: Dict[str, Any],
    llm: Optional[Any], commit_message: Optional[str], trigger: str, diff_summary: Optional[str] = None,
):
    session = _redact_session_free_text(session)
    commit_message = _redact_optional_memory_text(commit_message)
    diff_summary = _redact_optional_memory_text(diff_summary)
    now = datetime.now()
    _date_ref = (
        consolidation.get("ended_at")
        or session.get("ended_at")
        or session.get("updated_at")
        or session.get("started_at")
    )
    try:
        today = datetime.fromisoformat(str(_date_ref)).strftime("%Y-%m-%d")
    except (ValueError, TypeError, AttributeError):
        today = now.strftime("%Y-%m-%d")
    sessions_dir = base_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    journal_file = sessions_dir / f"{today}.md"

    project     = consolidation["active_project"] or "inconnu"
    duration    = consolidation["duration_min"]
    task        = consolidation["probable_task"]
    focus       = session.get("focus_level", "normal")
    friction    = float(session.get("max_friction", 0.0))
    apps        = session.get("recent_apps", [])
    files_count = session.get("files_changed", 0)
    top_file_paths = _clean_file_paths(session.get("top_file_paths") or session.get("top_files", []))
    top_files   = _clean_files(session.get("top_files", []))
    scope_source = "snapshot"

    if trigger == "commit":
        top_files, scope_source = _resolve_commit_scope(session, diff_summary=diff_summary)
    elif not top_files and diff_summary and trigger in {"commit", None}:
        files_from_diff = extract_file_names_from_diff_summary(diff_summary)
        if files_from_diff:
            top_files = files_from_diff[:5]

    summary_source = "deterministic_fallback"
    summary_status = "llm_unavailable"
    summary_error = None

    if llm is not None:
        try:
            body = _llm_summary(
                llm, project, duration, task, focus, friction, apps,
                top_files, files_count, commit_message, diff_summary,
                scope_source=scope_source,
            )
            summary_source = "llm"
            summary_status = "generated"
        except Exception as exc:
            log.warning("Memory : erreur résumé LLM, fallback déterministe utilisé : %s", exc)
            summary_status = "failed"
            summary_error = str(exc)
            body = _deterministic_summary(
                duration, task, focus, friction, top_files, files_count,
                commit_message, diff_summary=diff_summary,
                terminal_summary=session.get("terminal_summary"),
                scope_source=scope_source,
            )
    else:
        body = _deterministic_summary(
            duration, task, focus, friction, top_files, files_count,
            commit_message, diff_summary=diff_summary,
            terminal_summary=session.get("terminal_summary"),
            scope_source=scope_source,
        )

    entry_id = _new_entry_id(now)
    session_record = consolidation.get("session_record") or {}
    ended_at = str(consolidation.get("ended_at") or session_record.get("ended_at") or now.isoformat())
    started_at = str(
        consolidation.get("started_at")
        or session_record.get("started_at")
        or (now - timedelta(minutes=max(duration, 0))).isoformat()
    )
    entry = _build_journal_entry(
        entry_id=entry_id, active_project=project, probable_task=task,
        activity_level=consolidation.get("activity_level"), task_confidence=consolidation.get("task_confidence"),
        duration_min=duration, body=body, commit_message=commit_message, recent_apps=apps,
        top_files=top_files, files_count=files_count, started_at=started_at, ended_at=ended_at,
        boundary_reason=str(session_record.get("boundary_reason") or trigger or "unknown"),
        scope_source=scope_source,
        uncertainty_flags=consolidation.get("uncertainty_flags") or session.get("uncertainty_flags"),
        delivered_at=consolidation.get("delivered_at") or session.get("delivered_at"),
        summary_source=summary_source,
        summary_status=summary_status,
        summary_error=summary_error,
        top_file_paths=top_file_paths,
        project_root=session.get("project_root") or session.get("repo_root"),
        project_source=consolidation.get("project_source"),
    )

    with _memory_write_lock:
        entries = _load_journal_entries(journal_file)
        entries.append(entry)
        _write_journal_document(journal_file, today, entries)

    commit_item_id = None
    if (commit_message or "").strip():
        commit_item_id = _commit_item_id(commit_message, entry.get("delivered_at"))
    return _resolve_commit_report_ref(journal_file, entry_id, commit_item_id)


_JOURNAL_SYSTEM = (
    "Tu es un assistant de journal de bord développeur. "
    "Tu réponds toujours directement en français, sans introduction, "
    "sans raisonnement en anglais, sans préambule d'aucune sorte."
)


def _llm_summary(llm, project, duration, task, focus, friction, apps, top_files, files_count, commit_message, diff_summary, *, scope_source="snapshot") -> str:
    prompt = build_journal_summary_prompt(
        project, duration, task, focus, friction, apps,
        top_files, files_count, commit_message, diff_summary,
        scope_source=scope_source,
    )
    facts_block = _journal_summary_facts_block(
        project, duration, task, focus, friction, apps,
        top_files, files_count, commit_message, diff_summary,
        scope_source=scope_source,
    )

    try:
        return _finalize_journal_summary(
            _llm_complete(llm, prompt, max_tokens=8192, think=True, system=_JOURNAL_SYSTEM, profile="journal_summary"),
            allow_plain_text=True,
            stage="initial",
        )
    except ValueError as first_error:
        log.debug(
            "Memory : résumé LLM initial invalide, retry : %s",
            first_error,
        )

    retry_prompt = f"""\
Données factuelles :
{facts_block}

Écris uniquement une phrase française factuelle pour le journal Pulse.
N'invente rien.
Aucun préambule.
Aucune analyse."""

    return _finalize_journal_summary(
        _llm_complete(llm, retry_prompt, max_tokens=8192, think=True, system=_JOURNAL_SYSTEM, profile="journal_summary"),
        allow_plain_text=True,
        stage="retry",
    )


def build_journal_summary_prompt(
    project, duration, task, focus, friction, apps, top_files, files_count,
    commit_message, diff_summary, *, work_intent=None, scope_source="snapshot",
) -> str:
    facts_block = _journal_summary_facts_block(
        project, duration, task, focus, friction, apps,
        top_files, files_count, commit_message, diff_summary,
        work_intent=work_intent,
        scope_source=scope_source,
    )
    return f"""\
Données factuelles du commit livré :
{facts_block}

Écris une note de journal Pulse en français.
Contraintes :
- 1 à 2 phrases maximum.
- Ton factuel, sobre, non marketing.
- Dis ce qui a été livré et la portée principale.
- N'invente aucun fait absent des données.
- Aucune analyse, aucun raisonnement, aucun commentaire méta.
- Réponds uniquement avec la note finale."""


def build_lightweight_journal_summary_prompt(
    project, duration, task, focus, friction, apps, top_files, files_count,
    commit_message, diff_summary, *, work_intent=None,
    scope_source="snapshot",
) -> str:
    facts_block = _lightweight_journal_facts_block(
        project, duration, task, focus, friction, apps,
        top_files, files_count, commit_message, diff_summary,
        work_intent=work_intent,
        scope_source=scope_source,
    )
    return f"""\
Tu rédiges une note courte de journal de développement pour un commit.
Sources primaires : commit_message, diff_summary, fichiers du commit et nombre de fichiers.
Contexte secondaire : projet et objectif de travail, seulement s'ils confirment les sources primaires.
Règles :
- Le commit_message est la source principale.
- Le diff_summary et les fichiers définissent la portée.
- L'objectif de travail est un contexte secondaire : il ne doit jamais remplacer, dominer ou contredire le commit.
- N'introduis aucun sujet absent du commit_message, du diff_summary ou des fichiers.
- Si les preuves sont faibles, écris une phrase factuelle sobre basée sur le commit.
- Ignore les détails de fichiers, routes, fonctions, classes et tests sauf s'ils expliquent directement le comportement.
- Ne liste pas de noms de classes de test, fonctions internes ou fichiers.

Données compactes
{facts_block}

Écris uniquement la note finale.
Une seule phrase française.
Pas de liste.
Pas de markdown.
Ne recopie aucun champ ni libellé."""


def _journal_summary_facts_block(
    project, duration, task, focus, friction, apps, top_files, files_count,
    commit_message, diff_summary, *, work_intent=None, scope_source="snapshot",
) -> str:
    commit_message = _redact_memory_text(commit_message)
    diff_summary = _redact_memory_text(diff_summary)
    facts: List[str] = [f"Projet : {project}", f"Durée : {duration} minutes"]
    intent = _safe_work_intent(work_intent)
    if intent:
        facts.append(f"Objectif de travail : {intent}")
    if commit_message:
        lines = [l for l in commit_message.splitlines() if not l.startswith("#")]
        full_msg = "\n".join(lines).strip()[:400]
        facts.append(f"Commit :\n{full_msg}")
    if diff_summary:
        for line in diff_summary.splitlines():
            facts.append(line)
    elif top_files:
        prefix = "Fichiers du commit"
        if scope_source == "fallback_snapshot":
            prefix = "Portée estimée depuis l'observation de session"
        facts.append(f"{prefix} : {cluster_files_for_display(top_files)}")
    elif files_count:
        facts.append(f"Fichiers modifiés : {files_count}")
    if friction >= 0.7:
        facts.append("Friction : élevée")
    return "\n".join(f"- {f}" for f in facts)


def _lightweight_journal_facts_block(
    project, duration, task, focus, friction, apps, top_files, files_count,
    commit_message, diff_summary, *, work_intent=None,
    scope_source="snapshot",
) -> str:
    commit_message = _redact_memory_text(commit_message)
    diff_summary = _redact_memory_text(diff_summary)
    facts: List[str] = []
    if commit_message:
        lines = [l for l in commit_message.splitlines() if not l.startswith("#")]
        full_msg = "\n".join(lines).strip()[:400]
        facts.append(f"commit_subject = {full_msg}")
        commit_type = _commit_type_from_message(full_msg)
        if commit_type:
            facts.append(f"commit_type = {commit_type}")
        delivery_hint = _commit_delivery_hint(full_msg)
        if delivery_hint:
            facts.append(f"commit_intent = {delivery_hint}")
    if diff_summary:
        facts.append(f"changed_scope = {_compact_lightweight_diff_summary(diff_summary)}")
    elif top_files:
        prefix = "changed_scope"
        if scope_source == "fallback_snapshot":
            prefix = "estimated_scope"
        facts.append(f"{prefix} = {cluster_files_for_display(top_files)}")
    elif files_count:
        facts.append(f"changed_files_count = {files_count}")
    facts.append(f"project = {project}")
    facts.append(f"duration_min = {duration}")
    intent = _safe_work_intent(work_intent)
    if intent:
        facts.append(f"secondary_work_intent = {intent}")
    if friction >= 0.7:
        facts.append("friction = élevée")
    return _limit_text("\n".join(facts), 1500)


def _compact_lightweight_diff_summary(diff_summary: str) -> str:
    lines = []
    for raw_line in str(diff_summary or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        line = re.sub(r"^diff compact\s*:\s*", "", line, flags=re.IGNORECASE)
        line = re.sub(r"^diff en cours\s*:\s*", "", line, flags=re.IGNORECASE)
        line = re.sub(r"^fonctions touchées\s*:\s*", "symboles ", line, flags=re.IGNORECASE)
        lines.append(line)
    return _limit_text(" ; ".join(lines), 700)


def _safe_work_intent(work_intent) -> Optional[str]:
    if work_intent is None:
        return None
    if hasattr(work_intent, "to_dict"):
        work_intent = work_intent.to_dict()
    if isinstance(work_intent, dict):
        summary = work_intent.get("summary")
    else:
        summary = str(work_intent)
    summary = _redact_memory_text(summary)
    summary = re.sub(r"\s+", " ", str(summary or "")).strip()
    if not summary:
        return None
    return summary[:240]


def _commit_type_from_message(commit_message: str) -> Optional[str]:
    match = re.match(r"^(\w+)(?:\([^)]*\))?!?:", str(commit_message or "").strip().lower())
    if not match:
        return None
    return match.group(1)


def _commit_delivery_hint(commit_message: str) -> Optional[str]:
    subject = str(commit_message or "").splitlines()[0].strip()
    if not subject:
        return None
    match = re.match(r"^(\w+)(?:\(([^)]*)\))?!?:\s*(.+)$", subject)
    if not match:
        return None
    commit_type, scope, description = match.groups()
    commit_type = commit_type.lower()
    scope = (scope or "").strip().lower()
    description = _humanize_commit_description(description)
    subsystem = {
        "daemon": "daemon",
        "storage": "stockage",
        "llm": "LLM local",
        "memory": "mémoire et journal",
        "journal": "journal",
    }.get(scope, scope)
    if commit_type == "fix":
        if subsystem:
            return f"corrige un problème côté {subsystem} : {description}"
        return f"corrige un problème : {description}"
    if commit_type == "feat":
        if subsystem:
            return f"ajoute une capacité côté {subsystem} : {description}"
        return f"ajoute une capacité : {description}"
    if commit_type == "test":
        return f"ajoute ou renforce des tests : {description}"
    if commit_type == "refactor":
        return f"réorganise le code sans changer l'objectif produit : {description}"
    return description


def _humanize_commit_description(description: str) -> str:
    text = str(description or "").strip().rstrip(".")
    normalized = re.sub(r"\s+", " ", text.lower())
    replacements = {
        "bound logs and suppress routine access noise": "borne les journaux et réduit le bruit des accès routiniers",
        "add safe log retention cleanup": "ajoute un nettoyage sûr de rétention des logs",
        "avoid heavy model warmup for lightweight flows": "évite le warmup du modèle lourd sur les flux lightweight",
        "disable embeddings by default": "désactive les embeddings par défaut",
    }
    return replacements.get(normalized, text)


def _limit_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def apply_validated_journal_summary(
    report_ref,
    text: Any,
    *,
    summary_source: str,
    stage: str,
) -> bool:
    journal_file, entry_id, commit_item_id = _report_ref_parts(report_ref)
    body = _finalize_journal_summary(text, allow_plain_text=True, stage=stage)
    return _replace_journal_entry(
        journal_file,
        str(entry_id),
        body,
        commit_item_id=commit_item_id,
        summary_source=summary_source,
        summary_status="generated",
        summary_error=None,
    )


def mark_journal_summary_failed(report_ref, error: Any) -> bool:
    journal_file, entry_id, commit_item_id = _report_ref_parts(report_ref)
    return _update_journal_entry_summary_metadata(
        journal_file,
        str(entry_id),
        commit_item_id=commit_item_id,
        summary_status="failed",
        summary_error=str(error or "unknown_error"),
    )


# New helpers for extracting and validating journal summary blocks

def _finalize_journal_summary(value: Any, *, allow_plain_text: bool = False, stage: str = "unknown") -> str:
    try:
        final_summary = _extract_final_journal_summary(value)
    except ValueError as exc:
        if not allow_plain_text or str(exc) != "missing_final_journal_summary_block":
            raise
        final_summary = str(value or "").strip()
    sanitized_summary = _sanitize_journal_summary(final_summary)
    _validate_journal_summary(sanitized_summary, stage=stage)
    return _redact_memory_text(sanitized_summary)

def _extract_final_journal_summary(value: Any) -> str:
    """Extract the only LLM text allowed to become persistent journal memory."""
    text = str(value or "").strip()
    match = re.search(r"<final>\s*(.*?)\s*</final>", text, flags=re.DOTALL | re.IGNORECASE)
    if match is None:
        raise ValueError("missing_final_journal_summary_block")
    summary = match.group(1).strip()
    if not summary:
        raise ValueError("empty_final_journal_summary_block")
    return summary


def _validate_journal_summary(value: Any, *, stage: str = "unknown") -> None:
    """Reject LLM reasoning or prompt/meta text before journal persistence."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty_journal_summary")

    lowered = text.lower()
    forbidden_markers = {
        "okay, let's":      "okay_lets",
        "let's tackle":     "lets_tackle",
        "the user wants":   "the_user_wants",
        "i need to":        "i_need_to",
        "we need to":       "we_need_to",
        "let me":           "let_me",
        "i should":         "i_should",
        "the prompt asks":  "the_prompt_asks",
        "final answer":     "final_answer",
        "reasoning":        "reasoning",
        "step by step":     "step_by_step",
        "analysis":         "analysis",
        "je dois":          "je_dois",
        "l'utilisateur veut": "utilisateur_veut",
        "je vais":          "je_vais",
        "raisonnement":     "raisonnement",
        "analyse les données": "analyse_donnees",
        "bloc final":       "bloc_final",
        "<think":           "think_tag",
        "</think>":         "think_close_tag",
        "<final":           "final_tag",
        "</final>":         "final_close_tag",
        "the project is":   "the_project_is",
        "the commit is":    "the_commit_is",
        "first,":           "first_comma",
        "looking at":       "looking_at",
        "based on":         "based_on",
    }
    for marker_text, marker_key in forbidden_markers.items():
        if marker_text in lowered:
            raise ValueError(
                f"reasoning_leak_in_journal_summary:marker={marker_key}:stage={stage}:len={len(text)}"
            )
    fact_label_markers = {
        r"\bcommit\s*:": "commit",
        r"\btype\s*:": "type",
        r"\bintention du commit\s*:": "commit_intent",
        r"\bdiff compact\b\s*:": "diff_compact",
        r"\bfonctions touchées\b\s*:": "touched_functions",
        r"\bprojet\s*:": "project",
        r"\bdurée\s*:": "duration",
        r"\bsources primaires\b\s*:": "primary_sources",
        r"\bcontexte secondaire\b\s*:": "secondary_context",
        r"\bsummary\s*:": "summary_label",
        r"\bnext_action\s*:": "next_action_label",
        r"\blast_objective\s*:": "last_objective_label",
    }
    matched_fact_labels = [
        marker_key
        for marker_pattern, marker_key in fact_label_markers.items()
        if re.search(marker_pattern, lowered)
    ]
    if matched_fact_labels:
        reason = "facts_block_echo" if len(matched_fact_labels) >= 2 else "prompt_echo"
        raise ValueError(
            f"{reason}:marker={matched_fact_labels[0]}:stage={stage}:len={len(text)}"
        )
    colon_label_count = len(re.findall(r"\b[A-Za-zÀ-ÖØ-öø-ÿ_ ]{3,32}\s*:", text))
    if colon_label_count >= 3:
        raise ValueError(
            f"facts_block_echo:marker=label_sequence:stage={stage}:len={len(text)}"
        )


def _sanitize_journal_summary(value: Any) -> str:
    """Keep LLM journal summaries as plain text so Markdown structure stays stable."""
    text = str(value or "").strip()
    if "<channel|>" in text:
        text = text.rsplit("<channel|>", 1)[-1]
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"</?[^>\n]+>", " ", text)
    cleaned_lines: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)
        line = line.replace("*", "")
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            cleaned_lines.append(line)
    return " ".join(cleaned_lines).strip()


def _deterministic_summary(duration, task, focus, friction, top_files, files_count, commit_message, *, diff_summary=None, terminal_summary=None, scope_source="snapshot") -> str:
    commit_message = _redact_memory_text(commit_message)
    terminal_summary = _redact_memory_text(terminal_summary)
    focus_str = {"deep": "focus profond", "scattered": "travail dispersé", "idle": "session légère", "normal": ""}.get(focus, "")
    parts = []
    if commit_message:
        parts.append(f"Livraison : \u00ab {commit_message.splitlines()[0]} \u00bb.")
    # La portée est rendue séparément par _render_journal_project_entry.
    # Ne pas la dupliquer ici dans le body.
    if terminal_summary and not diff_summary and not commit_message:
        parts.append(terminal_summary)
    if focus_str:
        parts.append(f"Rythme : {focus_str}.")
    if friction >= 0.7:
        parts.append("Friction : élevée.")
    if not parts:
        parts.append(f"Session de {duration} min.")
    return _redact_memory_text(" ".join(parts))


def _has_substantive_commit_signal(*, commit_message, diff_summary, top_files, files_count) -> bool:
    if diff_summary and diff_summary.strip():
        return True
    if len(top_files) >= 2 or files_count >= 2:
        return True
    if commit_message and len(commit_message.split()) >= 3:
        return True
    return False


def should_use_llm_for_commit(*, diff_summary, top_files, files_count, commit_message=None) -> bool:
    # Un commit avec message conventionnel bien formé mérite toujours le LLM.
    if commit_message and re.match(r'^(feat|fix|refactor|docs|test|perf|style|chore|build|ci)\b', commit_message.strip().lower()):
        return True
    if diff_summary and diff_summary.strip():
        return True
    if len(top_files) >= 2 or files_count >= 3:
        return True
    return False


# ── Nettoyage des fichiers ────────────────────────────────────────────────────

def _clean_files(files: List[str]) -> List[str]:
    result = []
    for f in files:
        name = Path(f).name
        if name in _NOISE_PATTERNS:
            continue
        if any(name.endswith(s) for s in _NOISE_SUFFIXES):
            continue
        if any(s in f for s in _NOISE_SUBSTRINGS):
            continue
        result.append(name)
    return result


def _clean_file_paths(files: List[Any]) -> List[str]:
    result: List[str] = []
    for raw in files or []:
        text = str(raw or "").strip()
        if not text or "/" not in text:
            continue
        name = Path(text).name
        if name in _NOISE_PATTERNS:
            continue
        if any(name.endswith(s) for s in _NOISE_SUFFIXES):
            continue
        if any(s in text for s in _NOISE_SUBSTRINGS):
            continue
        if text not in result:
            result.append(text)
    return result


def _infer_project_from_session_evidence(session_data: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    paths = _clean_file_paths(session_data.get("top_file_paths") or session_data.get("top_files", []))
    active_file = str(session_data.get("active_file") or "").strip()
    if active_file:
        paths = _clean_file_paths([active_file, *paths])

    resolution = resolve_work_evidence(
        WorkEvidenceInput(
            active_project=_normalize_project_name(session_data.get("active_project")),
            project_hint=_normalize_project_name(session_data.get("project_hint")),
            file_paths=tuple(paths),
            repo_roots=tuple(
                str(value)
                for value in (session_data.get("project_root"), session_data.get("repo_root"))
                if str(value or "").strip()
            ),
            terminal_cwd=session_data.get("terminal_cwd"),
            terminal_project=_normalize_project_name(session_data.get("terminal_project")),
            terminal_command_category=session_data.get("terminal_command_category"),
            active_app=session_data.get("active_app"),
            active_app_bundle_id=session_data.get("active_app_bundle_id"),
            window_title=session_data.get("active_window_title") or session_data.get("window_title"),
            recent_apps=tuple(_compact_strings(session_data.get("recent_apps", []))),
            recent_app_bundle_ids=tuple(
                str(value).strip() or None
                for value in (session_data.get("recent_app_bundle_ids") or [])
            ),
            work_intent_project=_work_intent_project(session_data),
            commit_repo_root=session_data.get("commit_repo_root"),
            commit_files=tuple(_clean_file_paths(session_data.get("commit_files", []))),
        )
    )
    if resolution.project and resolution.project_confidence >= 0.75:
        return resolution.project, resolution.project_source
    return None, None


def _work_intent_project(session_data: Dict[str, Any]) -> Optional[str]:
    explicit = _normalize_project_name(session_data.get("work_intent_project"))
    if explicit:
        return explicit
    intent = session_data.get("work_intent")
    if hasattr(intent, "to_dict"):
        intent = intent.to_dict()
    if isinstance(intent, dict):
        return _normalize_project_name(intent.get("project"))
    return None


def _has_project_work_evidence(
    session_data: Dict[str, Any],
    session_record: Optional[Dict[str, Any]],
    active_project: Optional[str],
    commit_message: Optional[str],
) -> bool:
    if str(commit_message or "").strip():
        return True

    sources = [session_data]
    if session_record:
        sources.append(session_record)

    for source in sources:
        if _compact_strings(source.get("commit_messages", [])):
            return True
        if _compact_strings(source.get("top_files", [])):
            return True
        if _clean_file_paths(source.get("top_file_paths", [])):
            return True
        if _clean_file_paths(source.get("commit_files", [])):
            return True
        if _clean_file_paths(source.get("commit_scope_files", [])):
            return True
        if str(source.get("active_file") or "").strip():
            return True
        if int(source.get("files_changed") or source.get("files_count") or 0) > 0:
            return True
        if any(str(source.get(key) or "").strip() for key in (
            "project_root",
            "repo_root",
            "commit_repo_root",
            "terminal_cwd",
            "terminal_project",
        )):
            return True
        intent_project = _work_intent_project(source)
        if intent_project and active_project and intent_project == _normalize_project_name(active_project):
            return True
    return False


def _should_discard_stale_active_project(
    session_data: Dict[str, Any],
    session_record: Optional[Dict[str, Any]],
    active_project: Optional[str],
    commit_message: Optional[str],
) -> bool:
    if not _normalize_project_name(active_project):
        return False
    activity = str(
        (session_record or {}).get("activity_level")
        or session_data.get("activity_level")
        or ""
    ).strip().lower()
    if activity != "idle":
        return False
    return not _has_project_work_evidence(
        session_data,
        session_record,
        active_project,
        commit_message,
    )


def _infer_journal_project(entry: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    return _infer_project_from_session_evidence(entry)


def _replace_journal_entry(
    journal_file: Path,
    entry_id: str,
    body: str,
    *,
    commit_item_id: Optional[str] = None,
    summary_source: Optional[str] = None,
    summary_status: Optional[str] = None,
    summary_error: Optional[str] = None,
) -> bool:
    body = _redact_memory_text(body)
    with _memory_write_lock:
        if not journal_file.exists():
            return False
        entries = _load_journal_entries(journal_file)
        updated = False
        for entry in entries:
            if commit_item_id and not (
                entry.get("entry_id") == entry_id or _entry_has_commit_item_id(entry, commit_item_id)
            ):
                continue
            if not commit_item_id and entry.get("entry_id") != entry_id:
                continue
            if commit_item_id:
                commit_items = _ensure_commit_item_ids(entry.get("commit_items", []))
                replaced_item = False
                for item in commit_items:
                    if item.get("commit_item_id") != commit_item_id:
                        continue
                    item["body"] = body.strip()
                    if summary_source is not None:
                        item["summary_source"] = summary_source
                    if summary_status is not None:
                        item["summary_status"] = summary_status
                    item["summary_error"] = summary_error
                    replaced_item = True
                    break
                if not replaced_item:
                    continue
                entry["commit_items"] = commit_items
                entry["body"] = _body_from_commit_items(commit_items)
                if len(commit_items) == 1 or not _entry_has_unresolved_commit_item_summaries(entry):
                    if summary_source is not None:
                        entry["summary_source"] = summary_source
                    if summary_status is not None:
                        entry["summary_status"] = summary_status
                    entry["summary_error"] = summary_error
                updated = True
                break
            else:
                entry["body"] = body.strip()
                commit_items = entry.get("commit_items")
                if isinstance(commit_items, list) and len(commit_items) == 1 and isinstance(commit_items[0], dict):
                    commit_items[0]["body"] = body.strip()
                    if summary_source is not None:
                        commit_items[0]["summary_source"] = summary_source
                    if summary_status is not None:
                        commit_items[0]["summary_status"] = summary_status
                    commit_items[0]["summary_error"] = summary_error
                elif isinstance(commit_items, list) and _entry_has_unresolved_commit_item_summaries(entry):
                    replacement_bodies = _commit_item_replacement_bodies(body, commit_items)
                    for index, item in enumerate(commit_items):
                        if not isinstance(item, dict):
                            continue
                        if not _commit_item_body_is_fallback(str(item.get("body") or "")):
                            continue
                        replacement = replacement_bodies[index] if index < len(replacement_bodies) else body.strip()
                        if replacement:
                            item["body"] = replacement
                if summary_source is not None:
                    entry["summary_source"] = summary_source
                if summary_status is not None:
                    entry["summary_status"] = summary_status
                entry["summary_error"] = summary_error
                updated = True
                break
        if not updated:
            return False
        journal_date = _journal_date_from_path(journal_file)
        _write_journal_document(journal_file, journal_date, entries)
        return True


def _update_journal_entry_summary_metadata(
    journal_file: Path,
    entry_id: str,
    *,
    commit_item_id: Optional[str] = None,
    summary_status: Optional[str] = None,
    summary_error: Optional[str] = None,
    summary_source: Optional[str] = None,
) -> bool:
    with _memory_write_lock:
        if not journal_file.exists():
            return False
        entries = _load_journal_entries(journal_file)
        updated = False
        for entry in entries:
            if commit_item_id and not (
                entry.get("entry_id") == entry_id or _entry_has_commit_item_id(entry, commit_item_id)
            ):
                continue
            if not commit_item_id and entry.get("entry_id") != entry_id:
                continue
            if commit_item_id:
                commit_items = _ensure_commit_item_ids(entry.get("commit_items", []))
                updated_item = False
                for item in commit_items:
                    if item.get("commit_item_id") != commit_item_id:
                        continue
                    if summary_source is not None:
                        item["summary_source"] = summary_source
                    if summary_status is not None:
                        item["summary_status"] = summary_status
                    item["summary_error"] = summary_error
                    updated_item = True
                    break
                if not updated_item:
                    continue
                entry["commit_items"] = commit_items
                if len(commit_items) == 1:
                    if summary_source is not None:
                        entry["summary_source"] = summary_source
                    if summary_status is not None:
                        entry["summary_status"] = summary_status
                    entry["summary_error"] = summary_error
                updated = True
                break
            else:
                if summary_source is not None:
                    entry["summary_source"] = summary_source
                if summary_status is not None:
                    entry["summary_status"] = summary_status
                entry["summary_error"] = summary_error
                updated = True
                break
        if not updated:
            return False
        journal_date = _journal_date_from_path(journal_file)
        _write_journal_document(journal_file, journal_date, entries)
        return True


def _commit_item_replacement_bodies(body: str, commit_items: List[Dict[str, Any]]) -> List[str]:
    clean_body = str(body or "").strip()
    if not clean_body:
        return []
    body_parts = [part.strip() for part in clean_body.split("\n") if part.strip()]
    if len(body_parts) == len(commit_items):
        return body_parts
    return [clean_body] * len(commit_items)


def _commit_item_id(message: Any, delivered_at: Any = None) -> str:
    message_text = _redact_memory_text(message).strip()
    delivered_text = str(delivered_at or "").strip()
    digest = hashlib.sha1(f"{message_text}\0{delivered_text}".encode("utf-8")).hexdigest()[:16]
    return f"commit-item-{digest}"


def _commit_item_id_for_item(item: Dict[str, Any]) -> str:
    existing = str(item.get("commit_item_id") or "").strip()
    if existing:
        return existing
    return _commit_item_id(item.get("message"), item.get("delivered_at"))


def _ensure_commit_item_ids(items: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        normalized["commit_item_id"] = _commit_item_id_for_item(normalized)
        result.append(normalized)
    return result


def _entry_has_commit_item_id(entry: Dict[str, Any], commit_item_id: str) -> bool:
    return any(
        item.get("commit_item_id") == commit_item_id
        for item in _ensure_commit_item_ids(entry.get("commit_items", []))
    )


def _body_from_commit_items(commit_items: List[Dict[str, Any]]) -> str:
    return "\n".join(
        _compact_strings([item.get("body") for item in commit_items if isinstance(item, dict)])
    )


def _report_ref_parts(report_ref: Any) -> tuple[Path, str, Optional[str]]:
    if not isinstance(report_ref, (tuple, list)) or len(report_ref) < 2:
        raise ValueError("invalid_report_ref")
    journal_file = Path(report_ref[0])
    entry_id = str(report_ref[1])
    commit_item_id = str(report_ref[2]).strip() if len(report_ref) >= 3 and report_ref[2] else None
    return journal_file, entry_id, commit_item_id


def _resolve_commit_report_ref(
    journal_file: Path,
    entry_id: str,
    commit_item_id: Optional[str],
):
    if not commit_item_id:
        return (journal_file, entry_id)
    for entry in _load_journal_entries(journal_file):
        if _entry_has_commit_item_id(entry, commit_item_id):
            return (journal_file, str(entry.get("entry_id") or entry_id), commit_item_id)
    return (journal_file, entry_id, commit_item_id)


def _new_entry_id(now: datetime) -> str:
    return now.strftime("%Y%m%d%H%M%S%f")


def _journal_task_confidence(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_journal_entry(*, entry_id, active_project, probable_task, activity_level, task_confidence,
    duration_min, body, commit_message, recent_apps, top_files, files_count, started_at, ended_at, boundary_reason,
    scope_source="snapshot", uncertainty_flags=None, delivered_at=None,
    summary_source="deterministic_fallback", summary_status="llm_unavailable", summary_error=None,
    top_file_paths=None, project_root=None, project_source=None) -> Dict[str, Any]:
    body = _redact_memory_text(body)
    commit_message = _redact_memory_text(commit_message)
    normalized_confidence = _journal_task_confidence(task_confidence)
    entry = {
        "entry_id": entry_id,
        "active_project": active_project or "Autre",
        "probable_task": probable_task or "general",
        "activity_level": activity_level or "unknown",
        "task_confidence": normalized_confidence,
        "duration_min": int(max(duration_min, 0)),
        "body": body.strip(),
        "commit_message": (commit_message or "").strip(),
        "recent_apps": _compact_strings(recent_apps[:6]),
        "top_files": list(top_files[:5]),
        "files_count": int(max(files_count or 0, 0)),
        "started_at": started_at,
        "ended_at": ended_at,
        "delivered_at": delivered_at,
        "boundary_reason": boundary_reason or "unknown",
        "scope_source": scope_source or "unknown",
        "uncertainty_flags": _compact_strings(uncertainty_flags or []),
        "summary_source": summary_source or "deterministic_fallback",
        "summary_status": summary_status or "unknown",
        "summary_error": summary_error,
        "project_source": project_source,
    }
    cleaned_paths = _clean_file_paths(top_file_paths or [])
    if cleaned_paths:
        entry["top_file_paths"] = cleaned_paths[:5]
    if project_root:
        entry["project_root"] = str(project_root)
    if (commit_message or "").strip():
        entry["commit_items"] = [
            {
                "commit_item_id": _commit_item_id(commit_message, delivered_at),
                "message": (commit_message or "").strip(),
                "body": body.strip(),
                "delivered_at": delivered_at,
                "top_files": list(top_files[:5]),
                "summary_source": summary_source or "deterministic_fallback",
                "summary_status": summary_status or "unknown",
                "summary_error": summary_error,
            }
        ]
    return entry


def _load_journal_entries(journal_file: Path) -> List[Dict[str, Any]]:
    if not journal_file.exists():
        return []
    content = journal_file.read_text(encoding="utf-8")
    match = _JOURNAL_HIDDEN_RE.search(content)
    if match is not None:
        try:
            raw_entries = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
        return [entry for entry in raw_entries if isinstance(entry, dict) and entry.get("entry_id")]
    return []


def _journal_date_from_path(journal_file: Path) -> str:
    return journal_file.stem


def _write_journal_document(journal_file: Path, journal_date: str, entries: List[Dict[str, Any]]) -> None:
    rendered = _render_journal_document(journal_date, entries)
    payload_entries = _journal_entries_for_hidden_payload(entries)
    payload = json.dumps(payload_entries, ensure_ascii=False, indent=2)
    hidden_block = "\n".join(["", _JOURNAL_DATA_START, payload, _JOURNAL_DATA_END, ""])
    journal_file.write_text(rendered.rstrip() + hidden_block, encoding="utf-8")


def _journal_entries_for_hidden_payload(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return canonical journal entries for the hidden structured payload.

    The visible journal already renders the normalized/merged/overlap-resolved
    view. Persisting raw entries in the hidden payload keeps obsolete snapshots
    alive and makes later consumers re-read entries that were explicitly
    absorbed or suppressed. Keep weak/noise entries for traceability, but drop
    entries that the resolver marked as demoted or fully suppressed.
    """
    normalized_entries = [_normalize_journal_entry(raw_entry) for raw_entry in entries]
    merged_entries = _merge_journal_entries(normalized_entries)
    resolved_entries = _resolve_journal_entry_overlaps(merged_entries)
    return [
        entry
        for entry in resolved_entries
        if not entry.get("overlap_demoted")
        and not _is_suppressed_journal_entry(entry)
    ]


def _render_journal_document(journal_date: str, entries: List[Dict[str, Any]]) -> str:
    ordered_entries = sorted(entries, key=_journal_entry_sort_key)
    merged_entries = _merge_journal_entries(ordered_entries)
    merged_entries = _resolve_journal_entry_overlaps(merged_entries)
    merged_entries = sorted(merged_entries, key=_journal_entry_sort_key)

    project_sections: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    noise_entries: List[Dict[str, Any]] = []
    for entry in merged_entries:
        if entry.get("overlap_demoted"):
            continue
        if _is_suppressed_journal_entry(entry):
            continue
        if _is_noise_journal_entry(entry):
            noise_entries.append(entry)
            continue
        section_title = _journal_section_title(entry)
        project_sections.setdefault(section_title, []).append(entry)

    lines = [f"# Journal Pulse — {journal_date}"]
    for project, project_entries in project_sections.items():
        lines.extend(["", f"## {project}", ""])
        for index, entry in enumerate(project_entries):
            lines.extend(_render_journal_project_entry(entry))
            if index < len(project_entries) - 1:
                lines.extend(["", "---", ""])

    if noise_entries:
        lines.extend(["", "## Activité faible / bruit", ""])
        for entry in noise_entries:
            lines.append(f"- {_render_noise_line(entry)}")

    return "\n".join(lines).rstrip() + "\n"


def _render_journal_project_entry(entry: Dict[str, Any]) -> List[str]:
    title = _journal_entry_title(entry)
    duration = int(entry.get("duration_min") or 0)
    time_range = _journal_entry_time_range(entry)
    lines = [f"### {time_range} — {title} ({duration} min)"]
    description = _journal_entry_description(entry)
    if description:
        lines.extend(description.splitlines())
    lines.append(f"{_journal_scope_label(entry)} : {_journal_entry_scope(entry)}.")        
    return lines


def _render_noise_line(entry: Dict[str, Any]) -> str:
    project = _journal_section_title(entry)
    title = _journal_entry_title(entry)
    duration = int(entry.get("duration_min") or 0)
    scope = _journal_entry_scope(entry)
    return f"{_journal_entry_time_range(entry)} — {project} / {title} ({duration} min) — {_journal_scope_label(entry).lower()} : {scope}"


def _journal_scope_label(entry: Dict[str, Any]) -> str:
    return "Portée estimée" if str(entry.get("scope_source") or "") == "fallback_snapshot" else "Portée"


def _journal_entry_sort_key(entry: Dict[str, Any]) -> tuple[str, str, str]:
    return (str(entry.get("started_at") or ""), str(entry.get("ended_at") or ""), str(entry.get("entry_id") or ""))


def _merge_journal_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_entries = [_normalize_journal_entry(raw_entry) for raw_entry in entries]
    normalized_entries = _trim_delivered_commit_overlaps(normalized_entries)
    normalized_entries = sorted(normalized_entries, key=_journal_entry_sort_key)

    merged: List[Dict[str, Any]] = []
    for entry in normalized_entries:
        if merged and _can_merge_journal_entries(merged[-1], entry):
            merged[-1] = _merge_journal_pair(merged[-1], entry)
        else:
            merged.append(entry)
    return merged


def _normalize_journal_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(entry)
    normalized["active_project"] = _normalize_project_name(normalized.get("active_project"))
    if normalized["active_project"] is None:
        inferred_project, project_source = _infer_journal_project(normalized)
        if inferred_project:
            normalized["active_project"] = inferred_project
            normalized["project_source"] = normalized.get("project_source") or project_source
        else:
            normalized["project_source"] = normalized.get("project_source") or "project_attribution_insufficient"
    normalized["probable_task"] = normalized.get("probable_task") or "general"
    normalized["activity_level"] = normalized.get("activity_level") or "unknown"
    normalized["top_files"] = [str(item) for item in normalized.get("top_files", []) if isinstance(item, str) and item.strip()]
    normalized["top_file_paths"] = _clean_file_paths(normalized.get("top_file_paths", []))
    normalized["recent_apps"] = _compact_strings(normalized.get("recent_apps", []))
    normalized["duration_min"] = int(max(normalized.get("duration_min") or 0, 0))
    normalized["body"] = _redact_memory_text(normalized.get("body"))
    normalized["commit_message"] = _redact_memory_text(normalized.get("commit_message"))
    normalized["commit_messages"] = _compact_strings(
        [
            _redact_memory_text(normalized.get("commit_message")),
            *(_redact_memory_text(item) for item in (normalized.get("commit_messages") or [])),
        ]
    )
    normalized["scope_source"] = str(normalized.get("scope_source") or "unknown")
    normalized["uncertainty_flags"] = _compact_strings(normalized.get("uncertainty_flags", []))
    normalized["task_confidence"] = _journal_task_confidence(normalized.get("task_confidence"))
    normalized["summary_source"] = str(normalized.get("summary_source") or "unknown")
    normalized["summary_status"] = str(normalized.get("summary_status") or "unknown")
    normalized["summary_error"] = normalized.get("summary_error")
    normalized["commit_items"] = _normalize_commit_items(normalized)
    normalized["probable_task"] = _correct_snapshot_task_from_scope(normalized)
    return normalized


def _normalize_commit_items(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    explicit_items = entry.get("commit_items")
    if isinstance(explicit_items, list):
        items: List[Dict[str, Any]] = []
        for item in explicit_items:
            if not isinstance(item, dict):
                continue
            message = _redact_memory_text(item.get("message")).strip()
            if not message:
                continue
            commit_item_id = str(item.get("commit_item_id") or "").strip() or _commit_item_id(message, item.get("delivered_at"))
            items.append(
                {
                    "commit_item_id": commit_item_id,
                    "message": message,
                    "body": _redact_memory_text(item.get("body")).strip(),
                    "delivered_at": item.get("delivered_at"),
                    "top_files": _compact_strings(item.get("top_files", [])),
                    "summary_source": item.get("summary_source"),
                    "summary_status": item.get("summary_status"),
                    "summary_error": item.get("summary_error"),
                }
            )
        if items:
            return items

    messages = _compact_strings(entry.get("commit_messages", []))
    if not messages:
        return []

    body = _redact_memory_text(entry.get("body")).strip()
    body_parts = [part.strip() for part in body.split("\n") if part.strip()]
    if len(messages) == 1:
        bodies = [body]
    elif len(body_parts) == len(messages):
        bodies = body_parts
    else:
        bodies = [""] * len(messages)

    top_files = _compact_strings(entry.get("top_files", []))
    delivered_at = entry.get("delivered_at")
    return [
        {
            "commit_item_id": _commit_item_id(message, delivered_at),
            "message": message,
            "body": bodies[index] if index < len(bodies) else "",
            "delivered_at": delivered_at,
            "top_files": top_files,
        }
        for index, message in enumerate(messages)
    ]


# ── Code/snapshot task correction ─────────────────────────────────────────────

def _correct_snapshot_task_from_scope(entry: Dict[str, Any]) -> str:
    """Avoid classifying code-file snapshots as writing.

    This is intentionally narrow: commit entries keep their commit-derived task,
    while weak snapshot entries on code files should not render as rédaction.
    """
    task = str(entry.get("probable_task") or "general")
    if task != "writing":
        return task
    if _compact_strings(entry.get("commit_messages", [])):
        return task
    scope_source = str(entry.get("scope_source") or "unknown")
    if scope_source not in {"snapshot", "fallback_snapshot", "unknown"}:
        return task
    top_files = _compact_strings(entry.get("top_files", []))
    if any(_is_code_file_name(name) for name in top_files):
        return "coding"
    return task


def _is_code_file_name(name: Any) -> bool:
    return Path(str(name or "")).suffix.lower() in _CODE_FILE_SUFFIXES


_JOURNAL_MERGE_GAP_MAX_MIN = 5
_JOURNAL_COMMIT_DELIVERY_MERGE_GAP_MAX_MIN = 10


def _can_merge_journal_entries(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    if left.get("active_project") != right.get("active_project"):
        return False
    if left.get("probable_task") != right.get("probable_task"):
        return False

    left_commits = _compact_strings(left.get("commit_messages", []))
    right_commits = _compact_strings(right.get("commit_messages", []))
    if left_commits and right_commits and not _commit_deliveries_are_close(left, right):
        return False

    left_start, left_end = _entry_bounds(left)
    right_start, right_end = _entry_bounds(right)
    if left_start is None or left_end is None or right_start is None or right_end is None:
        return False

    if right_start <= left_end and left_start <= right_end:
        return True

    gap_min = (right_start - left_end).total_seconds() / 60
    return 0 <= gap_min <= _JOURNAL_MERGE_GAP_MAX_MIN


def _commit_deliveries_are_close(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_delivered = _parse_entry_datetime(left.get("delivered_at"))
    right_delivered = _parse_entry_datetime(right.get("delivered_at"))
    if left_delivered is None or right_delivered is None:
        return True
    gap_min = abs((right_delivered - left_delivered).total_seconds()) / 60
    return gap_min <= _JOURNAL_COMMIT_DELIVERY_MERGE_GAP_MAX_MIN


def _merge_journal_pair(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(left)
    merged["entry_id"] = str(left.get("entry_id") or right.get("entry_id") or "")
    merged["ended_at"] = right.get("ended_at") or left.get("ended_at")
    merged["delivered_at"] = right.get("delivered_at") or left.get("delivered_at")
    merged["task_confidence"] = max(_float_or_zero(left.get("task_confidence")), _float_or_zero(right.get("task_confidence")))
    merged["files_count"] = max(int(left.get("files_count") or 0), len(_merge_unique_strings(left.get("top_files", []), right.get("top_files", []))), int(right.get("files_count") or 0))
    merged["top_files"] = _merge_unique_strings(left.get("top_files", []), right.get("top_files", []))
    merged["commit_messages"] = _merge_unique_strings(left.get("commit_messages", []), right.get("commit_messages", []))
    merged["commit_items"] = _merge_commit_items(left.get("commit_items", []), right.get("commit_items", []))
    merged["recent_apps"] = _merge_unique_strings(left.get("recent_apps", []), right.get("recent_apps", []))
    merged["top_file_paths"] = _merge_unique_strings(left.get("top_file_paths", []), right.get("top_file_paths", []))
    merged["project_root"] = left.get("project_root") or right.get("project_root")
    merged["project_source"] = left.get("project_source") or right.get("project_source")
    merged["commit_message"] = merged["commit_messages"][0] if merged["commit_messages"] else ""
    merged["scope_source"] = _stronger_scope_source(left.get("scope_source"), right.get("scope_source"))
    # Durée réelle : diff entre started_at et ended_at fusionnés.
    # Si real_elapsed >> sum_durations (facteur 3x), c'est qu'il y a eu
    # un gap (verrou écran, idle long) entre les deux entrées.
    # Dans ce cas on utilise sum_durations qui reflète le vrai temps de travail.
    start_dt = _parse_entry_datetime(left.get("started_at"))
    end_dt = _parse_entry_datetime(merged.get("ended_at"))
    left_start = _parse_entry_datetime(left.get("started_at"))
    left_end = _parse_entry_datetime(left.get("ended_at"))
    right_start = _parse_entry_datetime(right.get("started_at"))
    right_end = _parse_entry_datetime(right.get("ended_at"))
    sum_durations = int(left.get("duration_min") or 0) + int(right.get("duration_min") or 0)
    if start_dt and end_dt and end_dt > start_dt:
        real_elapsed = max(int((end_dt - start_dt).total_seconds() / 60), 0)
        overlaps = (
            left_start is not None
            and left_end is not None
            and right_start is not None
            and right_end is not None
            and right_start <= left_end
            and left_start <= right_end
        )
        if overlaps and not _compact_strings(left.get("commit_messages", [])) and not _compact_strings(right.get("commit_messages", [])):
            merged["duration_min"] = real_elapsed
        elif merged["commit_messages"] and real_elapsed < sum_durations:
            merged["duration_min"] = max(real_elapsed, 1)
        # Si le ratio est raisonnable (< 3x), real_elapsed est fiable.
        # Sinon il y a eu un gap — on garde sum_durations.
        elif sum_durations > 0 and real_elapsed > sum_durations * 3:
            merged["duration_min"] = sum_durations
        else:
            merged["duration_min"] = max(real_elapsed, sum_durations)
    else:
        merged["duration_min"] = sum_durations
    # Corps : si pas de commit, garder uniquement le plus récent (right).
    # Si commit, concaténer uniquement les bodies des entrées qui ont un commit
    # pour que le comptage body_parts == commit_messages reste cohérent.
    if merged["commit_messages"]:
        merged["body"] = "\n".join(_compact_strings([item.get("body") for item in merged.get("commit_items", [])]))
    else:
        merged["body"] = str(right.get("body") or left.get("body") or "").strip()
    return merged


def _merge_commit_items(left_items: Any, right_items: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*(left_items or []), *(right_items or [])]:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "").strip()
        item_id = _commit_item_id_for_item(item)
        if not message or item_id in seen:
            continue
        seen.add(item_id)
        result.append(
            {
                "commit_item_id": item_id,
                "message": message,
                "body": str(item.get("body") or "").strip(),
                "delivered_at": item.get("delivered_at"),
                "top_files": _compact_strings(item.get("top_files", [])),
                "summary_source": item.get("summary_source"),
                "summary_status": item.get("summary_status"),
                "summary_error": item.get("summary_error"),
            }
        )
    return result


def _journal_entry_title(entry: Dict[str, Any]) -> str:
    task_labels = {"coding": "développement", "debug": "débogage", "writing": "rédaction", "exploration": "exploration", "browsing": "exploration", "general": "travail général"}
    task = str(entry.get("probable_task") or "general")
    return task_labels.get(task, task.replace("_", " "))


def _journal_entry_description(entry: Dict[str, Any]) -> str:
    lines: List[str] = []
    commit_messages = _compact_strings(entry.get("commit_messages", []))
    commit_items = _commit_items_for_render(entry)
    body = str(entry.get("body") or "").strip()
    body = _strip_commit_sentence(body, commit_messages)
    if body.startswith(("Port\u00e9e : ", "Port\u00e9e estim\u00e9e : ")) and not commit_messages:
        body = ""

    if commit_items:
        ended_at = _format_journal_time(entry.get("ended_at"))
        for index, item in enumerate(commit_items):
            message = str(item.get("message") or "")
            item_body = _strip_commit_sentence(str(item.get("body") or "").strip(), [message])
            lines.append(_journal_commit_line(message))
            if item_body:
                lines.append(item_body)
            delivered_at = _format_journal_time(item.get("delivered_at"))
            if delivered_at != "??:??" and delivered_at != ended_at:
                lines.append(f"Livré à {delivered_at}.")
            if index < len(commit_items) - 1:
                lines.append("")
                lines.append("")
    elif commit_messages:
        if len(commit_messages) == 1:
            # Commit unique : message en gras, résumé en dessous
            lines.append(_journal_commit_line(commit_messages[0]))
            if body:
                lines.append(body)
            delivered_at = _format_journal_time(entry.get("delivered_at"))
            ended_at = _format_journal_time(entry.get("ended_at"))
            if delivered_at != "??:??" and delivered_at != ended_at:
                lines.append(f"Livré à {delivered_at}.")
        else:
            # Plusieurs commits : tenter l'appariement avec les paragraphes du body.
            # Si le compte correspond, chaque commit en gras suivi de son résumé,
            # avec double saut de ligne entre chaque paire pour lisibilité.
            body_parts = [p.strip() for p in body.split("\n") if p.strip()]
            if body_parts and len(body_parts) == len(commit_messages):
                for i, (msg, summary) in enumerate(zip(commit_messages, body_parts)):
                    lines.append(_journal_commit_line(msg))
                    lines.append(summary)
                    if i < len(commit_messages) - 1:
                        lines.append("")
                        lines.append("")
            else:
                for msg in commit_messages:
                    lines.append(_journal_commit_line(msg))
            if body:
                lines.append(body)
    else:
        if body:
            lines.append(body)

    lines.extend(_journal_uncertainty_lines(entry))

    if not lines:
        duration = int(entry.get("duration_min") or 0)
        lines.append(f"Activité estimée sur {_journal_entry_title(entry)} pendant {duration} min.")
    return "\n".join(lines)


def _journal_uncertainty_lines(entry: Dict[str, Any]) -> List[str]:
    flags = set(_compact_strings(entry.get("uncertainty_flags", [])))
    confidence = _journal_task_confidence(entry.get("task_confidence"))
    lines: List[str] = []
    if "tool_assisted" in flags:
        lines.append("Assistance outil probable.")
    if "async_commit" in flags:
        lines.append("Livraison possiblement asynchrone.")
    if confidence is not None and confidence < 0.5:
        lines.append("Signaux de travail incertains.")
    elif flags.intersection({"low_evidence", "short_episode", "single_block"}):
        lines.append("Signaux de travail incertains.")
    return lines


def _commit_items_for_render(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = entry.get("commit_items")
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if isinstance(item, dict) and str(item.get("message") or "").strip():
            result.append(item)
    return result


def _journal_commit_line(message: str) -> str:
    subject = next((line.strip() for line in str(message or "").splitlines() if line.strip()), "")
    escaped = subject.replace("\\", "\\\\").replace("*", r"\*")
    return f"**{escaped}**"


def _journal_entry_scope(entry: Dict[str, Any]) -> str:
    top_files = _compact_strings(entry.get("top_files", []))
    if top_files:
        return cluster_files_for_display(top_files)
    files_count = int(entry.get("files_count") or 0)
    if files_count > 0:
        return f"{files_count} fichier(s) / module(s)"
    return "non déterminée"


def _journal_entry_time_range(entry: Dict[str, Any]) -> str:
    start_dt, end_dt = _entry_bounds(entry)
    if start_dt and end_dt and start_dt.date() != end_dt.date():
        return f"{start_dt.strftime('%d/%m %H:%M')} \u2192 {end_dt.strftime('%d/%m %H:%M')}"
    if start_dt and end_dt and start_dt.strftime("%H:%M") == end_dt.strftime("%H:%M"):
        return start_dt.strftime("%H:%M")
    return f"{_format_journal_time(entry.get('started_at'))} \u2192 {_format_journal_time(entry.get('ended_at'))}"


def _format_journal_time(value: Any) -> str:
    if not value:
        return "??:??"
    text = str(value)
    try:
        return datetime.fromisoformat(text).strftime("%H:%M")
    except ValueError:
        if "T" in text: return text.split("T", 1)[1][:5]
        if " " in text: return text.split(" ", 1)[1][:5]
        return text[:5]


def _journal_section_title(entry: Dict[str, Any]) -> str:
    project = _normalize_project_name(entry.get("active_project"))
    if project is None:
        return _off_project_section_title(entry)
    if _is_off_project_entry(entry):
        return _off_project_section_title(entry)
    return project


def _normalize_project_name(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if text.lower() in _UNKNOWN_PROJECT_NAMES:
        return None
    return text or None


def _off_project_section_title(entry: Dict[str, Any]) -> str:
    apps = set(_compact_strings(entry.get("recent_apps", [])))
    if apps and apps.issubset(_BROWSER_APPS):
        return "Recherche / navigation"
    if apps and apps.issubset(_ADMIN_APPS):
        return "Administratif / veille"
    return "Hors projet"


def _is_off_project_entry(entry: Dict[str, Any]) -> bool:
    if _normalize_project_name(entry.get("active_project")) is None:
        return True
    task = str(entry.get("probable_task") or "general")
    activity = str(entry.get("activity_level") or "unknown")
    commit_messages = _compact_strings(entry.get("commit_messages", []))
    apps = _compact_strings(entry.get("recent_apps", []))
    return (task == "general" and activity == "unknown" and not commit_messages and _looks_like_navigation_or_admin(apps))


def _looks_like_navigation_or_admin(apps: List[str]) -> bool:
    if not apps:
        return False
    return any(app in _BROWSER_APPS or app in _ADMIN_APPS for app in apps)


def _is_strong_project_entry(entry: Dict[str, Any]) -> bool:
    if _normalize_project_name(entry.get("active_project")) is None:
        return False
    if _compact_strings(entry.get("commit_messages", [])):
        return True
    if _has_non_technical_scope(entry):
        return True
    confidence = _float_or_zero(entry.get("task_confidence"))
    task = str(entry.get("probable_task") or "general")
    return task != "general" and confidence >= 0.65


def _is_weak_project_entry(entry: Dict[str, Any]) -> bool:
    return _normalize_project_name(entry.get("active_project")) is not None and not _is_strong_project_entry(entry)


def _has_non_technical_scope(entry: Dict[str, Any]) -> bool:
    top_files = _compact_strings(entry.get("top_files", []))
    return bool(top_files) and not _all_files_technical(top_files)


def _resolve_journal_entry_overlaps(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(entries) < 2:
        return entries

    result: List[Dict[str, Any]] = _trim_delivered_commit_overlaps(entries)
    removed_ids: set[str] = set()

    i = 0
    while i < len(result):
        entry = result[i]
        if str(entry.get("entry_id") or "") in removed_ids:
            i += 1
            continue
        j = i + 1
        while j < len(result):
            other = result[j]
            if str(other.get("entry_id") or "") in removed_ids:
                j += 1
                continue
            if not _entries_heavily_overlap(entry, other):
                j += 1
                continue
            if _should_fuse_overlapping_entries(entry, other):
                fused = _fuse_overlapping_pair(entry, other)
                result[i] = fused
                entry = fused
                removed_ids.add(str(other.get("entry_id") or ""))
                j += 1
                continue
            weaker, _ = _choose_weaker_overlapping_entry(entry, other)
            if weaker is not None:
                weaker_id = str(weaker.get("entry_id") or "")
                removed_ids.add(weaker_id)
                if weaker_id == str(entry.get("entry_id") or ""):
                    break
            j += 1
        i += 1

    return [_mark_overlap_demoted(e) if str(e.get("entry_id") or "") in removed_ids else e for e in result]


def _trim_delivered_commit_overlaps(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    adjusted_by_id: Dict[str, Dict[str, Any]] = {}
    latest_end_by_project: Dict[str, datetime] = {}

    for entry in sorted(entries, key=_journal_entry_delivery_key):
        if not _compact_strings(entry.get("commit_messages", [])):
            continue
        project = _normalize_project_name(entry.get("active_project"))
        if project is None:
            continue

        start_dt, end_dt = _entry_bounds(entry)
        if start_dt is None or end_dt is None or end_dt <= start_dt:
            continue

        current = entry
        previous_end = latest_end_by_project.get(project)
        if previous_end is not None and start_dt < previous_end < end_dt:
            current = dict(entry)
            current["started_at"] = previous_end.isoformat()
            current["duration_min"] = max(int((end_dt - previous_end).total_seconds() / 60), 1)
            adjusted_by_id[str(current.get("entry_id") or "")] = current

        latest_end = latest_end_by_project.get(project)
        if latest_end is None or end_dt > latest_end:
            latest_end_by_project[project] = end_dt

    if not adjusted_by_id:
        return list(entries)

    return [adjusted_by_id.get(str(entry.get("entry_id") or ""), entry) for entry in entries]


def _journal_entry_delivery_key(entry: Dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(entry.get("delivered_at") or entry.get("ended_at") or ""),
        str(entry.get("ended_at") or ""),
        str(entry.get("started_at") or ""),
        str(entry.get("entry_id") or ""),
    )


def _should_fuse_overlapping_entries(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return (
        not _compact_strings(left.get("commit_messages", []))
        and not _compact_strings(right.get("commit_messages", []))
        and left.get("active_project") == right.get("active_project")
        and left.get("probable_task") == right.get("probable_task")
    )


def _fuse_overlapping_pair(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    fused = _merge_journal_pair(left, right)
    left_start = str(left.get("started_at") or "")
    right_start = str(right.get("started_at") or "")
    left_end = str(left.get("ended_at") or "")
    right_end = str(right.get("ended_at") or "")
    fused["started_at"] = min(left_start, right_start) if left_start and right_start else left_start or right_start
    fused["ended_at"] = max(left_end, right_end) if left_end and right_end else left_end or right_end
    start_dt = _parse_entry_datetime(fused["started_at"])
    end_dt = _parse_entry_datetime(fused["ended_at"])
    if start_dt and end_dt and end_dt > start_dt:
        fused["duration_min"] = max(int((end_dt - start_dt).total_seconds() / 60), 0)
    return fused


def _entries_heavily_overlap(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_start, left_end = _entry_bounds(left)
    right_start, right_end = _entry_bounds(right)
    if left_start is None or left_end is None or right_start is None or right_end is None:
        return False
    overlap_start = max(left_start, right_start)
    overlap_end = min(left_end, right_end)
    if overlap_end <= overlap_start:
        return False
    overlap_seconds = (overlap_end - overlap_start).total_seconds()
    shortest_seconds = min(max((left_end - left_start).total_seconds(), 60.0), max((right_end - right_start).total_seconds(), 60.0))
    return (overlap_seconds / shortest_seconds) >= 0.5


def _entry_bounds(entry: Dict[str, Any]) -> tuple[Optional[datetime], Optional[datetime]]:
    return _parse_entry_datetime(entry.get("started_at")), _parse_entry_datetime(entry.get("ended_at"))


def _parse_entry_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _choose_weaker_overlapping_entry(left: Dict[str, Any], right: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if _same_project(left, right):
        if _is_strong_commit_entry(left) and _is_weak_snapshot_entry(right):
            return right, left
        if _is_strong_commit_entry(right) and _is_weak_snapshot_entry(left):
            return left, right

    left_project = _is_strong_project_entry(left)
    right_project = _is_strong_project_entry(right)
    left_off = _is_off_project_entry(left)
    right_off = _is_off_project_entry(right)

    if left_project and right_off and _is_weak_unknown_entry(right): return right, left
    if right_project and left_off and _is_weak_unknown_entry(left): return left, right
    if left_off and _is_weak_project_entry(right): return right, left
    if right_off and _is_weak_project_entry(left): return left, right
    return None, None


def _same_project(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_project = _normalize_project_name(left.get("active_project"))
    right_project = _normalize_project_name(right.get("active_project"))
    return left_project is not None and left_project == right_project


def _is_commit_entry(entry: Dict[str, Any]) -> bool:
    return bool(_compact_strings(entry.get("commit_messages", [])))


def _is_strong_commit_entry(entry: Dict[str, Any]) -> bool:
    if not _is_commit_entry(entry):
        return False

    scope_source = str(entry.get("scope_source") or "unknown")
    top_files = _compact_strings(entry.get("top_files", []))

    if scope_source in {"commit_diff", "commit_files"}:
        return True
    if scope_source == "fallback_snapshot" and top_files:
        return True
    return False


def _is_weak_snapshot_entry(entry: Dict[str, Any]) -> bool:
    if _is_commit_entry(entry):
        return False
    if str(entry.get("scope_source") or "unknown") not in {"snapshot", "fallback_snapshot", "unknown", "count_only"}:
        return False
    confidence = _float_or_zero(entry.get("task_confidence"))
    if confidence >= 0.8 and _has_non_technical_scope(entry):
        return False
    return True


def _is_weak_unknown_entry(entry: Dict[str, Any]) -> bool:
    return _is_off_project_entry(entry) and not _compact_strings(entry.get("commit_messages", []))


def _mark_overlap_demoted(entry: Dict[str, Any]) -> Dict[str, Any]:
    demoted = dict(entry)
    demoted["overlap_demoted"] = True
    return demoted


def _is_noise_journal_entry(entry: Dict[str, Any]) -> bool:
    duration = int(entry.get("duration_min") or 0)
    task = str(entry.get("probable_task") or "general")
    commit_messages = _compact_strings(entry.get("commit_messages", []))
    body = str(entry.get("body") or "").strip()
    top_files = _compact_strings(entry.get("top_files", []))
    off_project = _is_off_project_entry(entry)
    activity = str(entry.get("activity_level") or "unknown")

    # Activité idle sans aucun signal de travail — peu importe la durée.
    # Signature typique : nuit devant YouTube, pause café, écran allumé sans usage.
    # Ces données n'ont pas leur place dans un journal de bord dev.
    if (
        activity == "idle"
        and task == "general"
        and not commit_messages
        and not top_files
    ):
        return True

    if duration < 3 and not commit_messages and not _has_useful_journal_body(body): return True
    if entry.get("overlap_demoted"): return True
    if task == "general" and not commit_messages and not off_project and not _has_useful_journal_body(body): return True
    if task == "general" and not commit_messages and not off_project and top_files and _all_files_technical(top_files): return True
    if duration < 5 and not commit_messages and top_files and _all_files_technical(top_files): return True
    return False


def _is_suppressed_journal_entry(entry: Dict[str, Any]) -> bool:
    commit_messages = _compact_strings(entry.get("commit_messages", []))
    top_files = _compact_strings(entry.get("top_files", []))
    return not commit_messages and top_files and _all_files_tooling_metadata(top_files)


def _has_useful_journal_body(body: str) -> bool:
    if not body:
        return False
    normalized = body.strip()
    return len(normalized) >= 20 and not normalized.startswith(("Session de ", "Activité estimée sur ", "Travail observé sur "))


def _all_files_technical(files: List[str]) -> bool:
    if not files:
        return False
    lowered = [name.lower() for name in files]
    return all(any(pattern in name for pattern in _TECHNICAL_FILE_PATTERNS) for name in lowered)


def _all_files_tooling_metadata(files: List[str]) -> bool:
    if not files:
        return False
    return all(Path(name).name.lower() in _TOOLING_METADATA_FILENAMES for name in files)


def _strip_commit_sentence(body: str, commit_messages: List[str]) -> str:
    if not body:
        return ""
    cleaned = body
    for message in commit_messages:
        if not message:
            continue
        escaped = re.escape(message)
        cleaned = re.sub(rf"^Livraison : \u00ab {escaped} \u00bb\.\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _resolve_commit_scope(session: Dict[str, Any], *, diff_summary: Optional[str]) -> tuple[List[str], str]:
    diff_files = extract_file_names_from_diff_summary(diff_summary or "")
    if diff_files:
        return _clean_files(diff_files[:5]), "commit_diff"

    commit_files = _clean_files(session.get("commit_scope_files", []))
    if commit_files:
        return commit_files[:5], "commit_files"

    snapshot_files = _clean_files(session.get("top_files", []))
    if snapshot_files:
        return snapshot_files[:5], "fallback_snapshot"

    if int(session.get("files_changed", 0) or 0) > 0:
        return [], "count_only"
    return [], "unknown"


def _stronger_scope_source(left: Any, right: Any) -> str:
    left_text = str(left or "unknown")
    right_text = str(right or "unknown")
    if _SCOPE_SOURCE_PRIORITY.get(right_text, -1) > _SCOPE_SOURCE_PRIORITY.get(left_text, -1):
        return right_text
    return left_text


def _compact_strings(values: List[Any]) -> List[str]:
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _merge_unique_strings(left: List[Any], right: List[Any]) -> List[str]:
    return _compact_strings([*left, *right])[:5]


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ── Projets et habitudes ──────────────────────────────────────────────────────

def _update_projects(base_dir: Path, session: Dict[str, Any], *, consolidation: Dict[str, Any]) -> None:
    project = consolidation["active_project"]
    if not project:
        return

    projects_file = base_dir / "projects.md"
    with _memory_write_lock:
        current  = _parse_project_sections(projects_file)
        today    = datetime.now().strftime("%Y-%m-%d")
        duration = consolidation["duration_min"]
        task     = consolidation["probable_task"]
        latest_session = _normalize_project_session_record(consolidation.get("session_record"))

        entry = current.get(project)
        if entry is None:
            current[project] = {"first_session": today, "last_session": today, "last_duration": duration, "last_task": task, "task": task, "recent_sessions": []}
        else:
            entry["last_session"] = today
            entry["last_duration"] = duration
            entry["last_task"] = task
            entry["task"] = task
            entry.setdefault("recent_sessions", [])

        entry = current[project]
        entry["recent_sessions"] = _merge_project_recent_sessions(entry.get("recent_sessions", []), latest_session)

        latest_known = entry["recent_sessions"][0] if entry["recent_sessions"] else None
        if latest_known is not None:
            entry["last_session"] = latest_known["date"]
            entry["last_duration"] = latest_known["duration_min"]
            entry["last_task"] = latest_known["probable_task"]

        dominant_task = _dominant_project_task(entry["recent_sessions"]) or entry["task"]
        entry["task"] = dominant_task

        lines = ["# Projets\n"]
        for name in sorted(current):
            item = current[name]
            lines.extend(["", f"## {name}", "",
                f"- Première session : {item['first_session']}",
                f"- Dernière session : {item['last_session']} ({item['last_duration']} min, {item.get('last_task', item['task'])})",
                f"- Type de travail estimé : {item['task']}",
            ])
            recent_sessions = item.get("recent_sessions", [])
            if recent_sessions:
                lines.append("- Sessions récentes :")
                for session_record in recent_sessions[:5]:
                    lines.append(f"  - {session_record['date_time']} | {session_record['probable_task']} | {session_record['activity_level']} | {session_record['duration_min']} min | {session_record['boundary_reason']} | {session_record['record_id']}")
        projects_file.write_text("\n".join(lines).strip() + "\n")


def _update_index(base_dir: Path) -> None:
    index_file = base_dir / "MEMORY.md"
    with _memory_write_lock:
        entries = [f"- [{f.stem}]({f.name})" for f in sorted(base_dir.glob("*.md")) if f.name != "MEMORY.md"]
        content = "# Index mémoire Pulse\n\n" + "\n".join(entries)
        if entries:
            content += "\n"
        index_file.write_text(content)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_project_sections(projects_file: Path) -> Dict[str, Dict[str, Any]]:
    if not projects_file.exists():
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    current_name = None
    in_recent_sessions = False

    for raw_line in projects_file.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_name = line[3:]
            result[current_name] = {"recent_sessions": []}
            in_recent_sessions = False
        elif current_name and line.startswith("- Première session : "):
            result[current_name]["first_session"] = line.split(": ", 1)[1]
            in_recent_sessions = False
        elif current_name and line.startswith("- Dernière session : "):
            value = line.split(": ", 1)[1]
            date_part, details = _split_last_session(value)
            result[current_name]["last_session"] = date_part
            result[current_name]["last_duration"] = details["duration"]
            result[current_name]["last_task"] = details["task"]
            in_recent_sessions = False
        elif current_name and (
            line.startswith("- Type de travail estimé : ")
            or line.startswith("- Type de travail " + "détecté : ")
        ):
            result[current_name]["task"] = line.split(": ", 1)[1]
            in_recent_sessions = False
        elif current_name and line in {"- Sessions récentes :", "- Épisodes récents :"}:
            in_recent_sessions = True
        elif current_name and in_recent_sessions and raw_line.startswith("  - "):
            session_record = _parse_project_session_line(raw_line.strip()[2:].strip())
            if session_record is not None:
                result[current_name]["recent_sessions"].append(session_record)
        elif line:
            in_recent_sessions = False

    return result


def _build_consolidation_frame(
    session_data: Dict[str, Any],
    *,
    commit_message: Optional[str] = None,
    trigger: Optional[str] = None,
) -> Dict[str, Any]:
    session_record = _latest_recent_session(_session_records(session_data))
    active_project = (session_record or {}).get("active_project") or session_data.get("active_project")
    inference_data = session_data
    if _should_discard_stale_active_project(session_data, session_record, active_project, commit_message):
        active_project = None
        inference_data = {**session_data, "active_project": None}
    project_source = "active_project" if active_project else None
    if not active_project:
        active_project, project_source = _infer_project_from_session_evidence(inference_data)
    probable_task = (session_record or {}).get("probable_task") or session_data.get("probable_task") or "general"
    task_confidence = (
        (session_record or {}).get("task_confidence")
        if (session_record or {}).get("task_confidence") is not None
        else session_data.get("task_confidence", session_data.get("confidence"))
    )
    uncertainty_flags = (
        (session_record or {}).get("uncertainty_flags")
        or session_data.get("uncertainty_flags")
        or []
    )
    if commit_message:
        probable_task = _commit_task_correction(commit_message, probable_task)
    session_duration_min = int(session_data.get("duration_min", 0) or 0)
    work_block = _resolve_commit_work_block(session_data, trigger=trigger)
    if work_block is not None:
        return {
            "session_record": session_record,
            "active_project": active_project,
            "project_source": project_source,
            "probable_task": probable_task,
            "activity_level": (session_record or {}).get("activity_level") or session_data.get("activity_level"),
            "task_confidence": task_confidence,
            "uncertainty_flags": uncertainty_flags,
            "duration_min": min(work_block["duration_min"], MAX_SESSION_DURATION_MIN),
            "started_at": work_block["started_at"],
            "ended_at": work_block["ended_at"],
            "delivered_at": work_block.get("delivered_at"),
        }
    if trigger == "commit" and commit_message and (session_data.get("delivered_at") or session_record is not None):
        return _commit_only_consolidation_frame(
            session_data,
            active_project=active_project,
            project_source=project_source,
            probable_task=probable_task,
            fallback_session_record=session_record,
            task_confidence=task_confidence,
            uncertainty_flags=uncertainty_flags,
        )
    duration_min = _session_record_duration_min(session_record)
    if duration_min is not None:
        duration_min = min(duration_min, MAX_SESSION_DURATION_MIN)
    use_session_window = _should_use_session_window_for_commit(
        trigger=trigger,
        session_duration_min=session_duration_min,
        session_record_duration_min=duration_min,
    )
    if duration_min is None or use_session_window:
        duration_min = session_duration_min

    started_at = (session_record or {}).get("started_at")
    ended_at = (session_record or {}).get("ended_at")
    if use_session_window:
        started_at = session_data.get("started_at") or started_at
        ended_at = session_data.get("ended_at") or session_data.get("updated_at") or ended_at

    return {
        "session_record": session_record,
        "active_project": active_project,
        "project_source": project_source,
        "probable_task": probable_task,
        "activity_level": (session_record or {}).get("activity_level") or session_data.get("activity_level"),
        "task_confidence": task_confidence,
        "uncertainty_flags": uncertainty_flags,
        "duration_min": duration_min,
        "started_at": started_at or session_data.get("started_at"),
        "ended_at": ended_at or session_data.get("ended_at") or session_data.get("updated_at"),
    }


def _commit_only_consolidation_frame(
    session_data: Dict[str, Any],
    *,
    active_project: Optional[str],
    probable_task: str,
    project_source: Optional[str] = None,
    fallback_session_record: Optional[Dict[str, Any]] = None,
    task_confidence: Any = None,
    uncertainty_flags: Any = None,
) -> Dict[str, Any]:
    delivered_at = _parse_entry_datetime(
        session_data.get("delivered_at")
        or session_data.get("ended_at")
        or session_data.get("updated_at")
        or (fallback_session_record or {}).get("ended_at")
        or (fallback_session_record or {}).get("started_at")
    ) or datetime.now()
    delivered_iso = delivered_at.isoformat()
    return {
        "session_record": None,
        "active_project": active_project,
        "project_source": project_source,
        "probable_task": probable_task,
        "activity_level": session_data.get("activity_level"),
        "task_confidence": task_confidence,
        "uncertainty_flags": uncertainty_flags or [],
        "duration_min": 1,
        "started_at": delivered_iso,
        "ended_at": delivered_iso,
        "delivered_at": delivered_iso,
    }



def _session_records(session_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return canonical recent sessions with legacy closed_episodes fallback."""
    records = session_data.get("recent_sessions")
    if records is None:
        records = session_data.get("closed_episodes")
    return records if isinstance(records, list) else []


def _resolve_commit_work_block(
    session_data: Dict[str, Any],
    *,
    trigger: Optional[str],
) -> Optional[Dict[str, Any]]:
    if trigger != "commit":
        return None

    started_at = _parse_entry_datetime(
        session_data.get("commit_activity_started_at")
        or session_data.get("work_block_started_at")
        or session_data.get("work_window_started_at")
    )
    ended_at = _parse_entry_datetime(
        session_data.get("commit_activity_ended_at")
        or session_data.get("work_block_ended_at")
        or session_data.get("work_window_ended_at")
        or session_data.get("updated_at")
        or session_data.get("ended_at")
    )
    if started_at is None or ended_at is None or ended_at <= started_at:
        return None

    duration_min = max(int((ended_at - started_at).total_seconds() / 60), 1)
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_min": duration_min,
        "delivered_at": session_data.get("delivered_at"),
    }


def _resolve_commit_work_window(
    session_data: Dict[str, Any],
    *,
    trigger: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Legacy alias kept for older tests/tools; use _resolve_commit_work_block."""
    return _resolve_commit_work_block(session_data, trigger=trigger)


def _should_use_session_window_for_commit(
    *,
    trigger: Optional[str],
    session_duration_min: int,
    session_record_duration_min: Optional[int],
) -> bool:
    if trigger != "commit":
        return False
    if session_duration_min <= 0:
        return False
    if session_record_duration_min is None:
        return True
    if session_record_duration_min <= 1 and session_duration_min >= 5:
        return True
    if session_record_duration_min > 0 and session_duration_min >= max(session_record_duration_min * 3, 10):
        return True
    return False


def _latest_recent_session(session_records: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(session_records, list):
        return None
    def _sort_key(item): return (str(item.get("ended_at") or ""), str(item.get("started_at") or ""))
    candidates = [item for item in session_records if isinstance(item, dict) and item.get("ended_at")]
    if not candidates:
        return None
    return max(candidates, key=_sort_key)


def _session_record_duration_min(session_record: Optional[Dict[str, Any]]) -> Optional[int]:
    if session_record is None:
        return None
    duration_sec = session_record.get("duration_sec")
    if duration_sec is None:
        return None
    try:
        return max(int(round(float(duration_sec) / 60.0)), 0)
    except (TypeError, ValueError):
        return None


def _normalize_project_session_record(session_record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(session_record, dict):
        return None
    ended_at = session_record.get("ended_at")
    started_at = session_record.get("started_at")
    timestamp = ended_at or started_at
    if not timestamp:
        return None
    duration_min = _session_record_duration_min(session_record)
    if duration_min is None:
        return None
    date, date_time = _format_project_session_timestamp(str(timestamp))

    return {
        "record_id": _session_record_id(session_record),
        "date": date, "date_time": date_time,
        "probable_task": str(session_record.get("probable_task") or "general"),
        "activity_level": str(session_record.get("activity_level") or "unknown"),
        "duration_min": duration_min,
        "boundary_reason": str(session_record.get("boundary_reason") or "unknown"),
    }


def _session_record_id(session_record: Dict[str, Any]) -> str:
    """Return canonical session id with legacy episode_id fallback."""
    return str(session_record.get("id") or session_record.get("episode_id") or "")


def _merge_project_recent_sessions(existing: List[Dict[str, Any]], latest: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sessions = [session_record for session_record in existing if isinstance(session_record, dict)]
    if latest is not None:
        sessions = [session_record for session_record in sessions if session_record.get("record_id") != latest["record_id"]]
        sessions.append(latest)
    sessions.sort(key=lambda item: (str(item.get("date_time") or ""), str(item.get("record_id") or "")), reverse=True)
    return sessions[:5]


def _dominant_project_task(session_records: List[Dict[str, Any]]) -> Optional[str]:
    counts: Dict[str, int] = {}
    for session_record in session_records:
        task = str(session_record.get("probable_task") or "general")
        counts[task] = counts.get(task, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda task: (counts[task], next((index for index, session_record in enumerate(session_records) if session_record.get("probable_task") == task), len(session_records)) * -1))


def _format_project_session_timestamp(timestamp: str) -> tuple[str, str]:
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp[:10], timestamp.replace("T", " ")[:16]
    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m-%d %H:%M")


def _parse_project_session_line(value: str) -> Optional[Dict[str, Any]]:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) != 6:
        return None
    duration_text = parts[3]
    if not duration_text.endswith(" min"):
        return None
    try:
        duration_min = int(duration_text[:-4].strip())
    except ValueError:
        return None
    date_time = parts[0]
    return {
        "date": date_time[:10], "date_time": date_time,
        "probable_task": parts[1] or "general", "activity_level": parts[2] or "unknown",
        "duration_min": duration_min, "boundary_reason": parts[4] or "unknown", "record_id": parts[5],
    }


def _split_last_session(value: str) -> tuple:
    if "(" not in value or ")" not in value:
        return value, {"duration": 0, "task": "general"}
    date_part, rest = value.split("(", 1)
    details = rest.rstrip(")")
    duration, task = 0, "general"
    if "," in details:
        dur_part, task_part = details.split(",", 1)
        tokens = dur_part.strip().split()
        if tokens and tokens[0].isdigit():
            duration = int(tokens[0])
        task = task_part.strip()
    return date_part.strip(), {"duration": duration, "task": task}


def _time_slot(hour: int) -> str:
    if 6 <= hour < 12: return "matin"
    if 12 <= hour < 18: return "après-midi"
    return "soir"


def _llm_complete(llm: Any, prompt: str, max_tokens: int = 150, think: Optional[bool] = None, system: str = "", profile: str = "default") -> str:
    if hasattr(llm, "complete"):
        kwargs: Dict[str, Any] = {"max_tokens": max_tokens, "profile": profile}
        if think is not None:
            kwargs["think"] = think
        if system:
            kwargs["system"] = system
        try:
            return llm.complete(prompt, **kwargs)
        except TypeError:
            kwargs.pop("think", None)
            kwargs.pop("system", None)
            kwargs.pop("profile", None)
            return llm.complete(prompt, **kwargs)
    raise TypeError("LLM provider incompatible")
