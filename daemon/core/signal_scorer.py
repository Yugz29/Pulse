from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

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
    edited_file_count_10m: int = 0
    file_type_mix_10m: Dict[str, int] = field(default_factory=dict)
    rename_delete_ratio_10m: float = 0.0
    dominant_file_mode: str = "none"
    work_pattern_candidate: Optional[str] = None


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

    def reset_session(self) -> None:
        """Réinitialise l'horloge de session — appelé après une longue veille."""
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

        recent_file_events = self._recent_file_events(file_events, now)
        edited_file_count_10m = self._edited_file_count_10m(recent_file_events)
        file_type_mix_10m = self._file_type_mix_10m(recent_file_events)
        rename_delete_ratio_10m = self._rename_delete_ratio_10m(recent_file_events)
        dominant_file_mode = self._dominant_file_mode(recent_file_events)
        friction_score = self._compute_friction(file_events, clipboard_events, now)
        work_pattern_candidate = self._work_pattern_candidate(
            file_type_mix=file_type_mix_10m,
            edited_file_count=edited_file_count_10m,
            rename_delete_ratio=rename_delete_ratio_10m,
            dominant_file_mode=dominant_file_mode,
            friction_score=friction_score,
        )
        probable_task = self._detect_task(
            recent_apps=recent_apps,
            clipboard_context=clipboard_context,
            friction_score=friction_score,
            edited_file_count=edited_file_count_10m,
            file_type_mix=file_type_mix_10m,
            dominant_file_mode=dominant_file_mode,
            work_pattern_candidate=work_pattern_candidate,
        )
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
        clipboard_context: Optional[str],
        friction_score: float,
        edited_file_count: int,
        file_type_mix: Dict[str, int],
        dominant_file_mode: str,
        work_pattern_candidate: Optional[str],
    ) -> str:
        active_set = set(recent_apps)
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
        if latest_app in self.WRITING_APPS and edited_file_count == 0:
            return "writing"
        if latest_app in self.BROWSER_APPS and edited_file_count == 0:
            return "browsing"
        if active_set & self.DEV_APPS and edited_file_count >= 1:
            return "coding"
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

    def _classify_file_type(self, path: str) -> str:
        lower_path = path.lower()
        name = lower_path.split("/")[-1]

        if any(marker in lower_path for marker in ("/tests/", "/test/", "/spec/")):
            return "test"
        if name.startswith("test_") or name.endswith(("_test.py", ".spec.ts", ".spec.tsx", "test.swift")):
            return "test"
        if name in {
            "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
            "pyproject.toml", "requirements.txt", "poetry.lock", "pipfile", "pipfile.lock",
            "cargo.toml", "cargo.lock", "go.mod", "go.sum", "package.swift",
            "podfile", "podfile.lock", "gemfile", "gemfile.lock", "makefile",
            "dockerfile", "docker-compose.yml", "docker-compose.yaml", ".env",
            "tsconfig.json", "vite.config.ts", "vite.config.js",
        }:
            return "config"
        if name.endswith((".md", ".rst", ".txt")) or "/docs/" in lower_path:
            return "docs"
        if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")):
            return "assets"
        if name.endswith((
            ".py", ".js", ".ts", ".tsx", ".jsx", ".swift", ".kt", ".java",
            ".go", ".rs", ".rb", ".php", ".c", ".h", ".cpp", ".hpp",
            ".m", ".mm", ".cs",
        )):
            return "source"
        return "other"

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
