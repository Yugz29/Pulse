"""
extractor.py — Génération des rapports de session Pulse.

Déclencheurs
────────────
  1. Commit git (signal principal — LLM activé)
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

import json
import logging
import re
import subprocess
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.core.file_cluster import cluster_files_for_display
from daemon.core.git_diff import extract_file_names_from_diff_summary
from daemon.memory.facts import FactEngine
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
_BROWSER_APPS = {"Safari", "Google Chrome", "Chrome", "Arc", "Firefox", "Brave Browser", "Brave"}
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
        else None
    )

    report_ref = _write_session_report(
        base_dir, session_data, consolidation=consolidation,
        llm=effective_llm, commit_message=commit_message, trigger=trigger, diff_summary=diff_summary,
    )

    if trigger == "commit" and llm is not None and report_ref is not None:
        _, current_entry_id = report_ref

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

        threading.Thread(target=_enrich_pending, daemon=True, name="pulse-journal-enrich").start()

    _cooldown.last_report_at[project] = datetime.now()
    _save_cooldown()
    _update_index(base_dir)

    # Vectoriser l'entrée dans un thread séparé — ne pas bloquer le pipeline.
    # L'embedding est lent (1-2s au premier appel) mais non critique.
    if report_ref is not None:
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
        threading.Thread(target=_vectorize, daemon=True, name="pulse-vectorize").start()

    return report_ref



def enrich_session_report(
    report_ref, session_data: Dict[str, Any], llm: Any,
    *, commit_message: Optional[str] = None, diff_summary: Optional[str] = None,
) -> bool:
    if report_ref is None or llm is None:
        return False
    journal_file, entry_id = report_ref
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
    if str(entry.get("summary_source") or "") == "llm":
        return False
    if str(entry.get("summary_status") or "unknown") not in {"failed", "llm_unavailable", "unknown", "deferred"}:
        return False
    if not str(entry.get("commit_message") or "").strip():
        return False
    if _is_suppressed_journal_entry(entry) or _is_noise_journal_entry(entry):
        return False
    return True


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
        delivered_at=consolidation.get("delivered_at") or session.get("delivered_at"),
        summary_source=summary_source,
        summary_status=summary_status,
        summary_error=summary_error,
    )

    with _memory_write_lock:
        entries = _load_journal_entries(journal_file)
        entries.append(entry)
        _write_journal_document(journal_file, today, entries)

    return (journal_file, entry_id)


def _llm_summary(llm, project, duration, task, focus, friction, apps, top_files, files_count, commit_message, diff_summary, *, scope_source="snapshot") -> str:
    facts: List[str] = [f"Projet : {project}", f"Durée : {duration} minutes"]
    if commit_message:
        facts.append(f'Commit : "{commit_message.splitlines()[0]}"')
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
    facts_block = "\n".join(f"- {f}" for f in facts)
    prompt = f"""\
Voici les données factuelles du commit livré :

{facts_block}

Écris 1 à 2 phrases courtes en français.
Adopte un ton de note de journal concise et factuelle.
Dis ce qui a été livré et la portée principale — pas comment ni les détails techniques.
Évite les tournures emphatiques comme « Ce commit améliore... ».
Si le message de commit est explicite, reformule-le naturellement dans ce ton.
N'invente aucun fait absent des données ci-dessus."""
    return _llm_complete(llm, prompt, max_tokens=256, think=False)


def _deterministic_summary(duration, task, focus, friction, top_files, files_count, commit_message, *, diff_summary=None, terminal_summary=None, scope_source="snapshot") -> str:
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
    return " ".join(parts)


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


def _replace_journal_entry(
    journal_file: Path,
    entry_id: str,
    body: str,
    *,
    summary_source: Optional[str] = None,
    summary_status: Optional[str] = None,
    summary_error: Optional[str] = None,
) -> bool:
    with _memory_write_lock:
        if not journal_file.exists():
            return False
        entries = _load_journal_entries(journal_file)
        updated = False
        for entry in entries:
            if entry.get("entry_id") == entry_id:
                entry["body"] = body.strip()
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


def _new_entry_id(now: datetime) -> str:
    return now.strftime("%Y%m%d%H%M%S%f")


def _build_journal_entry(*, entry_id, active_project, probable_task, activity_level, task_confidence,
    duration_min, body, commit_message, recent_apps, top_files, files_count, started_at, ended_at, boundary_reason,
    scope_source="snapshot", delivered_at=None,
    summary_source="deterministic_fallback", summary_status="llm_unavailable", summary_error=None) -> Dict[str, Any]:
    return {
        "entry_id": entry_id,
        "active_project": active_project or "Autre",
        "probable_task": probable_task or "general",
        "activity_level": activity_level or "unknown",
        "task_confidence": task_confidence,
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
        "summary_source": summary_source or "deterministic_fallback",
        "summary_status": summary_status or "unknown",
        "summary_error": summary_error,
    }


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
    normalized["probable_task"] = normalized.get("probable_task") or "general"
    normalized["activity_level"] = normalized.get("activity_level") or "unknown"
    normalized["top_files"] = [str(item) for item in normalized.get("top_files", []) if isinstance(item, str) and item.strip()]
    normalized["recent_apps"] = _compact_strings(normalized.get("recent_apps", []))
    normalized["duration_min"] = int(max(normalized.get("duration_min") or 0, 0))
    normalized["commit_messages"] = _compact_strings([normalized.get("commit_message"), *normalized.get("commit_messages", [])])
    normalized["scope_source"] = str(normalized.get("scope_source") or "unknown")
    normalized["summary_source"] = str(normalized.get("summary_source") or "unknown")
    normalized["summary_status"] = str(normalized.get("summary_status") or "unknown")
    normalized["summary_error"] = normalized.get("summary_error")
    normalized["probable_task"] = _correct_snapshot_task_from_scope(normalized)
    return normalized


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
    merged["task_confidence"] = max(_float_or_zero(left.get("task_confidence")), _float_or_zero(right.get("task_confidence")))
    merged["files_count"] = max(int(left.get("files_count") or 0), len(_merge_unique_strings(left.get("top_files", []), right.get("top_files", []))), int(right.get("files_count") or 0))
    merged["top_files"] = _merge_unique_strings(left.get("top_files", []), right.get("top_files", []))
    merged["commit_messages"] = _merge_unique_strings(left.get("commit_messages", []), right.get("commit_messages", []))
    merged["recent_apps"] = _merge_unique_strings(left.get("recent_apps", []), right.get("recent_apps", []))
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
        left_has_commit = bool((left.get("commit_message") or "").strip())
        right_has_commit = bool((right.get("commit_message") or "").strip())
        left_body = left.get("body") if left_has_commit else None
        right_body = right.get("body") if right_has_commit else None
        merged["body"] = "\n".join(_compact_strings([left_body, right_body]))
    else:
        merged["body"] = str(right.get("body") or left.get("body") or "").strip()
    return merged


def _journal_entry_title(entry: Dict[str, Any]) -> str:
    task_labels = {"coding": "développement", "debug": "débogage", "writing": "rédaction", "exploration": "exploration", "browsing": "exploration", "general": "travail général"}
    task = str(entry.get("probable_task") or "general")
    return task_labels.get(task, task.replace("_", " "))


def _journal_entry_description(entry: Dict[str, Any]) -> str:
    lines: List[str] = []
    commit_messages = _compact_strings(entry.get("commit_messages", []))
    body = str(entry.get("body") or "").strip()
    body = _strip_commit_sentence(body, commit_messages)
    if body.startswith(("Port\u00e9e : ", "Port\u00e9e estim\u00e9e : ")) and not commit_messages:
        body = ""

    if commit_messages:
        if len(commit_messages) == 1:
            # Commit unique : message en gras, résumé en dessous
            lines.append(f"**{commit_messages[0]}**")
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
                    lines.append(f"**{msg}**")
                    lines.append(summary)
                    if i < len(commit_messages) - 1:
                        lines.append("")
                        lines.append("")
            else:
                lines.append("Commits : " + " \u00b7 ".join(commit_messages))
                if body:
                    lines.append(body)
    else:
        if body:
            lines.append(body)

    if not lines:
        duration = int(entry.get("duration_min") or 0)
        lines.append(f"Travail observ\u00e9 sur {_journal_entry_title(entry)} pendant {duration} min.")
    return "\n".join(lines)


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
    return len(normalized) >= 20 and not normalized.startswith(("Session de ", "Travail observé sur "))


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
                f"- Type de travail détecté : {item['task']}",
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
        elif current_name and line.startswith("- Type de travail détecté : "):
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
    probable_task = (session_record or {}).get("probable_task") or session_data.get("probable_task") or "general"
    if commit_message:
        probable_task = _commit_task_correction(commit_message, probable_task)
    session_duration_min = int(session_data.get("duration_min", 0) or 0)
    work_block = _resolve_commit_work_block(session_data, trigger=trigger)
    if work_block is not None:
        return {
            "session_record": session_record,
            "active_project": active_project,
            "probable_task": probable_task,
            "activity_level": (session_record or {}).get("activity_level") or session_data.get("activity_level"),
            "task_confidence": (session_record or {}).get("task_confidence") or session_data.get("task_confidence"),
            "duration_min": work_block["duration_min"],
            "started_at": work_block["started_at"],
            "ended_at": work_block["ended_at"],
            "delivered_at": work_block.get("delivered_at"),
        }
    duration_min = _session_record_duration_min(session_record)
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
        "probable_task": probable_task,
        "activity_level": (session_record or {}).get("activity_level") or session_data.get("activity_level"),
        "task_confidence": (session_record or {}).get("task_confidence") or session_data.get("task_confidence"),
        "duration_min": duration_min,
        "started_at": started_at or session_data.get("started_at"),
        "ended_at": ended_at or session_data.get("ended_at") or session_data.get("updated_at"),
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


def _llm_complete(llm: Any, prompt: str, max_tokens: int = 150, think: Optional[bool] = None) -> str:
    if hasattr(llm, "complete"):
        kwargs = {"max_tokens": max_tokens}
        if think is not None:
            kwargs["think"] = think
        try:
            return llm.complete(prompt, **kwargs)
        except TypeError:
            kwargs.pop("think", None)
            return llm.complete(prompt, **kwargs)
    raise TypeError("LLM provider incompatible")
