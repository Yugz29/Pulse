"""L'interface que toute implémentation de modèle doit servir."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    prompt: str
    max_tokens: int = 1024
    # None = le paramètre n'est pas envoyé. 0.0 réduit l'aléa de
    # l'échantillonnage ; ce n'est pas une garantie de reproductibilité tant
    # que prompt, modèle, poids et runtime ne sont pas figés. C'est un choix
    # de configuration (`llm_temperature`), pas un défaut imposé.
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

    Une `ProviderError` nue est **transitoire et propre à cet appel** (délai
    dépassé, 5xx, erreur de génération) : réessayable, sans consommer le
    budget d'échecs. Les deux sous-classes disent autre chose.
    """


class ProviderUnavailable(ProviderError):
    """Le modèle n'est pas joignable du tout : runtime absent, poids non
    chargés, endpoint injoignable. La même erreur pour toute candidate, le
    passage s'arrête à la première (audit 2026-09-06, défaut 5)."""


class ProviderInputRefused(ProviderError):
    """Le modèle refuse cette entrée-là, et la refusera encore : plafond de
    tokens, HTTP 400 sur le contenu. Consomme le budget comme une sortie
    invalide."""


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
