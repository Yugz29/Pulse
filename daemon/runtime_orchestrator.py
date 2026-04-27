from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

from daemon.memory.extractor import (
    enrich_session_report,
    find_git_root,
    get_fact_engine,
    last_session_context,
    load_memory_context,
    render_project_memory,
    read_commit_message,
    read_head_sha,
    reset_cooldown_for_tests,
    reset_fact_engine_for_tests,
    should_use_llm_for_commit,
    update_memories_from_session,
)
from daemon.core.context_formatter import (
    format_file_activity_summary,
    format_file_work_reading,
    has_informative_file_reading,
)
from daemon.core.episode_fsm import EpisodeFSM
from daemon.core.current_context_adapters import current_context_to_markdown
from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.contracts import ProposalCandidate
from daemon.core.event_bus import DEFAULT_EVENT_BUS_SIZE
from daemon.core.file_classifier import file_signal_significance
from daemon.core.git_diff import read_diff_summary, read_commit_diff_summary, extract_file_names_from_diff_summary
from daemon.core.proposal_candidate_adapter import proposal_candidate_to_proposal
from daemon.core.proposals import proposal_store
from daemon.core.session_fsm import SessionFSM
from daemon.core.uid import new_uid
from daemon.core.workspace_context import find_workspace_root


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
        commit_poll_sec: float = 0.4,
        commit_confirm_timeout_sec: float = 15.0,
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
        self.commit_poll_sec = commit_poll_sec
        self.commit_confirm_timeout_sec = commit_confirm_timeout_sec

        self._frozen_memory: str | None = None
        self._frozen_memory_at: datetime | None = None
        self._runtime_lock = threading.Lock()
        self._debounce_lock = threading.Lock()
        self._pending_file_events = []
        self._file_flush_deadline: float | None = None
        self._file_flush_condition = threading.Condition(self._debounce_lock)
        self._file_flush_stopped = False
        self._accumulated_window_titles: list[str] = []
        self._file_flush_worker = threading.Thread(
            target=self._file_flush_loop,
            daemon=True,
            name="pulse-file-burst",
        )
        self._file_flush_worker.start()
        self._last_head_sha: dict[str, str] = {}
        self._head_sha_lock = threading.Lock()
        self._commit_watch_lock = threading.Lock()
        self._pending_commit_watch: set[str] = set()
        self._diff_cooldown_sec: float = 120.0
        self._last_diff_triggered: dict[str, float] = {}
        self._diff_trigger_lock = threading.Lock()
        # Thread de sync périodique — écrit dans le journal toutes les 30 min
        # même sans commit ni screen_lock, tant qu'il y a un diff actif.
        self._periodic_sync_interval_sec: float = 30 * 60
        self._periodic_sync_stopped: bool = False
        self._periodic_sync_worker = threading.Thread(
            target=self._periodic_sync_loop,
            daemon=True,
            name="pulse-periodic-sync",
        )
        self._periodic_sync_worker.start()
        self._fact_engine = get_fact_engine()
        self._current_context_builder = CurrentContextBuilder()
        self._session_fsm = SessionFSM()
        self._episode_fsm = EpisodeFSM()

    @property
    def session_fsm(self) -> SessionFSM:
        return self._session_fsm

    @property
    def fact_engine(self):
        return self._fact_engine

    @property
    def current_episode(self):
        return self._episode_fsm.current_episode

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
        project_memory = ""
        try:
            project_memory = render_project_memory()
        except Exception as exc:
            self.log.warning("freeze_memory: render mémoire projet échoué : %s", exc)

        support_memory = ""
        try:
            support_memory = self.memory_store.render(captured_at=captured_at) or ""
        except Exception as exc:
            self.log.warning("freeze_memory: render support technique échoué : %s", exc)

        legacy = ""
        if not project_memory and not support_memory:
            self.log.warning("freeze_memory: mémoire projet absente — fallback vers legacy context")
            legacy = load_memory_context()

        # Profil utilisateur issu des faits consolidés (facts.db)
        facts_profile = ""
        try:
            facts_profile = self._fact_engine.render_for_context(limit=8)
        except Exception as exc:
            self.log.warning("freeze_memory: facts render échoué : %s", exc)

        blocks = [
            block
            for block in [project_memory, facts_profile, support_memory, legacy]
            if block.strip()
        ]
        frozen = "\n\n".join(blocks)

        with self._runtime_lock:
            self._frozen_memory = frozen or ""
            self._frozen_memory_at = captured_at
        self.log.info(
            "Mémoire figée : %d car. (%s)%s",
            len(self._frozen_memory),
            captured_at.strftime("%H:%M:%S"),
            f" — {len(facts_profile)} car. de profil utilisateur" if facts_profile else "",
        )

    def _export_memory_payload(self) -> dict:
        payload = self.session_memory.export_memory_payload()
        if isinstance(payload, dict):
            return payload
        return self.session_memory.export_session_data()

    def handle_event(self, event) -> None:
        if self._should_ignore_event(event):
            return
        if self.runtime_state.is_paused():
            return

        # Pendant le verrou écran, seuls screen_locked/screen_unlocked
        # sont traités. Les events fichier et app sont ignorés pour éviter
        # que des écritures système en arrière-plan polluent l'activité.
        _SCREEN_PASSTHROUGH = {"screen_locked", "screen_unlocked"}
        if self.runtime_state.is_screen_locked() and event.type not in _SCREEN_PASSTHROUGH:
            return

        if event.type == "screen_locked":
            self._session_fsm.on_screen_locked(when=event.timestamp)
            self._episode_fsm.on_screen_locked(when=event.timestamp)
            self.runtime_state.mark_screen_locked(when=event.timestamp)
            threading.Thread(target=self.llm_unload_background, daemon=True).start()
            # DayDream — déclenche si 23:59 est passé
            self._run_daydream_if_pending()

        elif event.type == "screen_unlocked":
            episode_locked_at = (
                self._session_fsm.last_screen_locked_at
                or self.runtime_state.get_last_screen_locked_at()
            )
            # Shim de compat Phase 2 :
            # si RuntimeState porte encore le marqueur legacy de lock mais que la FSM
            # ne l'a pas, on réinjecte ce timestamp une seule fois avant l'unlock.
            # Ce cas intervient surtout pendant la coexistence RuntimeState/FSM
            # et dans certains tests qui préparent directement RuntimeState.
            # À supprimer quand RuntimeState ne sera plus porteur du marqueur de lock
            # utilisé uniquement pour compat.
            if (
                self._session_fsm.last_screen_locked_at is None
                and self.runtime_state.get_last_screen_locked_at() is not None
            ):
                self._session_fsm.on_screen_locked(
                    when=self.runtime_state.get_last_screen_locked_at(),
                )
            transition = self._session_fsm.on_screen_unlocked(
                when=event.timestamp,
                sleep_session_threshold_min=self.sleep_session_threshold_min,
            )
            self.runtime_state.mark_screen_unlocked()
            if transition.should_reset_clock:
                sleep_min = transition.sleep_minutes or 0.0
                if transition.should_start_new_session:
                    self._refresh_runtime_signals_for_closure(drain_pending=True)
                    session_ended_at = episode_locked_at or event.timestamp
                    self._persist_episode_transition(
                        self._episode_fsm.close_current(
                            ended_at=session_ended_at,
                            boundary_reason="screen_lock",
                        )
                    )
                    self.log.info("Longue veille (%.0f min) → nouvelle session", sleep_min)
                    try:
                        snapshot = self._export_memory_payload()
                        if snapshot.get("duration_min", 0) > 0:
                            update_memories_from_session(snapshot, llm=self.summary_llm)
                    except Exception as exc:
                        self.log.warning("sync mémoire pré-reset échouée : %s", exc)
                    self.session_memory.new_session(
                        started_at=self._session_fsm.session_started_at,
                        ended_at=session_ended_at,
                    )
                    self._persist_episode_transition(
                        self._episode_fsm.ensure_active(
                            session_id=self._current_session_id(),
                            started_at=event.timestamp,
                        )
                    )
                else:
                    # Verrou court : reset du timer scorer uniquement.
                    # Le temps de veille ne doit pas s'accumuler dans session_duration_min.
                    # On ne cree pas de nouvelle session : le contexte de travail
                    # (projet, fichier actif) est conserve.
                    self.log.debug(
                        "Verrou court (%.0f min) -> reset timer scorer, session conservee",
                        sleep_min,
                    )
                    self._episode_fsm.on_screen_unlocked(
                        session_id=self._current_session_id(),
                        when=event.timestamp,
                        boundary_detected=False,
                    )
                if transition.should_clear_sleep_markers:
                    self.runtime_state.clear_sleep_markers()
            def _warmup_with_events():
                self.scorer.bus.publish("llm_loading", {"model": ""})
                self.llm_warmup_background()
                self.scorer.bus.publish("llm_ready", {"model": ""})

            threading.Thread(target=_warmup_with_events, daemon=True).start()

        self.session_memory.record_event(event)

        # Accumuler les titres de fenêtres pour DayDream
        if event.type == "app_activated":
            title = (event.payload or {}).get("window_title")
            if title and len(title) >= 15:
                self._accumulated_window_titles.append(title)

        path = (event.payload or {}).get("path", "")
        if event.type in ("file_modified", "file_created") and "/COMMIT_EDITMSG" in path:
            self._schedule_commit_watch(path)
            return

        if event.type.startswith("file_"):
            self._enqueue_file_event(event)
        else:
            self._process_signals(event)

    def shutdown_runtime(self) -> None:
        try:
            with self._file_flush_condition:
                self._file_flush_stopped = True
                self._file_flush_condition.notify_all()
            self._refresh_runtime_signals_for_closure(drain_pending=True)
            self._persist_episode_transition(
                self._episode_fsm.close_current(
                    ended_at=datetime.now(),
                    boundary_reason="session_end",
                )
            )
            snapshot = self._export_memory_payload()
            if snapshot.get("duration_min", 0) > 0:
                update_memories_from_session(snapshot)
            # Persiste l'état courant pour le prochain démarrage.
            self._save_restart_state(snapshot)
            self.session_memory.close()
        except Exception as exc:
            self.log.warning("shutdown sync failed: %s", exc)

    _RESTART_STATE_PATH = Path.home() / ".pulse" / "restart_state.json"
    _RESTART_CONTINUE_MAX_MIN = 5    # < 5 min  → reprise transparente
    _RESTART_RESUME_MAX_MIN   = 30   # 5-30 min → reprise avec note de gap

    def _save_restart_state(self, snapshot: dict) -> None:
        try:
            import json as _json
            from pathlib import Path as _Path
            state = {
                "shutdown_at": datetime.now().isoformat(),
                "active_project": snapshot.get("active_project"),
                "probable_task":  snapshot.get("probable_task"),
                "activity_level": snapshot.get("activity_level"),
                "started_at": (
                    self._session_fsm.session_started_at.isoformat()
                    if self._session_fsm.session_started_at else None
                ),
            }
            self._RESTART_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._RESTART_STATE_PATH.write_text(_json.dumps(state, ensure_ascii=False))
            self.log.info("restart state sauvegardé : %s", state)
        except Exception as exc:
            self.log.warning("restart state save échoué : %s", exc)

    def _load_restart_state(self) -> dict | None:
        try:
            import json as _json
            if not self._RESTART_STATE_PATH.exists():
                return None
            state = _json.loads(self._RESTART_STATE_PATH.read_text())
            shutdown_at = datetime.fromisoformat(state["shutdown_at"])
            elapsed_min = (datetime.now() - shutdown_at).total_seconds() / 60
            state["elapsed_min"] = elapsed_min
            return state
        except Exception as exc:
            self.log.warning("restart state load échoué : %s", exc)
            return None

    def _apply_restart_state(self, state: dict) -> None:
        elapsed_min = state.get("elapsed_min", 999)
        project = state.get("active_project")
        task = state.get("probable_task", "general")
        started_at_raw = state.get("started_at")

        if elapsed_min > self._RESTART_RESUME_MAX_MIN:
            # Trop long — nouvelle session, on oublie.
            self.log.info("restart state ignoré (%.0f min > %d min)",
                          elapsed_min, self._RESTART_RESUME_MAX_MIN)
            return

        if elapsed_min <= self._RESTART_CONTINUE_MAX_MIN:
            # Reprise transparente — on restaure le started_at original.
            if started_at_raw:
                try:
                    original_started_at = datetime.fromisoformat(started_at_raw)
                    self._session_fsm.session_started_at = original_started_at
                    self.log.info(
                        "reprise transparente (%.0f min) depuis %s",
                        elapsed_min, original_started_at.strftime("%H:%M")
                    )
                except ValueError:
                    pass
        else:
            # Zone grise 5-30 min — on reprend le contexte mais pas le timer.
            self.log.info(
                "reprise partielle (%.0f min) — contexte conservé sans timer",
                elapsed_min
            )

        # Dans les deux cas — restaurer le contexte projet/tâche.
        self.log.info("contexte restauré : projet=%s tâche=%s", project, task)

    def _daydream_scheduler(self) -> None:
        """Tourne en boucle, marque DayDream pending à 23:59 chaque jour."""
        import time as _time
        while True:
            now = datetime.now()
            # Calculer le prochain 23:59
            target = now.replace(hour=23, minute=59, second=0, microsecond=0)
            if now >= target:
                target = target.replace(day=target.day + 1)
            wait_sec = (target - now).total_seconds()
            _time.sleep(max(wait_sec, 1))
            from daemon.memory.daydream import mark_daydream_pending
            mark_daydream_pending()

    def _run_daydream_if_pending(self) -> None:
        """Lance DayDream dans un thread si le flag est actif."""
        from daemon.memory.daydream import should_trigger_daydream, trigger_daydream
        if not should_trigger_daydream():
            return
        self.log.info("DayDream : déclenchement au screen_lock.")
        llm = self.llm_runtime.provider()
        window_titles = list(self._accumulated_window_titles)
        self._accumulated_window_titles.clear()

        threading.Thread(
            target=trigger_daydream,
            kwargs={"llm": llm, "window_titles": window_titles},
            daemon=True,
            name="pulse-daydream",
        ).start()

    def build_context_snapshot(self) -> str:
        """
        Snapshot minimal du contexte courant pour le LLM.

        Principe : seuls les faits directement utiles pour répondre à une
        question ou appeler un outil. Pas de bruit, pas de duplication.

        La mémoire persistante (frozen_memory) est injectée séparément dans
        build_system_prompt() — ne pas la répéter ici.
        """
        state = self.store.to_dict()
        snapshot = self.runtime_state.get_runtime_snapshot()
        current_context = self._render_current_context(
            present=snapshot.present,
            signals=snapshot.signals,
            active_app=snapshot.latest_active_app or state.get("active_app"),
        )

        diff_summary: str | None = None
        if current_context.project_root:
            try:
                diff_summary = read_diff_summary(current_context.project_root)
            except Exception:
                diff_summary = None

        last_session_line: str | None = None
        if current_context.active_project:
            last_session_line = last_session_context(current_context.active_project)

        return current_context_to_markdown(
            current_context,
            signals=snapshot.signals,
            diff_summary=diff_summary,
            last_session_line=last_session_line,
        )

    def deferred_startup(self) -> None:
        time.sleep(0.2)
        self.llm_runtime.load_persisted_models()

        # Restaurer l'état précédent si le redémarrage est récent.
        restart_state = self._load_restart_state()
        if restart_state:
            self._apply_restart_state(restart_state)

        purged = self.memory_store.purge_expired()
        if purged:
            self.log.info("Mémoire : %d entrée(s) expirée(s) supprimée(s)", purged)

        # Purge les events bruts antérieurs à 48h depuis session.db.
        # Les sessions journalisées n'ont plus besoin de leurs events bruts.
        try:
            purged_events = self.session_memory.purge_old_events(keep_hours=48)
            if purged_events:
                self.log.info("session.db : %d event(s) anciens purgés", purged_events)
        except Exception as exc:
            self.log.warning("purge session.db échouée : %s", exc)

        try:
            archived_legacy = self._fact_engine.archive_legacy_facts()
            if archived_legacy:
                self.log.info("Facts : %d fait(s) legacy archivé(s)", archived_legacy)
        except Exception as exc:
            self.log.warning("Facts : archivage legacy échoué : %s", exc)

        # Decay des faits utilisateurs silencieux depuis > DECAY_START_DAYS jours
        try:
            decayed = self._fact_engine.decay_all()
            if decayed:
                self.log.info("Facts : decay appliqué sur %d fait(s)", decayed)
        except Exception as exc:
            self.log.warning("Facts : decay échoué : %s", exc)

        self.freeze_memory()
        provider = self.llm_runtime.provider()
        if provider and hasattr(provider, "warmup"):
            self.log.info("LLM warmup en cours (%s)...", provider.model)
            self.scorer.bus.publish("llm_loading", {"model": provider.model})
            ok = provider.warmup()
            if ok:
                self.log.info("LLM warmup terminé (%s)", provider.model)
            else:
                self.log.warning("LLM warmup échoué au démarrage (Ollama indisponible ?)")
            self.scorer.bus.publish("llm_ready", {"model": provider.model})
        self.log.info("\u2713 Init différé terminé")

        # Scheduler DayDream — déclenche le flag à 23:59 chaque jour.
        threading.Thread(
            target=self._daydream_scheduler,
            daemon=True,
            name="pulse-daydream-scheduler",
        ).start()

    def _should_ignore_event(self, event) -> bool:
        if not event.type.startswith("file_"):
            return False
        path = (event.payload or {}).get("path", "")
        if not path:
            return True
        if path.endswith(".git/COMMIT_EDITMSG") or "/COMMIT_EDITMSG" in path:
            return False
        if file_signal_significance(path) != "meaningful":
            return True
        dedupe_key = "{0}:{1}".format(event.type, path)
        return self.runtime_state.should_ignore_file_event(dedupe_key=dedupe_key)

    def _schedule_commit_watch(self, path: str) -> None:
        git_root = find_git_root(path)
        if not git_root:
            return

        root_key = str(git_root)
        with self._commit_watch_lock:
            if root_key in self._pending_commit_watch:
                return
            self._pending_commit_watch.add(root_key)

        threading.Thread(
            target=self._handle_commit_event,
            args=(path,),
            daemon=True,
        ).start()

    def _periodic_sync_loop(self) -> None:
        """
        Boucle de fond : écrit dans le journal toutes les 30 min si actif.

        Conditions pour déclencher :
        - Pas en pause, pas écran verrouillé
        - Un diff actif est disponible (activité réelle détectée)
        - Au moins 20 min de session
        - Au moins 25 min depuis le dernier sync (laisse une marge)
        """
        import time as _time
        _time.sleep(60)  # délai initial au démarrage du daemon
        while not self._periodic_sync_stopped:
            _time.sleep(self._periodic_sync_interval_sec)
            if self._periodic_sync_stopped:
                return
            try:
                if self.runtime_state.is_paused():
                    continue
                if self.runtime_state.is_screen_locked():
                    continue
                diff_summary = self.runtime_state.get_diff_summary() or None
                if not diff_summary:
                    continue
                snapshot = self.runtime_state.get_runtime_snapshot()
                if snapshot.present.session_duration_min < 20:
                    continue
                previous_sync_at = self.runtime_state.get_last_memory_sync_at()
                if previous_sync_at is not None:
                    elapsed_min = (datetime.now() - previous_sync_at).total_seconds() / 60
                    if elapsed_min < 25:
                        continue
                self.log.info("periodic sync déclenché (diff actif, %d min de session)",
                              snapshot.present.session_duration_min)
                memory_snapshot = self._export_memory_payload()
                threading.Thread(
                    target=self._sync_memory_background,
                    args=(memory_snapshot, None, None, "screen_lock", diff_summary),
                    daemon=True,
                ).start()
            except Exception as exc:
                self.log.warning("periodic sync échouée : %s", exc)

    def _trigger_diff_background(self, workspace: str) -> None:
        """Lance read_diff_summary en background avec cooldown par workspace."""
        now = time.monotonic()
        with self._diff_trigger_lock:
            last = self._last_diff_triggered.get(workspace)
            if last is not None and now - last < self._diff_cooldown_sec:
                return
            self._last_diff_triggered[workspace] = now

        def _compute() -> None:
            try:
                summary = read_diff_summary(workspace)
                if summary:
                    self.runtime_state.set_diff_summary(workspace, summary)
                    self.log.debug("diff mis à jour : %s", workspace)
            except Exception as exc:
                self.log.debug("diff échoué (%s) : %s", workspace, exc)

        threading.Thread(target=_compute, daemon=True, name="pulse-diff").start()

    def _handle_commit_event(self, path: str) -> None:
        git_root = find_git_root(path)
        if not git_root:
            return

        root_key = str(git_root)
        try:
            baseline_sha = read_head_sha(git_root)
            with self._head_sha_lock:
                previous_sha = self._last_head_sha.get(root_key)

            # Cas 1: on connaissait déjà HEAD et il a changé avant même que
            # l'event COMMIT_EDITMSG nous arrive.
            if baseline_sha and previous_sha and baseline_sha != previous_sha:
                with self._head_sha_lock:
                    self._last_head_sha[root_key] = baseline_sha
                self._process_confirmed_commit(git_root)
                return

            # Cas 2: premier commit après redémarrage. Si HEAD est tout frais,
            # on le traite immédiatement au lieu d'attendre un changement
            # supplémentaire qui n'arrivera jamais.
            if baseline_sha and previous_sha is None and self._head_commit_is_recent(git_root):
                with self._head_sha_lock:
                    self._last_head_sha[root_key] = baseline_sha
                self._process_confirmed_commit(git_root)
                return

            if baseline_sha:
                with self._head_sha_lock:
                    self._last_head_sha.setdefault(root_key, baseline_sha)

            deadline = time.monotonic() + self.commit_confirm_timeout_sec
            while time.monotonic() < deadline:
                time.sleep(self.commit_poll_sec)
                current_sha = read_head_sha(git_root)
                if not current_sha or current_sha == baseline_sha:
                    continue

                with self._head_sha_lock:
                    previous_sha = self._last_head_sha.get(root_key)
                    if current_sha == previous_sha:
                        return
                    self._last_head_sha[root_key] = current_sha

                self._process_confirmed_commit(git_root)
                return

            self.log.debug("COMMIT_EDITMSG touché sans nouveau HEAD — ignoré (%s)", root_key)
        finally:
            with self._commit_watch_lock:
                self._pending_commit_watch.discard(root_key)

    def _head_commit_is_recent(self, git_root, max_age_sec: float = 45.0) -> bool:
        """
        Retourne True si le commit HEAD a été créé récemment.
        Sert de garde-fou pour le premier commit après redémarrage quand
        COMMIT_EDITMSG est reçu après l'avancement de HEAD.
        """
        try:
            result = subprocess.run(
                ["git", "show", "-s", "--format=%ct", "HEAD"],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode != 0:
                return False
            ts = int(result.stdout.strip())
            age = time.time() - ts
            return 0 <= age <= max_age_sec
        except Exception:
            return False

    def _process_confirmed_commit(self, git_root) -> None:
        commit_msg = read_commit_message(git_root)
        self.log.info(
            "Commit git confirmé [%s] : %s",
            git_root.name,
            (commit_msg or "").splitlines()[0] if commit_msg else "(sans message)",
        )
        self._refresh_runtime_signals_for_closure(drain_pending=True)
        self._persist_episode_transition(
            self._episode_fsm.on_commit(
                session_id=self._current_session_id(),
                when=datetime.now(),
            )
        )

        diff_summary: str | None = None
        try:
            diff_summary = read_commit_diff_summary(git_root) or None
        except Exception:
            pass

        snapshot = self._export_memory_payload()
        threading.Thread(
            target=self._sync_memory_background,
            args=(snapshot, self.summary_llm, commit_msg, "commit", diff_summary),
            daemon=True,
        ).start()

    def _enqueue_file_event(self, event) -> None:
        with self._file_flush_condition:
            self._pending_file_events.append(event)
            self._file_flush_deadline = time.monotonic() + self.file_debounce_sec
            self._file_flush_condition.notify_all()

    def _file_flush_loop(self) -> None:
        while True:
            with self._file_flush_condition:
                while not self._file_flush_stopped and not self._pending_file_events:
                    self._file_flush_condition.wait()
                if self._file_flush_stopped:
                    return
                deadline = self._file_flush_deadline
                if deadline is None:
                    self._file_flush_condition.wait()
                    continue
                wait_sec = max(deadline - time.monotonic(), 0.0)
                if wait_sec > 0:
                    self._file_flush_condition.wait(timeout=wait_sec)
                    continue
            self._flush_file_events()

    def _flush_file_events(self) -> None:
        with self._debounce_lock:
            events = self._pending_file_events[:]
            self._pending_file_events = []
            self._file_flush_deadline = None
        self._process_file_burst(events)

    def _process_signals(self, trigger_event) -> None:
        if trigger_event.type == "user_idle":
            self._session_fsm.on_user_idle()

        previous_activity = self._session_fsm.last_meaningful_activity_at
        previous_present = self.runtime_state.get_runtime_snapshot().present
        recent_events = self.scorer.bus.recent(DEFAULT_EVENT_BUS_SIZE)
        observed_now = self._observed_now(
            trigger_event=trigger_event,
            recent_events=recent_events,
            previous_present=previous_present,
        )
        lifecycle_transition = self._session_fsm.observe_recent_events(
            recent_events=recent_events,
            now=observed_now,
        )

        if lifecycle_transition.boundary_detected:
            self.log.info(
                "Frontière session : reason=%s sleep=%.0fmin new_session=%s",
                lifecycle_transition.boundary_reason,
                lifecycle_transition.sleep_minutes or 0,
                lifecycle_transition.should_start_new_session,
            )
            try:
                snapshot = self._export_memory_payload()
                if snapshot.get("duration_min", 0) >= 5:
                    threading.Thread(
                        target=self._sync_memory_background,
                        args=(snapshot, None, None, "screen_lock"),
                        daemon=True,
                    ).start()
            except Exception as exc:
                self.log.warning("session boundary flush échouée : %s", exc)
            if lifecycle_transition.should_start_new_session:
                self._refresh_runtime_signals_for_closure(drain_pending=True)
                session_ended_at = previous_activity
                if lifecycle_transition.boundary_reason == "idle":
                    self._persist_episode_transition(
                        self._episode_fsm.on_idle_timeout(
                            session_id=None,
                            last_meaningful_activity_at=previous_activity,
                            resumed_at=None,
                        )
                    )
                elif lifecycle_transition.boundary_reason == "screen_lock":
                    locked_at = self._latest_screen_lock_after(
                        recent_events=recent_events,
                        since=previous_activity,
                    )
                    session_ended_at = locked_at or previous_activity or datetime.now()
                    self._persist_episode_transition(
                        self._episode_fsm.close_current(
                            ended_at=session_ended_at,
                            boundary_reason="screen_lock",
                        )
                    )
                self.session_memory.new_session(
                    started_at=self._session_fsm.session_started_at,
                    ended_at=session_ended_at,
                )

        project_hint = None
        if (
            not lifecycle_transition.should_start_new_session
            and lifecycle_transition.state != SessionFSM.LOCKED
        ):
            project_hint = previous_present.active_project

        signals = self.scorer.compute(
            session_started_at=self._session_fsm.session_started_at,
            observed_now=observed_now,
            project_hint=project_hint,
            diff_summary=self.runtime_state.get_diff_summary() or None,
        )
        present = self.runtime_state.update_present(
            signals=signals,
            session_status=lifecycle_transition.state,
            awake=lifecycle_transition.state != SessionFSM.LOCKED,
            locked=lifecycle_transition.state == SessionFSM.LOCKED,
            updated_at=observed_now,
        )
        previous_decision = self.runtime_state.get_runtime_snapshot().decision
        decision = self.decision_engine.evaluate(present, trigger_event=trigger_event)
        decision = self._attach_context_proposal_if_needed(
            present=present,
            signals=signals,
            decision=decision,
            previous_decision=previous_decision,
            trigger_event=trigger_event,
        )
        episode_transition = self._episode_fsm.ensure_active(
            session_id=self._current_session_id(),
            started_at=self._session_fsm.last_meaningful_activity_at,
        )
        semantic_transition = self._episode_fsm.on_semantic_signal(
            session_id=self._current_session_id(),
            when=observed_now,
            active_project=present.active_project,
            probable_task=present.probable_task,
            task_confidence=getattr(signals, "task_confidence", 0.0),
        )
        if (
            semantic_transition.boundary_detected
            or semantic_transition.closed_episode is not None
            or semantic_transition.opened_episode is not None
        ):
            episode_transition = semantic_transition
        episode_transition = self._bind_live_semantics_to_active_episode(
            episode_transition,
            present=present,
            signals=signals,
        )
        self._persist_episode_transition(episode_transition)
        self.session_memory.update_present_snapshot(
            present,
            signals=signals,
        )
        previous_sync_at = self.runtime_state.get_last_memory_sync_at()
        should_sync = self._should_sync_memory(trigger_event.type, present, previous_sync_at)
        self.runtime_state.set_analysis(
            signals=signals,
            decision=decision,
        )
        if should_sync:
            snapshot = self._export_memory_payload()
            llm = self._summary_llm_for(trigger_event.type, present)
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

    def _attach_context_proposal_if_needed(
        self,
        *,
        present,
        signals,
        decision,
        previous_decision,
        trigger_event,
    ):
        if not self._should_emit_context_proposal(decision, previous_decision):
            return decision

        candidate = self._build_context_injection_candidate(
            present=present,
            signals=signals,
            decision=decision,
            trigger_event=trigger_event,
        )
        proposal = proposal_candidate_to_proposal(
            candidate,
            proposal_id=new_uid(),
        )
        proposal_store.add(proposal)
        proposal_store.resolve(proposal.id, "executed")

        payload = dict(decision.payload or {})
        payload["proposal_id"] = proposal.id
        return replace(decision, payload=payload)

    def _should_emit_context_proposal(self, decision, previous_decision) -> bool:
        if decision.action != "inject_context" or decision.reason != "context_ready":
            return False
        if previous_decision is None:
            return True
        previous_payload = self._normalized_decision_payload(previous_decision.payload)
        current_payload = self._normalized_decision_payload(decision.payload)
        return not (
            previous_decision.action == decision.action
            and previous_decision.reason == decision.reason
            and previous_payload == current_payload
        )

    def _normalized_decision_payload(self, payload):
        normalized = dict(payload or {})
        normalized.pop("proposal_id", None)
        return normalized

    def _build_context_injection_candidate(
        self,
        *,
        present,
        signals,
        decision,
        trigger_event,
    ) -> ProposalCandidate:
        payload = dict(decision.payload or {})
        evidence = [
            {"kind": "project", "label": "Projet", "value": present.active_project or "inconnu"},
            {"kind": "task", "label": "Tâche", "value": present.probable_task or "general"},
            {"kind": "focus", "label": "Focus", "value": present.focus_level},
            {
                "kind": "session",
                "label": "Durée session",
                "value": f"{present.session_duration_min} min",
            },
        ]
        file_activity = format_file_activity_summary(signals)
        if file_activity:
            evidence.append({
                "kind": "file_activity",
                "label": "Activité fichiers",
                "value": file_activity,
            })
        if has_informative_file_reading(signals):
            file_reading = format_file_work_reading(signals)
            if file_reading:
                evidence.append({
                    "kind": "file_reading",
                    "label": "Lecture de la session",
                    "value": file_reading,
                })
        if present.active_file:
            evidence.append({"kind": "file", "label": "Fichier actif", "value": present.active_file})

        return ProposalCandidate(
            type="context_injection",
            trigger=trigger_event.type,
            decision_action=decision.action,
            decision_reason=decision.reason,
            evidence=evidence,
            confidence=0.66,
            proposed_action="inject_current_context",
            details={
                "decision_action": decision.action,
                "decision_reason": decision.reason,
                "project": present.active_project,
                "task": present.probable_task,
                "focus_level": present.focus_level,
                "session_duration_min": present.session_duration_min,
                "active_file": present.active_file,
                "edited_file_count_10m": signals.edited_file_count_10m,
                "file_type_mix_10m": dict(signals.file_type_mix_10m),
                "rename_delete_ratio_10m": signals.rename_delete_ratio_10m,
                "dominant_file_mode": signals.dominant_file_mode,
                "work_pattern_candidate": signals.work_pattern_candidate,
                "decision_payload": payload,
            },
        )

    def _sync_memory_background(
        self,
        snapshot: dict,
        llm,
        commit_message: str | None = None,
        trigger: str = "screen_lock",
        diff_summary: str | None = None,
    ) -> None:
        try:
            if diff_summary is None:
                diff_summary = self.runtime_state.get_diff_summary() or None
            top_files = snapshot.get("top_files", []) or []
            files_count = snapshot.get("files_changed", 0) or 0
            defer_llm = (
                trigger == "commit"
                and llm is not None
                and should_use_llm_for_commit(
                    diff_summary=diff_summary,
                    top_files=top_files,
                    files_count=files_count,
                )
            )
            report_ref = update_memories_from_session(
                snapshot,
                llm=llm,
                commit_message=commit_message,
                trigger=trigger,
                diff_summary=diff_summary,
                defer_llm_enrichment=defer_llm,
            )
            if report_ref is None:
                self.log.info(
                    "memory sync skipped project=%s duration=%smin trigger=%s",
                    snapshot.get("active_project"),
                    snapshot.get("duration_min"),
                    trigger,
                )
                return

            runtime_snapshot = self.runtime_state.get_runtime_snapshot()
            self.runtime_state.set_analysis(
                signals=runtime_snapshot.signals,
                decision=runtime_snapshot.decision,
                memory_synced_at=datetime.now(),
            )
            self.log.info(
                "memory sync ok project=%s duration=%smin trigger=%s",
                snapshot.get("active_project"),
                snapshot.get("duration_min"),
                trigger,
            )
            # Rafraîchit la mémoire injectée dans le prompt après chaque sync.
            # Garantit que les nouveaux faits consolidés sont visibles
            # sans attendre le prochain redémarrage du daemon.
            self.freeze_memory()
            if defer_llm and report_ref is not None:
                threading.Thread(
                    target=self._enrich_commit_summary_background,
                    args=(report_ref, snapshot, llm, commit_message, diff_summary),
                    daemon=True,
                ).start()
        except Exception as exc:
            self.log.warning("memory sync échouée : %s", exc)

    def _enrich_commit_summary_background(
        self,
        report_ref,
        snapshot: dict,
        llm,
        commit_message: str | None,
        diff_summary: str | None,
    ) -> None:
        started_at = time.monotonic()
        model = getattr(llm, "get_model", lambda: "unknown")() if llm is not None else "unknown"
        try:
            ok = enrich_session_report(
                report_ref,
                snapshot,
                llm,
                commit_message=commit_message,
                diff_summary=diff_summary,
            )
            latency_ms = int((time.monotonic() - started_at) * 1000)
            project = snapshot.get("active_project")
            if ok:
                self.log.info(
                    f"llm_request_terminal request_kind=commit_summary status=success "
                    f"provider=ollama model={model} latency_ms={latency_ms} project={project}",
                )
                self.freeze_memory()
            else:
                self.log.warning(
                    f"llm_request_terminal request_kind=commit_summary status=invalid "
                    f"provider=ollama model={model} latency_ms={latency_ms} project={project} "
                    f"reason=entry_not_found",
                )
        except Exception as exc:
            latency_ms = int((time.monotonic() - started_at) * 1000)
            project = snapshot.get("active_project")
            self.log.error(
                f"llm_request_terminal request_kind=commit_summary status=error "
                f"provider=ollama model={model} latency_ms={latency_ms} project={project} "
                f"reason={exc.__class__.__name__.lower()}",
            )

    def _should_sync_memory(self, event_type, present, previous_sync_at) -> bool:
        if present.session_duration_min < 20:
            if not self.runtime_state.get_diff_summary():
                return False
        if event_type in {"screen_locked", "user_idle", "screen_unlocked"}:
            # Cooldown court pour éviter les doubles syncs sur events rapprochés
            if previous_sync_at is not None:
                elapsed = (datetime.now() - previous_sync_at).total_seconds()
                if elapsed < 60:  # moins d'1 minute → on skip
                    return False
            return True
        if previous_sync_at is None:
            return True
        return datetime.now() - previous_sync_at >= timedelta(minutes=10)

    def _summary_llm_for(self, event_type, present):
        if present.session_duration_min < 20:
            return None
        if event_type == "commit":
            return self.summary_llm
        return None

    def reset_for_tests(self) -> None:
        with self._debounce_lock:
            self._pending_file_events = []
            self._file_flush_deadline = None
            self._file_flush_stopped = False
        if self._file_flush_worker is None or not self._file_flush_worker.is_alive():
            self._file_flush_worker = threading.Thread(
                target=self._file_flush_loop,
                daemon=True,
                name="pulse-file-burst",
            )
            self._file_flush_worker.start()
        self._periodic_sync_stopped = True
        with self._commit_watch_lock:
            self._pending_commit_watch = set()
        with self._head_sha_lock:
            self._last_head_sha = {}
        with self._diff_trigger_lock:
            self._last_diff_triggered = {}
        with self._runtime_lock:
            self._frozen_memory = None
            self._frozen_memory_at = None
        reset_fact_engine_for_tests()
        reset_cooldown_for_tests()
        self._fact_engine = get_fact_engine()
        self._session_fsm.reset_for_tests()
        self._episode_fsm.reset_for_tests()
        proposal_store.clear()

    def _persist_episode_transition(self, transition) -> None:
        if transition is None:
            return
        if transition.closed_episode is not None:
            self.session_memory.save_episode(
                self._freeze_closed_episode_semantics(transition.closed_episode)
            )
        if transition.opened_episode is not None:
            self.session_memory.save_episode(transition.opened_episode)
        elif transition.current_episode is not None:
            self.session_memory.save_episode(transition.current_episode)

    def _bind_live_semantics_to_active_episode(self, transition, *, present, signals):
        if transition is None:
            return transition
        if (
            self._episode_fsm.semantic_boundary_pending
            and transition.opened_episode is None
            and transition.closed_episode is None
        ):
            return None
        updated = self._episode_fsm.sync_current_semantics(
            active_project=present.active_project,
            probable_task=present.probable_task,
            activity_level=present.activity_level,
            task_confidence=getattr(signals, "task_confidence", 0.0),
        )
        if updated is None:
            if transition.opened_episode is None and transition.closed_episode is None:
                return None
            return transition
        opened_episode = transition.opened_episode
        if opened_episode is not None and opened_episode.id == updated.id:
            opened_episode = updated
        return replace(
            transition,
            opened_episode=opened_episode,
            current_episode=updated,
        )

    def _freeze_closed_episode_semantics(self, episode):
        snapshot = self.runtime_state.get_runtime_snapshot()
        present = snapshot.present
        signals = snapshot.signals
        if episode is None:
            return episode
        active_project = episode.active_project or present.active_project
        if episode.probable_task is not None:
            probable_task = episode.probable_task
        elif signals is None:
            probable_task = "unknown"
        else:
            probable_task = present.probable_task or "unknown"
        if episode.activity_level is not None:
            activity_level = episode.activity_level
        elif signals is None:
            activity_level = "idle"
        else:
            activity_level = present.activity_level or "idle"
        if episode.task_confidence is not None:
            task_confidence = episode.task_confidence
        else:
            task_confidence = getattr(signals, "task_confidence", None)
            if task_confidence is None:
                task_confidence = 0.0
        return replace(
            episode,
            active_project=active_project,
            probable_task=probable_task,
            activity_level=activity_level,
            task_confidence=task_confidence,
        )

    def _refresh_runtime_signals_for_closure(self, *, drain_pending: bool) -> None:
        if drain_pending:
            self._drain_pending_file_events()
        snapshot = self.runtime_state.get_runtime_snapshot()
        signals = self.scorer.compute(
            session_started_at=self._session_fsm.session_started_at,
            observed_now=(
                snapshot.present.updated_at
                or self._session_fsm.last_meaningful_activity_at
            ),
            project_hint=snapshot.present.active_project,
            diff_summary=self.runtime_state.get_diff_summary() or None,
        )
        if signals is None or not hasattr(signals, "session_duration_min"):
            return
        decision = self.runtime_state.get_runtime_snapshot().decision
        try:
            present = self.runtime_state.update_present(
                signals=signals,
                session_status=self._session_fsm.state,
                awake=self._session_fsm.state != SessionFSM.LOCKED,
                locked=self._session_fsm.state == SessionFSM.LOCKED,
            )
        except Exception as exc:
            self.log.warning("refresh signaux pré-fermeture échoué : %s", exc)
            return
        semantic_update = self._episode_fsm.sync_current_semantics(
            active_project=present.active_project,
            probable_task=present.probable_task,
            activity_level=present.activity_level,
            task_confidence=getattr(signals, "task_confidence", 0.0),
        )
        if semantic_update is not None:
            self.session_memory.save_episode(semantic_update)
        self.session_memory.update_present_snapshot(
            present,
            signals=signals,
        )
        self.runtime_state.set_analysis(
            signals=signals,
            decision=decision,
        )

    def _render_current_context(self, *, present, signals, active_app: str | None):
        return self._current_context_builder.build(
            present=present,
            active_app=active_app,
            signals=signals,
            find_git_root_fn=find_git_root,
            find_workspace_root_fn=find_workspace_root,
        )

    def _drain_pending_file_events(self) -> None:
        with self._debounce_lock:
            events = self._pending_file_events[:]
            self._pending_file_events = []
            self._file_flush_deadline = None
        self._process_file_burst(events)

    def _process_file_burst(self, events) -> None:
        if not events:
            return
        self.log.debug("file burst flush n=%d", len(events))
        trigger = self._latest_event_by_timestamp(
            events,
            predicate=lambda event: event.type != "file_deleted",
        )
        if trigger is None:
            trigger = self._latest_event_by_timestamp(events) or events[-1]
        self._process_signals(trigger)
        snapshot = self.runtime_state.get_runtime_snapshot()
        workspace = None
        if snapshot.present.active_file:
            root = find_workspace_root(snapshot.present.active_file)
            if root:
                workspace = str(root)
        if workspace:
            self._trigger_diff_background(workspace)

    @staticmethod
    def _latest_event_by_timestamp(events, predicate=None):
        best_event = None
        best_key = None
        for index, event in enumerate(events):
            if predicate is not None and not predicate(event):
                continue
            candidate = (event.timestamp, index)
            if best_key is None or candidate > best_key:
                best_event = event
                best_key = candidate
        return best_event

    @classmethod
    def _observed_now(cls, *, trigger_event, recent_events, previous_present):
        candidates = [trigger_event.timestamp]
        latest_recent = cls._latest_event_by_timestamp(recent_events)
        if latest_recent is not None:
            candidates.append(latest_recent.timestamp)
        if previous_present.updated_at is not None:
            candidates.append(previous_present.updated_at)
        return max(candidates)

    def _current_session_id(self) -> str | None:
        session_id = getattr(self.session_memory, "session_id", None)
        if isinstance(session_id, str) and session_id:
            return session_id
        return None

    @staticmethod
    def _latest_screen_lock_after(recent_events, since):
        if since is None:
            return None
        lock_at = None
        for event in recent_events:
            if event.type != "screen_locked" or event.timestamp <= since:
                continue
            if lock_at is None or event.timestamp > lock_at:
                lock_at = event.timestamp
        return lock_at
