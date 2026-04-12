import json
import logging
import threading
import time
from urllib import request, error

log = logging.getLogger("pulse")


class OllamaProvider:
    def __init__(
        self,
        url: str = "http://localhost:11434",
        model: str = "mistral",
        num_ctx: int = 8192,
        keep_alive: str = "30m",
    ):
        self.url        = url.rstrip("/")
        self.model      = model
        self.num_ctx    = num_ctx    # Taille du contexte — réduit la RAM (KV cache)
        self.keep_alive = keep_alive # Durée avant déchargement du modèle
        self._models_lock = threading.Lock()
        self._models_cache = None
        self._models_cache_at = 0.0
        self._models_error_at = 0.0
        self._models_cache_ttl = 30.0
        self._models_error_backoff = 10.0
        self._health_lock = threading.Lock()
        self._last_success_at = 0.0
        self._last_failure_at = 0.0
        self._health_ttl = 120.0

    @property
    def is_online(self) -> bool:
        """
        True uniquement si Ollama a répondu lors du dernier fetch réel.
        False si on sert du cache stale (Ollama down mais cache présent).
        """
        with self._models_lock:
            return self._models_error_at == 0.0 and self._models_cache is not None

    @property
    def is_operational(self) -> bool:
        """
        True si un appel utile au provider a réussi récemment.
        N'est pas invalidé par un échec de listing des modèles : /api/tags
        peut échouer alors que le modèle configuré répond encore.
        """
        with self._health_lock:
            if self._last_success_at <= 0.0:
                return False
            if self._last_failure_at > self._last_success_at:
                return False
            return time.monotonic() - self._last_success_at < self._health_ttl

    def _mark_success(self) -> None:
        with self._health_lock:
            self._last_success_at = time.monotonic()

    def _mark_failure(self) -> None:
        with self._health_lock:
            self._last_failure_at = time.monotonic()

    def warmup(self) -> bool:
        """Pré-charge le modèle. Retourne True si Ollama a répondu."""
        return self._keep_alive_request(self.keep_alive)

    def unload(self) -> bool:
        """Décharge le modèle immédiatement. Retourne True si Ollama a répondu."""
        return self._keep_alive_request("0")

    def _keep_alive_request(self, keep_alive: str) -> bool:
        """Envoie une requête vide pour contrôler le cycle de vie du modèle."""
        payload = {
            "model":      self.model,
            "prompt":     "",
            "keep_alive": keep_alive,
        }
        req = request.Request(
            self.url + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as _:
                self._mark_success()
                return True
        except Exception as exc:
            self._mark_failure()
            log.warning("Ollama keep_alive(%s) échoué : %s", keep_alive, exc)
            return False

    def stream(self, prompt: str, system: str = "", max_tokens: int = 600):
        """
        Génère la réponse token par token via l'API Ollama streaming.
        - keep_alive : contrôle la durée de chargement en mémoire
        - num_ctx    : taille du contexte (impact direct sur la RAM/KV cache)
        - timeout    : 300s pour laisser le temps aux questions complexes
        """
        payload = {
            "model":      self.model,
            "stream":     True,
            "prompt":     prompt,
            "system":     system,
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": max_tokens,
                "num_ctx":     self.num_ctx,
                "temperature": 0.3,
                "top_p":       0.95,
                "top_k":       64,
            },
        }

        req = request.Request(
            self.url + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        saw_success = False
        try:
            with request.urlopen(req, timeout=300) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = chunk.get("response", "")
                    # Détection d'une erreur Ollama dans le flux
                    if "error" in chunk:
                        self._mark_failure()
                        raise RuntimeError(f"Ollama error: {chunk['error']}")
                    if token:
                        if not saw_success:
                            self._mark_success()
                            saw_success = True
                        yield token
                    if chunk.get("done"):
                        if not saw_success:
                            self._mark_success()
                        break
        except error.URLError as exc:
            self._mark_failure()
            raise RuntimeError("Ollama unavailable") from exc

    def complete(self, prompt: str, system: str = "", max_tokens: int = 160) -> str:
        """
        Réponse complète — implémenté par-dessus stream() pour éviter
        le bloc `stream: False` qui attend la réponse entière (thinking
        compris) avant de rendre la main. Avec stream=True, les tokens
        arrivent au fil de l'eau et le timeout est moins agressif.
        """
        tokens = []
        for token in self.stream(prompt=prompt, system=system, max_tokens=max_tokens):
            tokens.append(token)
        text = "".join(tokens).strip()
        if not text:
            raise RuntimeError("Ollama returned an empty response")
        return text

    def list_models(self) -> list:
        now = time.monotonic()
        with self._models_lock:
            if (
                self._models_cache is not None
                and now - self._models_cache_at < self._models_cache_ttl
            ):
                return list(self._models_cache)
            if self._models_error_at and now - self._models_error_at < self._models_error_backoff:
                if self._models_cache is not None:
                    return list(self._models_cache)
                raise RuntimeError("Ollama unavailable")

        req = request.Request(
            self.url + "/api/tags",
            headers={"Content-Type": "application/json"},
            method="GET",
        )

        try:
            with request.urlopen(req, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            with self._models_lock:
                self._models_error_at = now
                stale = None if self._models_cache is None else list(self._models_cache)
            if stale is not None:
                return stale
            raise RuntimeError("Ollama unavailable") from exc

        models = []
        for item in body.get("models", []):
            name = item.get("name")
            if name:
                models.append(name)
        with self._models_lock:
            self._models_cache = list(models)
            self._models_cache_at = now
            self._models_error_at = 0.0
        self._mark_success()
        return models
