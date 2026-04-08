import json
from urllib import request, error


class OllamaProvider:
    def __init__(self, url: str = "http://localhost:11434", model: str = "mistral"):
        self.url = url.rstrip("/")
        self.model = model

    def complete(self, prompt: str, system: str = "", max_tokens: int = 160) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "prompt": prompt,
            "system": system,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.2,
            },
        }

        req = request.Request(
            self.url + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=8) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise RuntimeError("Ollama unavailable") from exc

        text = (body.get("response") or "").strip()
        if not text:
            raise RuntimeError("Ollama returned an empty response")
        return text

    def list_models(self) -> list:
        req = request.Request(
            self.url + "/api/tags",
            headers={"Content-Type": "application/json"},
            method="GET",
        )

        try:
            with request.urlopen(req, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise RuntimeError("Ollama unavailable") from exc

        models = []
        for item in body.get("models", []):
            name = item.get("name")
            if name:
                models.append(name)
        return models
