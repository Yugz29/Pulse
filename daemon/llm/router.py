import logging
from typing import Optional

from .ollama_provider import OllamaProvider
from .apple_foundation_provider import AppleFoundationProvider

log = logging.getLogger("pulse")


class LLMRouter:
    def __init__(self, config: Optional[dict] = None):
        config = config or {}
        llm_cfg = config.get("llm", {})

        provider = llm_cfg.get("provider", "ollama")
        if provider != "ollama":
            raise ValueError("Unsupported provider: {0}".format(provider))

        self.default = OllamaProvider(
            url=llm_cfg.get("ollama_url", "http://localhost:11434"),
            model=llm_cfg.get("model", "mistral"),
        )

        # Provider Apple Foundation Models — optionnel.
        # Utilisé pour les tâches légères (journal summaries, classification).
        # Fallback automatique vers Ollama si Perspective Server est indisponible.
        self.apple: Optional[AppleFoundationProvider] = None
        try:
            self.apple = AppleFoundationProvider()
        except Exception as exc:
            log.warning("AppleFoundationProvider non chargé : %s", exc)

    # ── Profils de tâche ──────────────────────────────────────────────────────
    #
    # journal_summary  → Apple Foundation Models (rapide, sans reasoning)
    # default          → Ollama (Qwen3 + think=True pour DayDream, etc.)

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 160,
        think: bool | None = None,
        profile: str = "default",
    ) -> str:
        if profile == "journal_summary" and self.apple is not None:
            try:
                return self.apple.complete(
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                log.warning(
                    "Apple Foundation indisponible pour journal_summary, fallback Ollama : %s", exc
                )
        return self.default.complete(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            think=think,
        )

    def list_models(self) -> list:
        return self.default.list_models()

    def get_model(self) -> str:
        return self.default.model

    def set_model(self, model: str) -> None:
        self.default.model = model

    def stream_messages(self, messages: list, max_tokens: int = 600):
        """
        Streaming sur un historique complet de messages.
        Délègue au provider actif.
        """
        return self.default.stream_messages(messages=messages, max_tokens=max_tokens)

    def chat_with_tools(
        self,
        messages: list,
        tools: list,
        max_tokens: int = 600,
    ) -> dict:
        """
        Appel non-streaming avec tool calling.
        Délègue au provider actif.
        """
        return self.default.chat_with_tools(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
