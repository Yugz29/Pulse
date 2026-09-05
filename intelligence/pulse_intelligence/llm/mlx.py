"""Provider local : le modèle servi par `mlx-lm` sur Apple Silicon.

`mlx_lm` est importé **paresseusement**, à l'intérieur des méthodes : un
environnement sans l'extra `mlx` (la CI, un poste qui ne fait tourner que la
référence distante) importe ce module sans erreur, la suite passe, et seul un
appel réel réclame la dépendance.

Le modèle est chargé une fois et gardé en mémoire pour la durée du process :
un passage `eval` ou `run` résume plusieurs sessions sans recharger 14 Go.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .provider import CompletionRequest, CompletionResult, ProviderError

DEFAULT_MODEL = "mlx-community/Qwen3.8-27B-4bit"


@dataclass
class MLXProvider:
    model: str = DEFAULT_MODEL
    name: str = "mlx"
    # Chargé au premier complete(), puis réutilisé. Non sérialisable, hors repr.
    _bundle: Any = field(default=None, repr=False, compare=False)

    def _ensure_loaded(self) -> tuple[Any, Any]:
        if self._bundle is None:
            try:
                from mlx_lm import load
            except ImportError as exc:
                raise ProviderError(
                    "mlx-lm absent : installe l'extra mlx "
                    "(`uv pip install -e '.[mlx]'`) pour le provider local"
                ) from exc
            try:
                self._bundle = load(self.model)
            except Exception as exc:  # chargement HF, poids, mémoire
                raise ProviderError(f"chargement du modèle {self.model} : {exc}") from exc
        return self._bundle

    def _render_prompt(self, tokenizer: Any, request: CompletionRequest) -> str:
        """Enveloppe système+prompt dans le template du modèle, thinking coupé."""
        messages = [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.prompt},
        ]
        template = getattr(tokenizer, "chat_template", None)
        kwargs: dict[str, Any] = {"add_generation_prompt": True, "tokenize": False}
        if template and "enable_thinking" in template:
            kwargs["enable_thinking"] = False
        try:
            return tokenizer.apply_chat_template(messages, **kwargs)
        except TypeError:
            # Version de mlx-lm sans le paramètre : on réessaie sans lui.
            kwargs.pop("enable_thinking", None)
            return tokenizer.apply_chat_template(messages, **kwargs)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        model, tokenizer = self._ensure_loaded()
        from mlx_lm import generate

        prompt = self._render_prompt(tokenizer, request)
        started = time.monotonic()
        try:
            text = generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=request.max_tokens,
                verbose=False,
            )
        except Exception as exc:
            raise ProviderError(f"génération : {exc}") from exc
        duration_ms = int((time.monotonic() - started) * 1000)

        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=_count(tokenizer, prompt),
            completion_tokens=_count(tokenizer, text),
            duration_ms=duration_ms,
            # temperature/max_tokens ne se négocient pas avec un modèle local :
            # rien à retirer, la génération est toujours acceptée.
            dropped_parameters=(),
        )

    def healthcheck(self) -> bool:
        """Le modèle se charge-t-il ? Coûteux (14 Go) mais ne lève pas."""
        try:
            self._ensure_loaded()
            return True
        except ProviderError:
            return False


def _count(tokenizer: Any, text: str) -> int | None:
    try:
        return len(tokenizer.encode(text))
    except Exception:
        return None
