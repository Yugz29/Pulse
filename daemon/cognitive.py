"""
cognitive.py — Couche de raisonnement de Pulse.

Construit le system prompt contextuel et expose ask() / ask_stream()
pour traiter les intentions utilisateur via le LLM.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Generator, Optional


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_TEMPLATE = """\
Tu es Pulse, un agent ambiant macOS qui observe le travail du développeur \
et répond à ses questions en français.

Tu as accès au contexte de la session courante : fichiers ouverts, projet actif, \
apps utilisées, signaux de focus et de friction, et ta mémoire persistante.

Règles :
- Réponds toujours en français, de façon concise et directe.
- Appuie-toi sur le contexte fourni quand c'est pertinent.
- Si tu ne sais pas, dis-le clairement plutôt que d'inventer.
- Texte brut uniquement : pas de markdown. Pas d'astérisques, pas de dièses \
en début de ligne, pas de backticks. Utilise des tirets simples pour les listes.

{context_block}
"""


def build_system_prompt(context_snapshot: str, frozen_memory: str = "") -> str:
    """
    Assemble le system prompt avec le contexte courant et la mémoire figée.
    Le contexte est tronqué à 3000 caractères pour rester dans les limites du modèle.
    """
    parts = []

    if frozen_memory.strip():
        parts.append(frozen_memory.strip())

    if context_snapshot.strip():
        ctx = context_snapshot.strip()
        if len(ctx) > 3_000:
            ctx = ctx[:3_000] + "\n[… contexte tronqué]"
        parts.append(ctx)

    context_block = "\n\n".join(parts) if parts else "(aucun contexte disponible)"
    return _SYSTEM_TEMPLATE.format(context_block=context_block)


# ── ask() — réponse complète ──────────────────────────────────────────────────

def ask(
    message: str,
    llm: Any,
    context_snapshot: str = "",
    frozen_memory: str = "",
    max_tokens: int = 600,
) -> dict:
    """
    Traite un message utilisateur et retourne une réponse complète.

    Retourne :
        {"ok": True,  "response": <str>, "model": <str>}
        {"ok": False, "error": <str>,    "code": <str>}
    """
    if not message.strip():
        return {"ok": False, "error": "Message vide", "code": "empty_message"}

    if llm is None:
        return {"ok": False, "error": "LLM non disponible", "code": "no_llm"}

    system = build_system_prompt(context_snapshot, frozen_memory)

    try:
        response = llm.complete(
            prompt=message.strip(),
            system=system,
            max_tokens=max_tokens,
        )
        return {
            "ok":       True,
            "response": response,
            "model":    getattr(llm, "get_model", lambda: "unknown")(),
        }
    except RuntimeError as exc:
        msg = str(exc)
        if "unavailable" in msg.lower():
            return {"ok": False, "error": "Ollama non disponible", "code": "llm_offline"}
        return {"ok": False, "error": msg, "code": "llm_error"}
    except Exception as exc:
        return {"ok": False, "error": f"Erreur inattendue : {exc}", "code": "unknown"}


# ── ask_stream() — réponse en streaming (SSE) ────────────────────────────────

def ask_stream(
    message: str,
    llm: Any,
    context_snapshot: str = "",
    frozen_memory: str = "",
    max_tokens: int = 600,
) -> Generator[str, None, None]:
    """
    Génère la réponse token par token au format SSE.

    Chaque ligne émise est un événement SSE :
        data: {"token": "...", "done": false}\n\n
        data: {"token": "",   "done": true,  "model": "..."}\n\n

    En cas d'erreur :
        data: {"error": "...", "code": "..."}\n\n
    """
    if not message.strip():
        yield _sse({"error": "Message vide", "code": "empty_message"})
        return

    if llm is None:
        yield _sse({"error": "LLM non disponible", "code": "no_llm"})
        return

    system = build_system_prompt(context_snapshot, frozen_memory)
    provider = getattr(llm, "default", llm)  # unwrap LLMRouter → OllamaProvider

    try:
        for token in provider.stream(
            prompt=message.strip(),
            system=system,
            max_tokens=max_tokens,
        ):
            yield _sse({"token": token, "done": False})

        model = getattr(llm, "get_model", lambda: "unknown")()
        yield _sse({"token": "", "done": True, "model": model})

    except RuntimeError as exc:
        msg = str(exc)
        code = "llm_offline" if "unavailable" in msg.lower() else "llm_error"
        yield _sse({"error": msg, "code": code})
    except Exception as exc:
        yield _sse({"error": f"Erreur inattendue : {exc}", "code": "unknown"})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
