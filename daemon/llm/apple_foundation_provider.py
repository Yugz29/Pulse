"""
AppleFoundationProvider — Apple Foundation Models via Perspective Server.

Perspective Server expose les Foundation Models d'Apple via une API compatible
Ollama sur le port 11435. Ce provider hérite d'OllamaProvider pour réutiliser
le parsing /api/chat, avec trois adaptations :

  1. think est toujours ignoré — Foundation Models n'a pas de mode raisonnement
     séparé, ce qui est une feature : réponse directe, zéro overhead thermique.

  2. warmup() est un simple ping — les Foundation Models sont toujours chargés
     tant qu'Apple Intelligence est actif. Pas de freeze au démarrage.

  3. Le suffix anti-tools est injecté dans le system prompt — Perspective Server
     expose des outils filesystem que le modèle peut déclencher si le prompt
     mentionne des noms de fichiers. L'injection empêche ce comportement pour
     les tâches de génération de texte.
"""

import logging
from .ollama_provider import OllamaProvider

log = logging.getLogger("pulse")

APPLE_BASE_URL = "http://localhost:11435"
APPLE_MODEL    = "apple.local"

# Injecté dans chaque system prompt pour empêcher le modèle d'interpréter
# les noms de fichiers dans les prompts comme des instructions d'édition.
_NO_TOOLS_SUFFIX = " Ne pas utiliser d'outils. Répondre uniquement avec du texte."


class AppleFoundationProvider(OllamaProvider):
    """
    Provider Apple Foundation Models via Perspective Server (port 11435).

    Drop-in replacement pour OllamaProvider sur les tâches légères :
    journal summaries, classification, complétion courte.
    Pour les tâches de raisonnement (DayDream), utiliser OllamaProvider.
    """

    def __init__(self) -> None:
        super().__init__(
            url=APPLE_BASE_URL,
            model=APPLE_MODEL,
            # num_ctx et keep_alive sont ignorés par Perspective Server
            # mais requis par le constructeur parent.
            num_ctx=8192,
            keep_alive="10m",
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def warmup(self) -> bool:
        """
        Ping Perspective Server pour vérifier la disponibilité.
        Foundation Models est toujours chargé — pas de warmup réel.
        """
        try:
            models = self.list_models()
            available = any(APPLE_MODEL.split(":")[0] in m for m in models)
            if available:
                self._mark_success()
                log.info("Apple Foundation Models disponible via Perspective Server")
            else:
                log.warning("Perspective Server actif mais %s introuvable", APPLE_MODEL)
            return available
        except Exception as exc:
            log.warning("Perspective Server indisponible au warmup : %s", exc)
            return False

    def unload(self) -> bool:
        """Foundation Models est géré nativement — pas de déchargement."""
        return True

    # ── Génération ─────────────────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 160,
        think: bool | None = None,  # ignoré — Foundation Models n'a pas de think mode
        **kwargs,
    ) -> str:
        """
        Complétion via Apple Foundation Models.

        - think est ignoré : réponse directe sans raisonnement séparé.
        - Le suffix anti-tools est ajouté au system prompt.
        - Pas de retry think=False (pas de reasoning_without_final possible).
        """
        effective_system = (system + _NO_TOOLS_SUFFIX) if system else _NO_TOOLS_SUFFIX.strip()
        return self._complete_once(
            prompt=prompt,
            system=effective_system,
            max_tokens=max_tokens,
            think=None,  # jamais transmis à Perspective Server
        )
