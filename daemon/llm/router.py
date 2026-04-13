from typing import Optional

from .ollama_provider import OllamaProvider


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

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 160,
        think: bool | None = None,
    ) -> str:
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
