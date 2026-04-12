from __future__ import annotations

import threading
import time
from pathlib import Path
from urllib import request as urllib_request

from daemon.settings import load_runtime_settings, save_runtime_settings


class LLMRuntime:
    def __init__(
        self,
        *,
        summary_llm,
        settings_path: Path,
        get_available_models,
        get_selected_command_model,
        set_selected_command_model,
        ollama_url: str = "http://localhost:11434",
        health_ttl: float = 8.0,
    ) -> None:
        self.summary_llm = summary_llm
        self.settings_path = settings_path
        self.get_available_models = get_available_models
        self.get_selected_command_model = get_selected_command_model
        self.set_selected_command_model = set_selected_command_model
        self.ollama_url = ollama_url.rstrip("/")
        self.health_ttl = health_ttl
        self._health_lock = threading.Lock()
        self._health_ok = False
        self._health_at = 0.0

    def provider(self):
        return getattr(self.summary_llm, "default", None)

    def ollama_ping(self) -> bool:
        now = time.monotonic()
        with self._health_lock:
            if now - self._health_at < self.health_ttl:
                return self._health_ok
        try:
            req = urllib_request.Request(f"{self.ollama_url}/api/version", method="GET")
            with urllib_request.urlopen(req, timeout=3):
                online = True
        except Exception:
            online = False
        with self._health_lock:
            self._health_ok = online
            self._health_at = now
        return online

    def warmup_background(self, log) -> None:
        provider = self.provider()
        if provider and hasattr(provider, "warmup"):
            log.info("LLM warmup en cours (%s)...", provider.model)
            ok = provider.warmup()
            if ok:
                log.info("LLM warmup terminé (%s)", provider.model)
            else:
                log.warning("LLM warmup échoué (Ollama indisponible ?)")

    def unload_background(self, log) -> None:
        provider = self.provider()
        if provider and hasattr(provider, "unload"):
            ok = provider.unload()
            if ok:
                log.info("LLM déchargé de la mémoire (%s)", provider.model)
            else:
                log.warning("LLM unload échoué (Ollama indisponible ?)")

    def get_selected_summary_model(self) -> str:
        return self.summary_llm.get_model()

    def set_selected_summary_model(self, model: str) -> bool:
        available = self.get_available_models()
        if available and model not in available:
            return False
        self.summary_llm.set_model(model)
        return True

    def set_unified_model(self, model: str) -> bool:
        available = self.get_available_models()
        if available and model not in available:
            return False
        self.summary_llm.set_model(model)
        self.set_selected_command_model(model)
        return True

    def load_persisted_models(self) -> None:
        settings = load_runtime_settings(self.settings_path)
        model = (
            settings.get("model")
            or settings.get("command_model")
            or ""
        ).strip()
        if model:
            self.set_unified_model(model)

    def persist_selected_models(self) -> None:
        model = self.get_selected_command_model()
        save_runtime_settings({"model": model}, settings_path=self.settings_path)
