"""Provider HTTP pour tout endpoint exposant l'API de complétion de chat.

Générique par construction : aucune URL, aucun nom d'hébergeur ici. Le point
d'accès, le jeton et le nom du modèle viennent de l'environnement ; le dépôt
ne sait pas à quoi il parle, et c'est voulu.

Usage prévu : référence de comparaison sur le corpus, et dépannage quand le
modèle local n'est pas disponible. Ce n'est pas le provider de production.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from .provider import CompletionRequest, CompletionResult, ProviderError


ENV_BASE_URL = "PULSE_LLM_BASE_URL"
ENV_API_KEY = "PULSE_LLM_API_KEY"
ENV_MODEL = "PULSE_LLM_MODEL"

DEFAULT_TIMEOUT_S = 120
# Les seuls paramètres qu'un endpoint peut refuser et qu'on accepte de retirer.
_NEGOTIABLE_PARAMETERS = ("temperature",)


def _completions_url(base_url: str) -> str:
    """`…/v1/chat/completions`, que la base porte déjà `/v1` ou non."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        return f"{root}/chat/completions"
    return f"{root}/v1/chat/completions"


@dataclass
class OpenAICompatibleProvider:
    base_url: str
    model: str
    api_key: str
    timeout_s: int = DEFAULT_TIMEOUT_S
    name: str = "openai-compatible"
    session: requests.Session = field(default_factory=requests.Session)

    @classmethod
    def from_environment(
        cls,
        *,
        fallback_base_url: str = "",
        fallback_model: str = "",
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ) -> "OpenAICompatibleProvider":
        """L'environnement prime ; la config sert de repli pour le non-secret.

        Le jeton n'a pas de repli : il ne vient que de l'environnement, jamais
        d'un fichier du dépôt.
        """
        base_url = os.environ.get(ENV_BASE_URL, "").strip() or fallback_base_url.strip()
        model = os.environ.get(ENV_MODEL, "").strip() or fallback_model.strip()
        api_key = os.environ.get(ENV_API_KEY, "").strip()
        if not base_url:
            raise ProviderError(
                f"point d'accès absent : renseigne {ENV_BASE_URL} "
                "(ou llm_base_url dans config.toml)"
            )
        if not api_key:
            # Un appel anonyme partirait quand même chez certains endpoints :
            # on refuse ici plutôt que d'envoyer le contexte de session sans
            # savoir qui le reçoit.
            raise ProviderError(f"jeton absent : renseigne {ENV_API_KEY}")
        if not model:
            raise ProviderError(
                f"modèle absent : renseigne {ENV_MODEL} (ou model_id dans config.toml)"
            )
        return cls(
            base_url=base_url, model=model, api_key=api_key, timeout_s=timeout_s
        )

    def complete(self, request: CompletionRequest) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "max_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        started = time.monotonic()
        response = self._post(payload)

        # Négociation de paramètres, pas retry sur contenu : certains modèles
        # derrière un endpoint « compatible » refusent un paramètre optionnel
        # (vu en réel : « `temperature` is deprecated for this model », 400).
        # On retire ce paramètre-là, une fois, et on le dit dans le résultat.
        # La liste est fermée : `max_tokens` n'en fait pas partie, le retirer
        # laisserait le modèle générer sans borne.
        dropped: list[str] = []
        for parameter in _NEGOTIABLE_PARAMETERS:
            if (
                response.status_code == 400
                and parameter in payload
                and parameter in response.text
            ):
                payload.pop(parameter)
                dropped.append(parameter)
                response = self._post(payload)
        duration_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 400:
            raise ProviderError(
                f"HTTP {response.status_code} : {_short_body(response)}"
            )
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"réponse inexploitable : {exc}") from exc
        if not isinstance(text, str):
            raise ProviderError("réponse inexploitable : content n'est pas du texte")

        usage = body.get("usage") or {}
        return CompletionResult(
            text=text,
            provider=self.name,
            model=str(body.get("model") or self.model),
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
            duration_ms=duration_ms,
            dropped_parameters=tuple(dropped),
        )

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        try:
            return self.session.post(
                _completions_url(self.base_url),
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"endpoint injoignable : {exc}") from exc

    def healthcheck(self) -> bool:
        """Ne lève jamais : un endpoint muet est une réponse, pas une panne."""
        root = self.base_url.rstrip("/")
        url = root if root.endswith("/v1") else f"{root}/v1"
        try:
            response = self.session.get(
                f"{url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_s,
            )
        except requests.RequestException:
            return False
        return response.status_code < 400


def _short_body(response: requests.Response) -> str:
    """Le corps d'erreur, borné. Les en-têtes — donc le jeton — n'y sont pas."""
    try:
        return response.text[:200]
    except Exception:  # pragma: no cover - défensif
        return "<corps illisible>"


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
