"""L'interface que toute implémentation de modèle doit servir."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    prompt: str
    max_tokens: int = 1024
    # None = le paramètre n'est pas envoyé. La reproductibilité à 0.0 est un
    # choix de configuration (`llm_temperature`), pas un défaut imposé.
    temperature: float | None = None


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_ms: int
    # Paramètres que l'endpoint a refusés et que le provider a retirés pour
    # obtenir une réponse. Vide dans le cas nominal. Un rapport d'eval doit
    # savoir qu'un résumé n'a pas été produit à température 0.
    dropped_parameters: tuple[str, ...] = ()


class ProviderError(RuntimeError):
    """Réseau, chargement, timeout — jamais un problème de contenu.

    Une sortie mal formée n'est pas une `ProviderError` : le provider l'a
    transportée correctement. C'est `parse_model_output` qui la rejette, en
    aval, là où le contrat de sortie est connu.
    """


class LLMProvider(Protocol):
    name: str
    # Le modèle réellement servi. C'est lui qui identifie le résumé dans
    # `summary_event_id` : deux modèles distincts derrière le même provider
    # doivent produire deux event_id distincts.
    model: str

    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Texte du modèle pour cette requête, ou `ProviderError`."""
        ...

    def healthcheck(self) -> bool:
        """Le modèle est-il joignable ? Ne lève pas."""
        ...
