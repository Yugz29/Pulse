from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from .event_bus import Event


@dataclass
class State:
    active_app: Optional[str] = None
    active_file: Optional[str] = None
    active_project: Optional[str] = None
    session_start: datetime = field(default_factory=datetime.now)
    last_event_type: Optional[str] = None
    last_activity: datetime = field(default_factory=datetime.now)


class StateStore:

    def __init__(self):
        self._state = State()

    def update(self, event: Event):
        self._state.last_event_type = event.type
        self._state.last_activity = datetime.now()

        # StateStore ne dérive plus le présent métier.
        # Il garde seulement les métadonnées de surface encore lues en legacy.
        if event.type == "app_activated":
            self._state.active_app = event.payload.get("app_name")

        elif event.type in ("app_launched", "app_terminated"):
            pass  # Info utile pour les logs, pas pour l'état courant

        elif event.type in ("file_created", "file_modified", "file_renamed", "file_deleted"):
            pass

        elif event.type == "clipboard_updated":
            pass  # Géré en phase 5 (signal scorer)

        elif event.type in ("screen_locked", "screen_unlocked"):
            pass

        # Anciens noms — rétrocompatibilité au cas où
        elif event.type == "app_switch":
            self._state.active_app = event.payload.get("app_name")
        elif event.type == "file_change":
            pass

    def get(self) -> State:
        return self._state

    def to_dict(self) -> dict:
        state = self._state
        session_duration = int(
            (datetime.now() - state.session_start).total_seconds() / 60
        )
        return {
            "active_app":           state.active_app,
            "active_file":          state.active_file,
            "active_project":       state.active_project,
            "session_duration_min": session_duration,
            "last_event_type":      state.last_event_type,
            "last_activity":        state.last_activity.isoformat(),
        }
