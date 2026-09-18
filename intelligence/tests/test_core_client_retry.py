"""Timeout Core configurable et reprise unique des GET (lot du 2026-09-18).

Le lot launchd s'est arrêté deux fois sur « Core injoignable » alors que Core
répondait : une fois parce que la requête était à cheval sur une veille du
Mac, une fois parce que `/context/sessions` de la veille chargée mettait 5 à
9 s, pile sur le timeout de 5 s codé en dur. Ici : le timeout vient de la
config, un GET a droit à une seconde tentative, un POST jamais.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

import pytest
import requests

from pulse_intelligence import cli
from pulse_intelligence.config import Config, ConfigError, load_config
from pulse_intelligence.core_client import (
    DEFAULT_TIMEOUT_S,
    RETRY_PAUSE_S,
    CoreClient,
    CoreUnavailable,
)


@dataclass
class _Response:
    status_code: int = 200
    payload: Any = None
    text: str = ""

    def json(self) -> Any:
        return self.payload


class _FlakySession:
    """Une session `requests` scriptée : lève les exceptions données, puis répond."""

    def __init__(self, *failures: Exception, response: _Response | None = None) -> None:
        self.failures = list(failures)
        self.response = response or _Response(payload={"ok": True})
        self.calls: list[tuple[str, str, float]] = []

    def request(self, method: str, url: str, *, timeout: float, **kwargs: Any) -> _Response:
        self.calls.append((method, url, timeout))
        if self.failures:
            raise self.failures.pop(0)
        return self.response


def _client(transport: _FlakySession, **kwargs: Any) -> tuple[CoreClient, list[float]]:
    pauses: list[float] = []
    client = CoreClient("http://core.test", session=transport, sleep=pauses.append, **kwargs)
    return client, pauses


def test_get_is_retried_once_after_a_transient_failure():
    transport = _FlakySession(requests.ReadTimeout("Read timed out"))
    client, pauses = _client(transport)

    assert client.status() == {"ok": True}
    assert [call[0] for call in transport.calls] == ["GET", "GET"]
    assert pauses == [RETRY_PAUSE_S]


def test_get_gives_up_after_the_second_failure():
    transport = _FlakySession(requests.ConnectionError("refused"), requests.ReadTimeout("again"))
    client, pauses = _client(transport)

    with pytest.raises(CoreUnavailable, match="Core injoignable sur http://core.test"):
        client.status()
    assert len(transport.calls) == 2
    assert pauses == [RETRY_PAUSE_S]


def test_post_is_never_retried():
    # Un POST rejoué pourrait créer deux fois : la reprise des POST passe par
    # les `pending` et l'identité par event_id, pas par le client HTTP.
    transport = _FlakySession(requests.ReadTimeout("Read timed out"))
    client, pauses = _client(transport)

    with pytest.raises(CoreUnavailable):
        client.post_activity({"event_id": "x"})
    assert [call[0] for call in transport.calls] == ["POST"]
    assert pauses == []


def test_timeout_reaches_every_request():
    transport = _FlakySession()
    client, _ = _client(transport, timeout_s=42)

    client.status()
    assert transport.calls[0][2] == 42


def test_default_timeout_is_no_longer_five_seconds():
    assert DEFAULT_TIMEOUT_S == 60.0
    assert Config().core_timeout_s == 60
    assert CoreClient("http://core.test").timeout_s == DEFAULT_TIMEOUT_S


def test_core_timeout_s_comes_from_config(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text("core_timeout_s = 90\n", encoding="utf-8")
    assert load_config(path).core_timeout_s == 90

    built: dict[str, Any] = {}

    class _Spy(CoreClient):
        def __init__(self, base_url: str, **kwargs: Any) -> None:
            built.update(kwargs, base_url=base_url)
            super().__init__(base_url, **kwargs)

    monkeypatch.setattr(cli, "CoreClient", _Spy)
    args = argparse.Namespace(
        config=path, core_url=None, state=tmp_path / "state.json", command="list"
    )
    _, client, _ = cli._load(args)
    assert built["timeout_s"] == 90
    assert client.timeout_s == 90


def test_core_timeout_s_must_be_a_positive_integer(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('core_timeout_s = "long"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="entier"):
        load_config(path)
