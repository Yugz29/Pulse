"""`eval` : corpus gelé, passage du modèle, résultats et meta.json."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from conftest import session_view
from pulse_intelligence import cli
from pulse_intelligence.evaluation import (
    DEFAULT_CORPUS,
    evaluate,
    load_corpus,
)
from pulse_intelligence.llm.provider import CompletionRequest, CompletionResult, ProviderError
from pulse_intelligence.provider_summarizer import ProviderSummarizer, prompt_path_for
from pulse_intelligence.summarizer import SummarizerError

PROMPT = prompt_path_for("v1")

VALID = json.dumps(
    {
        "reprise": {"doing": "d", "stopped_at": "s", "open": "o"},
        "structured": {
            "project": "Pulse", "intents": [], "central_files": [],
            "blockers": [], "confidence": "low",
        },
    }
)


@dataclass
class StubProvider:
    """Provider contrôlé : texte imposé, `dropped_parameters` imposé."""

    name: str = "stub"
    model: str = "stub/model"
    text: str = VALID
    dropped: tuple[str, ...] = ()
    raise_error: ProviderError | None = None

    def complete(self, request: CompletionRequest) -> CompletionResult:
        if self.raise_error is not None:
            raise self.raise_error
        return CompletionResult(
            text=self.text, provider=self.name, model=self.model,
            prompt_tokens=10, completion_tokens=20, duration_ms=5,
            dropped_parameters=self.dropped,
        )

    def healthcheck(self) -> bool:
        return True


def _summarizer(provider: StubProvider) -> ProviderSummarizer:
    return ProviderSummarizer(provider=provider, model_id=provider.model, prompt_path=PROMPT)


def _tiny_corpus(tmp_path):
    """Un corpus d'un fichier, à la forme des vraies fixtures gelées."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    raw = session_view("aaaaaaaaaaaaaaaa", files={"created": [], "modified": ["a.py"], "deleted": []})
    fixture = {
        "id": "aaaaaaaaaaaaaaaa", "date": "2026-09-02", "label": "work-1",
        "why": "fixture de test", "session_raw": raw,
        "context": {"workspace": {"path": "/w"}, "last_session_summary": None, "last_agent_session": None},
    }
    (corpus / "aaaaaaaaaaaaaaaa.json").write_text(json.dumps(fixture), encoding="utf-8")
    return corpus


# --- Le corpus réel gelé --------------------------------------------------


def test_the_frozen_corpus_has_exactly_ten_sessions():
    """Dix d'origine gelées (sans `added`), plus les extensions datées."""
    entries = load_corpus(DEFAULT_CORPUS)
    frozen = [e for e in entries if e.added is None]

    assert len(frozen) == 10
    # Chaque fixture porte de quoi reconstruire l'entrée hors ligne.
    for e in entries:
        assert e.session_raw["id"] == e.id
        assert isinstance(e.context, dict)
        assert e.why


def test_the_extension_entries_carry_a_previous_summary_annex(capture_timezone):
    """Ajoutées le 2026-09-06 pour mesurer D1 (`docs/dogfooding.md`) : leur
    contexte est pris à fin − 1 s, donc l'annexe est le résumé d'une *autre*
    session, jamais le leur."""
    from pulse_intelligence.session_input import build_model_input

    extension = {e.id: e for e in load_corpus(DEFAULT_CORPUS) if e.added is not None}

    assert set(extension) == {
        "1e420dda8b6eee77", "eef4956b36dd37ce",  # D1 : annexe previous_summary
        "8af930d9ef437d2a", "d98778994319cd07",  # D3 : annexe agent_session
    }
    for sid in ("1e420dda8b6eee77", "eef4956b36dd37ce", "d98778994319cd07"):
        annex = build_model_input(extension[sid].view, extension[sid].context)["previous_summary"]
        assert annex is not None and annex["id"] != sid
        assert annex["reprise"]["open"]
    # 8af930d9 est la première session de sa journée : pas de résumé précédent.
    assert build_model_input(extension["8af930d9ef437d2a"].view, extension["8af930d9ef437d2a"].context)["previous_summary"] is None
    for sid in ("8af930d9ef437d2a", "d98778994319cd07"):
        agent = build_model_input(extension[sid].view, extension[sid].context)["agent_session"]
        assert agent is not None and "PR #28" in agent["summary"]


def test_the_frozen_corpus_covers_several_projects_and_weeks():
    entries = load_corpus(DEFAULT_CORPUS)
    projects = {p for e in entries for p in e.session_raw.get("projects", [])}
    months = {e.date[:7] for e in entries}

    assert len(projects) >= 3
    assert len(months) >= 2  # pas que septembre


# --- Le passage ------------------------------------------------------------


def test_a_valid_output_is_written_and_counted(tmp_path):
    outcomes, run_dir = evaluate(
        _summarizer(StubProvider()), provider_name="stub",
        corpus_dir=_tiny_corpus(tmp_path), out_dir=tmp_path / "out",
    )

    assert [o.status for o in outcomes] == ["ok"]
    result = json.loads((run_dir / "aaaaaaaaaaaaaaaa.json").read_text())
    assert result["status"] == "ok"
    assert result["reprise"]["doing"] == "d"


def test_an_invalid_output_is_rejected_and_keeps_its_raw(tmp_path):
    outcomes, run_dir = evaluate(
        _summarizer(StubProvider(text="je ne suis pas du json")),
        provider_name="stub", corpus_dir=_tiny_corpus(tmp_path), out_dir=tmp_path / "out",
    )

    assert outcomes[0].status == "rejected"
    result = json.loads((run_dir / "aaaaaaaaaaaaaaaa.json").read_text())
    # La sortie rejetée est conservée : c'est elle qui explique pourquoi.
    assert "raw_output" in result and "pas du json" in result["raw_output"]


def test_a_provider_failure_is_recorded_as_failed(tmp_path):
    outcomes, _ = evaluate(
        _summarizer(StubProvider(raise_error=ProviderError("endpoint down"))),
        provider_name="stub", corpus_dir=_tiny_corpus(tmp_path), out_dir=tmp_path / "out",
    )

    assert outcomes[0].status == "failed"
    assert "endpoint down" in outcomes[0].detail


def test_dropped_parameters_reach_the_meta_json(tmp_path):
    _, run_dir = evaluate(
        _summarizer(StubProvider(dropped=("temperature",))),
        provider_name="stub", corpus_dir=_tiny_corpus(tmp_path), out_dir=tmp_path / "out",
    )

    meta = json.loads((run_dir / "meta.json").read_text())
    # Le point demandé : un résumé sans température 0 est traçable.
    assert meta["sessions"][0]["dropped_parameters"] == ["temperature"]
    assert meta["ok"] == 1 and meta["session_count"] == 1


def test_the_output_directory_is_named_by_provider_and_model(tmp_path):
    _, run_dir = evaluate(
        _summarizer(StubProvider(model="mlx-community/Qwen3.8-27B-4bit")),
        provider_name="mlx", corpus_dir=_tiny_corpus(tmp_path), out_dir=tmp_path / "out",
    )

    # Le slash du modèle ne crée pas un sous-dossier accidentel.
    assert run_dir.name == "mlx-mlx-community-Qwen3.8-27B-4bit"


def test_an_empty_corpus_is_an_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        evaluate(_summarizer(StubProvider()), provider_name="stub", corpus_dir=empty, out_dir=tmp_path / "out")


# --- CLI -------------------------------------------------------------------


def test_cli_eval_runs_on_the_fake_provider(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text('llm_provider = "fake"\nmodel_id = "fake/eval"\n', encoding="utf-8")

    code = cli.main(
        ["--config", str(config), "eval",
         "--corpus", str(_tiny_corpus(tmp_path)), "--out", str(tmp_path / "out")]
    )

    assert code == 0
    assert "1/1 valides" in capsys.readouterr().out


def test_cli_eval_refuses_the_fake_summarizer_shortcut(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")  # aucun provider

    code = cli.main(["--config", str(config), "eval",
                     "--corpus", str(_tiny_corpus(tmp_path)), "--out", str(tmp_path / "out")])

    assert code == 1
    assert "provider" in capsys.readouterr().err


# --- L'entrée synthétique de stress ---------------------------------------


def test_the_stress_fixture_is_outside_the_corpus_and_labelled():
    stress = DEFAULT_CORPUS.parent / "stress" / "synthetic-60k.json"
    assert stress.exists()
    data = json.loads(stress.read_text())
    assert data["_synthetic"] is True
    assert data["session_raw"]["_synthetic"] is True
    # Elle ne doit pas être ramassée par le corpus.
    assert not (DEFAULT_CORPUS / stress.name).exists()
    # Et elle vise bien ~60k tokens.
    from pulse_intelligence.selection import SessionView
    from pulse_intelligence.session_input import build_model_input, serialize_input
    from datetime import date
    view = SessionView(data["session_raw"], date.fromisoformat(data["date"]))
    tokens = len(serialize_input(build_model_input(view, data["context"]))) // 4
    assert tokens >= 55_000
