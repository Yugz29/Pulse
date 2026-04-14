"""
OllamaProvider — client HTTP pour l'API Ollama locale.

Utilise /api/chat (format messages) pour stream() et complete(),
ce qui permet le tool calling natif en phase 2.
Garde /api/generate uniquement pour les appels lifecycle (warmup/unload).

Format /api/chat streaming :
  → {"model": ..., "messages": [...], "stream": true, "options": {...}}
  ← {"message": {"role": "assistant", "content": "token"}, "done": false}
  ← {"message": {"role": "assistant", "content": ""}, "done": true, "done_reason": "stop"}
"""

import json
import logging
import threading
import time
from urllib import request, error

log = logging.getLogger("pulse")
_DEBUG_CHUNK_PREVIEW = 280
_INVALID_FINAL_CODE = "invalid_final_response"


def _invalid_final_response(reason: str) -> RuntimeError:
    return RuntimeError(f"{_INVALID_FINAL_CODE}: {reason}")


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

    # ── Santé ─────────────────────────────────────────────────────────────────

    @property
    def is_online(self) -> bool:
        with self._models_lock:
            return self._models_error_at == 0.0 and self._models_cache is not None

    @property
    def is_operational(self) -> bool:
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

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def warmup(self) -> bool:
        """Pré-charge le modèle en mémoire. Retourne True si Ollama a répondu."""
        return self._keep_alive_request(self.keep_alive)

    def unload(self) -> bool:
        """Décharge le modèle immédiatement. Retourne True si Ollama a répondu."""
        return self._keep_alive_request("0")

    def _keep_alive_request(self, keep_alive: str) -> bool:
        """
        Envoie une requête vide via /api/generate pour contrôler le cycle de vie.
        /api/generate est conservé ici car /api/chat ne supporte pas keep_alive seul.
        """
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

    # ── Génération via /api/chat ───────────────────────────────────────────────

    def chat_with_tools(
        self,
        messages: list,
        tools: list,
        max_tokens: int = 600,
    ) -> dict:
        """
        Appel non-streaming à /api/chat avec tool calling.
        Retourne le dict complet de la réponse Ollama.

        Si le modèle veut appeler un outil, la réponse contient :
          response["message"]["tool_calls"] = [{"function": {"name": ..., "arguments": {...}}}]

        Si le modèle répond directement :
          response["message"]["content"] = "..."
        """
        payload = {
            "model":      self.model,
            "stream":     False,
            "messages":   messages,
            "tools":      tools,
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
            self.url + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
                if "error" in body:
                    self._mark_failure()
                    log.warning("Ollama chat_with_tools error model=%s error=%s", self.model, body["error"])
                    raise RuntimeError(f"Ollama error: {body['error']}")
                self._mark_success()
                return body
        except error.URLError as exc:
            self._mark_failure()
            log.warning("Ollama chat_with_tools indisponible model=%s error=%s", self.model, exc)
            raise RuntimeError("Ollama unavailable") from exc

    def stream_messages(self, messages: list, max_tokens: int = 600):
        """
        Streaming /api/chat sur un historique complet de messages.
        Utilisé pour la réponse finale après exécution des outils.

        Yields: str (tokens individuels)
        """
        payload = {
            "model":      self.model,
            "stream":     True,
            "messages":   messages,
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
            self.url + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        saw_success = False
        saw_reasoning = False
        raw_chunk_count = 0
        try:
            with request.urlopen(req, timeout=300) as response:
                for raw_line in response:
                    raw_chunk_count += 1
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in chunk:
                        self._mark_failure()
                        raise RuntimeError(f"Ollama error: {chunk['error']}")
                    msg   = chunk.get("message") or {}
                    token = msg.get("content") or ""
                    if isinstance(msg, dict) and (msg.get("thinking") or msg.get("reasoning")):
                        saw_reasoning = True
                    if not token and raw_chunk_count <= 5:
                        log.debug(
                            "Ollama /api/chat chunk sans content exploitable [%d]: %s",
                            raw_chunk_count,
                            _summarize_chunk_for_debug(chunk, line),
                        )
                    if token:
                        if not saw_success:
                            self._mark_success()
                            saw_success = True
                        yield token
                    if chunk.get("done"):
                        if not saw_success:
                            log.warning(
                                "Ollama /api/chat terminé sans token visible: %s",
                                _summarize_chunk_for_debug(chunk, line),
                            )
                            self._mark_failure()
                            reason = "reasoning_without_final" if saw_reasoning else "empty_final"
                            raise _invalid_final_response(reason)
                        break
        except error.URLError as exc:
            self._mark_failure()
            log.warning("Ollama stream_messages indisponible model=%s error=%s", self.model, exc)
            raise RuntimeError("Ollama unavailable") from exc

    def stream(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 600,
        think: bool | None = None,
    ):
        """
        Génère la réponse token par token via /api/chat (streaming).

        Utilise le format messages plutôt que prompt/system de /api/generate.
        Prêt pour le tool calling natif en phase 2 (champ tools à ajouter).

        Yields: str (tokens individuels)
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":      self.model,
            "stream":     True,
            "messages":   messages,
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": max_tokens,
                "num_ctx":     self.num_ctx,
                "temperature": 0.3,
                "top_p":       0.95,
                "top_k":       64,
            },
        }
        if think is not None:
            payload["think"] = think

        req = request.Request(
            self.url + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        saw_success = False
        saw_reasoning = False
        raw_chunk_count = 0
        try:
            with request.urlopen(req, timeout=300) as response:
                for raw_line in response:
                    raw_chunk_count += 1
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if "error" in chunk:
                        self._mark_failure()
                        raise RuntimeError(f"Ollama error: {chunk['error']}")

                    # /api/chat : le token est dans chunk["message"]["content"]
                    # (peut être None ou absent si tool_call en phase 2)
                    msg   = chunk.get("message") or {}
                    token = msg.get("content") or ""
                    if isinstance(msg, dict) and (msg.get("thinking") or msg.get("reasoning")):
                        saw_reasoning = True
                    if not token and raw_chunk_count <= 5:
                        log.debug(
                            "Ollama stream chunk sans content exploitable [%d]: %s",
                            raw_chunk_count,
                            _summarize_chunk_for_debug(chunk, line),
                        )

                    if token:
                        if not saw_success:
                            self._mark_success()
                            saw_success = True
                        yield token

                    if chunk.get("done"):
                        if not saw_success:
                            log.warning(
                                "Ollama stream terminé sans token visible: %s",
                                _summarize_chunk_for_debug(chunk, line),
                            )
                            self._mark_failure()
                            reason = "reasoning_without_final" if saw_reasoning else "empty_final"
                            raise _invalid_final_response(reason)
                        break

        except error.URLError as exc:
            self._mark_failure()
            log.warning("Ollama stream indisponible model=%s error=%s", self.model, exc)
            raise RuntimeError("Ollama unavailable") from exc

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 160,
        think: bool | None = None,
    ) -> str:
        """
        Réponse complète — construit par-dessus stream() pour réutiliser
        le parsing /api/chat et bénéficier du même timeout.
        """
        tokens = []
        for token in self.stream(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            think=think,
        ):
            tokens.append(token)
        text = "".join(tokens).strip()
        if not text:
            log.warning("Ollama complete sans contenu final exploitable model=%s", self.model)
            raise _invalid_final_response("empty_final")
        return text

    # ── Listing des modèles ───────────────────────────────────────────────────

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


def _summarize_chunk_for_debug(chunk: dict, raw_line: str) -> str:
    """
    Résume un chunk Ollama pour diagnostic sans noyer les logs.
    Utile pour les modèles qui renvoient du reasoning/thinking sans texte final.
    """
    try:
        msg = chunk.get("message") or {}
        summary = {
            "keys": sorted(chunk.keys()),
            "done": chunk.get("done"),
            "done_reason": chunk.get("done_reason"),
            "message_keys": sorted(msg.keys()) if isinstance(msg, dict) else [],
            "role": msg.get("role") if isinstance(msg, dict) else None,
            "content_len": len(msg.get("content") or "") if isinstance(msg, dict) else 0,
        }
        if isinstance(msg, dict):
            for key in ("thinking", "reasoning", "tool_calls"):
                if key in msg:
                    value = msg.get(key)
                    if isinstance(value, str):
                        summary[f"{key}_len"] = len(value)
                    elif isinstance(value, list):
                        summary[f"{key}_count"] = len(value)
                    else:
                        summary[f"{key}_type"] = type(value).__name__
        return json.dumps(summary, ensure_ascii=False)
    except Exception:
        preview = raw_line[:_DEBUG_CHUNK_PREVIEW]
        if len(raw_line) > _DEBUG_CHUNK_PREVIEW:
            preview += "…"
        return preview
