from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
import subprocess

from daemon.memory.extractor import (
    enrich_session_report,
    find_git_root,
    get_fact_engine,
    last_session_context,
    load_memory_context,
    read_commit_file_names,
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
from daemon.core.current_context_adapters import current_context_to_markdown
from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.contracts import ProposalCandidate, SessionContext
from daemon.core.event_bus import DEFAULT_EVENT_BUS_SIZE
from daemon.core.file_classifier import file_signal_significance
from daemon.core.git_diff import read_diff_summary, read_commit_diff_summary, extract_file_names_from_diff_summary
from daemon.core.proposal_candidate_adapter import proposal_candidate_to_proposal
from daemon.core.proposals import proposal_store
from daemon.core.resume_card import (
    build_resume_card_context,
    generate_resume_card,
    should_offer_resume_card,
)
from daemon.core.session_fsm import SessionFSM
from daemon.core.uid import new_uid
from daemon.core.restart_manager import RestartManager
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
        self._last_resume_card_at: datetime | None = None
        self._pending_resume_card_lock = threading.Lock()
        self._pending_resume_card = False
        self._resume_card_wait_timeout_sec: float = 90.0
        self._resume_card_wait_poll_sec: float = 0.5
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
        self._restart_manager = RestartManager()

    @property
    def session_fsm(self) -> SessionFSM:
        return self._session_fsm

    @property
    def current_context(self) -> SessionContext | None:
        snapshot = self.runtime_state.get_runtime_snapshot()
        present = snapshot.present
        session = self.session_memory.get_session()
        started_at = (
            self._session_fsm.session_started_at.isoformat()
            if self._session_fsm.session_started_at
            else session.get("started_at")
        )
        if not started_at:
            return None

        duration_sec = None
        if present.session_duration_min is not None:
            duration_sec = max(int(present.session_duration_min), 0) * 60

        signals = snapshot.signals
        task_confidence = getattr(signals, "task_confidence", None) if signals is not None else None
        return SessionContext(
            id=f"current-{self.session_memory.session_id}",
            session_id=self.session_memory.session_id,
            started_at=started_at,
            ended_at=None,
            boundary_reason=None,
            duration_sec=duration_sec,
            active_project=present.active_project or session.get("active_project"),
            probable_task=present.probable_task or session.get("probable_task"),
            activity_level=present.activity_level,
            task_confidence=task_confidence,
        )

    @property
    def fact_engine(self):
        return self._fact_engine

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
        return self.session_memory.export_memory_payload()

    def handle_event(self, event) -> None:
        if self._should_ignore_event(event):
            return
        if event.type == "resume_card":
            return
        if self.runtime_state.is_paused():
            return

        _SCREEN_PASSTHROUGH = {"screen_locked", "screen_unlocked"}
        if self.runtime_state.is_screen_locked() and event.type not in _SCREEN_PASSTHROUGH:
            return

        resume_sleep_minutes: float | None = None

        if event.type == "screen_locked":
            self._session_fsm.on_screen_locked(when=event.timestamp)
            self.runtime_state.mark_screen_locked(when=event.timestamp)
            threading.Thread(target=self.llm_unload_background, daemon=True).start()
            self._run_daydream_if_pending()

        elif event.type == "screen_unlocked":
            self._run_daydream_if_pending()
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
            resume_sleep_minutes = transition.sleep_minutes
            self.runtime_state.mark_screen_unlocked()
            if transition.should_reset_clock:
                sleep_min = transition.sleep_minutes or 0.0
                if transition.should_start_new_session:
                    self._refresh_runtime_signals_for_closure(drain_pending=True)
                    self.log.info("Longue veille (%.0f min) → nouvelle session", sleep_min)
                    try:
                        snapshot = self._export_memory_payload()
                        if snapshot.get("duration_min", 0) > 0:
                            update_memories_from_session(snapshot, llm=self.summary_llm)
                    except Exception as exc:
                        self.log.warning("sync mémoire pré-reset échouée : %s", exc)
                    self.session_memory.new_session(
                        started_at=self._session_fsm.session_started_at,
                        ended_at=self.runtime_state.get_last_screen_locked_at() or event.timestamp,
                        close_reason="screen_lock",
                    )
                else:
                    self.log.debug(
                        "Verrou court (%.0f min) -> reset timer scorer, session conservée",
                        sleep_min,
                    )
                if transition.should_clear_sleep_markers:
                    self.runtime_state.clear_sleep_markers()

            def _warmup_with_events():
                self.scorer.bus.publish("llm_loading", {"model": ""})
                self.llm_warmup_background()
                self.scorer.bus.publish("llm_ready", {"model": ""})

            threading.Thread(target=_warmup_with_events, daemon=True).start()

        self.session_memory.record_event(event)

        if event.type in {"app_activated", "window_title_poll"}:
            title = (event.payload or {}).get("window_title") or (event.payload or {}).get("title")
            if title and len(title) >= 15:
                self._accumulated_window_titles.append(title)

        if event.type == "claude_desktop_session":
            title = (event.payload or {}).get("title", "")
            cwd   = (event.payload or {}).get("cwd", "")
            if title:
                self._accumulated_window_titles.append(f"Claude: {title}")
            if cwd:
                try:
                    from daemon.core.workspace_context import extract_project_name
                    project = extract_project_name(cwd)
                    if project:
                        self.log.debug("claude_desktop_session : projet=%s titre=%s", project, title)
                except Exception:
                    pass

        path = (event.payload or {}).get("path", "")
        if event.type in ("file_modified", "file_created") and "/COMMIT_EDITMSG" in path:
            self._schedule_commit_watch(path)
            return

        if event.type.startswith("file_"):
            self._enqueue_file_event(event)
        else:
            self._process_signals(event)
            if event.type == "screen_unlocked":
                self._maybe_emit_resume_card(
                    event=event,
                    sleep_minutes=resume_sleep_minutes,
                )

    def _maybe_emit_resume_card(
        self,
        *,
        event,
        sleep_minutes: float | None,
        memory_payload: dict | None = None,
        event_type: str | None = None,
    ) -> None:
        try:
            snapshot = self.runtime_state.get_runtime_snapshot()
            payload = memory_payload if isinstance(memory_payload, dict) else self._export_memory_payload()
            active_project = snapshot.present.active_project or payload.get("active_project")
            if not should_offer_resume_card(
                event_type=event_type or event.type,
                sleep_minutes=sleep_minutes,
                active_project=active_project,
                memory_payload=payload,
                last_offered_at=self._last_resume_card_at,
                now=event.timestamp,
            ):
                return
            context = build_resume_card_context(
                runtime_snapshot=snapshot,
                memory_payload=payload,
                sleep_minutes=sleep_minutes,
                diff_summary=snapshot.last_diff_summary,
            )
            should_wait_for_llm = (
                self._resume_card_can_use_llm()
                and (
                    event_type in {None, "screen_unlocked", "resume_after_pause"}
                    or event.type == "screen_unlocked"
                )
            )
            self._last_resume_card_at = event.timestamp
            if should_wait_for_llm:
                self._schedule_resume_card_emit(
                    context=context,
                    event_timestamp=event.timestamp,
                    wait_for_llm=True,
                )
            else:
                self._emit_resume_card_now(context=context, emitted_at=event.timestamp)
        except Exception as exc:
            self.log.warning("resume_card skipped: %s", exc)

    def _resume_card_can_use_llm(self) -> bool:
        return self.summary_llm is not None and hasattr(self.summary_llm, "complete")

    def _emit_resume_card_now(self, *, context: dict, emitted_at: datetime, force_fallback: bool = False) -> None:
        llm = None if force_fallback else self.summary_llm
        card = generate_resume_card(context, llm=llm)
        self.scorer.bus.publish("resume_card", card.to_event_payload(), emitted_at)
        self.log.info(
            "resume_card emitted project=%s generated_by=%s confidence=%.2f fallback=%s",
            card.project,
            card.generated_by,
            card.confidence,
            force_fallback,
        )

    def _schedule_resume_card_emit(self, *, context: dict, event_timestamp: datetime, wait_for_llm: bool) -> None:
        with self._pending_resume_card_lock:
            if self._pending_resume_card:
                self.log.debug("resume_card already pending — skip duplicate schedule")
                return
            self._pending_resume_card = True

        threading.Thread(
            target=self._emit_resume_card_background,
            kwargs={
                "context": context,
                "event_timestamp": event_timestamp,
                "wait_for_llm": wait_for_llm,
            },
            daemon=True,
            name="pulse-resume-card",
        ).start()

    def _emit_resume_card_background(self, *, context: dict, event_timestamp: datetime, wait_for_llm: bool) -> None:
        try:
            llm_ready = True
            if wait_for_llm:
                llm_ready = self._wait_for_llm_ready_for_resume(since=event_timestamp)
            if llm_ready:
                self._emit_resume_card_now(context=context, emitted_at=datetime.now())
            else:
                self._emit_resume_card_now(context=context, emitted_at=datetime.now(), force_fallback=True)
        except Exception as exc:
            self.log.warning("resume_card background emit skipped: %s", exc)
        finally:
            with self._pending_resume_card_lock:
                self._pending_resume_card = False

    def _wait_for_llm_ready_for_resume(self, *, since: datetime) -> bool:
        deadline = time.monotonic() + self._resume_card_wait_timeout_sec
        saw_loading = False
        while time.monotonic() < deadline:
            recent = self.scorer.bus.recent(DEFAULT_EVENT_BUS_SIZE)
            for item in recent:
                if item.timestamp < since:
                    continue
                if item.type == "llm_loading":
                    saw_loading = True
                if item.type == "llm_ready":
                    if saw_loading:
                        self.log.debug("resume_card: LLM ready observed after unlock")
                    return True
            time.sleep(self._resume_card_wait_poll_sec)
        self.log.warning(
            "resume_card: LLM readiness timeout after %.0fs — using deterministic fallback",
            self._resume_card_wait_timeout_sec,
        )
        return False

    def shutdown_runtime(self) -> None:
        try:
            with self._file_flush_condition:
                self._file_flush_stopped = True
                self._file_flush_condition.notify_all()
            self._refresh_runtime_signals_for_closure(drain_pending=True)
            snapshot = self._export_memory_payload()
            if snapshot.get("duration_min", 0) > 0:
                update_memories_from_session(snapshot)
            self._restart_manager.save(snapshot, session_fsm=self._session_fsm)
            self.session_memory.close(close_reason="session_end")
        except Exception as exc:
            self.log.warning("shutdown sync failed: %s", exc)

    def _daydream_scheduler(self) -> None:
        import time as _time
        from datetime import timedelta
        while True:
            now = datetime.now()
            target = now.replace(hour=23, minute=59, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_sec = (target - now).total_seconds()
            _time.sleep(max(wait_sec, 1))
            from daemon.memory.daydream import mark_daydream_pending
            mark_daydream_pending()
            if self.runtime_state.is_screen_locked():
                self._run_daydream_if_pending()

    def _run_daydream_if_pending(self) -> None:
        from daemon.memory.daydream import claim_daydream_run, trigger_daydream
        ref_date = claim_daydream_run()
        if ref_date is None:
            return
        self.log.info("DayDream : déclenchement au screen_lock pour %s.", ref_date)
        llm = self.llm_runtime.provider()
        window_titles = list(self._accumulated_window_titles)
        self._accumulated_window_titles.clear()
        threading.Thread(
            target=trigger_daydream,
            kwargs={"llm": llm, "window_titles": window_titles, "ref_date": ref_date},
            daemon=True,
            name="pulse-daydream",
        ).start()

    def build_context_snapshot(self) -> str:
        snapshot = self.runtime_state.get_runtime_snapshot()
        current_context = self._render_current_context(
            present=snapshot.present,
            signals=snapshot.signals,
            active_app=snapshot.latest_active_app,
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

        restart_state = self._restart_manager.load()
        if restart_state:
            self._restart_manager.apply(
                restart_state,
                session_fsm=self._session_fsm,
                session_memory=self.session_memory,
            )
            self._restart_manager.recover_missed_commits(
                restart_state,
                summary_llm=self.summary_llm,
            )

        purged = self.memory_store.purge_expired()
        if purged:
            self.log.info("Mémoire : %d entrée(s) expirée(s) supprimée(s)", purged)

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
        self._recover_missed_daydream()
        self.log.info("\u2713 Init différé terminé")

        threading.Thread(
            target=self._daydream_scheduler,
            daemon=True,
            name="pulse-daydream-scheduler",
        ).start()

    def _recover_missed_daydream(self) -> None:
        try:
            from daemon.memory.daydream import mark_daydream_pending
            yesterday = (datetime.now() - timedelta(days=1)).date()
            mark_daydream_pending(ref_date=yesterday)
            self._run_daydream_if_pending()
        except Exception as exc:
            self.log.warning("DayDream catch-up échoué : %s", exc)

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
        import time as _time
        _time.sleep(60)
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

            if baseline_sha and previous_sha and baseline_sha != previous_sha:
                with self._head_sha_lock:
                    self._last_head_sha[root_key] = baseline_sha
                self._process_confirmed_commit(git_root)
                return

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
        commit_at = datetime.now()
        commit_msg = read_commit_message(git_root)
        self.log.info(
            "Commit git confirmé [%s] : %s",
            git_root.name,
            (commit_msg or "").splitlines()[0] if commit_msg else "(sans message)",
        )
        self._refresh_runtime_signals_for_closure(drain_pending=True)

        diff_summary: str | None = None
        try:
            diff_summary = read_commit_diff_summary(git_root) or None
        except Exception:
            pass

        snapshot = self._export_memory_payload()
        snapshot["active_project"] = git_root.name or snapshot.get("active_project")
        diff_files = extract_file_names_from_diff_summary(diff_summary or "")
        commit_scope_files = diff_files or read_commit_file_names(git_root)
        if diff_files:
            snapshot["top_files"] = diff_files[:5]
            snapshot["files_changed"] = max(
                int(snapshot.get("files_changed", 0) or 0),
                len(diff_files),
            )
        snapshot["commit_scope_files"] = commit_scope_files[:8]
        self._annotate_commit_work_block(
            snapshot,
            commit_at=commit_at,
            commit_scope_files=commit_scope_files,
            git_root=git_root,
        )
        threading.Thread(
            target=self._sync_memory_background,
            args=(snapshot, self.summary_llm, commit_msg, "commit", diff_summary),
            daemon=True,
        ).start()

    def _annotate_commit_work_block(
        self,
        snapshot: dict,
        *,
        commit_at: datetime,
        commit_scope_files: list[str] | None = None,
        git_root=None,
    ) -> None:
        snapshot["delivered_at"] = commit_at.isoformat()
        activity_window = None
        if commit_scope_files:
            try:
                activity_window = self.session_memory.find_file_activity_window(
                    commit_scope_files,
                    before=commit_at,
                    repo_root=str(git_root) if git_root is not None else None,
                )
            except Exception as exc:
                self.log.warning("commit activity window introuvable : %s", exc)

        if isinstance(activity_window, dict):
            started_at = _parse_optional_datetime(activity_window.get("started_at"))
            ended_at = _parse_optional_datetime(activity_window.get("ended_at"))
            if started_at is not None and ended_at is not None and ended_at >= started_at:
                snapshot["commit_activity_started_at"] = started_at.isoformat()
                snapshot["commit_activity_ended_at"] = ended_at.isoformat()
                snapshot["commit_activity_event_count"] = int(activity_window.get("event_count") or 0)
                self._set_commit_work_block(snapshot, started_at=started_at, ended_at=ended_at)
                return

        work_block_started_at = _parse_optional_datetime(
            snapshot.get("work_block_started_at") or snapshot.get("work_window_started_at")
        )
        if work_block_started_at is None:
            work_block_started_at = self._session_fsm.session_started_at
        runtime_snapshot = self.runtime_state.get_runtime_snapshot()
        payload_block_end = _parse_optional_datetime(snapshot.get("work_block_ended_at") or snapshot.get("work_window_ended_at"))
        block_end = payload_block_end or runtime_snapshot.present.updated_at or commit_at
        if block_end < commit_at:
            block_end = commit_at

        if work_block_started_at is not None:
            self._set_commit_work_block(snapshot, started_at=work_block_started_at, ended_at=block_end)
        elif snapshot.get("started_at"):
            snapshot["work_block_started_at"] = snapshot.get("started_at")
            snapshot["work_window_started_at"] = snapshot.get("started_at")
            snapshot["work_block_ended_at"] = block_end.isoformat()
            snapshot["work_window_ended_at"] = block_end.isoformat()

    def _annotate_commit_work_window(self, *args, **kwargs) -> None:
        """Alias legacy pour les tests/outils qui utilisent encore work_window."""
        self._annotate_commit_work_block(*args, **kwargs)

    @staticmethod
    def _set_commit_work_block(snapshot: dict, *, started_at: datetime, ended_at: datetime) -> None:
        snapshot["work_block_started_at"] = started_at.isoformat()
        snapshot["work_block_ended_at"] = ended_at.isoformat()
        snapshot["work_window_started_at"] = snapshot["work_block_started_at"]
        snapshot["work_window_ended_at"] = snapshot["work_block_ended_at"]

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

        resume_memory_payload: dict | None = None
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
                resume_memory_payload = snapshot
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
                if lifecycle_transition.boundary_reason == "screen_lock":
                    locked_at = self._latest_screen_lock_after(
                        recent_events=recent_events,
                        since=previous_activity,
                    )
                    session_ended_at = locked_at or previous_activity or datetime.now()
                self.session_memory.new_session(
                    started_at=self._session_fsm.session_started_at,
                    ended_at=session_ended_at,
                    close_reason="idle_timeout" if lifecycle_transition.boundary_reason == "idle" else "screen_lock",
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
        self.session_memory.update_present_snapshot(present, signals=signals)
        previous_sync_at = self.runtime_state.get_last_memory_sync_at()
        should_sync = self._should_sync_memory(trigger_event.type, present, previous_sync_at)
        self.runtime_state.set_analysis(signals=signals, decision=decision)
        if (
            lifecycle_transition.boundary_detected
            and lifecycle_transition.should_start_new_session
            and lifecycle_transition.sleep_minutes is not None
        ):
            self._maybe_emit_resume_card(
                event=trigger_event,
                sleep_minutes=lifecycle_transition.sleep_minutes,
                memory_payload=resume_memory_payload,
                event_type="resume_after_pause",
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

    def _attach_context_proposal_if_needed(self, *, present, signals, decision, previous_decision, trigger_event):
        if not self._should_emit_context_proposal(decision, previous_decision):
            return decision
        candidate = self._build_context_injection_candidate(
            present=present, signals=signals, decision=decision, trigger_event=trigger_event,
        )
        proposal = proposal_candidate_to_proposal(candidate, proposal_id=new_uid())
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

    def _build_context_injection_candidate(self, *, present, signals, decision, trigger_event) -> ProposalCandidate:
        payload = dict(decision.payload or {})
        evidence = [
            {"kind": "project", "label": "Projet", "value": present.active_project or "inconnu"},
            {"kind": "task", "label": "Tâche", "value": present.probable_task or "general"},
            {"kind": "focus", "label": "Focus", "value": present.focus_level},
            {"kind": "session", "label": "Durée session", "value": f"{present.session_duration_min} min"},
        ]
        file_activity = format_file_activity_summary(signals)
        if file_activity:
            evidence.append({"kind": "file_activity", "label": "Activité fichiers", "value": file_activity})
        if has_informative_file_reading(signals):
            file_reading = format_file_work_reading(signals)
            if file_reading:
                evidence.append({"kind": "file_reading", "label": "Lecture de la session", "value": file_reading})
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

    def _sync_memory_background(self, snapshot, llm, commit_message=None, trigger="screen_lock", diff_summary=None):
        try:
            if diff_summary is None:
                diff_summary = self.runtime_state.get_diff_summary() or None
            top_files = snapshot.get("top_files", []) or []
            files_count = snapshot.get("files_changed", 0) or 0
            defer_llm = (
                trigger == "commit"
                and llm is not None
                and should_use_llm_for_commit(diff_summary=diff_summary, top_files=top_files, files_count=files_count)
            )
            report_ref = update_memories_from_session(
                snapshot, llm=llm, commit_message=commit_message,
                trigger=trigger, diff_summary=diff_summary, defer_llm_enrichment=defer_llm,
            )
            if report_ref is None:
                self.log.info(
                    "memory sync skipped project=%s duration=%smin trigger=%s",
                    snapshot.get("active_project"), snapshot.get("duration_min"), trigger,
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
                snapshot.get("active_project"), snapshot.get("duration_min"), trigger,
            )
            self.freeze_memory()
            if defer_llm and report_ref is not None:
                threading.Thread(
                    target=self._enrich_commit_summary_background,
                    args=(report_ref, snapshot, llm, commit_message, diff_summary),
                    daemon=True,
                ).start()
        except Exception as exc:
            self.log.warning("memory sync échouée : %s", exc)

    def _enrich_commit_summary_background(self, report_ref, snapshot, llm, commit_message, diff_summary):
        started_at = time.monotonic()
        model = getattr(llm, "get_model", lambda: "unknown")() if llm is not None else "unknown"
        try:
            ok = enrich_session_report(report_ref, snapshot, llm, commit_message=commit_message, diff_summary=diff_summary)
            latency_ms = int((time.monotonic() - started_at) * 1000)
            project = snapshot.get("active_project")
            if ok:
                self.log.info(f"llm_request_terminal request_kind=commit_summary status=success provider=ollama model={model} latency_ms={latency_ms} project={project}")
                self.freeze_memory()
            else:
                self.log.warning(f"llm_request_terminal request_kind=commit_summary status=invalid provider=ollama model={model} latency_ms={latency_ms} project={project} reason=entry_not_found")
        except Exception as exc:
            latency_ms = int((time.monotonic() - started_at) * 1000)
            project = snapshot.get("active_project")
            self.log.error(f"llm_request_terminal request_kind=commit_summary status=error provider=ollama model={model} latency_ms={latency_ms} project={project} reason={exc.__class__.__name__.lower()}")

    def _should_sync_memory(self, event_type, present, previous_sync_at) -> bool:
        if present.session_duration_min < 20:
            if not self.runtime_state.get_diff_summary():
                return False
        if event_type in {"screen_locked", "user_idle", "screen_unlocked"}:
            if previous_sync_at is not None:
                elapsed = (datetime.now() - previous_sync_at).total_seconds()
                if elapsed < 60:
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
        self._last_resume_card_at = None
        with self._pending_resume_card_lock:
            self._pending_resume_card = False
        reset_fact_engine_for_tests()
        reset_cooldown_for_tests()
        self._fact_engine = get_fact_engine()
        self._session_fsm.reset_for_tests()
        proposal_store.clear()

    def _refresh_runtime_signals_for_closure(self, *, drain_pending: bool) -> None:
        if drain_pending:
            self._drain_pending_file_events()
        snapshot = self.runtime_state.get_runtime_snapshot()
        signals = self.scorer.compute(
            session_started_at=self._session_fsm.session_started_at,
            observed_now=(snapshot.present.updated_at or self._session_fsm.last_meaningful_activity_at),
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
        self.session_memory.update_present_snapshot(present, signals=signals)
        self.runtime_state.set_analysis(signals=signals, decision=decision)

    def _render_current_context(self, *, present, signals, active_app):
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
        trigger = self._latest_event_by_timestamp(events, predicate=lambda e: e.type != "file_deleted")
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


def _parse_optional_datetime(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
