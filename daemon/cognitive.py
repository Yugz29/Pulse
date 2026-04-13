"""
cognitive.py — Couche de raisonnement de Pulse.

Construit le system prompt contextuel et expose ask() / ask_stream()
pour traiter les intentions utilisateur via le LLM.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Generator, Optional

# Nombre maximum d'itérations dans la boucle agentique.
# Empêche les boucles infinies si le modèle continue d'appeler des outils.
_MAX_TOOL_ITERATIONS = 5


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
    parts = []

    if frozen_memory.strip():
        parts.append(frozen_memory.strip())

    if context_snapshot.strip():
        parts.append(context_snapshot.strip())

    context_block = "\n\n".join(parts) if parts else "(aucun contexte disponible)"
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
    if not message.strip():
        yield _sse({"error": "Message vide", "code": "empty_message"})
        return

    if llm is None:
        yield _sse({"error": "LLM non disponible", "code": "no_llm"})
        return

    system = build_system_prompt(context_snapshot, frozen_memory)
    provider = getattr(llm, "default", llm)  # unwrap LLMRouter → OllamaProvider
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(_normalize_history(history))
    messages.append({"role": "user", "content": message.strip()})

    try:
        for token in provider.stream_messages(
            messages=messages,
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
      data: {"token": "...", "done": false}\n\n              ← tokens de la réponse
      data: {"token": "",   "done": true, "model": "..."}\n\n  ← fin
      data: {"error": "...", "code": "..."}\n\n             ← erreur

    Algorithme :
      1. Appel non-streaming /api/chat avec outils (décision modèle)
      2. Si tool_calls → exécute chaque outil, ajoute le résultat aux messages, reboucle
      3. Si réponse texte → streaming /api/chat sur l'historique complet
      4. Limité à _MAX_TOOL_ITERATIONS itérations
    """
    if not message.strip():
        yield _sse({"error": "Message vide", "code": "empty_message"})
        return

    if llm is None:
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
                # Pas d'outil demandé — réponse directe disponible dans msg["content"]
                # On préfère streamer via stream_messages() pour une meilleure UX
                # (les tokens arrivent progressivement au lieu d'un bloc)
                messages.append({"role": "assistant", "content": msg.get("content", "")})
                break

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

        # ─ Réponse finale en streaming sur l'historique complet
        # (inclut tous les résultats d'outils comme contexte)
        saw_token = False
        for token in provider.stream_messages(
            messages=messages,
            max_tokens=max_tokens,
        ):
            saw_token = True
            yield _sse({"token": token, "done": False})

        # Si stream_messages n'a rien produit (contenu déjà dans la décision),
        # on émet le contenu accumulé dans le dernier message assistant.
        if not saw_token:
            last_assistant = next(
                (m for m in reversed(messages) if m.get("role") == "assistant"),
                None,
            )
            content = (last_assistant or {}).get("content", "")
            if content:
                yield _sse({"token": content, "done": False})

        model = getattr(llm, "get_model", lambda: "unknown")()
        yield _sse({"token": "", "done": True, "model": model})

    except RuntimeError as exc:
        msg_str = str(exc)
        code = "llm_offline" if "unavailable" in msg_str.lower() else "llm_error"
        yield _sse({"error": msg_str, "code": code})
    except Exception as exc:
        yield _sse({"error": f"Erreur inattendue : {exc}", "code": "unknown"})
