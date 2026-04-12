from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from daemon.memory.extractor import (
    find_git_root,
    load_memory_context,
    read_commit_message,
    read_head_sha,
    update_memories_from_session,
)


class RuntimeOrchestrator:
    def __init__(
        self,
        *,
        store,
        scorer,
        decision_engine,
        summary_llm,
        session_memory,
        memory_store,
        runtime_state,
        llm_runtime,
        log,
        sleep_session_threshold_min: int = 30,
        file_debounce_sec: float = 0.25,
    ) -> None:
        self.store = store
        self.scorer = scorer
        self.decision_engine = decision_engine
        self.summary_llm = summary_llm
        self.session_memory = session_memory
        self.memory_store = memory_store
        self.runtime_state = runtime_state
        self.llm_runtime = llm_runtime
        self.log = log
        self.sleep_session_threshold_min = sleep_session_threshold_min
        self.file_debounce_sec = file_debounce_sec

        self._frozen_memory: str | None = None
        self._frozen_memory_at: datetime | None = None
        self._runtime_lock = threading.Lock()
        self._debounce_lock = threading.Lock()
        self._file_debounce_timer: threading.Timer | None = None
        self._pending_file_events = []
        self._last_head_sha: dict[str, str] = {}
        self._head_sha_lock = threading.Lock()

    def llm_unload_background(self) -> None:
        self.llm_runtime.unload_background(self.log)

    def llm_warmup_background(self) -> None:
        self.llm_runtime.warmup_background(self.log)

    def get_frozen_memory(self) -> str:
        with self._runtime_lock:
            return self._frozen_memory or ""

    def get_frozen_memory_at(self):
        return self._frozen_memory_at

    def freeze_memory(self) -> None:
        captured_at = datetime.now()
        structured = self.memory_store.render(captured_at=captured_at)
        legacy = load_memory_context() if not structured else ""
        with self._runtime_lock:
            self._frozen_memory = structured or legacy or ""
            self._frozen_memory_at = captured_at
        self.log.info(
            "Mémoire figée au démarrage : %d car. (%s)",
            len(self._frozen_memory or ""),
            captured_at.strftime("%H:%M:%S"),
        )

    def handle_event(self, event) -> None:
        if self._should_ignore_event(event):
            return
        if self.runtime_state.is_paused():
            return

        if event.type == "screen_locked":
            self.runtime_state.mark_screen_locked()
            threading.Thread(target=self.llm_unload_background, daemon=True).start()

        elif event.type == "screen_unlocked":
            locked_at = self.runtime_state.get_last_screen_locked_at()
            if locked_at is not None:
                sleep_min = (datetime.now() - locked_at).total_seconds() / 60
                if sleep_min >= self.sleep_session_threshold_min:
                    self.log.info("Longue veille (%.0f min) → nouvelle session", sleep_min)
                    try:
                        snapshot = self.session_memory.export_session_data()
                        if snapshot.get("duration_min", 0) > 0:
                            update_memories_from_session(snapshot, llm=self.summary_llm)
                    except Exception as exc:
                        self.log.warning("sync mémoire pré-reset échouée : %s", exc)
                    self.scorer.reset_session()
                    self.session_memory.new_session()
                    self.runtime_state.clear_sleep_markers()
            threading.Thread(target=self.llm_warmup_background, daemon=True).start()

        self.session_memory.record_event(event)

        path = (event.payload or {}).get("path", "")
        if event.type in ("file_modified", "file_created") and "/COMMIT_EDITMSG" in path:
            threading.Thread(target=self._handle_commit_event, args=(path,), daemon=True).start()
            return

        if event.type.startswith("file_"):
            self._enqueue_file_event(event)
        else:
            self._process_signals(event)

    def shutdown_runtime(self) -> None:
        try:
            snapshot = self.session_memory.export_session_data()
            if snapshot.get("duration_min", 0) > 0:
                update_memories_from_session(snapshot)
            self.session_memory.close()
        except Exception as exc:
            self.log.warning("shutdown sync failed: %s", exc)

    def build_context_snapshot(self) -> str:
        state = self.store.to_dict()
        session_data = self.session_memory.export_session_data()
        recent_events = self.session_memory.get_recent_events(limit=8)
        memory_context = self.get_frozen_memory()
        signals, decision = self.runtime_state.get_context_snapshot()

        sections = [
            "# Pulse Context Snapshot",
            "",
            "## État courant",
            "- Projet : {0}".format(state.get("active_project") or "non détecté"),
            "- Fichier actif : {0}".format(state.get("active_file") or "inconnu"),
            "- App active : {0}".format(state.get("active_app") or "inconnue"),
            "- Durée session : {0} min".format(state.get("session_duration_min", 0)),
            "- Dernier event : {0}".format(state.get("last_event_type") or "inconnu"),
        ]

        if signals:
            sections.extend(
                [
                    "",
                    "## Signaux",
                    "- Tâche probable : {0}".format(signals.probable_task),
                    "- Focus : {0}".format(signals.focus_level),
                    "- Friction : {0:.2f}".format(signals.friction_score),
                    "- Clipboard : {0}".format(signals.clipboard_context or "aucun"),
                    "- Apps récentes : {0}".format(", ".join(signals.recent_apps) or "aucune"),
                ]
            )

        if decision:
            sections.extend(
                [
                    "",
                    "## Dernière décision",
                    "- Action : {0}".format(decision.action),
                    "- Niveau : {0}".format(decision.level),
                    "- Raison : {0}".format(decision.reason),
                ]
            )
            if decision.payload:
                parts = ["{0}={1}".format(k, v) for k, v in sorted(decision.payload.items())]
                sections.append("- Payload : {0}".format(", ".join(parts)))

        sections.extend(
            [
                "",
                "## Session",
                "- ID : {0}".format(session_data.get("session_id") or "inconnu"),
                "- Fichiers modifiés : {0}".format(session_data.get("files_changed", 0)),
                "- Events : {0}".format(session_data.get("event_count", 0)),
                "- Friction max : {0:.2f}".format(float(session_data.get("max_friction", 0.0))),
            ]
        )

        if recent_events:
            sections.extend(["", "## Events récents"])
            for event in recent_events:
                payload = event.get("payload") or {}
                key = (
                    payload.get("app_name")
                    or payload.get("path")
                    or payload.get("content_kind")
                    or payload.get("tool_use_id")
                    or payload.get("decision")
                )
                suffix = " ({0})".format(key) if key else ""
                sections.append(
                    "- {0}: {1}{2}".format(
                        event.get("timestamp", "?"),
                        event.get("type", "?"),
                        suffix,
                    )
                )

        if memory_context:
            sections.extend(["", "## Mémoire persistante", memory_context.strip()])

        return "\n".join(sections).strip() + "\n"

    def deferred_startup(self) -> None:
        time.sleep(0.2)
        self.llm_runtime.load_persisted_models()
        purged = self.memory_store.purge_expired()
        if purged:
            self.log.info("Mémoire : %d entrée(s) expirée(s) supprimée(s)", purged)
        self.freeze_memory()
        provider = self.llm_runtime.provider()
        if provider and hasattr(provider, "warmup"):
            self.log.info("LLM warmup en cours (%s)...", provider.model)
            ok = provider.warmup()
            if ok:
                self.log.info("LLM warmup terminé (%s)", provider.model)
            else:
                self.log.warning("LLM warmup échoué au démarrage (Ollama indisponible ?)")
        self.log.info("✓ Init différé terminé")

    def _should_ignore_event(self, event) -> bool:
        if not event.type.startswith("file_"):
            return False
        path = (event.payload or {}).get("path", "")
        if not path:
            return True

        if path.endswith(".git/COMMIT_EDITMSG") or "/COMMIT_EDITMSG" in path:
            return False

        if not self._is_meaningful_file_path(path):
            return True
        dedupe_key = "{0}:{1}".format(event.type, path)
        return self.runtime_state.should_ignore_file_event(dedupe_key=dedupe_key)

    def _handle_commit_event(self, path: str) -> None:
        git_root = find_git_root(path)
        if not git_root:
            return

        current_sha = read_head_sha(git_root)
        root_key = str(git_root)

        with self._head_sha_lock:
            previous_sha = self._last_head_sha.get(root_key)
            self._last_head_sha[root_key] = current_sha or ""

        if not current_sha or current_sha == previous_sha:
            self.log.debug("COMMIT_EDITMSG touché mais HEAD inchangé — ignoré (%s)", root_key)
            return

        commit_msg = read_commit_message(git_root)
        self.log.info(
            "Commit git confirmé [%s] : %s",
            git_root.name,
            (commit_msg or "").splitlines()[0] if commit_msg else "(sans message)",
        )

        snapshot = self.session_memory.export_session_data()
        threading.Thread(
            target=self._sync_memory_background,
            args=(snapshot, self.summary_llm, commit_msg, "commit"),
            daemon=True,
        ).start()

    def _is_meaningful_file_path(self, path: str) -> bool:
        if not path:
            return False
        name = path.split("/")[-1]
        if name.startswith("."):
            return False
        if name.endswith((".DS_Store", "~", ".xcuserstate")):
            return False
        if ".sb-" in name:
            return False
        if any(
            segment in path
            for segment in ("/.git/", "/node_modules/", "/__pycache__/", "/xcuserdata/", "/DerivedData/")
        ):
            return False
        return True

    def _enqueue_file_event(self, event) -> None:
        with self._debounce_lock:
            self._pending_file_events.append(event)
            if self._file_debounce_timer is not None:
                self._file_debounce_timer.cancel()
            timer = threading.Timer(self.file_debounce_sec, self._flush_file_events)
            timer.daemon = True
            self._file_debounce_timer = timer
            timer.start()

    def _flush_file_events(self) -> None:
        with self._debounce_lock:
            events = self._pending_file_events[:]
            self._pending_file_events = []
            self._file_debounce_timer = None
        if not events:
            return
        self.log.debug("file burst flush n=%d", len(events))
        self._process_signals(events[-1])

    def _process_signals(self, trigger_event) -> None:
        signals = self.scorer.compute()
        self.session_memory.update_signals(signals)
        decision = self.decision_engine.evaluate(signals, trigger_event=trigger_event)
        previous_sync_at = self.runtime_state.get_last_memory_sync_at()
        should_sync = self._should_sync_memory(trigger_event.type, signals, previous_sync_at)
        self.runtime_state.set_analysis(
            signals=signals,
            decision=decision,
            memory_synced_at=datetime.now() if should_sync else None,
        )
        if should_sync:
            snapshot = self.session_memory.export_session_data()
            llm = self._summary_llm_for(trigger_event.type, signals)
            trigger_map = {
                "screen_locked": "screen_lock",
                "screen_unlocked": "screen_lock",
                "user_idle": "user_idle",
            }
            trigger = trigger_map.get(trigger_event.type, "screen_lock")
            threading.Thread(
                target=self._sync_memory_background,
                args=(snapshot, llm, None, trigger),
                daemon=True,
            ).start()
        if decision.action != "silent":
            self.log.info(
                "decision=%s level=%s reason=%s",
                decision.action,
                decision.level,
                decision.reason,
            )

    def _sync_memory_background(
        self,
        snapshot: dict,
        llm,
        commit_message: str | None = None,
        trigger: str = "screen_lock",
    ) -> None:
        try:
            update_memories_from_session(
                snapshot,
                llm=llm,
                commit_message=commit_message,
                trigger=trigger,
            )
            self.log.info(
                "memory sync ok project=%s duration=%smin trigger=%s",
                snapshot.get("active_project"),
                snapshot.get("duration_min"),
                trigger,
            )
        except Exception as exc:
            self.log.warning("memory sync échouée : %s", exc)

    def _should_sync_memory(self, event_type, signals, previous_sync_at) -> bool:
        if signals.session_duration_min < 20:
            return False
        if event_type in {"screen_locked", "user_idle", "screen_unlocked"}:
            return True
        if previous_sync_at is None:
            return True
        return datetime.now() - previous_sync_at >= timedelta(minutes=10)

    def _summary_llm_for(self, event_type, signals):
        if signals.session_duration_min < 20:
            return None
        if event_type in {"screen_locked", "user_idle"}:
            return self.summary_llm
        if signals.focus_level == "idle":
            return self.summary_llm
        return None

    def reset_for_tests(self) -> None:
        with self._debounce_lock:
            if self._file_debounce_timer is not None:
                self._file_debounce_timer.cancel()
            self._file_debounce_timer = None
            self._pending_file_events = []
        with self._head_sha_lock:
            self._last_head_sha = {}
        with self._runtime_lock:
            self._frozen_memory = None
            self._frozen_memory_at = None
