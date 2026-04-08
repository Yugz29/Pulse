from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from .event_bus import EventBus


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

    def compute(self) -> Signals:
        recent = self.bus.recent(100)
        now = datetime.now()

        file_events = [
            e for e in recent
            if e.type in self._file_event_types()
            and self._is_meaningful_file_path(e.payload.get("path"))
        ]
        active_file = self._last_file_path(file_events)
        active_project = self._extract_project(active_file)

        app_events = [e for e in recent if e.type in {"app_activated", "app_switch"}]
        recent_apps = self._recent_apps(app_events, now)

        clipboard_events = [
            e for e in recent if e.type in {"clipboard_updated", "clipboard_update"}
        ]
        clipboard_context = self._last_clipboard_context(clipboard_events)

        friction_score = self._compute_friction(file_events, clipboard_events, now)
        probable_task = self._detect_task(recent_apps, clipboard_context, friction_score)
        focus_level = self._detect_focus_level(recent, app_events, file_events, now)

        return Signals(
            active_project=active_project,
            active_file=active_file,
            probable_task=probable_task,
            friction_score=friction_score,
            focus_level=focus_level,
            session_duration_min=int((now - self._session_start).total_seconds() / 60),
            recent_apps=recent_apps,
            clipboard_context=clipboard_context,
        )

    def _file_event_types(self) -> set[str]:
        return {
            "file_created", "file_modified", "file_renamed", "file_deleted", "file_change"
        }

    def _last_file_path(self, file_events: list) -> Optional[str]:
        for event in reversed(file_events):
            path = event.payload.get("path")
            if path:
                return path
        return None

    def _recent_apps(self, app_events: list, now: datetime) -> List[str]:
        window_start = now - timedelta(minutes=30)
        apps: List[str] = []
        seen = set()

        for event in app_events:
            if event.timestamp < window_start:
                continue
            app_name = event.payload.get("app_name")
            if app_name and app_name not in seen:
                seen.add(app_name)
                apps.append(app_name)

        return apps[-10:]

    def _last_clipboard_context(self, clipboard_events: list) -> Optional[str]:
        for event in reversed(clipboard_events):
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

        if self._last_clipboard_context(clipboard_events) == "stacktrace":
            friction = min(friction + 0.3, 1.0)

        return round(friction, 2)

    def _detect_task(
        self, recent_apps: List[str], clipboard_context: Optional[str], friction_score: float
    ) -> str:
        active_set = set(recent_apps)

        if clipboard_context == "stacktrace" or friction_score >= 0.75:
            return "debug"
        if active_set & self.DEV_APPS:
            return "coding"
        if active_set & self.WRITING_APPS:
            return "writing"
        if active_set & self.BROWSER_APPS:
            return "browsing"
        return "general"

    def _detect_focus_level(
        self, recent: list, app_events: list, file_events: list, now: datetime
    ) -> str:
        if any(event.type in {"screen_locked", "user_idle"} for event in recent[-5:]):
            return "idle"

        recent_app_switches = [
            event for event in app_events if event.timestamp >= now - timedelta(minutes=10)
        ]
        recent_file_edits = [
            event for event in file_events if event.timestamp >= now - timedelta(minutes=10)
        ]

        if len(recent_app_switches) >= 6:
            return "scattered"
        if len(recent_app_switches) <= 1 and len(recent_file_edits) >= 2:
            return "deep"
        return "normal"

    def _extract_project(self, file_path: Optional[str]) -> Optional[str]:
        if not file_path:
            return None

        parts = file_path.split("/")
        for marker in ("Projets", "Projects", "Developer", "src", "workspace"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        return None

    def _is_meaningful_file_path(self, path: Optional[str]) -> bool:
        if not path:
            return False

        name = path.split("/")[-1]
        if name.startswith("."):
            return False
        if name.endswith((".DS_Store", "~", ".xcuserstate")):
            return False
        if ".sb-" in name:
            return False
        if any(part in path for part in ("/.git/", "/node_modules/", "/__pycache__/", "/xcuserdata/", "/DerivedData/")):
            return False
        return True
