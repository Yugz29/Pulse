"""Verrou de fichier exclusif (flock) pour les passages qui écrivent des manifestes.

Le hook SessionEnd et le passage horaire launchd peuvent lancer l'archivage
des transcripts, puis l'émission des agent_session, au même moment. Chaque
phase prend son verrou pour la durée de ses écritures ; le second appelant
attend, puis abandonne proprement après ``timeout_s``.
"""

from __future__ import annotations

import fcntl
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .private_files import ensure_private_directory


DEFAULT_LOCK_TIMEOUT_S = 60.0
_POLL_INTERVAL_S = 0.05


class LockTimeout(RuntimeError):
    """Le verrou est resté tenu par un autre passage au-delà du délai."""


@contextmanager
def exclusive_lock(
    path: Path,
    *,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
) -> Iterator[None]:
    ensure_private_directory(path.parent)
    deadline = time.monotonic() + timeout_s
    with path.open("a+") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(
                        f"verrou occupé depuis plus de {timeout_s:.0f} s : {path}"
                    ) from None
                time.sleep(_POLL_INTERVAL_S)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
