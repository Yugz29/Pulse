"""État local du job : ce qui a été émis, ce qui attend Core, ce qui a
échoué. Jamais dans trace.db.

``pending`` porte le payload canonique d'un résumé validé, gelé *avant* le
POST vers Core : si le POST échoue ou que la confirmation se perd, le tick
suivant renvoie ces octets exacts — jamais un payload recalculé avec un
nouveau ``generated_at``. Seule une régénération volontaire (autre
``prompt_version`` ou ``model_id``, donc autre ``event_id``) produit un
nouveau payload.

``~/.pulse_intelligence/`` suit la même politique de permissions que Core
après hardening : dossier ``0700``, fichiers ``0600``.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAX_ATTEMPTS = 3
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def ensure_private_home(path: Path) -> Path:
    """Crée le dossier en 0700 ; le resserre s'il existait plus large."""
    target = path.expanduser()
    if not target.exists():
        target.mkdir(parents=True, mode=PRIVATE_DIRECTORY_MODE)
        os.chmod(target, PRIVATE_DIRECTORY_MODE)
    elif stat.S_IMODE(target.stat().st_mode) & 0o077:
        os.chmod(target, PRIVATE_DIRECTORY_MODE)
    return target


@dataclass
class JobState:
    path: Path
    emitted: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "JobState":
        state = cls(path=path)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            state.emitted = dict(raw.get("emitted", {}))
            state.pending = dict(raw.get("pending", {}))
            state.failures = {k: int(v) for k, v in raw.get("failures", {}).items()}
            state.failed = dict(raw.get("failed", {}))
        return state

    def save(self) -> None:
        ensure_private_home(self.path.parent)
        payload = {
            "emitted": self.emitted,
            "pending": self.pending,
            "failures": self.failures,
            "failed": self.failed,
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.chmod(temporary, PRIVATE_FILE_MODE)
        os.replace(temporary, self.path)

    def knows(self, event_id: str) -> bool:
        return event_id in self.emitted

    def known_summaries(self) -> set[tuple[str, str, str]]:
        """(session_id, prompt_version, model_id) déjà émis."""
        return {
            (
                str(entry.get("session_id")),
                str(entry.get("prompt_version")),
                str(entry.get("model_id")),
            )
            for entry in self.emitted.values()
        }

    def record_pending(
        self,
        event_id: str,
        *,
        session_id: str,
        prompt_version: str,
        model_id: str,
        at: str,
        event: dict[str, Any],
        previous_summary: dict[str, Any] | None = None,
    ) -> None:
        """Gèle le payload validé avant le POST. Sur disque avant tout envoi.

        ``previous_summary`` est l'annexe telle que le modèle l'a reçue (id,
        label, reprise du résumé précédent), ou ``None`` s'il n'en a pas eu.
        Elle n'entre pas dans l'événement — Core ne la connaît que par
        ``input_hash`` — mais ``show`` en a besoin pour mettre le ``open``
        produit en regard du ``open`` reçu (défaut D1, `docs/dogfooding.md`).
        """
        self.pending[event_id] = {
            "session_id": session_id,
            "prompt_version": prompt_version,
            "model_id": model_id,
            "at": at,
            "event": event,
            "previous_summary": previous_summary,
        }
        self.save()

    def pending_event(self, event_id: str) -> dict[str, Any] | None:
        """Le payload gelé qui attend encore la confirmation de Core."""
        entry = self.pending.get(event_id)
        if entry is None or not isinstance(entry.get("event"), dict):
            return None
        return entry["event"]

    def record_emitted(
        self,
        event_id: str,
        *,
        session_id: str,
        prompt_version: str,
        model_id: str,
        at: str,
        event: dict[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "session_id": session_id,
            "prompt_version": prompt_version,
            "model_id": model_id,
            "at": at,
        }
        if event is not None:
            # Copie locale de ce qui a été émis : `show <id>` lit ici, Core
            # reste la vérité (`show latest` lit /context).
            entry["event"] = event
        pending = self.pending.pop(event_id, None)
        if pending is not None and "previous_summary" in pending:
            # L'annexe suit le payload gelé, y compris sur un POST rejoué.
            entry["previous_summary"] = pending["previous_summary"]
        self.emitted[event_id] = entry
        self.failures.pop(session_id, None)
        self.save()

    def summaries_for(self, session_id: str) -> list[dict[str, Any]]:
        """Les entrées émises pour une session (événement et annexe), du plus
        ancien au plus récent. Une entrée sans clé ``previous_summary`` date
        d'avant l'enregistrement de l'annexe : « inconnue », pas « aucune »."""
        entries = [
            entry
            for entry in self.emitted.values()
            if entry.get("session_id") == session_id and isinstance(entry.get("event"), dict)
        ]
        entries.sort(key=lambda entry: str(entry.get("at", "")))
        return entries

    def events_for(self, session_id: str) -> list[dict[str, Any]]:
        """Les événements émis pour une session, du plus ancien au plus récent."""
        return [entry["event"] for entry in self.summaries_for(session_id)]

    def session_ids(self) -> list[str]:
        """Les sessions dont au moins un événement émis est conservé ici."""
        return sorted(
            {
                str(entry["session_id"])
                for entry in self.emitted.values()
                if entry.get("session_id") and isinstance(entry.get("event"), dict)
            }
        )

    def latest_event(self) -> dict[str, Any] | None:
        entries = [
            entry for entry in self.emitted.values() if isinstance(entry.get("event"), dict)
        ]
        if not entries:
            return None
        return max(entries, key=lambda entry: str(entry.get("at", "")))["event"]

    def record_failure(self, session_id: str, reason: str) -> int:
        count = self.failures.get(session_id, 0) + 1
        self.failures[session_id] = count
        if count >= MAX_ATTEMPTS:
            self.failed[session_id] = reason
        self.save()
        return count

    def is_failed(self, session_id: str) -> bool:
        return session_id in self.failed
