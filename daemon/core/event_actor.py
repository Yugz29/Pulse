"""
event_actor.py — Attribution probabiliste de l'auteur d'un event fichier.

Chaque signal CONTRIBUE à un score par actor ; aucun signal seul ne décide.
Le verdict est le actor avec le score normalisé le plus élevé.

Axes orthogonaux :
  - EventActor    : qui a probablement initié l'event
  - NoisePolicy   : comment le scorer doit traiter ce fichier (indépendant de l'actor)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


# ── Types publics ─────────────────────────────────────────────────────────────

class EventActor(str, Enum):
    USER          = "user"
    SYSTEM        = "system"
    TOOL_ASSISTED = "tool_assisted"
    UNKNOWN       = "unknown"


class NoisePolicy(str, Enum):
    """
    Politique de traitement dans le scorer. Définie sur la nature structurelle
    du fichier, pas sur l'actor — les deux axes sont indépendants.

    NORMAL       : comptabilisé normalement dans tous les signaux.
    DOWNRANK     : poids réduit (artefacts de dépendances, fichiers générés).
    OBSERVE_ONLY : enregistré en mémoire de session, exclu du scoring temps-réel.
    IGNORE       : ne devrait pas atteindre le bus — garde-fou défensif.
    """
    NORMAL       = "normal"
    DOWNRANK     = "downrank"
    OBSERVE_ONLY = "observe_only"
    IGNORE       = "ignore"


@dataclass(frozen=True)
class ActorAttribution:
    actor: EventActor
    confidence: float        # 0.0–1.0 : certitude sur l'actor retenu
    automation_score: float  # 0.0–1.0 : probabilité d'automatisation (signal continu)
    noise_policy: NoisePolicy


# ── Constantes ────────────────────────────────────────────────────────────────

# Prior utilisateur : on suppose l'activité humaine sauf preuve contraire.
_USER_BASELINE = 1.0

# Segments présents dans les chemins purement système (jamais user-initiated).
_SYSTEM_PATH_SEGMENTS = (
    "/.Spotlight-",
    "/private/var/folders/",
    "/System/Library/",
    "/Library/Caches/",
    "com.apple.",
    "appPrivateData",
    "syncstatus",
)

# Artefacts de dépendances : générés par npm/yarn/cargo/etc., pas par l'utilisateur.
# À downranker, pas à exclure — ils indiquent une activité de gestion de dépendances.
_DEPENDENCY_ARTIFACTS = frozenset({
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pipfile.lock",
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "podfile.lock",
    "go.sum",
})

# Apps dont les modifications fichiers sont souvent outil-assistées.
# Signal FAIBLE (0.8) : insuffisant seul pour dépasser le baseline user (1.0).
_TOOL_ASSISTED_APPS = frozenset({
    "Cursor",
    "Windsurf",
    "Copilot",
    "Codex",
    "Claude",
    "GitHub Copilot",
})

_BURST_FILE_COUNT  = 4    # fichiers distincts dans la fenêtre burst
_BURST_WINDOW_MS   = 600  # millisecondes
_REPEAT_COUNT      = 3    # même fichier répété N fois = process en boucle
_REPEAT_WINDOW_SEC = 30   # fenêtre de détection repeat


# ── Helpers publics ───────────────────────────────────────────────────────────

def file_noise_policy(path: str) -> NoisePolicy:
    """
    Retourne la NoisePolicy structurelle d'un fichier.
    Indépendant de l'actor et du contexte d'exécution.
    """
    name = path.split("/")[-1].lower()
    if name in _DEPENDENCY_ARTIFACTS:
        return NoisePolicy.DOWNRANK
    return NoisePolicy.NORMAL


# ── Scoring interne ───────────────────────────────────────────────────────────

@dataclass
class _ActorScores:
    user: float          = 0.0
    system: float        = 0.0
    tool_assisted: float = 0.0

    def resolve(self) -> tuple[EventActor, float, float]:
        """
        Normalise les scores avec le prior user et retourne
        (actor, confidence, automation_score).
        """
        u = self.user + _USER_BASELINE
        s = self.system
        t = self.tool_assisted
        total = u + s + t

        pairs = [
            (EventActor.USER, u),
            (EventActor.SYSTEM, s),
            (EventActor.TOOL_ASSISTED, t),
        ]
        best_actor, best_score = max(pairs, key=lambda x: x[1])
        confidence      = round(best_score / total, 2)
        automation_score = round((t + s * 0.5) / total, 2)
        return best_actor, confidence, automation_score


# ── Classifier ────────────────────────────────────────────────────────────────

class EventActorClassifier:
    """
    Attribue un auteur probable à chaque event fichier entrant.

    Signaux et leurs contributions :
      1. Chemin système absolu              → system  +4.0  (fort)
      2. Répétition rapide du même fichier  → system  +2.0  (process en boucle)
      3. Artefact de dépendance             → tool    +1.5  (généré par outil)
      4. Burst de fichiers distincts        → tool    +0.0–4.0  (continu)
      5. App outil active                   → tool    +0.8  (faible, jamais décisif seul)

    Exemple de résolution avec baseline user=1.0 :
      - App outil seul    : tool=0.8,  user=1.0 → USER gagne  (55%)
      - Burst seul (4)    : tool=2.5,  user=1.0 → TOOL_ASSISTED (71%)
      - Burst + app       : tool=3.3,  user=1.0 → TOOL_ASSISTED (77%)
      - Chemin système    : sys=4.0,   user=1.0 → SYSTEM  (80%)
    """

    def classify(
        self,
        event_type: str,
        payload: dict,
        *,
        latest_app: Optional[str],
        recent_events: list,
        now: Optional[datetime] = None,
    ) -> ActorAttribution:
        now = now or datetime.now()

        if event_type not in {"file_modified", "file_created", "file_renamed", "file_deleted"}:
            return ActorAttribution(EventActor.USER, 1.0, 0.0, NoisePolicy.NORMAL)

        path = payload.get("path", "")
        noise = file_noise_policy(path)
        scores = _ActorScores()

        # Signal 1 : chemin système absolu
        if self._is_system_path(path):
            scores.system += 4.0

        # Signal 2 : même fichier modifié plusieurs fois rapidement
        if self._is_rapid_repeat(path, now, recent_events):
            scores.system += 2.0

        # Signal 3 : artefact de dépendance connu
        name = path.split("/")[-1].lower()
        if name in _DEPENDENCY_ARTIFACTS:
            scores.tool_assisted += 1.5

        # Signal 4 : burst de fichiers distincts (score continu)
        scores.tool_assisted += self._burst_score(now, recent_events)

        # Signal 5 : app outil active — signal faible
        if latest_app in _TOOL_ASSISTED_APPS:
            scores.tool_assisted += 0.8

        actor, confidence, automation_score = scores.resolve()
        return ActorAttribution(actor, confidence, automation_score, noise)

    # ── Détecteurs privés ──────────────────────────────────────────────────────

    def _is_system_path(self, path: str) -> bool:
        return any(seg in path for seg in _SYSTEM_PATH_SEGMENTS)

    def _is_rapid_repeat(self, path: str, now: datetime, recent_events: list) -> bool:
        if not path:
            return False
        cutoff = now - timedelta(seconds=_REPEAT_WINDOW_SEC)
        count = sum(
            1 for e in recent_events
            if e.type in {"file_modified", "file_created"}
            and e.payload.get("path") == path
            and e.timestamp >= cutoff
        )
        return count >= _REPEAT_COUNT

    def _burst_score(self, now: datetime, recent_events: list) -> float:
        """
        Score continu basé sur le nombre de fichiers distincts modifiés
        dans la fenêtre burst. Retourne 0.0 sous le seuil, croît au-dessus.
        """
        cutoff = now - timedelta(milliseconds=_BURST_WINDOW_MS)
        file_types = {"file_modified", "file_created", "file_renamed", "file_deleted"}
        distinct = {
            e.payload.get("path")
            for e in recent_events
            if e.type in file_types
            and e.timestamp >= cutoff
            and e.payload.get("path")
        }
        count = len(distinct)
        if count < _BURST_FILE_COUNT:
            return 0.0
        # Croissance linéaire au-delà du seuil, cap à 4.0
        return round(min(2.5 + (count - _BURST_FILE_COUNT) * 0.25, 4.0), 2)
