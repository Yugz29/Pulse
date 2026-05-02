from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from daemon.core.uid import new_uid

RESUME_PAUSE_THRESHOLD_MIN = 20
RESUME_CARD_COOLDOWN_MIN = 120

DisplaySize = Literal["compact", "standard", "expanded"]
GeneratedBy = Literal["deterministic", "llm"]


@dataclass(frozen=True)
class ResumeCard:
    id: str
    project: str | None
    title: str
    summary: str
    last_objective: str
    next_action: str
    confidence: float
    source_refs: list[str] = field(default_factory=list)
    generated_by: GeneratedBy = "deterministic"
    display_size: DisplaySize = "standard"
    created_at: datetime = field(default_factory=datetime.now)

    def to_event_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


def should_offer_resume_card(
    *,
    event_type: str,
    sleep_minutes: float | None,
    active_project: str | None,
    memory_payload: dict[str, Any] | None,
    last_offered_at: datetime | None,
    now: datetime | None = None,
    pause_threshold_min: int = RESUME_PAUSE_THRESHOLD_MIN,
    cooldown_min: int = RESUME_CARD_COOLDOWN_MIN,
) -> bool:
    if event_type not in {"screen_unlocked", "resume_after_pause"}:
        return False
    if sleep_minutes is None or sleep_minutes < pause_threshold_min:
        return False
    if not _clean(active_project):
        return False
    payload = memory_payload or {}
    if int(payload.get("duration_min", 0) or 0) <= 0 and not _work_block_started_at(payload):
        return False
    if last_offered_at is not None:
        reference = now or datetime.now()
        if reference - last_offered_at < timedelta(minutes=cooldown_min):
            return False
    return True


def build_resume_card_context(
    *,
    runtime_snapshot,
    memory_payload: dict[str, Any] | None,
    sleep_minutes: float | None,
    diff_summary: str | None = None,
) -> dict[str, Any]:
    present = runtime_snapshot.present
    signals = runtime_snapshot.signals
    payload = dict(memory_payload or {})
    recent_journal_entries = list(payload.get("recent_journal_entries") or [])[:5]
    recent_files = _recent_files(payload, signals, recent_journal_entries=recent_journal_entries)
    work_block_started_at = _work_block_started_at(payload)
    work_block_commit_count = payload.get("work_block_commit_count") or payload.get("work_window_commit_count") or 0
    recent_sessions = list(payload.get("recent_sessions") or payload.get("closed_episodes") or [])[:3]
    source_refs = ["present_state", "session_memory"]
    if work_block_started_at:
        source_refs.append("work_block")
    if recent_sessions:
        source_refs.append("recent_sessions")
    if recent_journal_entries:
        source_refs.append("recent_journal_entries")
    if diff_summary:
        source_refs.append("git_diff")

    context = {
        "project": present.active_project or payload.get("active_project"),
        "active_file": _resume_active_file(present.active_file or payload.get("active_file"), recent_files),
        "probable_task": present.probable_task or payload.get("probable_task") or "general",
        "activity_level": present.activity_level or payload.get("activity_level") or "idle",
        "focus_level": present.focus_level or payload.get("focus_level") or "normal",
        "duration_min": present.session_duration_min or payload.get("duration_min") or 0,
        "sleep_minutes": sleep_minutes,
        "recent_files": recent_files,
        "commit_scope_files": list(payload.get("commit_scope_files") or [])[:5],
        "work_block_started_at": work_block_started_at,
        "work_block_commit_count": work_block_commit_count,
        "recent_sessions": recent_sessions,
        "recent_journal_entries": recent_journal_entries,
        "diff_summary": diff_summary or "",
        "source_refs": source_refs,
    }
    _attach_legacy_resume_context_aliases(context)
    return context


def _attach_legacy_resume_context_aliases(context: dict[str, Any]) -> None:
    """Expose old resume context keys while prompts/tools migrate.

    Canonical keys:
    - work_block_started_at
    - work_block_commit_count
    - recent_sessions

    Legacy aliases:
    - work_window_started_at
    - work_window_commit_count
    - closed_episodes
    """
    context["work_window_started_at"] = context["work_block_started_at"]
    context["work_window_commit_count"] = context["work_block_commit_count"]
    context["closed_episodes"] = context["recent_sessions"]


def generate_resume_card(context: dict[str, Any], llm: Any = None) -> ResumeCard:
    deterministic = _deterministic_card(context)
    if llm is None or not hasattr(llm, "complete"):
        return deterministic

    try:
        prompt = _llm_prompt(context, deterministic)
        raw = llm.complete(prompt, max_tokens=480)
        parsed = _parse_llm_card(raw)
        if parsed is None:
            return deterministic
        return _card_from_llm(context, deterministic, parsed)
    except Exception:
        return deterministic


# --- Debug version for local routes ---
def generate_resume_card_with_debug(context: dict[str, Any], llm: Any = None) -> tuple[ResumeCard, dict[str, Any]]:
    """Generate a resume card and return debug diagnostics for local routes."""
    deterministic = _deterministic_card(context)
    debug: dict[str, Any] = {
        "llm_available": llm is not None and hasattr(llm, "complete"),
        "llm_called": False,
        "fallback_reason": None,
        "raw_preview": None,
        "error": None,
    }
    if not debug["llm_available"]:
        debug["fallback_reason"] = "llm_unavailable"
        return deterministic, debug

    try:
        prompt = _llm_prompt(context, deterministic)
        debug["llm_called"] = True
        raw = llm.complete(prompt, max_tokens=480)
        debug["raw_preview"] = _limit_line(str(raw or ""), 800)
        parsed, parse_reason = _parse_llm_card_with_reason(raw)
        if parsed is None:
            debug["fallback_reason"] = parse_reason or "parse_failed"
            return deterministic, debug
        return _card_from_llm(context, deterministic, parsed), debug
    except Exception as exc:
        debug["fallback_reason"] = "exception"
        debug["error"] = f"{type(exc).__name__}: {exc}"
        return deterministic, debug


def _work_block_started_at(payload: dict[str, Any]) -> Any:
    return payload.get("work_block_started_at") or payload.get("work_window_started_at")


@dataclass(frozen=True)
class _JournalFocus:
    hint: str | None = None
    summary: str | None = None
    last_objective: str | None = None
    next_action: str | None = None


def _recent_journal_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
        if len(result) >= 5:
            break
    return result


def _journal_focus(entries: list[dict[str, Any]]) -> _JournalFocus:
    if not entries:
        return _JournalFocus()

    best = _best_journal_entry(entries)
    if best is None:
        return _JournalFocus()

    project = _clean(best.get("project") or best.get("active_project"))
    task = _clean(best.get("task") or best.get("probable_task")) or "general"
    files = _compact_text_list(best.get("top_files"))
    short_files = [_resume_short_file(path) for path in files if _resume_short_file(path)]
    file_focus = ", ".join(short_files[:3]) if short_files else None
    duration = _journal_duration(best)

    topic = _journal_topic(best, file_focus=file_focus)
    if not topic:
        return _JournalFocus()

    prefix = f"Tu étais sur {project}" if project else "Tu reprenais une session récente"
    duration_label = f" · {duration} min" if duration else ""
    summary = f"{prefix} : {topic}{duration_label}."

    if file_focus:
        last_objective = f"Stabiliser {file_focus}."
        next_action = f"Rouvrir {short_files[0]} et tester le comportement attendu."
    else:
        last_objective = f"Reprendre : {topic}."
        next_action = "Relire le dernier changement utile, puis tester le comportement attendu."

    hint_parts = [part for part in (project, task, f"{duration} min" if duration else None) if part]
    return _JournalFocus(
        hint=" / ".join(hint_parts) if hint_parts else None,
        summary=summary,
        last_objective=last_objective,
        next_action=next_action,
    )


def _journal_topic(entry: dict[str, Any], *, file_focus: str | None) -> str | None:
    commit_message = _clean(entry.get("commit_message"))
    commit_messages = _compact_text_list(entry.get("commit_messages"))
    body = _clean(entry.get("body"))

    raw = commit_message or (commit_messages[0] if commit_messages else None) or body
    topic = _humanize_commit_message(raw)
    topic = _strip_low_value_resume_prefixes(topic)
    if topic:
        return _limit_line(topic, 68)
    if file_focus:
        return f"travail autour de {file_focus}"
    return None


def _strip_low_value_resume_prefixes(value: str | None) -> str | None:
    text = _clean(value)
    if not text:
        return None

    prefixes = (
        "le commit ajoute ",
        "ce commit ajoute ",
        "ce commit ajuste ",
        "ce commit corrige ",
        "implémentation de ",
        "implementation de ",
        "en cours : ",
    )
    lowered = text.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    return text[:1].lower() + text[1:] if text else None


def _best_journal_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    meaningful: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        task = _clean(entry.get("task") or entry.get("probable_task")) or "general"
        body = _clean(entry.get("body"))
        commit_message = _clean(entry.get("commit_message"))
        files = _compact_text_list(entry.get("top_files"))
        if task == "general" and not body and not commit_message and not files:
            continue
        meaningful.append(entry)
    return meaningful[0] if meaningful else None


def _journal_duration(entry: dict[str, Any]) -> int | None:
    value = entry.get("duration_min")
    try:
        duration = int(float(value))
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def _humanize_commit_message(value: str | None) -> str | None:
    text = _clean(value)
    if not text:
        return None
    if ":" in text:
        prefix, rest = text.split(":", 1)
        if prefix.lower().split("(", 1)[0] in {"feat", "fix", "docs", "test", "refactor", "chore"}:
            text = rest.strip()
    text = text.replace("_", " ").strip()
    return text


def _compact_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _deterministic_card(context: dict[str, Any]) -> ResumeCard:
    project = _clean(context.get("project"))
    task = _clean(context.get("probable_task")) or "general"
    activity = _clean(context.get("activity_level")) or "idle"
    active_file = _resume_short_file(context.get("active_file"))
    recent_files = [_resume_short_file(path) for path in context.get("recent_files", []) if _resume_short_file(path)]
    commit_scope_files = [_resume_short_file(path) for path in context.get("commit_scope_files", []) if _resume_short_file(path)]
    recent_journal_entries = _recent_journal_entries(context.get("recent_journal_entries"))
    journal_focus = _journal_focus(recent_journal_entries)
    primary_file = active_file or (recent_files[0] if recent_files else None) or (commit_scope_files[0] if commit_scope_files else None)
    file_focus = _file_focus_label(primary_file, recent_files, commit_scope_files)
    diff_focus = _diff_focus_label(context.get("diff_summary"))
    recent_session_hint = journal_focus.hint or _recent_session_hint(context.get("recent_sessions"))

    summary = journal_focus.summary or _resume_summary(
        project=project,
        task=task,
        activity=activity,
        file_focus=file_focus,
        diff_focus=diff_focus,
        recent_session_hint=recent_session_hint,
    )
    last_objective = journal_focus.last_objective or _resume_last_objective(
        task=task,
        activity=activity,
        file_focus=file_focus,
        diff_focus=diff_focus,
        recent_session_hint=recent_session_hint,
    )
    next_action = journal_focus.next_action or _resume_next_action(
        primary_file=primary_file,
        file_focus=file_focus,
        diff_focus=diff_focus,
        recent_session_hint=recent_session_hint,
    )

    evidence_count = len(context.get("source_refs") or [])
    if file_focus:
        evidence_count += 1
    if diff_focus:
        evidence_count += 1
    if recent_session_hint:
        evidence_count += 1
    if journal_focus.summary:
        evidence_count += 1
    confidence = min(0.9, 0.52 + evidence_count * 0.08)
    return ResumeCard(
        id=new_uid(),
        project=project,
        title="Reprise de contexte",
        summary=_limit_line(summary, 110),
        last_objective=_limit_line(last_objective, 120),
        next_action=_limit_line(next_action, 130),
        confidence=round(confidence, 2),
        source_refs=list(context.get("source_refs") or []),
        generated_by="deterministic",
        display_size=_display_size(summary, last_objective, next_action),
    )


def _card_from_llm(
    context: dict[str, Any],
    fallback: ResumeCard,
    parsed: dict[str, Any],
) -> ResumeCard:
    summary = _normalize_resume_card_terms(_clean(parsed.get("summary")) or fallback.summary)
    last_objective = _normalize_resume_card_terms(_clean(parsed.get("last_objective")) or fallback.last_objective)
    next_action = _normalize_resume_card_terms(_clean(parsed.get("next_action")) or fallback.next_action)
    display_size = _display_size(summary, last_objective, next_action)
    summary_limit, objective_limit, action_limit = _llm_card_text_limits(display_size)
    return ResumeCard(
        id=fallback.id,
        project=fallback.project,
        title=_clean(parsed.get("title")) or fallback.title,
        summary=_limit_line(summary, summary_limit),
        last_objective=_limit_line(last_objective, objective_limit),
        next_action=_limit_line(next_action, action_limit),
        confidence=max(0.0, min(float(parsed.get("confidence") or fallback.confidence), 0.95)),
        source_refs=list(context.get("source_refs") or fallback.source_refs),
        generated_by="llm",
        display_size=display_size,
        created_at=fallback.created_at,
    )


def _resume_summary(
    *,
    project: str | None,
    task: str,
    activity: str,
    file_focus: str | None,
    diff_focus: str | None,
    recent_session_hint: str | None,
) -> str:
    base = f"Tu étais sur {project}" if project else "Tu revenais sur une session de travail"
    if diff_focus:
        return f"{base}, sur des changements récents dans {diff_focus}."
    if file_focus:
        return f"{base}, en {activity} autour de {file_focus}."
    if recent_session_hint:
        return f"{base}, dans la continuité de {recent_session_hint}."
    return f"{base}."


def _resume_last_objective(
    *,
    task: str,
    activity: str,
    file_focus: str | None,
    diff_focus: str | None,
    recent_session_hint: str | None,
) -> str:
    task_label = task if task != "general" else activity
    if diff_focus:
        return f"Stabiliser {diff_focus}."
    if file_focus:
        return f"Reprendre le travail {task_label} autour de {file_focus}."
    if recent_session_hint:
        return f"Reprendre la continuité de {recent_session_hint}."
    return f"Reprendre le travail {task_label}."


def _resume_next_action(
    *,
    primary_file: str | None,
    file_focus: str | None,
    diff_focus: str | None,
    recent_session_hint: str | None,
) -> str:
    if diff_focus:
        first_file = diff_focus.split(",", 1)[0].strip()
        return f"Rouvrir {first_file}, relire le dernier changement et tester."
    if primary_file:
        return f"Rouvrir {primary_file}, relire le dernier changement et valider la suite."
    if file_focus:
        return f"Reprendre par {file_focus} et vérifier le prochain geste concret."
    if recent_session_hint:
        return f"Reprendre depuis {recent_session_hint} et confirmer le prochain fichier utile."
    return "Reprendre par le dernier fichier actif ou relancer une action de test ciblée."


def _llm_prompt(context: dict[str, Any], fallback: ResumeCard) -> str:
    llm_context = _llm_resume_context(context)
    return (
        "Tu écris une Resume Card Pulse en français pour aider l'utilisateur à reprendre son travail après une pause.\n"
        "Réponds uniquement en JSON valide avec les clés: title, summary, last_objective, next_action, confidence.\n"
        "Objectif: produire une vraie reprise, pas une phrase générique.\n"
        "summary: résume ce qui était concrètement en cours en 1 phrase.\n"
        "last_objective: explique le but de travail probable, pas seulement le nom d'un fichier.\n"
        "next_action: donne le prochain geste vérifiable et concret.\n"
        "Contraintes fortes:\n"
        "- 'Resume Card' signifie carte de reprise Pulse, jamais CV ou curriculum vitae;\n"
        "- n'utilise jamais le terme CV dans la réponse;\n"
        "- français naturel, phrases courtes;\n"
        "- n'invente rien hors contexte;\n"
        "- ne dis pas seulement 'relire le journal', 'rouvrir le fichier', ou 'tester le comportement attendu' sans préciser quoi;\n"
        "- ne recopie pas les messages de commit en anglais tels quels: reformule leur sens en français;\n"
        "- évite les détails bruts de diff du type (+127 -5);\n"
        "- maximum 5 lignes côté UI.\n\n"
        f"Contexte de reprise priorisé:\n{json.dumps(llm_context, ensure_ascii=False, default=str)[:5000]}\n\n"
        f"Fallback déterministe, à améliorer si possible:\n{json.dumps(fallback.to_event_payload(), ensure_ascii=False)}"
    )

def _normalize_resume_card_terms(value: str) -> str:
    text = str(value or "")
    replacements = {
        "cartes de CV": "cartes de reprise",
        "carte de CV": "carte de reprise",
        "cartes CV": "cartes de reprise",
        "carte CV": "carte de reprise",
        "Cartes de CV": "Cartes de reprise",
        "Carte de CV": "Carte de reprise",
        "Cartes CV": "Cartes de reprise",
        "Carte CV": "Carte de reprise",
        "de CV": "de reprise",
        "du CV": "de la reprise",
    }
    for needle, replacement in replacements.items():
        text = text.replace(needle, replacement)
    return text


def _llm_resume_context(context: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, task-oriented context for LLM resume synthesis."""
    journal_entries = _recent_journal_entries(context.get("recent_journal_entries"))
    compact_entries: list[dict[str, Any]] = []
    for entry in journal_entries[:5]:
        files = [_resume_short_file(path) for path in _compact_text_list(entry.get("top_files"))]
        compact_entries.append({
            "project": entry.get("project") or entry.get("active_project"),
            "task": entry.get("task") or entry.get("probable_task"),
            "activity_level": entry.get("activity_level"),
            "duration_min": entry.get("duration_min"),
            "body": _limit_line(str(entry.get("body") or ""), 220),
            "commit_message": _humanize_commit_message(str(entry.get("commit_message") or "")),
            "commit_messages": [_humanize_commit_message(item) for item in _compact_text_list(entry.get("commit_messages"))[:3]],
            "top_files": [file for file in files if file][:5],
            "boundary_reason": entry.get("boundary_reason"),
        })

    return {
        "project": context.get("project"),
        "probable_task": context.get("probable_task"),
        "activity_level": context.get("activity_level"),
        "focus_level": context.get("focus_level"),
        "duration_min": context.get("duration_min"),
        "sleep_minutes": context.get("sleep_minutes"),
        "active_file": _resume_short_file(context.get("active_file")),
        "recent_files": [_resume_short_file(path) for path in context.get("recent_files", []) if _resume_short_file(path)][:5],
        "commit_scope_files": [_resume_short_file(path) for path in context.get("commit_scope_files", []) if _resume_short_file(path)][:5],
        "diff_focus": _diff_focus_label(context.get("diff_summary")),
        "recent_journal_entries": compact_entries,
        "source_refs": context.get("source_refs") or [],
    }


def _parse_llm_card(raw: Any) -> dict[str, Any] | None:
    parsed, _reason = _parse_llm_card_with_reason(raw)
    return parsed


def _parse_llm_card_with_reason(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, str):
        return None, "non_string_response"
    text = raw.strip()
    if not text:
        return None, "empty_response"
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc.msg}"
    if not isinstance(parsed, dict):
        return None, "json_not_object"
    if not any(_clean(parsed.get(key)) for key in ("summary", "last_objective", "next_action")):
        return None, "missing_resume_fields"
    for key in ("summary", "last_objective", "next_action"):
        value = _clean(parsed.get(key))
        if value and _is_low_value_llm_resume_line(value):
            return None, f"low_value_line:{key}"
    return parsed, None


def _is_low_value_llm_resume_line(value: str) -> bool:
    text = value.strip().lower()
    banned_exact = {
        "relire le journal.",
        "relire le dernier journal.",
        "rouvrir le fichier.",
        "tester le comportement attendu.",
        "vérifier le prochain geste.",
    }
    if text in banned_exact:
        return True
    weak_patterns = (
        "relire le journal",
        "relire le dernier journal",
        "vérifier le prochain geste",
    )
    return any(pattern in text for pattern in weak_patterns)


def _recent_files(
    payload: dict[str, Any],
    signals: Any,
    *,
    recent_journal_entries: list[dict[str, Any]] | None = None,
) -> list[str]:
    files: list[str] = []

    for entry in recent_journal_entries or []:
        if not isinstance(entry, dict):
            continue
        files.extend(str(item) for item in _compact_text_list(entry.get("top_files")))

    for key in ("commit_scope_files", "top_files", "recent_files"):
        value = payload.get(key) or []
        if isinstance(value, list):
            files.extend(str(item) for item in value if item)

    active_file = getattr(signals, "active_file", None)
    if active_file:
        files.append(str(active_file))

    seen: set[str] = set()
    result: list[str] = []
    for path in files:
        short = _resume_short_file(path)
        if not short or short in seen:
            continue
        seen.add(short)
        result.append(path)
        if len(result) >= 5:
            break
    return result


def _file_focus_label(
    primary_file: str | None,
    recent_files: list[str],
    commit_scope_files: list[str],
) -> str | None:
    files = _dedupe_text([primary_file, *recent_files, *commit_scope_files])
    if not files:
        return None
    if len(files) == 1:
        return files[0]
    return ", ".join(files[:3])


def _diff_focus_label(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None

    names = [
        _resume_short_file(match)
        for match in re.findall(r"[A-Za-z0-9_+./-]+\.[A-Za-z0-9_+-]+", text)
    ]
    names = _dedupe_text([name for name in names if name])
    if names:
        return ", ".join(names[:3])

    cleaned = re.sub(r"\([+\-0-9\s]+\)", "", text)
    cleaned = cleaned.replace("Diff en cours :", "").replace("Fonctions touchées :", "")
    cleaned = cleaned.strip(" :,-")
    return _limit_line(cleaned, 58) if cleaned else None


def _resume_active_file(value: Any, recent_files: list[str]) -> str | None:
    candidate = _resume_short_file(value)
    if candidate:
        return str(value)
    for item in recent_files:
        if _resume_short_file(item):
            return str(item)
    return None


def _resume_short_file(value: Any) -> str | None:
    short = _short_file(value)
    if not short or _is_low_value_resume_file(short):
        return None
    return short


def _is_low_value_resume_file(name: str) -> bool:
    lowered = name.lower()
    blocked_names = {
        ".ds_store",
        "model-recommendations.json",
        "models_cache.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
    if lowered in blocked_names:
        return True
    return lowered.endswith((".tmp", ".log", ".lock"))


def _recent_session_hint(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    first = value[0]
    if not isinstance(first, dict):
        return None
    project = _clean(first.get("project"))
    task = _clean(first.get("task") or first.get("probable_task"))
    duration = first.get("duration_min") or first.get("duration")
    parts: list[str] = []
    if project:
        parts.append(project)
    if task:
        parts.append(task)
    if duration:
        try:
            parts.append(f"{int(float(duration))} min")
        except (TypeError, ValueError):
            pass
    return " / ".join(parts) if parts else None


def _dedupe_text(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _clean(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result

def _llm_card_text_limits(display_size: DisplaySize) -> tuple[int, int, int]:
    if display_size == "expanded":
        return 260, 260, 260
    if display_size == "standard":
        return 150, 160, 170
    return 110, 120, 130


def _display_size(*lines: str) -> DisplaySize:
    char_count = sum(len(line or "") for line in lines)
    if char_count <= 95:
        return "compact"
    if char_count <= 210:
        return "standard"
    return "expanded"


def _short_file(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    return Path(text).name or text


def _limit_line(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None
