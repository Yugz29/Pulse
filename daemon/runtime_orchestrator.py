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
from daemon.core.file_classifier import file_signal_significance
from daemon.core.git_diff import read_diff_summary, read_commit_diff_summary
from daemon.core.proposals import Proposal, proposal_store
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
        self._file_debounce_timer: threading.Timer | None = None
        self._pending_file_events = []
        self._last_head_sha: dict[str, str] = {}
        self._head_sha_lock = threading.Lock()
        self._commit_watch_lock = threading.Lock()
        self._pending_commit_watch: set[str] = set()
        self._fact_engine = get_fact_engine()
        # Dernière valeur connue du compteur de resets d'inactivité du scorer.
        # Quand il augmente, le scorer a détecté une nouvelle frontière de session.
        self._last_scorer_reset_count: int = 0

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

        # Profil utilisateur issu des faits consolidés (facts.db)
        facts_profile = ""
        try:
            facts_profile = self._fact_engine.render_for_context(limit=8)
        except Exception as exc:
            self.log.warning("freeze_memory: facts render échoué : %s", exc)

        blocks = [b for b in [structured or legacy, facts_profile] if b.strip()]
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
            self.runtime_state.mark_screen_locked()
            threading.Thread(target=self.llm_unload_background, daemon=True).start()

        elif event.type == "screen_unlocked":
            self.runtime_state.mark_screen_unlocked()
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
            self._schedule_commit_watch(path)
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
        """
        Snapshot minimal du contexte courant pour le LLM.

        Principe : seuls les faits directement utiles pour répondre à une
        question ou appeler un outil. Pas de bruit, pas de duplication.

        La mémoire persistante (frozen_memory) est injectée séparément dans
        build_system_prompt() — ne pas la répéter ici.
        """
        state = self.store.to_dict()
        signals, _ = self.runtime_state.get_context_snapshot()

        # C4 — Signals est prioritaire sur StateStore pour active_file et active_project.
        # Raison : signals.active_file vient de _last_file_path() qui exclut file_deleted
        # et opère sur une fenêtre courante. StateStore.active_file ne se réinitialise
        # jamais à None — il peut pointer un fichier obsolète depuis le démarrage du daemon.
        # Fallback sur state uniquement si signals n'a pas de valeur courante.
        active_project = (signals.active_project if signals else None) or state.get("active_project")
        active_file    = (signals.active_file    if signals else None) or state.get("active_file")
        active_app = state.get("active_app")

        # C5 — Signals est la source de vérité pour la durée de session.
        # StateStore.session_start est figé au démarrage du daemon et n'est jamais
        # resynchronisé sur les frontières de session. Sa valeur est quasi-toujours
        # supérieure ou égale à la vraie durée. On préfère 0 à une durée fausse.
        if signals and signals.session_duration_min > 0:
            session_duration_min = signals.session_duration_min
        else:
            session_duration_min = 0

        # Racine git pour les outils
        project_root: str | None = None
        if active_file:
            try:
                git_root = find_git_root(active_file)
                if git_root:
                    project_root = str(git_root)
                else:
                    workspace_root = find_workspace_root(active_file)
                    if workspace_root:
                        project_root = str(workspace_root)
            except Exception:
                try:
                    workspace_root = find_workspace_root(active_file)
                    if workspace_root:
                        project_root = str(workspace_root)
                except Exception:
                    pass

        lines = [
            "# Contexte session",
            f"- Projet : {active_project or 'non détecté'}",
            f"- Racine projet : {project_root or 'inconnue'}",
            f"- Fichier actif : {active_file or 'aucun'}",
            f"- App active : {active_app or 'inconnue'}",
            f"- Durée session : {session_duration_min or 0} min",
        ]

        if signals:
            lines += [
                f"- Tâche probable : {signals.probable_task}",
                f"- Focus : {signals.focus_level}",
            ]
            file_activity = format_file_activity_summary(signals)
            if file_activity:
                lines.append(f"- Activité fichiers : {file_activity}")
            if has_informative_file_reading(signals):
                file_reading = format_file_work_reading(signals)
                if file_reading:
                    lines.append(f"- Lecture de la session : {file_reading}")
            if signals.recent_apps:
                lines.append(f"- Apps récentes : {', '.join(signals.recent_apps[:4])}")

        # Diff git — ce qui a réellement changé dans le code
        if project_root:
            try:
                diff = read_diff_summary(project_root)
                if diff:
                    lines.append(f"- {diff.replace(chr(10), chr(10) + '  ')}")
            except Exception:
                pass

        # Continuité projet — la dernière session connue pour ce projet
        # last_session_context() retourne None proprement si donnée absente.
        if active_project:
            session_ctx = last_session_context(active_project)
            if session_ctx:
                lines.append(f"- {session_ctx}")

        return "\n".join(lines)

    def deferred_startup(self) -> None:
        time.sleep(0.2)
        self.llm_runtime.load_persisted_models()
        purged = self.memory_store.purge_expired()
        if purged:
            self.log.info("Mémoire : %d entrée(s) expirée(s) supprimée(s)", purged)

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

        diff_summary: str | None = None
        try:
            diff_summary = read_commit_diff_summary(git_root) or None
        except Exception:
            pass

        snapshot = self.session_memory.export_session_data()
        threading.Thread(
            target=self._sync_memory_background,
            args=(snapshot, self.summary_llm, commit_msg, "commit", diff_summary),
            daemon=True,
        ).start()

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
        # On préfère le dernier event non-delete comme trigger pour _process_signals.
        # Un burst se terminant par file_deleted (ex. refactoring avec suppression finale)
        # ne doit pas bloquer inject_context : DecisionEngine n'accepte pas file_deleted
        # comme trigger valide dans _can_emit_context_proposal.
        # Fallback sur events[-1] uniquement si tout le burst est composé de deletions.
        trigger = next(
            (e for e in reversed(events) if e.type != "file_deleted"),
            events[-1],
        )
        self._process_signals(trigger)

    def _process_signals(self, trigger_event) -> None:
        signals = self.scorer.compute()

        # Détection de frontière de session par inactivité :
        # si le scorer a reset son horloge (gap > timeout ou screen_lock),
        # on synchro la session mémoire pour éviter la divergence de durée.
        current_reset_count = self.scorer.inactivity_reset_count
        if current_reset_count > self._last_scorer_reset_count:
            self._last_scorer_reset_count = current_reset_count
            self.log.info(
                "Session boundary detected (inactivity/screen_lock) — flushing session memory"
            )
            try:
                snapshot = self.session_memory.export_session_data()
                if snapshot.get("duration_min", 0) >= 5:
                    threading.Thread(
                        target=self._sync_memory_background,
                        args=(snapshot, None, None, "screen_lock"),
                        daemon=True,
                    ).start()
            except Exception as exc:
                self.log.warning("session boundary flush échouée : %s", exc)
            self.session_memory.new_session()

        self.session_memory.update_signals(signals)
        _, previous_decision = self.runtime_state.get_context_snapshot()
        decision = self.decision_engine.evaluate(signals, trigger_event=trigger_event)
        decision = self._attach_context_proposal_if_needed(
            signals=signals,
            decision=decision,
            previous_decision=previous_decision,
            trigger_event=trigger_event,
        )
        previous_sync_at = self.runtime_state.get_last_memory_sync_at()
        should_sync = self._should_sync_memory(trigger_event.type, signals, previous_sync_at)
        self.runtime_state.set_analysis(
            signals=signals,
            decision=decision,
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

    def _attach_context_proposal_if_needed(self, *, signals, decision, previous_decision, trigger_event):
        if not self._should_emit_context_proposal(decision, previous_decision):
            return decision

        proposal = self._build_context_injection_proposal(
            signals=signals,
            decision=decision,
            trigger_event=trigger_event,
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

    def _build_context_injection_proposal(self, *, signals, decision, trigger_event) -> Proposal:
        payload = dict(decision.payload or {})
        evidence = [
            {"kind": "project", "label": "Projet", "value": signals.active_project or "inconnu"},
            {"kind": "task", "label": "Tâche", "value": signals.probable_task or "general"},
            {"kind": "focus", "label": "Focus", "value": signals.focus_level},
            {
                "kind": "session",
                "label": "Durée session",
                "value": f"{signals.session_duration_min} min",
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
        if signals.active_file:
            evidence.append({"kind": "file", "label": "Fichier actif", "value": signals.active_file})

        proposal = Proposal(
            id=new_uid(),
            type="context_injection",
            trigger=trigger_event.type,
            title="Contexte de session prêt à être injecté",
            summary="Le contexte local est jugé assez riche pour une réponse assistée.",
            rationale="La session a accumulé assez de contexte local pour justifier une injection de contexte existante.",
            evidence=evidence,
            confidence=0.66,
            proposed_action="inject_current_context",
            metadata={
                "details": {
                    "decision_action": decision.action,
                    "decision_reason": decision.reason,
                    "project": signals.active_project,
                    "task": signals.probable_task,
                    "focus_level": signals.focus_level,
                    "session_duration_min": signals.session_duration_min,
                    "active_file": signals.active_file,
                    "edited_file_count_10m": signals.edited_file_count_10m,
                    "file_type_mix_10m": dict(signals.file_type_mix_10m),
                    "rename_delete_ratio_10m": signals.rename_delete_ratio_10m,
                    "dominant_file_mode": signals.dominant_file_mode,
                    "work_pattern_candidate": signals.work_pattern_candidate,
                    "decision_payload": payload,
                },
            },
        )
        return proposal

    def _sync_memory_background(
        self,
        snapshot: dict,
        llm,
        commit_message: str | None = None,
        trigger: str = "screen_lock",
        diff_summary: str | None = None,
    ) -> None:
        try:
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

            signals, decision = self.runtime_state.get_context_snapshot()
            self.runtime_state.set_analysis(
                signals=signals,
                decision=decision,
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

    def _should_sync_memory(self, event_type, signals, previous_sync_at) -> bool:
        if signals.session_duration_min < 20:
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

    def _summary_llm_for(self, event_type, signals):
        if signals.session_duration_min < 20:
            return None
        if event_type == "commit":
            return self.summary_llm
        return None

    def reset_for_tests(self) -> None:
        with self._debounce_lock:
            if self._file_debounce_timer is not None:
                self._file_debounce_timer.cancel()
            self._file_debounce_timer = None
            self._pending_file_events = []
        with self._commit_watch_lock:
            self._pending_commit_watch = set()
        with self._head_sha_lock:
            self._last_head_sha = {}
        with self._runtime_lock:
            self._frozen_memory = None
            self._frozen_memory_at = None
        reset_fact_engine_for_tests()
        reset_cooldown_for_tests()
        self._fact_engine = get_fact_engine()
        proposal_store.clear()
