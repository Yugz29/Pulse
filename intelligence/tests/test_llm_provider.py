"""Couche modèle : provider, pont vers `Summarizer`, câblage de la CLI."""

from __future__ import annotations

import json

import pytest

from conftest import REFERENCE, session_view
from pulse_intelligence import cli
from pulse_intelligence.config import Config, ConfigError, load_config
from pulse_intelligence.llm.fake import FakeProvider
from pulse_intelligence.llm.provider import CompletionRequest, ProviderError
from pulse_intelligence.provider_summarizer import (
    ProviderSummarizer,
    prompt_path_for,
)
from pulse_intelligence.session_summary import parse_model_output
from pulse_intelligence.summarizer import SummarizerError


PROMPT = prompt_path_for("v1")


def today() -> str:
    return REFERENCE.astimezone().date().isoformat()


def base_args(fake_core, tmp_path) -> list[str]:
    return ["--core-url", fake_core.url, "--state", str(tmp_path / "state.json")]


# --- FakeProvider ---------------------------------------------------------


def test_fake_provider_echoes_the_session_id_it_was_given():
    provider = FakeProvider()
    prompt = json.dumps({"session": {"id": "aaaaaaaaaaaaaaaa"}})

    result = provider.complete(CompletionRequest(system="s", prompt=prompt))

    # La sortie rejoue l'identifiant : c'est la preuve que le contexte a
    # circulé jusqu'au modèle, pas seulement que quelque chose est revenu.
    assert "aaaaaaaaaaaaaaaa" in result.text
    assert result.provider == "fake"
    assert provider.calls[0].prompt == prompt


def test_fake_provider_output_passes_the_real_validation():
    result = FakeProvider().complete(
        CompletionRequest(system="s", prompt='{"session":{"id":"bbbbbbbbbbbbbbbb"}}')
    )

    # Le faux provider ne doit pas produire une sortie que le vrai parseur
    # rejetterait, sinon les tests d'aval ne prouvent rien.
    parsed = parse_model_output(result.text, allowed_paths=set())
    assert parsed.structured["confidence"] == "low"
    assert parsed.structured["central_files"] == []


def test_fake_provider_raises_what_it_was_told_to_raise():
    provider = FakeProvider(fail_with=ProviderError("endpoint injoignable"))

    with pytest.raises(ProviderError, match="injoignable"):
        provider.complete(CompletionRequest(system="s", prompt="p"))


def test_fake_provider_can_return_an_unparsable_output():
    result = FakeProvider(invalid_output=True).complete(
        CompletionRequest(system="s", prompt="p")
    )

    with pytest.raises(Exception):
        parse_model_output(result.text, allowed_paths=set())


# --- ProviderSummarizer ---------------------------------------------------


def test_provider_summarizer_wraps_the_input_in_the_versioned_prompt():
    provider = FakeProvider()
    summarizer = ProviderSummarizer(
        provider=provider, model_id="essai/modele", prompt_path=PROMPT, temperature=0.0
    )

    summarizer.summarize('{"session":{"id":"cccccccccccccccc"}}')

    request = provider.calls[0]
    # Le prompt est le système, l'entrée sérialisée est le message. L'un ne
    # doit jamais se retrouver dans l'autre.
    assert request.system == PROMPT.read_text(encoding="utf-8")
    assert request.prompt == '{"session":{"id":"cccccccccccccccc"}}'
    assert request.temperature == 0.0


def test_provider_summarizer_sends_no_temperature_unless_configured():
    provider = FakeProvider()
    summarizer = ProviderSummarizer(
        provider=provider, model_id="essai/modele", prompt_path=PROMPT
    )

    summarizer.summarize("{}")

    assert provider.calls[0].temperature is None


def test_llm_temperature_loads_as_a_float_and_may_be_absent(tmp_path):
    from pulse_intelligence.config import load_config as load

    path = tmp_path / "config.toml"
    path.write_text("llm_temperature = 0\n", encoding="utf-8")
    assert load(path).llm_temperature == 0.0

    path.write_text('llm_temperature = "froid"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="nombre"):
        load(path)

    assert Config().llm_temperature is None


def test_provider_summarizer_keeps_its_model_id_and_max_tokens():
    provider = FakeProvider()
    summarizer = ProviderSummarizer(
        provider=provider,
        model_id="mlx-community/Modele-4bit",
        prompt_path=PROMPT,
        max_tokens=256,
    )

    summarizer.summarize("{}")

    # `model_id` entre dans summary_event_id : il traverse sans être réécrit.
    assert summarizer.model_id == "mlx-community/Modele-4bit"
    assert provider.calls[0].max_tokens == 256


def test_a_provider_failure_becomes_a_summarizer_failure():
    summarizer = ProviderSummarizer(
        provider=FakeProvider(fail_with=ProviderError("timeout")),
        model_id="essai/modele",
        prompt_path=PROMPT,
    )

    # summarize_session ne connaît que SummarizerError ; la panne d'un runtime
    # d'inférence ne doit pas remonter telle quelle jusqu'à lui.
    with pytest.raises(SummarizerError, match="timeout"):
        summarizer.summarize("{}")


def test_a_missing_prompt_fails_at_construction_not_mid_pass(tmp_path):
    with pytest.raises(SummarizerError, match="introuvable"):
        ProviderSummarizer(
            provider=FakeProvider(),
            model_id="essai/modele",
            prompt_path=tmp_path / "absent.md",
        )


def test_the_shipped_prompt_states_the_output_contract():
    text = PROMPT.read_text(encoding="utf-8")

    for expected in ("reprise", "structured", "central_files", "confidence"):
        assert expected in text
    assert "n'invente" in text.lower()


# --- Configuration --------------------------------------------------------


def test_the_three_llm_keys_load_from_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'llm_provider = "fake"\n'
        'llm_base_url = "http://127.0.0.1:1234"\n'
        "llm_max_tokens = 256\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.llm_provider == "fake"
    assert config.llm_base_url == "http://127.0.0.1:1234"
    assert config.llm_max_tokens == 256


def test_llm_max_tokens_must_be_an_integer(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('llm_max_tokens = "beaucoup"\n', encoding="utf-8")

    # Sans son entrée dans _INT_FIELDS, load_config accepterait la chaîne.
    with pytest.raises(ConfigError, match="entier"):
        load_config(path)


def test_no_provider_is_chosen_by_default():
    # Le choix du modèle est une décision écrite, jamais un défaut.
    assert Config().llm_provider == ""


def test_default_prompt_version_is_the_current_one_and_resolves_to_a_file():
    # v2 courante depuis le 2026-09-06 (spec §7) ; v1 reste livrée pour rejouer la référence.
    assert Config().prompt_version == "v2"
    assert prompt_path_for("v2").is_file() and prompt_path_for("v1").is_file()


def test_prompt_v3_is_selectable_by_configuration_and_v2_is_untouched():
    """v3 (points `open` référencés) se choisit par `prompt_version = "v3"` ;
    le défaut reste v2, dont le texte est épinglé : aucune retouche silencieuse
    d'un prompt déjà mesuré (règle du pas 3)."""
    import hashlib

    from pulse_intelligence.llm.fake import FakeProvider
    from pulse_intelligence.session_input import uses_open_items

    assert uses_open_items("v3") and not uses_open_items(Config().prompt_version)
    summarizer = ProviderSummarizer(provider=FakeProvider(), model_id="m", prompt_path=prompt_path_for("v3"))
    for expected in ('"kind": "observed"', '"kind": "carried_over"', '"kind": "requested"',
                     "non observé", "previous_summary:<i>", "agent_request:0"):
        assert expected in summarizer.system, expected
    pinned = {
        "v1": "e411269c34fc3604c623cc6772b01bc8ca93861e63d8ce75880f193192efcfd0",
        "v2": "585ee39c01efbad05c8cfd19dacf8ac62297287520875c6c9cb6830bd6b63a05",
    }
    for version, digest in pinned.items():
        assert hashlib.sha256(prompt_path_for(version).read_bytes()).hexdigest() == digest, version


def test_the_suite_never_reads_the_developer_home(tmp_path):
    # Fixture autouse de conftest : `load_config()` sans chemin tombe sur un dossier vide,
    # jamais sur ~/.pulse_intelligence — sinon une config de dogfooding fait rougir la suite.
    assert load_config() == Config()


# --- Câblage de la CLI ----------------------------------------------------


def _config_file(tmp_path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_refuses_an_unknown_provider(fake_core, tmp_path, capsys):
    config = _config_file(tmp_path, 'llm_provider = "ollama"\n')

    code = cli.main(
        ["--config", str(config), *base_args(fake_core, tmp_path), "run", "--once"]
    )

    assert code == 1
    assert "ollama" in capsys.readouterr().err


def test_cli_runs_end_to_end_on_the_fake_provider(fake_core, tmp_path, capsys):
    """Critère d'acceptation n°1 : la chaîne complète tourne sans réseau."""
    fake_core.add_sessions(today(), session_view("dddddddddddddddd"))
    config = _config_file(tmp_path, 'llm_provider = "fake"\n')

    code = cli.main(
        ["--config", str(config), *base_args(fake_core, tmp_path), "run", "--once"]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "candidates=1 created=1" in out
    # L'événement est parti vers Core, validé par parse_model_output au passage.
    summaries = [p for p in fake_core.posts if p["type"] == "session_summary"]
    assert summaries, "aucun session_summary reçu par Core"
    details = summaries[-1]["details"]
    assert "dddddddddddddddd" in details["reprise"]["doing"]


def test_fake_provider_ignores_the_id_of_the_annexed_previous_summary():
    """Régression : l'annexe `previous_summary` trie avant `session`.

    L'entrée est sérialisée `sort_keys=True`, donc une recherche par motif
    tombait sur l'`id` de la session précédente et le faux résumé citait le
    voisin. Vu en conditions réelles sur la trace du 2026-09-05.
    """
    prompt = json.dumps(
        {
            "agent_session": None,
            "previous_summary": {"id": "1111111111111111", "label": "work-1"},
            "session": {"id": "2222222222222222"},
        },
        sort_keys=True,
    )

    result = FakeProvider().complete(CompletionRequest(system="s", prompt=prompt))

    assert "2222222222222222" in result.text
    assert "1111111111111111" not in result.text
