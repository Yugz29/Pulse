"""État local du job : ce qui a été émis, ce qui a échoué. Jamais dans trace.db.

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
    failures: dict[str, int] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "JobState":
        state = cls(path=path)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            state.emitted = dict(raw.get("emitted", {}))
            state.failures = {k: int(v) for k, v in raw.get("failures", {}).items()}
            state.failed = dict(raw.get("failed", {}))
        return state

    def save(self) -> None:
        ensure_private_home(self.path.parent)
        payload = {
            "emitted": self.emitted,
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

    def record_emitted(
        self,
        event_id: str,
        *,
        session_id: str,
        prompt_version: str,
        model_id: str,
        at: str,
    ) -> None:
        self.emitted[event_id] = {
            "session_id": session_id,
            "prompt_version": prompt_version,
            "model_id": model_id,
            "at": at,
        }
        self.failures.pop(session_id, None)
        self.save()

    def record_failure(self, session_id: str, reason: str) -> int:
        count = self.failures.get(session_id, 0) + 1
        self.failures[session_id] = count
        if count >= MAX_ATTEMPTS:
            self.failed[session_id] = reason
        self.save()
        return count

    def is_failed(self, session_id: str) -> bool:
        return session_id in self.failed
