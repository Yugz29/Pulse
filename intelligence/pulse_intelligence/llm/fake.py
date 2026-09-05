"""Provider de test : aucune dépendance, aucun réseau, aucun modèle.

Distinct de `FakeSummarizer` (`summarizer.py`), et les deux restent : le
`FakeSummarizer` sert la suite livrée aux étapes 1 et 2, où le prompt n'existe
pas encore et où le test fournit directement la sortie du modèle. `FakeProvider`
teste la couche d'en dessous — que la requête est bien construite et que le
contexte a circulé jusqu'au modèle.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from .provider import CompletionRequest, CompletionResult, ProviderError


# L'identifiant de session est un sha256 tronqué à 16 hex (Core 0.5.0).
_SESSION_ID = re.compile(r'"id"\s*:\s*"([0-9a-f]{16})"')

DEFAULT_MODEL = "fake/provider"


def _session_id_of(prompt: str) -> str:
    """L'identifiant de LA session résumée, pas le premier `id` venu.

    L'entrée est sérialisée `sort_keys=True` et annexe `previous_summary`, qui
    porte l'`id` de la session *précédente* — et qui trie avant `session`. Une
    recherche par motif rendait donc l'identifiant du voisin, et le faux
    résumé citait la mauvaise session. On lit la structure ; le motif ne sert
    que si l'entrée n'est pas le JSON attendu.
    """
    try:
        payload = json.loads(prompt)
        session_id = payload["session"]["id"]
    except (ValueError, KeyError, TypeError):
        match = _SESSION_ID.search(prompt)
        return match.group(1) if match else "session inconnue"
    return session_id if isinstance(session_id, str) else "session inconnue"


def _echoing_output(prompt: str) -> str:
    """Une sortie conforme qui rejoue l'identifiant de la session résumée.

    `central_files` reste vide : le garde-fou de `parse_model_output` exige que
    chaque chemin cité vienne de l'entrée, et un faux provider n'a pas à
    deviner lesquels sont dans la vue. Un test qui veut vérifier ce garde-fou
    passe sa propre sortie par `outputs`.
    """
    session_id = _session_id_of(prompt)
    return json.dumps(
        {
            "reprise": {
                "doing": f"Reprise de la session {session_id}.",
                "stopped_at": "Sortie fixée du faux provider.",
                "open": "Rien, c'est un faux modèle.",
            },
            "structured": {
                "project": None,
                "intents": [],
                "central_files": [],
                "blockers": [],
                "confidence": "low",
            },
        },
        ensure_ascii=False,
    )


@dataclass
class FakeProvider:
    """Rend une sortie fixée et enregistre chaque requête reçue."""

    name: str = "fake"
    model: str = DEFAULT_MODEL
    outputs: str | list[str] | None = None
    fail_with: ProviderError | None = None
    invalid_output: bool = False
    healthy: bool = True
    calls: list[CompletionRequest] = field(default_factory=list)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        started = time.monotonic()
        self.calls.append(request)
        if self.fail_with is not None:
            raise self.fail_with
        if self.invalid_output:
            text = "je ne suis pas du JSON"
        elif isinstance(self.outputs, str):
            text = self.outputs
        elif isinstance(self.outputs, list) and self.outputs:
            index = min(len(self.calls) - 1, len(self.outputs) - 1)
            text = self.outputs[index]
        else:
            text = _echoing_output(request.prompt)
        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=None,
            completion_tokens=None,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def healthcheck(self) -> bool:
        return self.healthy
