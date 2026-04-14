"""
cognitive.py — Couche de raisonnement de Pulse.

Construit le system prompt contextuel et expose ask() / ask_stream()
pour traiter les intentions utilisateur via le LLM.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Generator, Optional

# Nombre maximum d'itérations dans la boucle agentique.
# Empêche les boucles infinies si le modèle continue d'appeler des outils.
_MAX_TOOL_ITERATIONS = 5
_INVALID_FINAL_CODE = "invalid_final_response"
MAX_SYSTEM_CONTEXT_CHARS = 6000
_CONTEXT_TRUNCATION_SUFFIX = "\n[… contexte tronqué …]"
log = logging.getLogger("pulse")


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_TEMPLATE = """\
Tu es Pulse, un agent ambiant macOS qui observe le travail du développeur \
et répond à ses questions en français.

Tu as accès au contexte de la session courante : fichiers ouverts, projet actif, \
apps utilisées, signaux de focus et de friction, et ta mémoire persistante.

Règles générales :
- Réponds toujours en français, de façon concise et directe.
- Appuie-toi sur le contexte fourni quand c'est pertinent.
- Si tu ne sais pas, dis-le clairement plutôt que d'inventer.
- Texte brut uniquement : pas de markdown. Pas d'astérisques, pas de dièses \
en début de ligne, pas de backticks. Utilise des tirets simples pour les listes.

Règles pour les outils :
- Utilise les outils disponibles dès que la question porte sur le code, les fichiers \
ou le risque du projet. N'attends pas un contexte parfait.
- Si 'Racine projet' est inconnue mais que le nom du projet est visible, \
passe le nom du projet directement à l'outil (ex: score_project(project_path='Pulse')). \
L'outil sait résoudre les noms de projets.
- Préfère score_project à score_file quand la question porte sur un projet entier.
- Un seul appel outil suffit la plupart du temps. Ne cherche pas à faire plusieurs \
appels si le premier résultat suffit à répondre.
- Quand un outil de scoring renvoie un score ou un label, respecte-le. Ne reformule \
pas "high" ou "critical" comme "stable".
- score_project est un classement relatif à l'intérieur du projet. Présente-le comme \
"les zones les plus risquées du projet", pas comme une preuve que tout est instable.
- score_file est une évaluation absolue du fichier. Si l'utilisateur compare score_project \
et score_file, explique explicitement la différence entre classement relatif et score absolu.

{context_block}
"""


def build_system_prompt(context_snapshot: str, frozen_memory: str = "") -> str:
    """
    Assemble le system prompt.
    - frozen_memory : mémoire persistante (injectée une seule fois)
    - context_snapshot : contexte session minimal (projet, fichier, signaux)

    Ordre : mémoire d'abord (stable, favorise le prefix cache),
    contexte ensuite (change à chaque appel).
    """
    context_block = _bounded_context_block(context_snapshot, frozen_memory)
    return _SYSTEM_TEMPLATE.format(context_block=context_block)


def _normalize_history(history: Optional[list[dict[str, Any]]] = None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            normalized.append({"role": role, "content": content})
    return normalized


def _bounded_context_block(context_snapshot: str, frozen_memory: str = "") -> str:
    frozen = frozen_memory.strip()
    snapshot = context_snapshot.strip()
    if not frozen and not snapshot:
        return "(aucun contexte disponible)"

    original_frozen_len = len(frozen)
    original_snapshot_len = len(snapshot)
    truncated = False

    if frozen:
        if len(frozen) > MAX_SYSTEM_CONTEXT_CHARS:
            frozen = _truncate_context_text(frozen, MAX_SYSTEM_CONTEXT_CHARS)
            snapshot = ""
            truncated = True
        else:
            remaining = MAX_SYSTEM_CONTEXT_CHARS - len(frozen)
            if snapshot:
                separator = "\n\n"
                if remaining > len(separator):
                    snapshot_budget = remaining - len(separator)
                    bounded_snapshot = _truncate_context_text(snapshot, snapshot_budget)
                    truncated = bounded_snapshot != snapshot
                    snapshot = bounded_snapshot
                else:
                    truncated = True
                    snapshot = ""
    elif snapshot:
        bounded_snapshot = _truncate_context_text(snapshot, MAX_SYSTEM_CONTEXT_CHARS)
        truncated = bounded_snapshot != snapshot
        snapshot = bounded_snapshot

    if truncated:
        log.warning(
            "llm_context_truncated budget_chars=%d frozen_len=%d snapshot_len=%d",
            MAX_SYSTEM_CONTEXT_CHARS,
            original_frozen_len,
            original_snapshot_len,
        )

    parts = []
    if frozen:
        parts.append(frozen)
    if snapshot:
        parts.append(snapshot)
    return "\n\n".join(parts) if parts else "(aucun contexte disponible)"


def _truncate_context_text(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
    if budget <= len(_CONTEXT_TRUNCATION_SUFFIX):
        return _CONTEXT_TRUNCATION_SUFFIX[:budget]
    return text[: budget - len(_CONTEXT_TRUNCATION_SUFFIX)] + _CONTEXT_TRUNCATION_SUFFIX


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
    started_at = time.monotonic()
    model = getattr(llm, "get_model", lambda: "unknown")() if llm is not None else "unknown"
    if not message.strip():
        _log_llm_terminal(
            request_kind="ask",
            status="invalid",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="empty_message",
        )
        return {"ok": False, "error": "Message vide", "code": "empty_message"}

    if llm is None:
        _log_llm_terminal(
            request_kind="ask",
            status="error",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="no_llm",
        )
        return {"ok": False, "error": "LLM non disponible", "code": "no_llm"}

    system = build_system_prompt(context_snapshot, frozen_memory)

    try:
        response = llm.complete(
            prompt=message.strip(),
            system=system,
            max_tokens=max_tokens,
        )
        _log_llm_terminal(
            request_kind="ask",
            status="success",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
        )
        return {
            "ok":       True,
            "response": response,
            "model":    model,
        }
    except RuntimeError as exc:
        msg = str(exc)
        if _is_invalid_final_error(msg):
            _log_llm_terminal(
                request_kind="ask",
                status="invalid",
                model=model,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                reason="invalid_final_response",
            )
            return {"ok": False, "error": "Réponse finale invalide", "code": "invalid_response"}
        if "unavailable" in msg.lower():
            _log_llm_terminal(
                request_kind="ask",
                status="error",
                model=model,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                reason="llm_offline",
            )
            return {"ok": False, "error": "Ollama non disponible", "code": "llm_offline"}
        _log_llm_terminal(
            request_kind="ask",
            status="error",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="llm_error",
        )
        return {"ok": False, "error": msg, "code": "llm_error"}
    except Exception as exc:
        _log_llm_terminal(
            request_kind="ask",
            status="error",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="unknown",
        )
        return {"ok": False, "error": f"Erreur inattendue : {exc}", "code": "unknown"}


# ── ask_stream() — réponse en streaming (SSE) ────────────────────────────────

def ask_stream(
    message: str,
    llm: Any,
    context_snapshot: str = "",
    frozen_memory: str = "",
    history: Optional[list[dict[str, Any]]] = None,
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
    started_at = time.monotonic()
    model = getattr(llm, "get_model", lambda: "unknown")() if llm is not None else "unknown"
    if not message.strip():
        _log_llm_terminal(
            request_kind="ask_stream",
            status="invalid",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="empty_message",
        )
        yield _sse({"error": "Message vide", "code": "empty_message"})
        return

    if llm is None:
        _log_llm_terminal(
            request_kind="ask_stream",
            status="error",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="no_llm",
        )
        yield _sse({"error": "LLM non disponible", "code": "no_llm"})
        return

    system = build_system_prompt(context_snapshot, frozen_memory)
    provider = getattr(llm, "default", llm)  # unwrap LLMRouter → OllamaProvider
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(_normalize_history(history))
    messages.append({"role": "user", "content": message.strip()})

    saw_token = False
    try:
        for token in provider.stream_messages(
            messages=messages,
            max_tokens=max_tokens,
        ):
            saw_token = True
            yield _sse({"token": token, "done": False})

        yield _sse({"token": "", "done": True, "model": model})
        _log_llm_terminal(
            request_kind="ask_stream",
            status="success",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
        )

    except RuntimeError as exc:
        msg = str(exc)
        if _is_invalid_final_error(msg):
            state = "degraded" if saw_token else "invalid"
            code = "degraded_response" if saw_token else "invalid_response"
            error = "Réponse incomplète." if saw_token else "Réponse finale invalide."
            _log_llm_terminal(
                request_kind="ask_stream",
                status=state,
                model=model,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                reason="stream_interrupted" if saw_token else "invalid_final_response",
            )
            yield _sse({"state": state, "error": error, "code": code})
            return
        if saw_token:
            _log_llm_terminal(
                request_kind="ask_stream",
                status="degraded",
                model=model,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                reason="stream_interrupted",
            )
            yield _sse({"state": "degraded", "error": "Réponse incomplète.", "code": "degraded_response"})
            return
        code = "llm_offline" if "unavailable" in msg.lower() else "llm_error"
        _log_llm_terminal(
            request_kind="ask_stream",
            status="error",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason=code,
        )
        yield _sse({"error": msg, "code": code})
    except Exception as exc:
        if saw_token:
            _log_llm_terminal(
                request_kind="ask_stream",
                status="degraded",
                model=model,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                reason="stream_interrupted",
            )
            yield _sse({"state": "degraded", "error": "Réponse incomplète.", "code": "degraded_response"})
            return
        _log_llm_terminal(
            request_kind="ask_stream",
            status="error",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="unknown",
        )
        yield _sse({"error": f"Erreur inattendue : {exc}", "code": "unknown"})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _is_invalid_final_error(message: str) -> bool:
    return _INVALID_FINAL_CODE in (message or "")


def _log_llm_terminal(
    *,
    request_kind: str,
    status: str,
    model: str,
    latency_ms: int,
    reason: str | None = None,
) -> None:
    message = (
        f"llm_request_terminal request_kind={request_kind} status={status} "
        f"provider=ollama model={model} latency_ms={latency_ms}"
    )
    if reason:
        message += f" reason={reason}"
    if status == "success":
        log.info(message)
    elif status in {"invalid", "degraded"}:
        log.warning(message)
    else:
        log.error(message)


# ── ask_stream_with_tools() — boucle agentique + SSE ─────────────────────

def ask_stream_with_tools(
    message: str,
    llm: Any,
    tools: list,
    tool_map: dict,
    context_snapshot: str = "",
    frozen_memory: str = "",
    history: Optional[list[dict[str, Any]]] = None,
    max_tokens: int = 600,
) -> Generator[str, None, None]:
    """
    Boucle agentique avec tool calling natif Ollama.

    Flux SSE émis :
      data: {"tool_call": "score_file", "status": "running"}\n\n   ← outil en cours
      data: {"token": "...", "done": false}\n\n              ← réponse finale canonique
      data: {"token": "",   "done": true, "model": "..."}\n\n  ← fin
      data: {"state": "invalid", "error": "...", "code": "..."}\n\n
      data: {"error": "...", "code": "..."}\n\n             ← erreur

    Algorithme :
      1. Appel non-streaming /api/chat avec outils (décision modèle)
      2. Si tool_calls → exécute chaque outil, ajoute le résultat aux messages, reboucle
      3. Si pas de tool_calls → le contenu assistant courant devient la réponse finale canonique
      4. Aucun second appel de génération n'est lancé pour "reformuler" la réponse
      5. Limité à _MAX_TOOL_ITERATIONS itérations
    """
    started_at = time.monotonic()
    model = getattr(llm, "get_model", lambda: "unknown")() if llm is not None else "unknown"
    if not message.strip():
        _log_llm_terminal(
            request_kind="ask_stream_with_tools",
            status="invalid",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="empty_message",
        )
        yield _sse({"error": "Message vide", "code": "empty_message"})
        return

    if llm is None:
        _log_llm_terminal(
            request_kind="ask_stream_with_tools",
            status="error",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="no_llm",
        )
        yield _sse({"error": "LLM non disponible", "code": "no_llm"})
        return

    system = build_system_prompt(context_snapshot, frozen_memory)
    provider = getattr(llm, "default", llm)  # unwrap LLMRouter → OllamaProvider

    # Historique de conversation (système + utilisateur + résultats outils)
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(_normalize_history(history))
    messages.append({"role": "user", "content": message.strip()})

    # Heartbeat immédiat — évite le timeout Swift en attendant la première décision LLM.
    # Sans ça, le client attend en silence pendant chat_with_tools() et coupe la connexion.
    yield _sse({"status": "thinking"})

    try:
        for _ in range(_MAX_TOOL_ITERATIONS):
            # ─ Décision : outil ou réponse directe ?
            response = provider.chat_with_tools(
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )
            msg        = response.get("message") or {}
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                # Pas d'outil demandé — la réponse courante est la seule réponse
                # finale canonique. On n'effectue pas de seconde génération.
                content = (msg.get("content") or "").strip()
                if not content:
                    _log_llm_terminal(
                        request_kind="ask_stream_with_tools",
                        status="invalid",
                        model=model,
                        latency_ms=int((time.monotonic() - started_at) * 1000),
                        reason="invalid_final_response",
                    )
                    yield _sse({"state": "invalid", "error": "Réponse finale invalide.", "code": "invalid_response"})
                    return
                yield _sse({"token": content, "done": False})
                yield _sse({"token": "", "done": True, "model": model})
                _log_llm_terminal(
                    request_kind="ask_stream_with_tools",
                    status="success",
                    model=model,
                    latency_ms=int((time.monotonic() - started_at) * 1000),
                )
                return

            # ─ Exécution des outils demandés
            # Ajoute la décision du modèle à l'historique
            messages.append({
                "role":       "assistant",
                "content":    msg.get("content") or "",
                "tool_calls": tool_calls,
            })

            for call in tool_calls:
                fn   = (call.get("function") or {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}

                # Signalé au client : outil en cours d'exécution
                yield _sse({"tool_call": name, "status": "running"})

                tool_fn = tool_map.get(name)
                if tool_fn:
                    try:
                        result = tool_fn(**args)
                    except Exception as exc:
                        result = f"Erreur lors de l'exécution de {name}: {exc}"
                else:
                    result = f"Outil inconnu: {name}"

                messages.append({
                    "role":      "tool",
                    "tool_name": name,
                    "content":   str(result),
                })

        # Trop d'itérations sans réponse finale canonique identifiable.
        _log_llm_terminal(
            request_kind="ask_stream_with_tools",
            status="invalid",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="invalid_final_response",
        )
        yield _sse({"state": "invalid", "error": "Réponse finale invalide.", "code": "invalid_response"})
        return

    except RuntimeError as exc:
        msg_str = str(exc)
        if _is_invalid_final_error(msg_str):
            _log_llm_terminal(
                request_kind="ask_stream_with_tools",
                status="invalid",
                model=model,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                reason="invalid_final_response",
            )
            yield _sse({"state": "invalid", "error": "Réponse finale invalide.", "code": "invalid_response"})
            return
        code = "llm_offline" if "unavailable" in msg_str.lower() else "llm_error"
        _log_llm_terminal(
            request_kind="ask_stream_with_tools",
            status="error",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason=code,
        )
        yield _sse({"error": msg_str, "code": code})
    except Exception as exc:
        _log_llm_terminal(
            request_kind="ask_stream_with_tools",
            status="error",
            model=model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            reason="unknown",
        )
        yield _sse({"error": f"Erreur inattendue : {exc}", "code": "unknown"})
