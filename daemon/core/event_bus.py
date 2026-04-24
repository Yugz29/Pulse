from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

DEFAULT_EVENT_BUS_SIZE = 500


@dataclass
class Event:
    type: str           # Ex: "file_change", "app_switch"
    payload: dict       # Données de l'event
    timestamp: datetime = field(default_factory=datetime.now)


class EventBus:
    """
    Système de communication interne du daemon.
    Les modules publient des events, les abonnés les reçoivent automatiquement.
    """

    def __init__(self, max_size: int = DEFAULT_EVENT_BUS_SIZE):
        # deque = queue circulaire — quand elle est pleine, le plus vieux est supprimé
        self._queue: deque[Event] = deque(maxlen=max_size)
        # Liste des fonctions abonnées — appelées à chaque publish
        self._subscribers: list[Callable[[Event], None]] = []
        # Lock = verrou pour éviter les conflits entre threads
        self._lock = threading.Lock()

    def publish(
        self,
        event_type: str,
        payload: dict,
        timestamp: datetime | None = None,
    ):
        """Publie un event et notifie tous les abonnés."""
        event = Event(
            type=event_type,
            payload=payload,
            timestamp=timestamp or datetime.now(),
        )

        with self._lock:
            self._queue.append(event)

        # Notifie chaque abonné — les erreurs sont isolées pour ne pas bloquer les autres
        for subscriber in self._subscribers:
            try:
                subscriber(event)
            except Exception as e:
                print(f"[EventBus] Erreur abonné : {e}")

    def subscribe(self, callback: Callable[[Event], None]):
        """S'abonne pour recevoir tous les futurs events."""
        self._subscribers.append(callback)

    def recent(self, n: int = 20) -> list[Event]:
        """Retourne les N derniers events."""
        with self._lock:
            return list(self._queue)[-n:]

    def recent_of_type(self, event_type: str, n: int = 10) -> list[Event]:
        """Retourne les N derniers events d'un type précis."""
        with self._lock:
            return [e for e in self._queue if e.type == event_type][-n:]

    def clear(self):
        """Vide la queue — utile pour les tests."""
        with self._lock:
            self._queue.clear()
