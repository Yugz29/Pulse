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
    recent_files = _recent_files(payload, signals)
    work_block_started_at = _work_block_started_at(payload)
    work_block_commit_count = payload.get("work_block_commit_count") or payload.get("work_window_commit_count") or 0
    recent_sessions = list(payload.get("recent_sessions") or payload.get("closed_episodes") or [])[:3]
    recent_journal_entries = list(payload.get("recent_journal_entries") or [])[:5]
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
        "active_file": present.active_file or payload.get("active_file"),
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
        raw = llm.complete(prompt, max_tokens=180)
        parsed = _parse_llm_card(raw)
        if parsed is None:
            return deterministic
        return _card_from_llm(context, deterministic, parsed)
    except Exception:
        return deterministic


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
    short_files = [_short_file(path) for path in files if _short_file(path)]
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
    active_file = _short_file(context.get("active_file"))
    recent_files = [_short_file(path) for path in context.get("recent_files", []) if _short_file(path)]
    commit_scope_files = [_short_file(path) for path in context.get("commit_scope_files", []) if _short_file(path)]
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
    summary = _clean(parsed.get("summary")) or fallback.summary
    last_objective = _clean(parsed.get("last_objective")) or fallback.last_objective
    next_action = _clean(parsed.get("next_action")) or fallback.next_action
    return ResumeCard(
        id=fallback.id,
        project=fallback.project,
        title=_clean(parsed.get("title")) or fallback.title,
        summary=_limit_line(summary, 110),
        last_objective=_limit_line(last_objective, 120),
        next_action=_limit_line(next_action, 130),
        confidence=max(0.0, min(float(parsed.get("confidence") or fallback.confidence), 0.95)),
        source_refs=list(context.get("source_refs") or fallback.source_refs),
        generated_by="llm",
        display_size=_display_size(summary, last_objective, next_action),
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
    return (
        "Tu écris une Resume Card Pulse en français.\n"
        "Réponds uniquement en JSON avec les clés: title, summary, last_objective, "
        "next_action, confidence.\n"
        "Contraintes: phrases courtes, pas d'invention, maximum 5 lignes côté UI. "
        "Ne réponds pas simplement qu'il faut relire le journal si le contexte contient déjà des fichiers, "
        "un diff, des sessions récentes ou des recent_journal_entries: résume directement ce qui est connu.\n\n"
        f"Contexte local:\n{json.dumps(context, ensure_ascii=False, default=str)[:5000]}\n\n"
        f"Fallback déterministe:\n{json.dumps(fallback.to_event_payload(), ensure_ascii=False)}"
    )


def _parse_llm_card(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if not any(_clean(parsed.get(key)) for key in ("summary", "last_objective", "next_action")):
        return None
    return parsed


def _recent_files(payload: dict[str, Any], signals: Any) -> list[str]:
    files: list[str] = []
    for key in ("commit_scope_files", "top_files"):
        value = payload.get(key) or []
        if isinstance(value, list):
            files.extend(str(item) for item in value if item)
    active_file = getattr(signals, "active_file", None)
    if active_file:
        files.insert(0, str(active_file))

    seen: set[str] = set()
    result: list[str] = []
    for path in files:
        if path in seen:
            continue
        seen.add(path)
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
        _short_file(match)
        for match in re.findall(r"[A-Za-z0-9_+./-]+\.[A-Za-z0-9_+-]+", text)
    ]
    names = _dedupe_text([name for name in names if name])
    if names:
        return ", ".join(names[:3])

    cleaned = re.sub(r"\([+\-0-9\s]+\)", "", text)
    cleaned = cleaned.replace("Diff en cours :", "").replace("Fonctions touchées :", "")
    cleaned = cleaned.strip(" :,-")
    return _limit_line(cleaned, 58) if cleaned else None


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
