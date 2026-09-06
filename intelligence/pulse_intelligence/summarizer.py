"""Interface du modèle. Le modèle est un détail d'implémentation.

Un Summarizer reçoit l'entrée sérialisée (le JSON de la vue de session,
voir session_summary.serialize_input) et rend le texte brut produit par le
modèle. Le prompt qui enveloppe cette entrée appartient à l'implémentation
réelle (MLXSummarizer, étape 3) ; le parsing de la sortie est commun.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class Summarizer(Protocol):
    model_id: str

    def summarize(self, model_input: str) -> str:
        """Texte brut du modèle pour cette entrée (JSON attendu, voir §7)."""
        ...


class SummarizerError(RuntimeError):
    """Le modèle n'a pas pu produire de sortie pour cet appel (délai, 5xx,
    génération) : transitoire, réessayable, ne consomme pas le budget."""


class SummarizerUnavailable(SummarizerError):
    """Modèle injoignable pour toutes les candidates : arrêt du passage."""


class SummarizerInputRefused(SummarizerError):
    """Entrée refusée de façon déterministe : consomme le budget."""


@dataclass
class FakeSummarizer:
    """Rend des sorties fixées, dans l'ordre, et enregistre chaque appel.

    Une seule chaîne est répétée ; une liste est consommée puis la dernière
    valeur est répétée. Une exception dans la liste est levée à son tour.
    """

    outputs: str | list[str | Exception]
    model_id: str = "fake/summarizer"
    calls: list[str] = field(default_factory=list)

    def summarize(self, model_input: str) -> str:
        self.calls.append(model_input)
        if isinstance(self.outputs, str):
            return self.outputs
        index = min(len(self.calls) - 1, len(self.outputs) - 1)
        selected = self.outputs[index]
        if isinstance(selected, Exception):
            raise selected
        return selected
