"""Provider HTTP générique, contre un faux endpoint local.

Aucune URL ni aucun nom d'hébergeur n'apparaît ici : le faux endpoint tourne
sur la boucle locale, sur un port éphémère, comme le faux Core.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from conftest import REFERENCE, session_view
from pulse_intelligence import cli
from pulse_intelligence.llm.openai_compatible import (
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MODEL,
    OpenAICompatibleProvider,
    _completions_url,
)
from pulse_intelligence.llm.provider import CompletionRequest, ProviderError


def today() -> str:
    return REFERENCE.astimezone().date().isoformat()


VALID_OUTPUT = json.dumps(
    {
        "reprise": {"doing": "d", "stopped_at": "s", "open": "o"},
        "structured": {
            "project": None,
            "intents": [],
            "central_files": [],
            "blockers": [],
            "confidence": "low",
        },
    }
)


@dataclass
class FakeEndpoint:
    """Rejoue une réponse de complétion et enregistre ce qu'il reçoit."""

    status: int = 200
    body: dict[str, Any] | None = None
    raw_body: str | None = None
    requests_seen: list[dict[str, Any]] = field(default_factory=list)
    auth_seen: list[str | None] = field(default_factory=list)
    url: str = ""


@pytest.fixture
def endpoint():
    state = FakeEndpoint()
    app = Flask(__name__)
    app.logger.disabled = True

    @app.post("/v1/chat/completions")
    def completions():
        state.requests_seen.append(request.get_json(silent=True) or {})
        state.auth_seen.append(request.headers.get("Authorization"))
        if state.raw_body is not None:
            return state.raw_body, state.status, {"Content-Type": "application/json"}
        body = state.body or {
            "model": "modele-de-test",
            "choices": [{"message": {"content": VALID_OUTPUT}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 22},
        }
        return jsonify(body), state.status

    @app.get("/v1/models")
    def models():
        state.auth_seen.append(request.headers.get("Authorization"))
        return jsonify({"data": []}), state.status

    server = make_server("127.0.0.1", 0, app)
    state.url = f"http://127.0.0.1:{server.port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _provider(endpoint: FakeEndpoint, **overrides) -> OpenAICompatibleProvider:
    options = {
        "base_url": endpoint.url,
        "model": "modele-de-test",
        "api_key": "jeton-de-test",
        "timeout_s": 5,
    }
    options.update(overrides)
    return OpenAICompatibleProvider(**options)


# --- Construction de la requête -------------------------------------------


def test_the_request_carries_the_two_roles_and_the_generation_settings(endpoint):
    provider = _provider(endpoint)

    provider.complete(
        CompletionRequest(system="le prompt", prompt="l'entrée", max_tokens=256)
    )

    sent = endpoint.requests_seen[0]
    assert sent["model"] == "modele-de-test"
    assert sent["messages"] == [
        {"role": "system", "content": "le prompt"},
        {"role": "user", "content": "l'entrée"},
    ]
    assert sent["max_tokens"] == 256
    assert sent["temperature"] == 0.0


def test_the_token_travels_as_a_bearer_header(endpoint):
    _provider(endpoint).complete(CompletionRequest(system="s", prompt="p"))

    assert endpoint.auth_seen[0] == "Bearer jeton-de-test"


def test_the_response_is_decoded_into_a_completion_result(endpoint):
    result = _provider(endpoint).complete(CompletionRequest(system="s", prompt="p"))

    assert result.text == VALID_OUTPUT
    assert result.provider == "openai-compatible"
    assert result.model == "modele-de-test"
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 22
    assert result.duration_ms >= 0


def test_missing_usage_is_not_an_error(endpoint):
    endpoint.body = {"choices": [{"message": {"content": VALID_OUTPUT}}]}

    result = _provider(endpoint).complete(CompletionRequest(system="s", prompt="p"))

    # Tous les endpoints ne comptent pas les tokens ; l'absence n'est pas une
    # panne, elle se lit `None` dans le rapport d'eval.
    assert result.prompt_tokens is None and result.completion_tokens is None


# --- Chemins d'erreur ------------------------------------------------------


def test_an_http_error_becomes_a_provider_error(endpoint):
    endpoint.status = 503
    endpoint.body = {"error": {"message": "surchargé"}}

    with pytest.raises(ProviderError, match="503"):
        _provider(endpoint).complete(CompletionRequest(system="s", prompt="p"))


def test_an_unparsable_response_becomes_a_provider_error(endpoint):
    endpoint.raw_body = "<html>passerelle</html>"

    with pytest.raises(ProviderError, match="inexploitable"):
        _provider(endpoint).complete(CompletionRequest(system="s", prompt="p"))


def test_a_response_without_choices_becomes_a_provider_error(endpoint):
    endpoint.body = {"model": "m", "usage": {}}

    with pytest.raises(ProviderError, match="inexploitable"):
        _provider(endpoint).complete(CompletionRequest(system="s", prompt="p"))


def test_an_unreachable_endpoint_becomes_a_provider_error():
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:9",
        model="m",
        api_key="k",
        timeout_s=2,
    )

    with pytest.raises(ProviderError, match="injoignable"):
        provider.complete(CompletionRequest(system="s", prompt="p"))


def test_an_error_message_never_carries_the_token(endpoint):
    endpoint.status = 401
    endpoint.body = {"error": {"message": "refusé"}}

    with pytest.raises(ProviderError) as caught:
        _provider(endpoint, api_key="jeton-tres-secret").complete(
            CompletionRequest(system="s", prompt="p")
        )

    # Le corps est borné et les en-têtes n'y sont pas : le jeton ne peut pas
    # ressortir dans un journal ou un rapport d'eval.
    assert "jeton-tres-secret" not in str(caught.value)


# --- Résolution de la configuration ---------------------------------------


def test_the_environment_supplies_the_endpoint(monkeypatch, endpoint):
    monkeypatch.setenv(ENV_BASE_URL, endpoint.url)
    monkeypatch.setenv(ENV_API_KEY, "jeton-de-test")
    monkeypatch.setenv(ENV_MODEL, "modele-de-test")

    provider = OpenAICompatibleProvider.from_environment()

    assert provider.base_url == endpoint.url
    assert provider.model == "modele-de-test"


def test_the_environment_wins_over_the_config_fallback(monkeypatch, endpoint):
    monkeypatch.setenv(ENV_BASE_URL, endpoint.url)
    monkeypatch.setenv(ENV_API_KEY, "jeton-de-test")

    provider = OpenAICompatibleProvider.from_environment(
        fallback_base_url="http://127.0.0.1:1",
        fallback_model="modele-de-repli",
    )

    assert provider.base_url == endpoint.url
    # Le modèle n'était pas dans l'environnement : le repli config sert.
    assert provider.model == "modele-de-repli"


def test_a_missing_token_refuses_before_any_call(monkeypatch):
    monkeypatch.setenv(ENV_BASE_URL, "http://127.0.0.1:1")
    monkeypatch.delenv(ENV_API_KEY, raising=False)

    # Rien ne part : le contexte de session ne s'envoie pas à un destinataire
    # qu'on n'a pas authentifié.
    with pytest.raises(ProviderError, match=ENV_API_KEY):
        OpenAICompatibleProvider.from_environment(fallback_model="m")


def test_a_missing_endpoint_is_named_in_the_error(monkeypatch):
    monkeypatch.delenv(ENV_BASE_URL, raising=False)
    monkeypatch.setenv(ENV_API_KEY, "k")

    with pytest.raises(ProviderError, match=ENV_BASE_URL):
        OpenAICompatibleProvider.from_environment()


def test_a_missing_model_is_named_in_the_error(monkeypatch):
    monkeypatch.setenv(ENV_BASE_URL, "http://127.0.0.1:1")
    monkeypatch.setenv(ENV_API_KEY, "k")
    monkeypatch.delenv(ENV_MODEL, raising=False)

    with pytest.raises(ProviderError, match=ENV_MODEL):
        OpenAICompatibleProvider.from_environment()


# --- Forme de l'URL --------------------------------------------------------


@pytest.mark.parametrize(
    "base, expected",
    [
        ("http://127.0.0.1:1", "http://127.0.0.1:1/v1/chat/completions"),
        ("http://127.0.0.1:1/", "http://127.0.0.1:1/v1/chat/completions"),
        ("http://127.0.0.1:1/v1", "http://127.0.0.1:1/v1/chat/completions"),
        ("http://127.0.0.1:1/v1/", "http://127.0.0.1:1/v1/chat/completions"),
    ],
)
def test_the_v1_segment_is_never_doubled(base, expected):
    assert _completions_url(base) == expected


# --- healthcheck -----------------------------------------------------------


def test_healthcheck_answers_without_raising(endpoint):
    assert _provider(endpoint).healthcheck() is True


def test_healthcheck_is_false_when_nothing_answers():
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:9", model="m", api_key="k", timeout_s=2
    )

    assert provider.healthcheck() is False


# --- Câblage CLI -----------------------------------------------------------


def _config_file(tmp_path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_reports_a_missing_token_without_running(
    fake_core, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv(ENV_BASE_URL, "http://127.0.0.1:1")
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    config = _config_file(
        tmp_path, 'llm_provider = "openai-compatible"\nmodel_id = "m"\n'
    )

    code = cli.main(
        [
            "--config", str(config),
            "--core-url", fake_core.url,
            "--state", str(tmp_path / "state.json"),
            "run", "--once",
        ]
    )

    # Sortie propre, pas une trace d'exception : ProviderError est attrapée par
    # main() puisqu'elle ne peut survenir qu'à la construction du provider.
    assert code == 1
    assert ENV_API_KEY in capsys.readouterr().err


def test_cli_runs_end_to_end_against_a_local_endpoint(
    fake_core, endpoint, tmp_path, monkeypatch, capsys
):
    """La chaîne complète, du faux Core au faux endpoint et retour."""
    fake_core.add_sessions(today(), session_view("eeeeeeeeeeeeeeee"))
    monkeypatch.setenv(ENV_BASE_URL, endpoint.url)
    monkeypatch.setenv(ENV_API_KEY, "jeton-de-test")
    monkeypatch.setenv(ENV_MODEL, "modele-de-test")
    config = _config_file(tmp_path, 'llm_provider = "openai-compatible"\n')

    code = cli.main(
        [
            "--config", str(config),
            "--core-url", fake_core.url,
            "--state", str(tmp_path / "state.json"),
            "run", "--once",
        ]
    )

    assert code == 0
    assert "candidates=1 created=1" in capsys.readouterr().out
    # Le prompt versionné et l'entrée sérialisée sont bien partis au modèle.
    messages = endpoint.requests_seen[0]["messages"]
    assert "reprise" in messages[0]["content"]
    assert "eeeeeeeeeeeeeeee" in messages[1]["content"]
    # Et le résumé est revenu jusqu'à Core.
    summaries = [p for p in fake_core.posts if p["type"] == "session_summary"]
    assert summaries and summaries[-1]["details"]["model_id"] == "modele-de-test"
