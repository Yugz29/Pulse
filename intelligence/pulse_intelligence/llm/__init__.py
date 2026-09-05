"""Couche modèle : transporte du texte, ne connaît rien de Pulse.

`LLMProvider` vit sous `Summarizer` (le contrat métier, inchangé depuis
l'étape 2). Un provider ne parse pas la sortie, ne réessaie pas sur contenu et
n'a aucune notion de session : il prend un système plus un prompt et rend du
texte. Spec `docs/specs/2026-09-05-llm-provider.md` v2.
"""

from .provider import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    ProviderError,
)

__all__ = [
    "CompletionRequest",
    "CompletionResult",
    "LLMProvider",
    "ProviderError",
]
