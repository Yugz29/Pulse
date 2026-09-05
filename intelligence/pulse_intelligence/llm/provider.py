"""L'interface que toute implémentation de modèle doit servir."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    prompt: str
    max_tokens: int = 1024
    temperature: float = 0.0


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_ms: int


class ProviderError(RuntimeError):
    """Réseau, chargement, timeout — jamais un problème de contenu.

    Une sortie mal formée n'est pas une `ProviderError` : le provider l'a
    transportée correctement. C'est `parse_model_output` qui la rejette, en
    aval, là où le contrat de sortie est connu.
    """


class LLMProvider(Protocol):
    name: str

    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Texte du modèle pour cette requête, ou `ProviderError`."""
        ...

    def healthcheck(self) -> bool:
        """Le modèle est-il joignable ? Ne lève pas."""
        ...
