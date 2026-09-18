"""Lecture tolérante et incrémentale du transcript live d'une session Claude Code.

Étape 1 bis du mode continu (``docs/decisions/2026-09-17-resumes-en-continu.md``,
décision du 2026-09-18) : le bloc « Session en cours » montre, pour chaque
session Claude Code vivante, ce que son transcript dit de l'agent — ses
commandes, son dernier test, ses échecs bruts, les fichiers qu'il a écrits.
Rien n'entre dans ``trace.db`` (rétention du 2026-08-30) ; rien ne passe par
un modèle ; le résumé de nuit et ``/context`` ne voient rien de plus.

Ce qui sort d'ici est borné à ce que le shell interactif expose déjà : la
**commande** et la **description** de l'agent, passées par ``redact_command``
(la description, texte libre, reçoit en plus un masque ``utilisateur:secret@``) ; l'**issue** (``ok`` / ``échec`` / ``interrompue``) ;
l'**heure** ; les **chemins** des fichiers édités. **Jamais** ``stdout``,
``stderr``, le prompt, ni le motif d'un ``Exit code``.

Le transcript est un JSONL en ajout seul, format non documenté de Claude
Code : la lecture est tolérante (une ligne illisible ou inconnue est
ignorée), incrémentale (on repart de l'offset du dernier rendu, un fichier
qui a rétréci est relu du début), et la dernière ligne sans retour à la
ligne — en cours d'écriture — est laissée pour le rendu suivant. Les entrées
de sous-agent (``isSidechain``) sont ignorées.
"""

from __future__ import annotations

import json
import os
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analysis.terminal import is_test_command
from .ingest import redact_command

MAX_COMMANDS = 10
MAX_FAILURES = 8
MAX_FILES = 8
# Une entrée d'outil sans résultat au-delà de ce nombre d'appels suivants
# est oubliée : un résultat n'arrive jamais après tant d'autres.
MAX_PENDING = 64

OK = "ok"
FAILED = "échec"
INTERRUPTED = "interrompue"

_FILE_TOOLS = {"Edit": "modifié", "MultiEdit": "modifié", "Write": "écrit", "NotebookEdit": "modifié"}
# La description est du texte libre écrit par l'agent : en plus des motifs de
# ``redact_command`` (pensés pour une ligne de commande), on masque toute
# forme ``utilisateur:secret@hôte`` même sans schéma d'URL.
_FREE_TEXT_USERINFO = re.compile(r"(?<![\w.+-])([\w.+-]+):([^\s:@/]+)@(?=[\w.-])")


_SEGMENT_SEPARATORS = ("&&", "||", ";", "|", "\n")


def redact_description(text: str) -> str:
    return _FREE_TEXT_USERINFO.sub(r"\1:[REDACTED]@", redact_command(text))


@dataclass
class TranscriptState:
    """Ce qu'un transcript a livré jusqu'à ``offset``, à reprendre au rendu suivant."""

    offset: int = 0
    inode: int | None = None
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)
    commands: deque = field(default_factory=lambda: deque(maxlen=MAX_COMMANDS))
    failures: deque = field(default_factory=lambda: deque(maxlen=MAX_FAILURES))
    last_test: dict[str, Any] | None = None
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    command_count: int = 0
    failure_count: int = 0
    test_count: int = 0
    failed_test_count: int = 0
    skipped_lines: int = 0
    last_at: str | None = None

    def view(self) -> dict[str, Any]:
        files = sorted(self.files.values(), key=lambda f: (f["last_at"] or ""), reverse=True)
        return {
            "commands": list(self.commands),
            "command_count": self.command_count,
            "failures": list(reversed(self.failures)),
            "failure_count": self.failure_count,
            "last_test": self.last_test,
            "test_count": self.test_count,
            "failed_test_count": self.failed_test_count,
            "files": files[:MAX_FILES],
            "file_count": len(files),
            "skipped_lines": self.skipped_lines,
            "last_at": self.last_at,
        }


_STATES: dict[str, TranscriptState] = {}


def read_transcript(path: Path | str, *, states: dict[str, TranscriptState] | None = None) -> dict[str, Any] | None:
    """La vue du transcript ``path``, lue depuis le dernier appel ; ``None`` s'il est illisible."""
    cache = _STATES if states is None else states
    key = str(path)
    state = cache.get(key) or TranscriptState()
    try:
        stat = os.stat(path)
    except OSError:
        cache.pop(key, None)
        return None
    if state.inode is not None and (stat.st_ino != state.inode or stat.st_size < state.offset):
        state = TranscriptState()
    state.inode = stat.st_ino
    try:
        with open(path, "rb") as handle:
            handle.seek(state.offset)
            chunk = handle.read()
    except OSError:
        return state.view()
    consumed = _consume(state, chunk)
    state.offset += consumed
    cache[key] = state
    return state.view()


def _consume(state: TranscriptState, chunk: bytes) -> int:
    """Applique les lignes complètes de ``chunk`` ; rend le nombre d'octets consommés."""
    end = chunk.rfind(b"\n")
    if end < 0:
        return 0
    complete = chunk[: end + 1]
    for raw in complete.split(b"\n"):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            state.skipped_lines += 1
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain"):
            continue
        _apply(state, entry)
    return len(complete)


def _apply(state: TranscriptState, entry: dict[str, Any]) -> None:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return
    stamp = entry.get("timestamp") if isinstance(entry.get("timestamp"), str) else None
    kind = entry.get("type")
    if kind == "assistant":
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                _remember_use(state, block, stamp)
    elif kind == "user":
        interrupted = bool((entry.get("toolUseResult") or {}).get("interrupted")) if isinstance(entry.get("toolUseResult"), dict) else False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                _settle_result(state, block, stamp, interrupted)


def _remember_use(state: TranscriptState, block: dict[str, Any], stamp: str | None) -> None:
    use_id = block.get("id")
    name = block.get("name")
    inputs = block.get("input") if isinstance(block.get("input"), dict) else {}
    if not isinstance(use_id, str) or not isinstance(name, str):
        return
    if name in _FILE_TOOLS:
        path = inputs.get("file_path") or inputs.get("notebook_path")
        if isinstance(path, str) and path:
            entry = state.files.setdefault(path, {"path": path, "count": 0, "last_at": None, "changes": {}})
            entry["count"] += 1
            entry["changes"][_FILE_TOOLS[name]] = entry["changes"].get(_FILE_TOOLS[name], 0) + 1
            entry["last_at"] = stamp or entry["last_at"]
            state.last_at = stamp or state.last_at
        return
    if name != "Bash":
        return
    command = inputs.get("command")
    if not isinstance(command, str):
        return
    description = inputs.get("description")
    state.pending[use_id] = {
        "at": stamp,
        "command": redact_command(command),
        "description": redact_description(description) if isinstance(description, str) and description else None,
        "test_command": is_agent_test_command(command),
    }
    while len(state.pending) > MAX_PENDING:
        state.pending.pop(next(iter(state.pending)))


def _settle_result(state: TranscriptState, block: dict[str, Any], stamp: str | None, interrupted: bool) -> None:
    use = state.pending.pop(block.get("tool_use_id"), None)
    if use is None:
        return
    if interrupted or _looks_interrupted(block):
        outcome = INTERRUPTED
    elif block.get("is_error"):
        outcome = FAILED
    else:
        outcome = OK
    command = {**use, "at": stamp or use["at"], "outcome": outcome}
    state.commands.append(command)
    state.command_count += 1
    state.last_at = command["at"] or state.last_at
    if command["test_command"]:
        state.test_count += 1
        state.last_test = command
        if outcome == FAILED:
            state.failed_test_count += 1
    if outcome == FAILED:
        state.failures.append(command)
        state.failure_count += 1


def _looks_interrupted(block: dict[str, Any]) -> bool:
    """Interruption volontaire signalée dans le résultat lui-même (code 130,
    ou message d'interruption) : pas un échec, comme pour ``/context``."""
    text = _result_text(block)
    head = text.lstrip()[:40].lower()
    return head.startswith("exit code 130") or "interrupted by user" in head


def _result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""


def is_agent_test_command(command: str) -> bool:
    """Un segment de la commande est une commande de test.

    Même règle que la projection (``is_test_command``), appliquée à chaque
    segment d'une commande composée : les commandes d'un agent enchaînent
    ``cd … && python -m pytest …`` (décision du 2026-09-17, marquage côté
    hook ; ici la même lecture, côté affichage seulement).
    """
    for segment in _segments(command):
        if is_test_command(segment):
            return True
    return False


def _segments(command: str) -> list[str]:
    parts = [command]
    for separator in _SEGMENT_SEPARATORS:
        parts = [piece for part in parts for piece in part.split(separator)]
    return [part.strip() for part in parts if part.strip()]
