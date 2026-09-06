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

from . import KNOWN_RECONSTRUCTION_VERSION
from .provider_summarizer import ProviderSummarizer, prompt_version_of
from .selection import SessionView
from .session_input import (
    build_model_input,
    input_paths,
    input_references,
    serialize_input,
    uses_open_items,
)
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
    # Date d'ajout pour une entrée hors gel ; None pour les dix d'origine,
    # qui restent la référence de l'étape 3.
    added: str | None = None

    @property
    def view(self) -> SessionView:
        return SessionView(self.session_raw, date.fromisoformat(self.date))


@dataclass
class EvalOutcome:
    entry: CorpusEntry
    status: str  # "ok" | "rejected" | "failed"
    detail: str | None
    parsed: ParsedSummary | None
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
                added=raw.get("added"),
            )
        )
    return entries


def reconstruction_versions(entries: list[CorpusEntry]) -> dict[str, int]:
    """Combien d'entrées du corpus portent chaque version de reconstruction.

    Le corpus est un export figé des vues de Core : une version qui n'est pas
    celle connue du code (`KNOWN_RECONSTRUCTION_VERSION`) veut dire que les
    entrées ont été capturées sous une autre reconstruction — à dire dans le
    rapport, pas à corriger."""
    counts: dict[str, int] = {}
    for entry in entries:
        key = str(entry.view.reconstruction_version)
        counts[key] = counts.get(key, 0) + 1
    return counts


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

    # Le schéma de `open` suit le prompt, comme en production : l'entrée est
    # référencée et la sortie validée au schéma v3 dès que le prompt l'attend.
    referenced = uses_open_items(prompt_version_of(summarizer.prompt_path))
    outcomes: list[EvalOutcome] = []
    for entry in entries:
        session = entry.view
        model_input = build_model_input(session, entry.context, references=referenced)
        serialized = serialize_input(model_input)

        try:
            result = summarizer.complete(serialized)
        except SummarizerError as exc:
            outcomes.append(
                EvalOutcome(
                    entry, "failed", str(exc), None,
                    None, None, None, (),
                )
            )
            _write_result(run_dir, entry, "failed", str(exc), None)
            continue

        try:
            parsed = parse_model_output(
                result.text, input_paths(session),
                references=input_references(model_input) if referenced else None,
            )
            status, detail = "ok", None
        except InvalidModelOutput as exc:
            parsed, status, detail = None, "rejected", str(exc)

        outcomes.append(
            EvalOutcome(
                entry, status, detail, parsed,
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
        if parsed.open_items is not None:
            # Les points validés, texte compris : `eval` écrit hors de Core,
            # c'est ici que les attentes annotées se comparent.
            payload["open_items"] = parsed.open_items
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
        # L'export dit sous quelle reconstruction ses entrées ont été figées,
        # et laquelle le code connaît : l'écart se lit sans ouvrir le corpus.
        "known_reconstruction_version": KNOWN_RECONSTRUCTION_VERSION,
        "corpus_reconstruction_versions": reconstruction_versions([o.entry for o in outcomes]),
        "session_count": len(outcomes),
        "ok": sum(o.status == "ok" for o in outcomes),
        "rejected": sum(o.status == "rejected" for o in outcomes),
        "failed": sum(o.status == "failed" for o in outcomes),
        "sessions": [
            {
                "id": o.entry.id,
                "label": o.entry.label,
                "status": o.status,
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


# --- Attentes annotées (`eval/expected/`) ------------------------------------
#
# Un fichier par session : le `open` attendu au schéma v3, chaque point avec
# un `why` ; `optional` liste des points acceptables sans être exigés ;
# `must_not` des motifs interdits (`kind`, `carried_from`, `text_matches`),
# chacun justifié. La comparaison ne juge pas la prose : un point attendu est
# retrouvé quand un point produit a la même nature et les mêmes preuves (ou la
# même origine `carried_from`). Le texte est affiché, jamais comparé.

DEFAULT_EXPECTED = Path(__file__).parent.parent / "eval" / "expected"


@dataclass(frozen=True)
class OpenComparison:
    session_id: str
    matched: list[tuple[dict[str, Any], dict[str, Any]]]   # (attendu, produit)
    optional_matched: list[tuple[dict[str, Any], dict[str, Any]]]
    missing: list[dict[str, Any]]                            # attendus jamais retrouvés
    unexpected: list[dict[str, Any]]                         # produits sans attente
    forbidden: list[tuple[dict[str, Any], dict[str, Any]]]  # (règle must_not, produit)
    error: str | None = None                                 # pas d'open_items (rejet, ancien schéma)

    @property
    def ok(self) -> bool:
        return self.error is None and not self.missing and not self.forbidden


def load_expectations(expected_dir: Path = DEFAULT_EXPECTED) -> dict[str, dict[str, Any]]:
    expectations = {}
    for path in sorted(expected_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        expectations[raw["id"]] = raw
    return expectations


def _same_point(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if expected.get("kind") != actual.get("kind"):
        return False
    if expected.get("kind") == "carried_over":
        return expected.get("carried_from") == actual.get("carried_from")
    return set(expected.get("evidence") or []) == set(actual.get("evidence") or [])


def _violates(rule: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Toutes les clauses de la règle doivent s'appliquer au point produit."""
    import re

    clauses = 0
    if "kind" in rule:
        clauses += 1
        if rule["kind"] != actual.get("kind"):
            return False
    if "carried_from" in rule:
        clauses += 1
        if rule["carried_from"] != actual.get("carried_from"):
            return False
    if "text_matches" in rule:
        clauses += 1
        haystack = f"{actual.get('text', '')} {actual.get('reason_kept', '')}"
        if not re.search(rule["text_matches"], haystack, re.IGNORECASE):
            return False
    return clauses > 0


def compare_open(
    session_id: str, actual_items: list[dict[str, Any]] | None, expectation: dict[str, Any]
) -> OpenComparison:
    if actual_items is None:
        return OpenComparison(session_id, [], [], list(expectation.get("open") or []), [], [],
                              error="aucun open_items : sortie rejetée ou au schéma d'origine")
    remaining = list(actual_items)
    matched, optional_matched, missing = [], [], []
    for expected in expectation.get("open") or []:
        hit = next((item for item in remaining if _same_point(expected, item)), None)
        if hit is None:
            missing.append(expected)
        else:
            matched.append((expected, hit))
            remaining.remove(hit)
    for expected in expectation.get("optional") or []:
        hit = next((item for item in remaining if _same_point(expected, item)), None)
        if hit is not None:
            optional_matched.append((expected, hit))
            remaining.remove(hit)
    forbidden = [
        (rule, item)
        for item in actual_items
        for rule in expectation.get("must_not") or []
        if _violates(rule, item)
    ]
    return OpenComparison(session_id, matched, optional_matched, missing, remaining, forbidden)


def _describe(item: dict[str, Any]) -> str:
    proof = ", ".join(item.get("evidence") or []) or "—"
    if item.get("carried_from"):
        proof = f"{proof} · repris de {item['carried_from']}"
    return f"[{item.get('kind', '?')}] {item.get('text', '')!s}  ← {proof}"


def format_comparison(comparison: OpenComparison) -> str:
    """L'écart, lisible d'un coup d'œil : ce qui est retrouvé, manquant,
    interdit, en plus. Une ligne par point, la justification en dessous."""
    verdict = "conforme" if comparison.ok else "écart"
    lines = [f"{comparison.session_id}  {verdict}"]
    if comparison.error:
        lines.append(f"  ! {comparison.error}")
    for expected, actual in comparison.matched:
        lines.append(f"  ✓ attendu retrouvé  {_describe(actual)}")
    for expected, actual in comparison.optional_matched:
        lines.append(f"  ✓ acceptable        {_describe(actual)}")
    for expected in comparison.missing:
        lines.append(f"  ✗ manquant          {_describe(expected)}")
        lines.append(f"      pourquoi : {expected.get('why', '—')}")
    for rule, actual in comparison.forbidden:
        clause = ", ".join(f"{k}={v}" for k, v in rule.items() if k != "why")
        lines.append(f"  ✗ interdit ({clause})  {_describe(actual)}")
        lines.append(f"      pourquoi : {rule.get('why', '—')}")
    for actual in comparison.unexpected:
        lines.append(f"  ? en plus           {_describe(actual)}")
    return "\n".join(lines)


def compare_run(run_dir: Path, expected_dir: Path = DEFAULT_EXPECTED) -> list[OpenComparison]:
    """Les résultats d'un passage `eval` face aux attentes qui existent."""
    comparisons = []
    for session_id, expectation in load_expectations(expected_dir).items():
        result_path = run_dir / f"{session_id}.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        items = result.get("open_items") if result.get("status") == "ok" else None
        comparison = compare_open(session_id, items, expectation)
        if items is None and result.get("status") != "ok":
            comparison = OpenComparison(
                session_id, [], [], list(expectation.get("open") or []), [], [],
                error=f"{result.get('status')} : {result.get('detail')}",
            )
        comparisons.append(comparison)
    return comparisons
