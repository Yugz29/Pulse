from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .event_bus import DEFAULT_EVENT_BUS_SIZE, EventBus
from .file_classifier import classify_file_type, file_signal_significance, is_pulse_internal_path
from .git_diff import extract_file_names_from_diff_summary
from .session_fsm import SESSION_TIMEOUT_MIN
from .workspace_context import extract_project_name, find_workspace_root


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
    # ── PR2 : couche activité + confiance sur la tâche ────────────────────────
    # Champs additifs avec défauts — non-breaking pour tout consommateur existant.
    #
    # activity_level : ce que l'utilisateur fait concrètement (bas niveau)
    #   editing | reading | executing | navigating | idle
    #
    # task_confidence : score normalisé du scorer pondéré (0.0–1.0)
    #   Exposé pour la décision et le debug ; non utilisé par decision_engine.
    activity_level: str = "idle"
    task_confidence: float = 0.5
    mcp_action_category: Optional[str] = None
    mcp_is_read_only: Optional[bool] = None
    mcp_decision: Optional[str] = None
    mcp_summary: Optional[str] = None
    terminal_action_category: Optional[str] = None
    terminal_project: Optional[str] = None
    terminal_cwd: Optional[str] = None
    terminal_exit_code: Optional[int] = None
    terminal_duration_ms: Optional[int] = None
    terminal_summary: Optional[str] = None
    terminal_command: Optional[str] = None
    terminal_success: Optional[bool] = None


class SignalScorer:
    """Convertit les derniers events en signaux simples pour le moteur local."""

    DEV_APPS = {
        "Xcode", "VSCode", "Visual Studio Code", "Code", "Cursor", "WebStorm",
        "PyCharm", "Terminal", "iTerm2", "Warp",
    }
    BROWSER_APPS = {"Safari", "Google Chrome", "Chrome", "Firefox", "Arc"}
    WRITING_APPS = {"Notion", "Obsidian", "Bear", "Notes", "Pages"}
    TERMINAL_APPS = {"Terminal", "iTerm2", "Warp"}

    def __init__(self, bus: EventBus):
        self.bus = bus

    def reset_session(self) -> None:
        """
        Compat legacy : la frontière de session est gérée par SessionFSM.
        Cette méthode reste présente pour éviter une rupture brutale d'API.
        """
        return None

    def compute(
        self,
        *,
        session_started_at: Optional[datetime] = None,
        observed_now: Optional[datetime] = None,
        project_hint: Optional[str] = None,
        diff_summary: Optional[str] = None,
    ) -> Signals:
        # Les fenêtres de calcul montent jusqu'à 30 min. En session active,
        # une coupe fixe à 100 tronque artificiellement ce signal bien avant
        # la saturation du bus.
        recent = self.bus.recent(DEFAULT_EVENT_BUS_SIZE)
        now = observed_now or datetime.now()
        effective_session_start = session_started_at or now

        file_events = [
            e for e in recent
            if e.type in self._file_event_types()
            and self._is_trackable_file_path(e.payload.get("path"))
        ]
        meaningful_file_events = [
            e for e in file_events
            if self._file_signal_significance(e.payload.get("path")) == "meaningful"
        ]
        recent_file_events = self._recent_file_events(file_events, now)
        recent_meaningful_file_events = self._recent_file_events(meaningful_file_events, now)

        dominant_workspace_root = self._dominant_workspace_root(recent_meaningful_file_events)
        if dominant_workspace_root:
            active_file = self._last_file_path_for_workspace(
                meaningful_file_events,
                dominant_workspace_root,
            )
            active_project = self._extract_project_from_workspace(dominant_workspace_root)
        else:
            active_file = self._last_file_path(meaningful_file_events)
            active_project = self._extract_project(active_file)

        app_events = [e for e in recent if e.type in {"app_activated", "app_switch"}]
        recent_apps = self._recent_apps(app_events, now)

        clipboard_events = [
            e for e in recent if e.type in {"clipboard_updated", "clipboard_update"}
        ]
        clipboard_context = self._last_clipboard_context(clipboard_events, now)
        mcp_signal = self._latest_mcp_signal(recent, now)
        terminal_signal = self._latest_terminal_signal(recent, now)
        latest_active_app = self._latest_active_app(app_events, now, minutes=5)
        has_recent_local_exploration = self._has_recent_local_exploration(recent, now)

        if not active_project:
            active_project = (terminal_signal or {}).get("terminal_project")
        if not active_project and project_hint:
            if self._should_keep_project_hint(
                latest_active_app=latest_active_app,
                has_recent_local_exploration=has_recent_local_exploration,
                mcp_signal=mcp_signal,
                terminal_signal=terminal_signal,
            ):
                active_project = project_hint

        # Seuls les events attribués à l'utilisateur (ou non attribués) alimentent
        # les comptages de scoring. Les events system/tool_assisted sont exclus pour
        # éviter que l'activité automatisée (LLM, scripts) n'inflate edited_file_count.
        # friction_score conserve tous les events : le churn automatisé est un signal
        # de charge système réel, pas à effacer du scoring de friction.
        user_recent_file_events = [
            e for e in recent_meaningful_file_events
            if e.payload.get("_actor", "user") in {"user", "unknown"}
        ]

        edited_file_count_10m = self._edited_file_count_10m(user_recent_file_events)
        file_type_mix_10m = self._file_type_mix_10m(user_recent_file_events)
        rename_delete_ratio_10m = self._rename_delete_ratio_10m(user_recent_file_events)
        dominant_file_mode = self._dominant_file_mode(user_recent_file_events)
        friction_score = self._compute_friction(meaningful_file_events, clipboard_events, now)
        work_pattern_candidate = self._work_pattern_candidate(
            file_type_mix=file_type_mix_10m,
            edited_file_count=edited_file_count_10m,
            rename_delete_ratio=rename_delete_ratio_10m,
            dominant_file_mode=dominant_file_mode,
            friction_score=friction_score,
        )
        probable_task, task_confidence = self._detect_task(
            active_project=active_project,
            recent_apps=recent_apps,
            latest_active_app=latest_active_app,
            clipboard_context=clipboard_context,
            mcp_signal=mcp_signal,
            terminal_signal=terminal_signal,
            friction_score=friction_score,
            edited_file_count=edited_file_count_10m,
            file_type_mix=file_type_mix_10m,
            dominant_file_mode=dominant_file_mode,
            work_pattern_candidate=work_pattern_candidate,
            diff_summary=diff_summary,
        )
        focus_level = self._detect_focus_level(recent, app_events, meaningful_file_events, now)
        activity_level = self._detect_activity_level(
            focus_level=focus_level,
            user_file_count=edited_file_count_10m,
            latest_active_app=latest_active_app,
            recent_apps=recent_apps,
            has_recent_local_exploration=has_recent_local_exploration,
            mcp_signal=mcp_signal,
            terminal_signal=terminal_signal,
        )

        return Signals(
            active_project=active_project,
            active_file=active_file,
            probable_task=probable_task,
            friction_score=friction_score,
            focus_level=focus_level,
            session_duration_min=int((now - effective_session_start).total_seconds() / 60),
            recent_apps=recent_apps,
            clipboard_context=clipboard_context,
            edited_file_count_10m=edited_file_count_10m,
            file_type_mix_10m=file_type_mix_10m,
            rename_delete_ratio_10m=rename_delete_ratio_10m,
            dominant_file_mode=dominant_file_mode,
            work_pattern_candidate=work_pattern_candidate,
            activity_level=activity_level,
            task_confidence=task_confidence,
            mcp_action_category=(mcp_signal or {}).get("mcp_action_category"),
            mcp_is_read_only=(mcp_signal or {}).get("mcp_is_read_only"),
            mcp_decision=(mcp_signal or {}).get("mcp_decision"),
            mcp_summary=(mcp_signal or {}).get("mcp_summary"),
            terminal_action_category=(terminal_signal or {}).get("terminal_action_category"),
            terminal_project=(terminal_signal or {}).get("terminal_project"),
            terminal_cwd=(terminal_signal or {}).get("terminal_cwd"),
            terminal_exit_code=(terminal_signal or {}).get("terminal_exit_code"),
            terminal_duration_ms=(terminal_signal or {}).get("terminal_duration_ms"),
            terminal_summary=(terminal_signal or {}).get("terminal_summary"),
            terminal_command=(terminal_signal or {}).get("terminal_command"),
            terminal_success=(terminal_signal or {}).get("terminal_success"),
        )

    def _file_event_types(self) -> set[str]:
        return {
            "file_created", "file_modified", "file_renamed", "file_deleted", "file_change"
        }

    def _last_file_path(self, file_events: list) -> Optional[str]:
        event = self._latest_event(
            file_events,
            predicate=lambda item: bool(item.payload.get("path")) and item.type != "file_deleted",
        )
        if event is None:
            return None
        return event.payload.get("path")

    def _last_file_path_for_workspace(self, file_events: list, workspace_root: str) -> Optional[str]:
        event = self._latest_event(
            file_events,
            predicate=lambda item: self._file_event_matches_workspace(
                item,
                workspace_root,
            ),
        )
        if event is None:
            return None
        return event.payload.get("path")

    def _dominant_workspace_root(self, file_events: list) -> Optional[str]:
        """
        Déduit un workspace dominant à partir d'une petite fenêtre récente
        de fichiers meaningful, avec une pondération décroissante pour rester
        réactif sans suivre aveuglément le tout dernier fichier isolé.
        """
        scored_candidates: dict[str, float] = {}
        latest_rank: dict[str, int] = {}
        recent_workspace_roots: list[str] = []

        for event in self._sort_events_by_timestamp(file_events, reverse=True):
            path = event.payload.get("path")
            if not path:
                continue
            workspace_root = self._workspace_root(path)
            if not workspace_root:
                continue
            recent_workspace_roots.append(workspace_root)
            if len(recent_workspace_roots) >= 6:
                break

        if not recent_workspace_roots:
            return None

        for index, workspace_root in enumerate(recent_workspace_roots):
            weight = 0.65 ** index
            scored_candidates[workspace_root] = scored_candidates.get(workspace_root, 0.0) + weight
            latest_rank.setdefault(workspace_root, index)

        return max(
            scored_candidates,
            key=lambda root: (scored_candidates[root], -latest_rank[root]),
        )

    def _recent_apps(self, app_events: list, now: datetime) -> List[str]:
        # Apps à exclure du scoring — l'app UI de Pulse elle-même ne doit pas
        # influencer la détection de patterns de workflow.
        _IGNORED_APPS = {"Pulse", "PulseApp"}
        window_start = now - timedelta(minutes=30)
        last_seen: dict[str, tuple[datetime, int]] = {}
        for index, event in enumerate(app_events):
            if event.timestamp < window_start:
                continue
            app_name = event.payload.get("app_name")
            if not app_name or app_name in _IGNORED_APPS:
                continue
            seen = last_seen.get(app_name)
            candidate = (event.timestamp, index)
            if seen is None or candidate > seen:
                last_seen[app_name] = candidate

        ordered = sorted(last_seen.items(), key=lambda item: item[1])
        return [app_name for app_name, _ in ordered][-10:]

    def _latest_active_app(self, app_events: list, now: datetime, minutes: int) -> Optional[str]:
        """
        Retourne l'app la plus recemment activee dans la fenetre [now - minutes, now].
        Utilise pour les decisions browsing/writing qui necessitent que l'app
        soit vraiment l'app courante, pas juste la derniere vue sur 30 min.
        """
        cutoff = now - timedelta(minutes=minutes)
        event = self._latest_event(
            app_events,
            predicate=lambda item: bool(item.payload.get("app_name")),
            cutoff=cutoff,
        )
        if event is None:
            return None
        return event.payload.get("app_name")

    def _should_keep_project_hint(
        self,
        *,
        latest_active_app: Optional[str],
        has_recent_local_exploration: bool,
        mcp_signal: Optional[dict],
        terminal_signal: Optional[dict],
    ) -> bool:
        if latest_active_app in (self.DEV_APPS | self.BROWSER_APPS | self.WRITING_APPS):
            return True
        if has_recent_local_exploration:
            return True
        if self._is_usable_mcp_signal(mcp_signal):
            return True
        if self._is_usable_terminal_signal(terminal_signal):
            return True
        return False

    def _last_clipboard_context(self, clipboard_events: list, now: datetime) -> Optional[str]:
        # Le clipboard n'est un signal actif que s'il est récent.
        # Une stacktrace copiée il y a 20 min ne doit plus forcer probable_task='debug'.
        # Fenêtre de 5 min : un copier-coller pertinent est généralement utilisé
        # dans la minute qui suit, pas un quart d'heure plus tard.
        recent_window = now - timedelta(minutes=5)
        event = self._latest_event(
            clipboard_events,
            predicate=lambda item: bool(
                item.payload.get("content_kind") or item.payload.get("content_type")
            ),
            cutoff=recent_window,
        )
        if event is None:
            return None
        return event.payload.get("content_kind") or event.payload.get("content_type")

    def _has_recent_local_exploration(self, recent: list, now: datetime) -> bool:
        recent_window = now - timedelta(minutes=5)
        return any(
            event.type == "local_exploration" and event.timestamp >= recent_window
            for event in recent
        )

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
        # Seuil minimum de 3 events pour que le ratio soit significatif.
        # Avec 1-2 events, un seul rename donne 1.0 — trop bruité.
        if len(recent_file_events) < 3:
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

    # ── Scorer pondéré multi-signaux ─────────────────────────────────────────
    #
    # Poids par (signal, tâche). Un signal absent contribue 0.
    # Score minimum pour déclarer une tâche : _TASK_MIN_SCORE.
    # En dessous : "general" avec confiance faible.
    #
    # Principes de calibration :
    #   - debug est difficile à déclencher : nécessite preuve concrète
    #     (clipboard stacktrace/error, ou debug_loop_candidate seul qui
    #      est déjà très spécifique : fichier unique + friction + source/test)
    #   - high_friction seule = 0.3 → jamais assez pour passer le seuil
    #   - reading_only = 0.8 exploration → en dessous du seuil seul
    #   - browsing supprimé des tâches (→ activity_level=navigating + exploration)
    #   - executing supprimé des tâches (→ activity_level=executing)

    _TASK_MIN_SCORE: float = 1.0

    _TASK_WEIGHTS: Dict[str, Dict[str, float]] = {
        # Édition active avec app dev
        "dev_app_with_edit":     {"coding": 1.5},
        # Fichiers source/test — preuve de code
        "source_files_2plus":    {"coding": 2.0},
        # Work patterns issus de _work_pattern_candidate
        "feature_pattern":       {"coding": 2.0},
        "refactor_pattern":      {"coding": 2.0},
        "setup_pattern":         {"coding": 1.0},
        "debug_loop_pattern":    {"debug":  3.0},
        # Documentation
        "docs_only":             {"writing": 2.5},
        # Apps writing actives (fenêtre 5 min — app vraiment courante)
        "writing_app_active":    {"writing": 2.0},
        # Navigation browser sans édition (exploration, pas tâche browsing)
        "browser_navigating":    {"exploration": 1.2},
        # App dev active mais aucune édition utilisateur — lecture/réflexion
        # Poids faible : seul, passe pas le seuil → retombe sur "general"
        "reading_only":          {"exploration": 0.8},
        # Clipboard — signal secondaire, rôle de corroboration
        "clipboard_stacktrace":  {"debug": 3.0},
        "clipboard_error":       {"debug": 2.0},
        "clipboard_code":        {"coding": 0.5},
        # MCP minimal : signal d'intention/outil, pas une preuve forte seule.
        "mcp_repo_inspection":   {"exploration": 1.0},
        "mcp_inspection":        {"exploration": 1.0},
        "mcp_testing":           {"coding": 1.0},
        "mcp_modification":      {"coding": 1.0},
        "terminal_inspection":   {"exploration": 1.0},
        "terminal_testing":      {"coding": 1.0},
        "terminal_build":        {"coding": 1.0},
        "terminal_setup":        {"coding": 1.0},
        "terminal_vcs":          {"exploration": 1.0},
        # Friction seule : poids quasi-nul, jamais décisif sans autre preuve
        "high_friction":         {"debug": 0.3},
        # Diff git — signal de secours quand aucun FSEvent récent.
        # Poids intentionnellement plus faibles que les signaux FSEvents :
        # le diff dit "ces fichiers ont changé" mais pas "tu es en train de les éditer".
        "diff_source_files":     {"coding": 1.2},
        "diff_test_files":       {"coding": 1.0, "debug": 0.4},
        "diff_docs_files":       {"writing": 1.2},
        # Séquence d'apps — signal d'intention basé sur les transitions.
        # Poids faibles : corroboration uniquement, jamais décisif seul.
        "app_ai_assisted":       {"coding": 0.8},   # IA + éditeur
        "app_test_debug_cycle":  {"debug": 0.8},    # éditeur + terminal alternés
        "app_research_then_code": {"coding": 0.6},  # navigateur puis éditeur
        "app_research_only":     {"exploration": 0.6},  # navigateur seul
    }

    def _collect_active_signals(
        self,
        *,
        active_project: Optional[str],
        recent_apps: List[str],
        latest_active_app: Optional[str],
        clipboard_context: Optional[str],
        mcp_signal: Optional[dict],
        terminal_signal: Optional[dict],
        friction_score: float,
        edited_file_count: int,
        file_type_mix: Dict[str, int],
        work_pattern_candidate: Optional[str],
        diff_summary: Optional[str] = None,
    ) -> frozenset:
        active = set()
        latest_app = recent_apps[-1] if recent_apps else None
        source_count = file_type_mix.get("source", 0)
        test_count   = file_type_mix.get("test", 0)
        docs_count   = file_type_mix.get("docs", 0)
        config_count = file_type_mix.get("config", 0)

        if latest_app in self.DEV_APPS and edited_file_count >= 1:
            active.add("dev_app_with_edit")

        # source_files_2plus : 2+ fichiers source/test DISTINCTS modifiés.
        # On exige edited_file_count >= 2 pour éviter qu'un même fichier
        # modifié N fois (debug loop) soit compté comme multi-fichiers.
        if source_count + test_count >= 2 and edited_file_count >= 2:
            active.add("source_files_2plus")

        _PATTERN_MAP = {
            "feature_candidate":  "feature_pattern",
            "refactor_candidate": "refactor_pattern",
            "debug_loop_candidate": "debug_loop_pattern",
        }
        if work_pattern_candidate in _PATTERN_MAP:
            active.add(_PATTERN_MAP[work_pattern_candidate])
        if work_pattern_candidate == "setup_candidate":
            has_setup_anchor = bool(active_project) or latest_active_app in self.DEV_APPS
            if has_setup_anchor:
                active.add("setup_pattern")

        if (
            docs_count >= 2
            and (source_count + test_count) == 0
            and config_count == 0
            and latest_active_app not in self.BROWSER_APPS
            and latest_active_app is not None
        ):
            active.add("docs_only")

        # Writing app : fenêtre 5 min — l'app doit être vraiment en avant-plan.
        # Désactivé si l'utilisateur édite des fichiers source ou test :
        # Notes/Notion ouverts pendant une session de code ne signifient pas writing.
        if latest_active_app in self.WRITING_APPS and (source_count + test_count) == 0:
            active.add("writing_app_active")

        # Browser sans édition → exploration (pas une tâche "browsing").
        if latest_active_app in self.BROWSER_APPS and edited_file_count == 0:
            active.add("browser_navigating")

        # Dev app sans édition → reading (signal faible, passe pas le seuil seul).
        if latest_app in self.DEV_APPS and edited_file_count == 0:
            active.add("reading_only")

        if clipboard_context == "stacktrace":
            active.add("clipboard_stacktrace")
        elif clipboard_context == "error_message":
            active.add("clipboard_error")
        elif clipboard_context == "code":
            active.add("clipboard_code")

        if edited_file_count == 0 and self._is_usable_mcp_signal(mcp_signal):
            category = (mcp_signal or {}).get("mcp_action_category")
            if category == "repo_inspection":
                active.add("mcp_repo_inspection")
            elif category == "inspection":
                active.add("mcp_inspection")
            elif category == "testing":
                active.add("mcp_testing")
            elif category == "modification":
                has_dev_anchor = bool(active_project) or latest_active_app in self.DEV_APPS
                if has_dev_anchor:
                    active.add("mcp_modification")

        if edited_file_count == 0 and self._is_usable_terminal_signal(terminal_signal):
            category = (terminal_signal or {}).get("terminal_action_category")
            if category == "inspection":
                active.add("terminal_inspection")
            elif category == "testing":
                active.add("terminal_testing")
            elif category == "vcs":
                active.add("terminal_vcs")
            elif category == "build":
                has_dev_anchor = bool(active_project) or latest_active_app in self.DEV_APPS
                if has_dev_anchor:
                    active.add("terminal_build")
            elif category == "setup":
                has_dev_anchor = bool(active_project) or latest_active_app in self.DEV_APPS
                if has_dev_anchor:
                    active.add("terminal_setup")

        if friction_score >= 0.75:
            active.add("high_friction")

        # Diff git — signal de secours quand aucun FSEvent récent (10 min).
        # Activé uniquement si edited_file_count == 0 pour ne pas doubler
        # les signaux FSEvents déjà présents.
        if edited_file_count == 0 and diff_summary:
            diff_files = extract_file_names_from_diff_summary(diff_summary)
            diff_type_mix: Dict[str, int] = {}
            for fname in diff_files:
                ftype = self._classify_file_type(fname)
                diff_type_mix[ftype] = diff_type_mix.get(ftype, 0) + 1
            if diff_type_mix.get("source", 0) >= 1:
                active.add("diff_source_files")
            if diff_type_mix.get("test", 0) >= 1:
                active.add("diff_test_files")
            if diff_type_mix.get("docs", 0) >= 1:
                active.add("diff_docs_files")

        # Séquence d'apps — signal d'intention basé sur les transitions.
        # Détecte les patterns de workflow depuis recent_apps (30 min).
        # Activé uniquement comme corroboration — poids faibles.
        app_pattern = self._detect_app_transition_pattern(recent_apps)
        if app_pattern:
            active.add(app_pattern)

        return frozenset(active)

    def _score_tasks(self, active_signals: frozenset) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        for sig in active_signals:
            for task, weight in self._TASK_WEIGHTS.get(sig, {}).items():
                scores[task] = scores.get(task, 0.0) + weight
        return scores

    def _detect_task(
        self,
        *,
        active_project: Optional[str],
        recent_apps: List[str],
        latest_active_app: Optional[str],
        clipboard_context: Optional[str],
        mcp_signal: Optional[dict],
        terminal_signal: Optional[dict],
        friction_score: float,
        edited_file_count: int,
        file_type_mix: Dict[str, int],
        dominant_file_mode: str,
        work_pattern_candidate: Optional[str],
        diff_summary: Optional[str] = None,
    ) -> tuple:
        active = self._collect_active_signals(
            active_project=active_project,
            recent_apps=recent_apps,
            latest_active_app=latest_active_app,
            clipboard_context=clipboard_context,
            mcp_signal=mcp_signal,
            terminal_signal=terminal_signal,
            friction_score=friction_score,
            edited_file_count=edited_file_count,
            file_type_mix=file_type_mix,
            work_pattern_candidate=work_pattern_candidate,
            diff_summary=diff_summary,
        )
        scores = self._score_tasks(active)

        if not scores:
            return "general", 0.4

        best_task  = max(scores, key=scores.__getitem__)
        best_score = scores[best_task]

        if best_score < self._TASK_MIN_SCORE:
            return "general", round(0.4 + best_score * 0.1, 2)

        positive_total = sum(v for v in scores.values() if v > 0) or 1.0
        confidence = round(min(best_score / positive_total, 0.92), 2)
        return best_task, confidence

    def _detect_activity_level(
        self,
        *,
        focus_level: str,
        user_file_count: int,
        latest_active_app: Optional[str],
        recent_apps: List[str],
        has_recent_local_exploration: bool,
        mcp_signal: Optional[dict] = None,
        terminal_signal: Optional[dict] = None,
    ) -> str:
        """
        Activité bas niveau : ce que l'utilisateur fait concrètement.
        Indépendant de la tâche inférée.

        Priorité : idle > executing > editing > navigating > reading > idle
        """
        if focus_level == "idle":
            return "idle"
        if self._is_usable_mcp_signal(mcp_signal):
            category = (mcp_signal or {}).get("mcp_action_category")
            if category in {"inspection", "repo_inspection"}:
                return "reading"
            if category in {"testing", "modification", "execution"}:
                return "executing"
        if self._is_usable_terminal_signal(terminal_signal):
            category = (terminal_signal or {}).get("terminal_action_category")
            is_read_only = (terminal_signal or {}).get("terminal_is_read_only")
            if category == "inspection" or (category == "vcs" and is_read_only):
                return "reading"
            return "executing"
        if latest_active_app in self.TERMINAL_APPS:
            return "executing"
        if user_file_count >= 1:
            return "editing"
        if latest_active_app in self.BROWSER_APPS or has_recent_local_exploration:
            return "navigating"
        # App dev ou writing récente (3 dernières des 30 min) sans édition → lecture
        if recent_apps and set(recent_apps[-3:]) & (self.DEV_APPS | self.WRITING_APPS):
            return "reading"
        return "idle"

    def _detect_focus_level(
        self, recent: list, app_events: list, file_events: list, now: datetime
    ) -> str:
        recent_app_switches = [
            event for event in app_events if event.timestamp >= now - timedelta(minutes=10)
        ]
        recent_file_edits = [
            event for event in file_events if event.timestamp >= now - timedelta(minutes=10)
        ]
        recent_by_timestamp = self._sort_events_by_timestamp(recent)
        has_recent_idle_signal = any(
            event.type in {"screen_locked", "user_idle"}
            for event in recent_by_timestamp[-5:]
        )

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

    def _latest_mcp_signal(self, recent: list, now: datetime, minutes: int = 10) -> Optional[dict]:
        cutoff = now - timedelta(minutes=minutes)
        event = self._latest_event(
            recent,
            predicate=lambda item: (
                item.type in {"mcp_command_received", "mcp_decision"}
                and bool((item.payload or {}).get("mcp_action_category"))
            ),
            cutoff=cutoff,
        )
        if event is None:
            return None
        return event.payload or {}

    def _is_usable_mcp_signal(self, mcp_signal: Optional[dict]) -> bool:
        if not mcp_signal:
            return False
        return mcp_signal.get("mcp_decision") != "deny"

    def _latest_terminal_signal(self, recent: list, now: datetime, minutes: int = 10) -> Optional[dict]:
        cutoff = now - timedelta(minutes=minutes)
        event = self._latest_event(
            recent,
            predicate=lambda item: (
                item.type in {"terminal_command_started", "terminal_command_finished"}
                and bool((item.payload or {}).get("terminal_action_category"))
            ),
            cutoff=cutoff,
        )
        if event is None:
            return None
        return event.payload or {}

    def _is_usable_terminal_signal(self, terminal_signal: Optional[dict]) -> bool:
        if not terminal_signal:
            return False
        return True

    def _extract_project_from_workspace(self, workspace_root: str) -> Optional[str]:
        name = Path(workspace_root).name.strip()
        return name or None

    def _workspace_root(self, file_path: Optional[str]) -> Optional[str]:
        root = find_workspace_root(file_path)
        return str(root) if root else None

    def _classify_file_type(self, path: str) -> str:
        return classify_file_type(path)

    def _file_signal_significance(self, path: Optional[str]) -> str:
        return file_signal_significance(path)

    def _is_trackable_file_path(self, path: Optional[str]) -> bool:
        return file_signal_significance(path) != "technical_noise"

    def _is_pulse_internal_path(self, path: str) -> bool:
        return is_pulse_internal_path(path)

    def _sort_events_by_timestamp(self, events: list, *, reverse: bool = False) -> list:
        indexed = list(enumerate(events))
        indexed.sort(
            key=lambda item: (item[1].timestamp, item[0]),
            reverse=reverse,
        )
        return [event for _, event in indexed]

    def _latest_event(
        self,
        events: list,
        *,
        predicate=None,
        cutoff: Optional[datetime] = None,
    ):
        best_event = None
        best_key: tuple[datetime, int] | None = None
        for index, event in enumerate(events):
            if cutoff is not None and event.timestamp < cutoff:
                continue
            if predicate is not None and not predicate(event):
                continue
            candidate = (event.timestamp, index)
            if best_key is None or candidate > best_key:
                best_event = event
                best_key = candidate
        return best_event

    def _detect_app_transition_pattern(self, recent_apps: List[str]) -> Optional[str]:
        """
        Détecte un pattern de workflow depuis la séquence d'apps (30 min).

        Retourne un signal parmi :
          app_ai_assisted       — IA + éditeur (Claude/ChatGPT suivi d'un éditeur)
          app_test_debug_cycle  — éditeur + terminal alternés (cycle test/debug)
          app_research_then_code — navigateur puis éditeur
          app_research_only     — navigateur seul sans éditeur
          None                  — pas de pattern détectable

        La séquence est lue dans l'ordre chronologique (recent_apps[-1] = plus récente).
        """
        if not recent_apps or len(recent_apps) < 2:
            return None

        AI_APPS = {"Claude", "ChatGPT", "Gemini", "Copilot", "Codex"}

        has_ai   = any(app in AI_APPS for app in recent_apps)
        has_dev  = any(app in self.DEV_APPS for app in recent_apps)
        has_browser = any(app in self.BROWSER_APPS for app in recent_apps)
        has_terminal = any(app in self.TERMINAL_APPS for app in recent_apps)

        # IA + éditeur → assistance active
        if has_ai and has_dev:
            return "app_ai_assisted"

        # Éditeur + terminal alternés → cycle test/debug
        # Exige au moins 3 apps pour avoir une vraie alternance.
        if has_dev and has_terminal and len(recent_apps) >= 3:
            dev_terminal_switches = 0
            for i in range(1, len(recent_apps)):
                prev_is_dev = recent_apps[i - 1] in self.DEV_APPS
                curr_is_terminal = recent_apps[i] in self.TERMINAL_APPS
                prev_is_terminal = recent_apps[i - 1] in self.TERMINAL_APPS
                curr_is_dev = recent_apps[i] in self.DEV_APPS
                if (prev_is_dev and curr_is_terminal) or (prev_is_terminal and curr_is_dev):
                    dev_terminal_switches += 1
            if dev_terminal_switches >= 2:
                return "app_test_debug_cycle"

        # Navigateur puis éditeur → recherche puis implémentation
        if has_browser and has_dev:
            # Vérifier que le navigateur précède l'éditeur dans la séquence
            last_browser_idx = max(
                (i for i, app in enumerate(recent_apps) if app in self.BROWSER_APPS),
                default=-1,
            )
            last_dev_idx = max(
                (i for i, app in enumerate(recent_apps) if app in self.DEV_APPS),
                default=-1,
            )
            if last_browser_idx < last_dev_idx:
                return "app_research_then_code"

        # Navigateur seul sans éditeur
        if has_browser and not has_dev:
            return "app_research_only"

        return None

    def _file_event_matches_workspace(self, event, workspace_root: str) -> bool:
        path = event.payload.get("path")
        if not path or event.type == "file_deleted":
            return False
        return self._workspace_root(path) == workspace_root
