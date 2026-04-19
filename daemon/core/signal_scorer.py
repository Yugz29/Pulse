from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .event_bus import EventBus
from .file_classifier import classify_file_type, file_signal_significance, is_pulse_internal_path
from .workspace_context import extract_project_name


@dataclass
class Signals:
    active_project: Optional[str]
    active_file: Optional[str]
    probable_task: str
    friction_score: float
    focus_level: str
    session_duration_min: int
    recent_apps: List[str]
    clipboard_context: Optional[str]
    edited_file_count_10m: int = 0
    file_type_mix_10m: Dict[str, int] = field(default_factory=dict)
    rename_delete_ratio_10m: float = 0.0
    dominant_file_mode: str = "none"
    work_pattern_candidate: Optional[str] = None


# Durée d'inactivité au-delà de laquelle une nouvelle session commence.
SESSION_TIMEOUT_MIN = 10

# Types d'events qui comptent comme activité significative pour les limites de session.
_MEANINGFUL_FILE_EVENT_TYPES = {"file_created", "file_modified", "file_renamed"}


class SignalScorer:
    """Convertit les derniers events en signaux simples pour le moteur local."""

    DEV_APPS = {
        "Xcode", "VSCode", "Visual Studio Code", "Cursor", "WebStorm",
        "PyCharm", "Terminal", "iTerm2", "Warp",
    }
    BROWSER_APPS = {"Safari", "Google Chrome", "Chrome", "Firefox", "Arc"}
    WRITING_APPS = {"Notion", "Obsidian", "Bear", "Notes", "Pages"}

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._session_start = datetime.now()
        self._last_meaningful_activity_at: Optional[datetime] = None
        # Incrémenté uniquement sur un vrai reset de frontière (inactivité ou screen_lock),
        # PAS sur l'ancrage de la première activité.
        # Permet à l'orchestrateur de détecter qu'une nouvelle session a commencé.
        self.inactivity_reset_count: int = 0

    def reset_session(self) -> None:
        """Réinitialise l'horloge de session — appelé après une veille ou un screen_lock."""
        self._session_start = datetime.now()
        self._last_meaningful_activity_at = None

    def compute(self) -> Signals:
        recent = self.bus.recent(100)
        now = datetime.now()

        # ── Détection des limites de session ──────────────────────────────────────────────
        # On cherche le timestamp de la dernière activité significative dans le bus.
        # Si le gap avec la précédente dépasse SESSION_TIMEOUT_MIN ou qu'un
        # screen_lock s'était produit entre les deux, la session redémarre
        # à partir de cette nouvelle activité.
        latest_meaningful = self._find_latest_meaningful_activity(recent)
        if latest_meaningful is not None and latest_meaningful >= self._session_start:
            prev = self._last_meaningful_activity_at
            if prev is not None:
                # Un reset ne se déclenche que s'il y a UNE NOUVELLE activité.
                # screen_locked seul (sans reprise) ne doit pas réinitialiser.
                has_new_activity = latest_meaningful > prev
                if has_new_activity:
                    screen_locked = self._has_screen_lock_after(recent, prev)
                    gap_min = (latest_meaningful - prev).total_seconds() / 60
                    if screen_locked or gap_min > SESSION_TIMEOUT_MIN:
                        self._session_start = latest_meaningful
                        self.inactivity_reset_count += 1
            else:
                # Première activité significative depuis le démarrage ou le dernier reset :
                # la session démarre réellement maintenant, pas au démarrage du daemon.
                self._session_start = latest_meaningful
            self._last_meaningful_activity_at = latest_meaningful
        # ───────────────────────────────────────────────────────────────────

        file_events = [
            e for e in recent
            if e.type in self._file_event_types()
            and self._is_trackable_file_path(e.payload.get("path"))
        ]
        meaningful_file_events = [
            e for e in file_events
            if self._file_signal_significance(e.payload.get("path")) == "meaningful"
        ]
        active_file = self._last_file_path(meaningful_file_events)
        active_project = self._extract_project(active_file)

        app_events = [e for e in recent if e.type in {"app_activated", "app_switch"}]
        recent_apps = self._recent_apps(app_events, now)

        clipboard_events = [
            e for e in recent if e.type in {"clipboard_updated", "clipboard_update"}
        ]
        clipboard_context = self._last_clipboard_context(clipboard_events, now)

        recent_file_events = self._recent_file_events(file_events, now)
        recent_meaningful_file_events = self._recent_file_events(meaningful_file_events, now)
        edited_file_count_10m = self._edited_file_count_10m(recent_meaningful_file_events)
        file_type_mix_10m = self._file_type_mix_10m(recent_meaningful_file_events)
        rename_delete_ratio_10m = self._rename_delete_ratio_10m(recent_meaningful_file_events)
        dominant_file_mode = self._dominant_file_mode(recent_meaningful_file_events)
        friction_score = self._compute_friction(meaningful_file_events, clipboard_events, now)
        work_pattern_candidate = self._work_pattern_candidate(
            file_type_mix=file_type_mix_10m,
            edited_file_count=edited_file_count_10m,
            rename_delete_ratio=rename_delete_ratio_10m,
            dominant_file_mode=dominant_file_mode,
            friction_score=friction_score,
        )
        probable_task = self._detect_task(
            recent_apps=recent_apps,
            latest_active_app=self._latest_active_app(app_events, now, minutes=5),
            clipboard_context=clipboard_context,
            friction_score=friction_score,
            edited_file_count=edited_file_count_10m,
            file_type_mix=file_type_mix_10m,
            dominant_file_mode=dominant_file_mode,
            work_pattern_candidate=work_pattern_candidate,
        )
        focus_level = self._detect_focus_level(recent, app_events, meaningful_file_events, now)

        return Signals(
            active_project=active_project,
            active_file=active_file,
            probable_task=probable_task,
            friction_score=friction_score,
            focus_level=focus_level,
            session_duration_min=int((now - self._session_start).total_seconds() / 60),
            recent_apps=recent_apps,
            clipboard_context=clipboard_context,
            edited_file_count_10m=edited_file_count_10m,
            file_type_mix_10m=file_type_mix_10m,
            rename_delete_ratio_10m=rename_delete_ratio_10m,
            dominant_file_mode=dominant_file_mode,
            work_pattern_candidate=work_pattern_candidate,
        )

    def _file_event_types(self) -> set[str]:
        return {
            "file_created", "file_modified", "file_renamed", "file_deleted", "file_change"
        }

    def _last_file_path(self, file_events: list) -> Optional[str]:
        for event in reversed(file_events):
            path = event.payload.get("path")
            if path and event.type != "file_deleted":
                return path
        return None

    def _recent_apps(self, app_events: list, now: datetime) -> List[str]:
        window_start = now - timedelta(minutes=30)
        # On veut que apps[-1] soit la DERNIÈRE app réellement activée dans la fenêtre,
        # pas la première fois qu'elle a été vue. Un dict ordonné permet de déplacer
        # chaque app à la fin à chaque nouvelle occurrence via pop + réinsertion.
        # Xcode → Chrome → Xcode donne [Chrome, Xcode], pas [Xcode, Chrome].
        ordered: dict = {}

        for event in app_events:
            if event.timestamp < window_start:
                continue
            app_name = event.payload.get("app_name")
            if not app_name:
                continue
            ordered.pop(app_name, None)  # supprime l'occurrence précédente si présente
            ordered[app_name] = None     # réinsère à la fin

        return list(ordered)[-10:]

    def _latest_active_app(self, app_events: list, now: datetime, minutes: int) -> Optional[str]:
        """
        Retourne l'app la plus recemment activee dans la fenetre [now - minutes, now].
        Utilise pour les decisions browsing/writing qui necessitent que l'app
        soit vraiment l'app courante, pas juste la derniere vue sur 30 min.
        """
        cutoff = now - timedelta(minutes=minutes)
        for event in reversed(app_events):
            if event.timestamp < cutoff:
                break
            name = event.payload.get("app_name")
            if name:
                return name
        return None

    def _last_clipboard_context(self, clipboard_events: list, now: datetime) -> Optional[str]:
        # Le clipboard n'est un signal actif que s'il est récent.
        # Une stacktrace copiée il y a 20 min ne doit plus forcer probable_task='debug'.
        # Fenêtre de 5 min : un copier-coller pertinent est généralement utilisé
        # dans la minute qui suit, pas un quart d'heure plus tard.
        recent_window = now - timedelta(minutes=5)
        for event in reversed(clipboard_events):
            if event.timestamp < recent_window:
                break
            kind = event.payload.get("content_kind") or event.payload.get("content_type")
            if kind:
                return kind
        return None

    def _compute_friction(self, file_events: list, clipboard_events: list, now: datetime) -> float:
        recent_window = now - timedelta(minutes=10)
        recent_paths = [
            event.payload.get("path")
            for event in file_events
            if event.timestamp >= recent_window and event.payload.get("path")
        ]

        max_churn = max(Counter(recent_paths).values(), default=0)
        friction = min(max_churn / 6.0, 1.0)

        if self._last_clipboard_context(clipboard_events, now) == "stacktrace":
            friction = min(friction + 0.3, 1.0)

        return round(friction, 2)

    def _recent_file_events(self, file_events: list, now: datetime) -> list:
        recent_window = now - timedelta(minutes=10)
        return [event for event in file_events if event.timestamp >= recent_window]

    def _edited_file_count_10m(self, recent_file_events: list) -> int:
        paths = {
            event.payload.get("path")
            for event in recent_file_events
            if event.payload.get("path")
        }
        return len(paths)

    def _file_type_mix_10m(self, recent_file_events: list) -> Dict[str, int]:
        mix: Counter[str] = Counter()
        for event in recent_file_events:
            path = event.payload.get("path")
            if not path:
                continue
            mix[self._classify_file_type(path)] += 1
        return dict(mix)

    def _rename_delete_ratio_10m(self, recent_file_events: list) -> float:
        if not recent_file_events:
            return 0.0
        structural = sum(
            1
            for event in recent_file_events
            if event.type in {"file_renamed", "file_deleted"}
        )
        return round(structural / len(recent_file_events), 2)

    def _dominant_file_mode(self, recent_file_events: list) -> str:
        paths = [
            event.payload.get("path")
            for event in recent_file_events
            if event.payload.get("path")
        ]
        distinct_count = len(set(paths))
        if distinct_count == 0:
            return "none"
        if distinct_count == 1:
            return "single_file"
        if distinct_count <= 4:
            return "few_files"
        return "multi_file"

    def _work_pattern_candidate(
        self,
        *,
        file_type_mix: Dict[str, int],
        edited_file_count: int,
        rename_delete_ratio: float,
        dominant_file_mode: str,
        friction_score: float,
    ) -> Optional[str]:
        source_count = file_type_mix.get("source", 0)
        test_count = file_type_mix.get("test", 0)
        config_count = file_type_mix.get("config", 0)
        docs_count = file_type_mix.get("docs", 0)

        if config_count >= 2 and config_count >= source_count + test_count:
            return "setup_candidate"
        if source_count >= 2 and edited_file_count >= 4 and rename_delete_ratio >= 0.25:
            return "refactor_candidate"
        if source_count >= 1 and edited_file_count >= 3 and (test_count >= 1 or docs_count >= 1):
            return "feature_candidate"
        if dominant_file_mode == "single_file" and friction_score >= 0.5 and (source_count + test_count) >= 1:
            return "debug_loop_candidate"
        return None

    def _detect_task(
        self,
        *,
        recent_apps: List[str],
        latest_active_app: Optional[str],
        clipboard_context: Optional[str],
        friction_score: float,
        edited_file_count: int,
        file_type_mix: Dict[str, int],
        dominant_file_mode: str,
        work_pattern_candidate: Optional[str],
    ) -> str:
        active_set = set(recent_apps)
        # latest_app (30 min) : sert pour coding — avoir ouvert Xcode il y a 20 min reste valide.
        # latest_active_app (5 min) : sert pour browsing/writing — l'app doit etre vraiment courante.
        latest_app = recent_apps[-1] if recent_apps else None
        source_count = file_type_mix.get("source", 0)
        test_count = file_type_mix.get("test", 0)
        config_count = file_type_mix.get("config", 0)
        docs_count = file_type_mix.get("docs", 0)
        code_file_activity = source_count + test_count
        coding_patterns = {"feature_candidate", "refactor_candidate", "debug_loop_candidate", "setup_candidate"}
        strong_coding_evidence = (
            code_file_activity >= 2
            or work_pattern_candidate in coding_patterns
            or (
                edited_file_count >= 3
                and dominant_file_mode in {"few_files", "multi_file"}
                and (code_file_activity >= 1 or config_count >= 2)
            )
        )
        strong_writing_evidence = (
            docs_count >= 2
            and code_file_activity == 0
            and config_count == 0
        )

        if clipboard_context == "stacktrace" or friction_score >= 0.75:
            return "debug"
        if strong_coding_evidence:
            return "coding"
        if strong_writing_evidence:
            return "writing"
        if latest_app in self.DEV_APPS and edited_file_count >= 1:
            return "coding"
        # browsing et writing : on exige que l'app soit active dans les 5 dernieres minutes.
        # Un switch browser il y a 20 min ne doit pas colorer toute la session.
        if latest_active_app in self.WRITING_APPS and edited_file_count == 0:
            return "writing"
        if latest_active_app in self.BROWSER_APPS and edited_file_count == 0:
            return "browsing"
        if active_set & self.DEV_APPS and edited_file_count >= 1:
            return "coding"
        return "general"

    def _detect_focus_level(
        self, recent: list, app_events: list, file_events: list, now: datetime
    ) -> str:
        recent_app_switches = [
            event for event in app_events if event.timestamp >= now - timedelta(minutes=10)
        ]
        recent_file_edits = [
            event for event in file_events if event.timestamp >= now - timedelta(minutes=10)
        ]
        has_recent_idle_signal = any(event.type in {"screen_locked", "user_idle"} for event in recent[-5:])

        if has_recent_idle_signal:
            if self._has_meaningful_recent_file_activity(recent_file_edits):
                return "normal"
            return "idle"

        if len(recent_app_switches) >= 6:
            # De nombreux switches n'impliquent pas un manque de focus si une
            # activite fichiers substantielle se produit en parallele.
            # Xcode/Terminal/Chrome en workflow de dev actif peut generer 6+ switches
            # tout en produisant de vraies modifications de code.
            if len(recent_file_edits) >= 3:
                return "normal"
            return "scattered"
        if len(recent_app_switches) <= 1 and len(recent_file_edits) >= 2:
            return "deep"
        return "normal"

    def _has_meaningful_recent_file_activity(self, recent_file_edits: list) -> bool:
        distinct_paths = {
            event.payload.get("path")
            for event in recent_file_edits
            if event.payload.get("path")
        }
        return len(distinct_paths) >= 3 or len(recent_file_edits) >= 4

    def _extract_project(self, file_path: Optional[str]) -> Optional[str]:
        return extract_project_name(file_path)

    def _classify_file_type(self, path: str) -> str:
        return classify_file_type(path)

    def _file_signal_significance(self, path: Optional[str]) -> str:
        return file_signal_significance(path)

    def _is_trackable_file_path(self, path: Optional[str]) -> bool:
        return file_signal_significance(path) != "technical_noise"

    def _is_pulse_internal_path(self, path: str) -> bool:
        return is_pulse_internal_path(path)

    def _find_latest_meaningful_activity(self, events: list) -> Optional[datetime]:
        """
        Retourne le timestamp de la dernière activité significative pour les
        limites de session : modification de fichier OU usage d'une app de dev.
        Évènements inspectés depuis la fin du bus (le plus récent en premier).
        """
        for event in reversed(events):
            if event.type in _MEANINGFUL_FILE_EVENT_TYPES:
                if self._is_trackable_file_path(event.payload.get("path")):
                    return event.timestamp
            if event.type in {"app_activated", "app_switch"}:
                if event.payload.get("app_name") in self.DEV_APPS:
                    return event.timestamp
        return None

    def _has_screen_lock_after(self, events: list, since: datetime) -> bool:
        """Retourne True s'il y a eu un screen_locked après `since` dans le bus."""
        return any(
            event.type == "screen_locked" and event.timestamp > since
            for event in events
        )
