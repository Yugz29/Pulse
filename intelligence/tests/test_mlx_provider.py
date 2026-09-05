"""MLXProvider : tout ce qui se teste sans charger 14 Go.

Le chargement réel du modèle et la génération sont couverts par un test `slow`,
exclu de la suite par défaut (voir pyproject). Ici : import paresseux, coupure
du thinking, comptage des tokens, câblage CLI — avec un `mlx_lm` simulé.
"""

from __future__ import annotations

import sys
import types

import pytest

from pulse_intelligence import cli
from pulse_intelligence.config import Config
from pulse_intelligence.llm.mlx import DEFAULT_MODEL, MLXProvider
from pulse_intelligence.llm.provider import CompletionRequest, ProviderError


class _Tokenizer:
    def __init__(self, template: str | None):
        self.chat_template = template
        self.template_calls: list[dict] = []

    def apply_chat_template(self, messages, **kwargs):
        self.template_calls.append(kwargs)
        return "PROMPT::" + messages[-1]["content"]

    def encode(self, text: str):
        return text.split()


def _install_fake_mlx(monkeypatch, tokenizer, output="{}", *, load_error=None, gen_error=None):
    """Pose un faux module `mlx_lm` importable, sans toucher au vrai."""
    module = types.ModuleType("mlx_lm")

    def load(model):
        if load_error:
            raise load_error
        return ("MODEL", tokenizer)

    def generate(model, tok, *, prompt, max_tokens, verbose):
        if gen_error:
            raise gen_error
        generate.last = {"prompt": prompt, "max_tokens": max_tokens}
        return output

    module.load = load
    module.generate = generate
    monkeypatch.setitem(sys.modules, "mlx_lm", module)
    return generate


def test_thinking_is_disabled_when_the_template_supports_it(monkeypatch):
    tok = _Tokenizer(template="... {% if enable_thinking %} ...")
    _install_fake_mlx(monkeypatch, tok)

    MLXProvider().complete(CompletionRequest(system="s", prompt="p", max_tokens=64))

    assert tok.template_calls[0].get("enable_thinking") is False


def test_no_thinking_flag_is_passed_when_the_template_lacks_it(monkeypatch):
    tok = _Tokenizer(template="pas de drapeau ici")
    _install_fake_mlx(monkeypatch, tok)

    MLXProvider().complete(CompletionRequest(system="s", prompt="p", max_tokens=64))

    assert "enable_thinking" not in tok.template_calls[0]


def test_the_result_carries_model_and_token_counts(monkeypatch):
    tok = _Tokenizer(template=None)
    _install_fake_mlx(monkeypatch, tok, output="un deux trois")

    result = MLXProvider(model="essai/modele").complete(
        CompletionRequest(system="s", prompt="p", max_tokens=64)
    )

    assert result.provider == "mlx"
    assert result.model == "essai/modele"
    assert result.completion_tokens == 3  # "un deux trois"
    assert result.dropped_parameters == ()


def test_the_model_is_loaded_once_and_kept(monkeypatch):
    tok = _Tokenizer(template=None)
    loads = {"n": 0}
    module = types.ModuleType("mlx_lm")

    def load(model):
        loads["n"] += 1
        return ("MODEL", tok)

    module.load = load
    module.generate = lambda *a, prompt, max_tokens, verbose: "{}"
    monkeypatch.setitem(sys.modules, "mlx_lm", module)

    provider = MLXProvider()
    provider.complete(CompletionRequest(system="s", prompt="p"))
    provider.complete(CompletionRequest(system="s", prompt="p"))

    assert loads["n"] == 1  # 14 Go chargés une seule fois


def test_a_missing_mlx_lm_becomes_a_clear_provider_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx_lm", None)  # force l'ImportError

    with pytest.raises(ProviderError, match="mlx-lm absent"):
        MLXProvider().complete(CompletionRequest(system="s", prompt="p"))


def test_a_load_failure_becomes_a_provider_error(monkeypatch):
    _install_fake_mlx(monkeypatch, _Tokenizer(None), load_error=RuntimeError("mémoire"))

    with pytest.raises(ProviderError, match="chargement du modèle"):
        MLXProvider().complete(CompletionRequest(system="s", prompt="p"))


def test_a_generation_failure_becomes_a_provider_error(monkeypatch):
    _install_fake_mlx(monkeypatch, _Tokenizer(None), gen_error=RuntimeError("kaput"))

    with pytest.raises(ProviderError, match="génération"):
        MLXProvider().complete(CompletionRequest(system="s", prompt="p"))


def test_cli_builds_an_mlx_provider_from_config():
    from pulse_intelligence.cli import _provider

    provider = _provider(Config(llm_provider="mlx", model_id="essai/modele"))

    assert isinstance(provider, MLXProvider)
    assert provider.model == "essai/modele"


def test_cli_mlx_defaults_to_the_pinned_model():
    from pulse_intelligence.cli import _provider

    provider = _provider(Config(llm_provider="mlx"))

    assert provider.model == DEFAULT_MODEL


@pytest.mark.slow
def test_real_qwen_loads_and_summarizes_without_thinking():
    """Charge le vrai modèle, résume une session du corpus, valide la sortie.

    Exclu par défaut (`-m 'not slow'`) : 14 Go et plusieurs secondes. À lancer
    quand l'extra mlx est présent, avec `pytest -m slow`.
    """
    from datetime import date

    from pulse_intelligence.evaluation import load_corpus
    from pulse_intelligence.provider_summarizer import ProviderSummarizer, prompt_path_for
    from pulse_intelligence.selection import SessionView
    from pulse_intelligence.session_input import (
        build_model_input,
        input_paths,
        serialize_input,
    )
    from pulse_intelligence.session_summary import parse_model_output

    entry = next(e for e in load_corpus() if e.id == "cda6ccce898d3e88")
    session = SessionView(entry.session_raw, date.fromisoformat(entry.date))
    serialized = serialize_input(build_model_input(session, entry.context))

    summarizer = ProviderSummarizer(
        provider=MLXProvider(), model_id=DEFAULT_MODEL,
        prompt_path=prompt_path_for("v1"), max_tokens=2048,
    )
    text = summarizer.summarize(serialized)

    assert "<think>" not in text and "</think>" not in text
    parsed = parse_model_output(text, input_paths(session))
    assert parsed.structured["confidence"] in {"high", "medium", "low"}


def test_an_oversized_input_is_refused_before_the_prefill(monkeypatch):
    """Refus explicite au lieu d'un OOM Metal (mesuré au spike B)."""

    class _BigTokenizer(_Tokenizer):
        def encode(self, text):
            return list(range(50_000))  # au-dessus du plafond

    tok = _BigTokenizer(template=None)
    gen = _install_fake_mlx(monkeypatch, tok)

    with pytest.raises(ProviderError, match="plafond"):
        MLXProvider(max_input_tokens=30_000).complete(
            CompletionRequest(system="s", prompt="p", max_tokens=64)
        )

    # Le refus est AVANT la génération : generate() n'a jamais été appelé.
    assert not hasattr(gen, "last")


def test_an_input_under_the_ceiling_is_generated(monkeypatch):
    tok = _Tokenizer(template=None)  # encode = text.split() -> peu de tokens
    _install_fake_mlx(monkeypatch, tok, output="{}")

    result = MLXProvider(max_input_tokens=30_000).complete(
        CompletionRequest(system="s", prompt="p q r", max_tokens=64)
    )

    assert result.text == "{}"


def test_the_ceiling_is_wired_from_config():
    from pulse_intelligence.cli import _provider

    provider = _provider(Config(llm_provider="mlx", llm_max_input_tokens=12345))

    assert provider.max_input_tokens == 12345
