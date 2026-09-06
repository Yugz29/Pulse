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

import fcntl
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAX_ATTEMPTS = 3
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
LOCK_SUFFIX = ".lock"


class StateLocked(RuntimeError):
    """Un autre passage tient déjà l'état (décision 2026-09-06, exécution unique)."""


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
    # Descripteur du verrou exclusif, tenu tant que l'instance vit (ou jusqu'à
    # `release`). Hors du fichier d'état : le format sur disque ne change pas.
    _lock_fd: int | None = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls, path: Path, *, lock: bool = False) -> "JobState":
        """Charge l'état ; ``lock=True`` prend d'abord le verrou exclusif.

        Le verrou (``flock`` sur ``state.json.lock``, non bloquant) couvre le
        chargement et tout ce qui suit : deux passages ne peuvent pas lire le
        même fichier puis se réécrire l'un l'autre. Il est refusé sur-le-champ
        (``StateLocked``), jamais attendu — un passage peut durer vingt
        minutes. Les lectures seules (``list``, ``show``) ne le prennent pas.
        """
        state = cls(path=path)
        if lock:
            state._lock_fd = _acquire_lock(path)
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
        # Nom temporaire unique : un nom fixe est une seconde course entre
        # deux sauvegardes réellement simultanées, même sous verrou côté CLI.
        fd, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2))
        os.chmod(temporary, PRIVATE_FILE_MODE)
        os.replace(temporary, self.path)

    def release(self) -> None:
        """Rend le verrou pris par ``load(lock=True)``. Idempotent."""
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

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
        origin: str | None = None,
    ) -> None:
        """``origin="core"`` : entrée récupérée depuis Core après perte
        d'état ; son ``event`` est l'événement normalisé par Core, pas la
        copie pré-normalisation d'une émission (voir défaut 9 de l'audit).
        Absente sur une émission : le format des entrées existantes ne
        change pas."""
        entry: dict[str, Any] = {
            "session_id": session_id,
            "prompt_version": prompt_version,
            "model_id": model_id,
            "at": at,
        }
        if origin is not None:
            entry["origin"] = origin
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
        self.failures.pop(event_id, None)
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

    def record_failure(self, session_id: str, reason: str, *, event_id: str | None = None) -> int:
        """Une tentative de plus pour cette identité de résumé.

        Clé = ``event_id`` (session, prompt, modèle) : changer de prompt ou
        de modèle ouvre un vrai nouveau budget (audit 2026-09-06, défaut 5).
        Sans ``event_id``, la clé reste la session, forme ancienne. Le format
        du fichier ne change pas : ``failures`` et ``failed`` restent des
        dictionnaires clé → compteur / motif.
        """
        key = event_id or session_id
        count = self.failures.get(key, 0) + 1
        self.failures[key] = count
        if count >= MAX_ATTEMPTS:
            self.failed[key] = reason
        self.save()
        return count

    def is_failed(self, session_id: str, event_id: str | None = None) -> bool:
        """Abandonnée sous l'une ou l'autre forme de clé : l'identité, ou la
        session entière (clé ancienne, abandon d'avant l'identité)."""
        return session_id in self.failed or (event_id is not None and event_id in self.failed)

    def failure_reason(self, session_id: str, event_id: str | None = None) -> str | None:
        if event_id is not None and event_id in self.failed:
            return self.failed[event_id]
        return self.failed.get(session_id)

    def clear_failures(self, session_id: str, event_id: str | None = None) -> None:
        """Reprise explicite (`summarize <id> --retry`) : efface les deux
        formes de clé pour cette session, compteurs et motifs."""
        for key in (session_id, event_id):
            if key is not None:
                self.failures.pop(key, None)
                self.failed.pop(key, None)
        self.save()


def _acquire_lock(path: Path) -> int:
    ensure_private_home(path.parent)
    lock_path = path.with_name(path.name + LOCK_SUFFIX)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, PRIVATE_FILE_MODE)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise StateLocked(f"un autre passage tient le verrou : {lock_path}") from exc
    return fd
