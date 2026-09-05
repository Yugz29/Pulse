"""`pulse-intel eval` : le modèle courant sur le corpus gelé, côte à côte.

Le corpus (`eval/corpus/`) est dix sessions réelles figées — vue Core et
contexte capturés une fois, reproductibles hors ligne, sans trace ni daemon.
`eval` reconstruit l'entrée exacte du modèle par le même code que la production
(`build_model_input`, `serialize_input`, `input_paths`), appelle le provider,
valide par `parse_model_output`, et écrit un résultat par session plus un
`meta.json` de passage. Pas de score automatique : un regard sur les fichiers.

Règle du pas 3 : tout changement de prompt ou de modèle passe par `eval` avant
d'être activé, et le rapport est joint à la PR.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .provider_summarizer import ProviderSummarizer
from .selection import SessionView
from .session_input import build_model_input, input_paths, serialize_input
from .session_summary import InvalidModelOutput, ParsedSummary, parse_model_output
from .summarizer import SummarizerError


DEFAULT_CORPUS = Path(__file__).parent.parent / "eval" / "corpus"
DEFAULT_OUT = Path(__file__).parent.parent / "eval" / "out"


@dataclass(frozen=True)
class CorpusEntry:
    id: str
    date: str
    label: str
    why: str
    session_raw: dict[str, Any]
    context: dict[str, Any]

    @property
    def view(self) -> SessionView:
        return SessionView(self.session_raw, date.fromisoformat(self.date))


@dataclass
class EvalOutcome:
    entry: CorpusEntry
    status: str  # "ok" | "rejected" | "failed"
    detail: str | None
    parsed: ParsedSummary | None
    input_tokens_est: int
    duration_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    dropped_parameters: tuple[str, ...]


def load_corpus(corpus_dir: Path = DEFAULT_CORPUS) -> list[CorpusEntry]:
    entries = []
    for path in sorted(corpus_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries.append(
            CorpusEntry(
                id=raw["id"],
                date=raw["date"],
                label=raw["label"],
                why=raw["why"],
                session_raw=raw["session_raw"],
                context=raw["context"],
            )
        )
    return entries


def _sanitize(model_id: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "-" for c in model_id)


def evaluate(
    summarizer: ProviderSummarizer,
    *,
    provider_name: str,
    corpus_dir: Path = DEFAULT_CORPUS,
    out_dir: Path = DEFAULT_OUT,
    now: datetime | None = None,
) -> tuple[list[EvalOutcome], Path]:
    """Passe le corpus, écrit un résultat par session et un `meta.json`."""
    entries = load_corpus(corpus_dir)
    if not entries:
        raise FileNotFoundError(f"corpus vide : {corpus_dir}")

    run_dir = out_dir / f"{provider_name}-{_sanitize(summarizer.model_id)}"
    run_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[EvalOutcome] = []
    for entry in entries:
        session = entry.view
        serialized = serialize_input(build_model_input(session, entry.context))
        tokens_est = len(serialized) // 4

        try:
            result = summarizer.complete(serialized)
        except SummarizerError as exc:
            outcomes.append(
                EvalOutcome(
                    entry, "failed", str(exc), None, tokens_est,
                    None, None, None, (),
                )
            )
            _write_result(run_dir, entry, "failed", str(exc), None)
            continue

        try:
            parsed = parse_model_output(result.text, input_paths(session))
            status, detail = "ok", None
        except InvalidModelOutput as exc:
            parsed, status, detail = None, "rejected", str(exc)

        outcomes.append(
            EvalOutcome(
                entry, status, detail, parsed, tokens_est,
                result.duration_ms, result.prompt_tokens,
                result.completion_tokens, result.dropped_parameters,
            )
        )
        _write_result(run_dir, entry, status, detail, parsed, raw_text=result.text)

    _write_meta(run_dir, summarizer, provider_name, outcomes, now)
    return outcomes, run_dir


def _write_result(
    run_dir: Path,
    entry: CorpusEntry,
    status: str,
    detail: str | None,
    parsed: ParsedSummary | None,
    raw_text: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "id": entry.id,
        "label": entry.label,
        "date": entry.date,
        "why": entry.why,
        "status": status,
    }
    if parsed is not None:
        payload["reprise"] = parsed.reprise
        payload["structured"] = parsed.structured
    else:
        payload["detail"] = detail
        # La sortie brute rejetée aide à comprendre pourquoi le prompt a lâché.
        if raw_text is not None:
            payload["raw_output"] = raw_text[:2000]
    (run_dir / f"{entry.id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )


def _write_meta(
    run_dir: Path,
    summarizer: ProviderSummarizer,
    provider_name: str,
    outcomes: list[EvalOutcome],
    now: datetime | None,
) -> None:
    meta = {
        "provider": provider_name,
        "model_id": summarizer.model_id,
        "prompt_path": summarizer.prompt_path.name,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "session_count": len(outcomes),
        "ok": sum(o.status == "ok" for o in outcomes),
        "rejected": sum(o.status == "rejected" for o in outcomes),
        "failed": sum(o.status == "failed" for o in outcomes),
        "sessions": [
            {
                "id": o.entry.id,
                "label": o.entry.label,
                "status": o.status,
                "input_tokens_est": o.input_tokens_est,
                "duration_ms": o.duration_ms,
                "prompt_tokens": o.prompt_tokens,
                "completion_tokens": o.completion_tokens,
                # Le point demandé : un résumé produit sans température 0 n'est
                # pas reproductible de la même façon, le rapport doit le dire.
                "dropped_parameters": list(o.dropped_parameters),
                "detail": o.detail,
            }
            for o in outcomes
        ],
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
