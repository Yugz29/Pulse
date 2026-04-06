from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from .event_bus import Event


@dataclass
class State:
    active_app: Optional[str] = None           # App en premier plan
    active_file: Optional[str] = None          # Dernier fichier modifié
    active_project: Optional[str] = None       # Projet détecté
    session_start: datetime = field(default_factory=datetime.now)
    last_event_type: Optional[str] = None      # Type du dernier event reçu
    last_activity: datetime = field(default_factory=datetime.now)


class StateStore:
    """
    Garde l'état courant du daemon en mémoire.
    Mis à jour à chaque event reçu depuis Swift.
    """

    def __init__(self):
        self._state = State()

    def update(self, event: Event):
        """Met à jour l'état en fonction de l'event reçu."""
        self._state.last_event_type = event.type
        self._state.last_activity = datetime.now()

        if event.type == "app_switch":
            self._state.active_app = event.payload.get("app_name")

        elif event.type == "file_change":
            path = event.payload.get("path", "")
            self._state.active_file = path
            # Détecte le projet depuis le chemin du fichier
            self._state.active_project = self._extract_project(path)

    def get(self) -> State:
        """Retourne l'état courant."""
        return self._state

    def to_dict(self) -> dict:
        """Sérialise l'état pour une réponse JSON."""
        state = self._state
        session_duration = int((datetime.now() - state.session_start).total_seconds() / 60)

        return {
            "active_app":      state.active_app,
            "active_file":     state.active_file,
            "active_project":  state.active_project,
            "session_duration_min": session_duration,
            "last_event_type": state.last_event_type,
            "last_activity":   state.last_activity.isoformat(),
        }

    def _extract_project(self, file_path: str) -> Optional[str]:
        """Extrait le nom du projet depuis le chemin d'un fichier."""
        parts = file_path.split("/")
        for marker in ["Projets", "Projects", "Developer", "src"]:
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        return None
