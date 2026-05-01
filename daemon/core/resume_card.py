from __future__ import annotations

import json
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
    source_refs = ["present_state", "session_memory"]
    if work_block_started_at:
        source_refs.append("work_block")
    if recent_sessions:
        source_refs.append("recent_sessions")
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


def _deterministic_card(context: dict[str, Any]) -> ResumeCard:
    project = _clean(context.get("project"))
    task = _clean(context.get("probable_task")) or "general"
    active_file = _short_file(context.get("active_file"))
    recent_files = [_short_file(path) for path in context.get("recent_files", []) if _short_file(path)]
    primary_file = active_file or (recent_files[0] if recent_files else None)

    summary = f"Tu étais sur {project}." if project else "Tu revenais sur une session de travail."
    if primary_file:
        last_objective = f"Reprendre le travail {task} autour de {primary_file}."
    else:
        last_objective = f"Reprendre le travail {task}."

    if context.get("diff_summary"):
        next_action = "Relire le diff actif puis reprendre le prochain changement utile."
    elif primary_file:
        next_action = f"Rouvrir {primary_file} et vérifier le prochain geste."
    else:
        next_action = "Relire le dernier journal de session avant de reprendre."

    evidence_count = len(context.get("source_refs") or [])
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


def _llm_prompt(context: dict[str, Any], fallback: ResumeCard) -> str:
    return (
        "Tu écris une Resume Card Pulse en français.\n"
        "Réponds uniquement en JSON avec les clés: title, summary, last_objective, "
        "next_action, confidence.\n"
        "Contraintes: phrases courtes, pas d'invention, maximum 5 lignes côté UI.\n\n"
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
