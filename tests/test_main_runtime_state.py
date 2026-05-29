import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ["HOME"] = _TEST_HOME

import daemon.main as daemon_main
from daemon.core.decision_engine import Decision
from daemon.core.signal_scorer import Signals
from daemon.runtime_state import WorkIntent


class TestMainRuntimeState(unittest.TestCase):
    def setUp(self):
        daemon_main.runtime_state.reset_for_tests()
        daemon_main.runtime_orchestrator.reset_for_tests()
        daemon_main.bus.clear()
        self.client = daemon_main.app.test_client()

    def tearDown(self):
        daemon_main.runtime_orchestrator.reset_for_tests()

    def test_state_exposes_runtime_signals_and_decision(self):
        daemon_main.runtime_state.set_paused(True)
        signals = Signals(
            active_project="Pulse",
            active_file="/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
            probable_task="coding",
            friction_score=0.42,
            focus_level="deep",
            session_duration_min=96,
            recent_apps=["Xcode", "Codex", "Safari"],
            clipboard_context="text",
            edited_file_count_10m=4,
            file_type_mix_10m={"source": 2, "test": 1, "docs": 1},
            rename_delete_ratio_10m=0.25,
            dominant_file_mode="few_files",
            work_pattern_candidate="feature_candidate",
        )
        decision = Decision(
            action="notify",
            level=2,
            reason="high_friction",
            payload={"file": "PanelView.swift"},
        )
        daemon_main.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        daemon_main.runtime_state.set_work_intent(WorkIntent(
            summary="réduire les coûts cachés du modèle local",
            source="manual",
            confidence=0.9,
            project="Pulse",
        ))
        daemon_main.runtime_state.set_analysis(signals=signals, decision=decision)
        daemon_main.runtime_state.set_latest_active_app("Xcode")

        with patch.dict(os.environ, {"PULSE_MODE": "core"}), \
             patch.object(
                 daemon_main.store,
                 "to_dict",
                 return_value={"active_app": "Xcode", "session_duration_min": 96},
             ):
            response = self.client.get("/state?include_debug=true")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["runtime_paused"])
        self.assertEqual(payload["pulse_mode"], "core")
        self.assertFalse(payload["experimental_enabled"])
        self.assertEqual(payload["active_app"], "Xcode")
        self.assertEqual(payload["active_project"], "Pulse")
        self.assertEqual(payload["present"]["session_status"], "active")
        self.assertFalse(payload["present"]["locked"])
        self.assertEqual(payload["present"]["active_project"], "Pulse")
        self.assertEqual(
            payload["present"]["work_intent"]["summary"],
            "réduire les coûts cachés du modèle local",
        )
        self.assertEqual(payload["present"]["probable_task"], "coding")
        self.assertEqual(
            payload["present"]["active_file"],
            "/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
        )
        self.assertEqual(payload["signals"]["active_project"], "Pulse")
        self.assertEqual(payload["signals"]["probable_task"], "coding")
        self.assertEqual(payload["signals"]["edited_file_count_10m"], 4)
        self.assertEqual(payload["signals"]["file_type_mix_10m"]["source"], 2)
        self.assertEqual(payload["signals"]["dominant_file_mode"], "few_files")
        self.assertEqual(payload["signals"]["work_pattern_candidate"], "feature_candidate")
        self.assertEqual(payload["decision"]["action"], "notify")
        self.assertEqual(payload["decision"]["payload"]["file"], "PanelView.swift")
        self.assertEqual(payload["debug"]["store"]["active_app"], "Xcode")
        self.assertEqual(payload["debug"]["signals"]["active_project"], "Pulse")
        self.assertNotIn("memory_candidate", payload)
        self.assertNotIn("memory_candidates", payload)
        self.assertNotIn("memory_candidate", payload["present"])
        self.assertNotIn("memory_candidates", payload["present"])

    def test_runtime_snapshot_is_atomic_for_present_signals_and_decision(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/pulse/main.py",
            probable_task="coding",
            friction_score=0.12,
            focus_level="deep",
            session_duration_min=42,
            recent_apps=["Xcode"],
            clipboard_context="text",
            activity_level="editing",
        )
        decision = Decision("notify", 2, "ready")

        daemon_main.runtime_state.set_latest_active_app("Xcode")
        daemon_main.runtime_state.set_paused(True)
        daemon_main.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        daemon_main.runtime_state.set_analysis(signals=signals, decision=decision)

        snapshot = daemon_main.runtime_state.get_runtime_snapshot()

        self.assertEqual(snapshot.present.active_project, "Pulse")
        self.assertEqual(snapshot.present.active_file, "/tmp/pulse/main.py")
        self.assertEqual(snapshot.signals.active_project, "Pulse")
        self.assertEqual(snapshot.decision.reason, "ready")
        self.assertTrue(snapshot.paused)
        self.assertEqual(snapshot.latest_active_app, "Xcode")

    def test_update_present_stores_canonical_runtime_snapshot(self):
        updated_at = datetime(2026, 4, 23, 10, 30, 0)
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/pulse/main.py",
            probable_task="coding",
            friction_score=0.12,
            focus_level="deep",
            session_duration_min=42,
            recent_apps=["Xcode"],
            clipboard_context="text",
            activity_level="editing",
        )

        daemon_main.runtime_state.update_present(
            signals=signals,
            session_status="locked",
            awake=False,
            locked=True,
            updated_at=updated_at,
        )

        present = daemon_main.runtime_state.get_present()
        self.assertEqual(present.session_status, "locked")
        self.assertFalse(present.awake)
        self.assertTrue(present.locked)
        self.assertEqual(present.active_project, "Pulse")
        self.assertEqual(present.active_file, "/tmp/pulse/main.py")
        self.assertEqual(present.probable_task, "coding")
        self.assertEqual(present.activity_level, "editing")
        self.assertEqual(present.focus_level, "deep")
        self.assertEqual(present.session_duration_min, 42)
        self.assertEqual(present.updated_at, updated_at)

    def test_should_ignore_file_event_reste_base_sur_temps_local_de_reception(self):
        first_seen = datetime(2026, 4, 23, 10, 0, 0)
        second_seen = first_seen + timedelta(milliseconds=500)
        later_seen = first_seen + timedelta(seconds=2)

        self.assertFalse(
            daemon_main.runtime_state.should_ignore_file_event(
                dedupe_key="file_modified:/tmp/main.py",
                now=first_seen,
            )
        )
        self.assertTrue(
            daemon_main.runtime_state.should_ignore_file_event(
                dedupe_key="file_modified:/tmp/main.py",
                now=second_seen,
            )
        )
        self.assertFalse(
            daemon_main.runtime_state.should_ignore_file_event(
                dedupe_key="file_modified:/tmp/main.py",
                now=later_seen,
            )
        )

    def test_event_endpoint_ignores_events_while_runtime_is_paused(self):
        daemon_main.runtime_state.set_paused(True)

        with patch.object(daemon_main.bus, "publish") as publish:
            response = self.client.post(
                "/event",
                json={"type": "file_modified", "path": "/tmp/test.py"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["paused"])
        self.assertTrue(payload["ignored"])
        publish.assert_not_called()

    def test_import_main_ne_demarre_pas_les_workers_permanents(self):
        self.assertFalse(daemon_main.runtime_orchestrator._started)
        self.assertIsNone(daemon_main.runtime_orchestrator._file_flush_worker)
        self.assertIsNone(daemon_main.runtime_orchestrator._periodic_sync_worker)
        self.assertIsNone(daemon_main.idle_presence_heartbeat._thread)

    def test_start_runtime_services_delegue_a_orchestrator_start(self):
        with patch.object(daemon_main.runtime_orchestrator, "start") as start, \
             patch.object(daemon_main.idle_presence_heartbeat, "start") as idle_start:
            daemon_main.start_runtime_services()

        start.assert_called_once()
        idle_start.assert_called_once()

    def test_start_runtime_services_s_appuie_sur_start_idempotent(self):
        with patch.object(daemon_main.runtime_orchestrator, "start") as start, \
             patch.object(daemon_main.idle_presence_heartbeat, "start") as idle_start:
            daemon_main.start_runtime_services()
            daemon_main.start_runtime_services()

        self.assertEqual(start.call_count, 2)
        self.assertEqual(idle_start.call_count, 2)

    def test_create_runtime_retourne_un_bundle_complet_sans_start(self):
        runtime = daemon_main.create_runtime()

        self.assertIsNotNone(runtime.bus)
        self.assertIsNotNone(runtime.store)
        self.assertIsNotNone(runtime.scorer)
        self.assertIsNotNone(runtime.decision_engine)
        self.assertIsNotNone(runtime.summary_llm)
        self.assertIsNotNone(runtime.session_memory)
        self.assertIsNotNone(runtime.memory_store)
        self.assertIsNotNone(runtime.runtime_state)
        self.assertIsNotNone(runtime.llm_runtime)
        self.assertIsNotNone(runtime.runtime_orchestrator)
        self.assertFalse(runtime.runtime_orchestrator._started)
        self.assertIsNone(runtime.runtime_orchestrator._file_flush_worker)
        self.assertIsNone(runtime.runtime_orchestrator._periodic_sync_worker)
        runtime.runtime_orchestrator.shutdown_runtime()

    def test_globals_legacy_pointent_vers_le_bundle_global(self):
        self.assertIs(daemon_main.bus, daemon_main.runtime.bus)
        self.assertIs(daemon_main.store, daemon_main.runtime.store)
        self.assertIs(daemon_main.scorer, daemon_main.runtime.scorer)
        self.assertIs(daemon_main.decision_engine, daemon_main.runtime.decision_engine)
        self.assertIs(daemon_main.summary_llm, daemon_main.runtime.summary_llm)
        self.assertIs(daemon_main.session_memory, daemon_main.runtime.session_memory)
        self.assertIs(daemon_main.memory_store, daemon_main.runtime.memory_store)
        self.assertIs(daemon_main.memory_candidate_store, daemon_main.runtime.memory_candidate_store)
        self.assertIs(daemon_main.runtime_state, daemon_main.runtime.runtime_state)
        self.assertIs(daemon_main.llm_runtime, daemon_main.runtime.llm_runtime)
        self.assertIs(daemon_main.runtime_orchestrator, daemon_main.runtime.runtime_orchestrator)

    def test_create_app_enregistre_les_routes_sans_demarrer_runtime(self):
        runtime = daemon_main.create_runtime()
        app = daemon_main.create_app(runtime)

        try:
            response = app.test_client().get("/ping")

            self.assertEqual(response.status_code, 200)
            self.assertFalse(runtime.runtime_orchestrator._started)
            self.assertIsNone(runtime.runtime_orchestrator._file_flush_worker)
            self.assertIsNone(runtime.runtime_orchestrator._periodic_sync_worker)
        finally:
            app.runtime_event_coalescer.close()
            runtime.runtime_orchestrator.shutdown_runtime()

    def test_runtime_api_route_inventory_documents_core_debug_and_lab_surfaces(self):
        route_methods = {}
        for rule in daemon_main.app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            route_methods.setdefault(rule.rule, set()).update(rule.methods - {"HEAD", "OPTIONS"})
        routes = set(route_methods)

        core_routes = {
            "/ping",
            "/health/core",
            "/state",
            "/event",
            "/feed",
        }
        debug_routes = {
            "/debug/state",
            "/insights",
            "/events/debug",
            "/events/schema",
            "/work-context",
            "/debug/commit-episode-links",
            "/debug/journal-candidates",
            "/debug/journal-comparison",
            "/debug/resume-card",
            "/debug/resume-card/llm",
            "/debug/work-episodes",
        }
        historical_minimal_memory_routes = {
            "/memory/sessions",
            "/search",
        }
        lab_memory_routes = {
            "/memory",
            "/memory/write",
            "/memory/remove",
            "/memory/usage",
        }
        mcp_routes = {
            "/mcp/pending",
            "/mcp/decision",
            "/mcp/intercept",
            "/mcp/proposals",
        }
        lab_or_legacy_routes = {
            "/ask",
            "/ask/stream",
            "/context",
            "/context-probes/request-preview",
            "/context-probes/requests",
            "/context-probes/requests/<request_id>",
            "/context-probes/requests/<request_id>/abort",
            "/context-probes/requests/<request_id>/approve",
            "/context-probes/requests/<request_id>/execute",
            "/context-probes/requests/<request_id>/refuse",
            "/context-probes/requests/<request_id>/result",
            "/context-probes/schema",
            "/daydreams",
            "/facts",
            "/facts/<fact_id>/archive",
            "/facts/<fact_id>/contradict",
            "/facts/<fact_id>/reinforce",
            "/facts/profile",
            "/facts/stats",
            "/llm/model",
            "/llm/models",
            "/context-probes/requests",
            "/work-intent/candidates",
            "/work-intent/candidates/<candidate_id>/accept",
            "/work-intent/candidates/<candidate_id>/refuse",
            "/llm/lightweight/status",
            "/llm/lightweight/pending",
            "/llm/lightweight/result",
        }
        daemon_control_routes = {
            "/daemon/pause",
            "/daemon/restart",
            "/daemon/resume",
            "/daemon/shutdown",
        }
        runtime_observation_routes = {
            "/observation",
            "/scoring/status",
            "/timeline/preview",
            "/timeline/schema",
            "/today_summary",
        }
        memory_candidate_routes = {
            "/memory/candidates",
            "/memory/candidates/<candidate_id>",
            "/memory/candidates/manual",
            "/memory/candidates/<candidate_id>/accept",
            "/memory/candidates/<candidate_id>/edit",
            "/memory/candidates/<candidate_id>/reject",
            "/memory/candidates/<candidate_id>/archive",
        }

        self.assertTrue(core_routes.issubset(routes))
        self.assertTrue(debug_routes.issubset(routes))
        self.assertTrue(historical_minimal_memory_routes.issubset(routes))
        self.assertTrue(lab_memory_routes.issubset(routes))
        self.assertTrue(mcp_routes.issubset(routes))
        self.assertTrue(lab_or_legacy_routes.issubset(routes))
        self.assertTrue(daemon_control_routes.issubset(routes))
        self.assertTrue(runtime_observation_routes.issubset(routes))
        self.assertTrue(memory_candidate_routes.issubset(routes))
        self.assertTrue(memory_candidate_routes.isdisjoint(core_routes))
        self.assertTrue(memory_candidate_routes.isdisjoint(debug_routes))
        self.assertTrue(memory_candidate_routes.isdisjoint(historical_minimal_memory_routes))
        self.assertTrue(memory_candidate_routes.isdisjoint(lab_memory_routes))
        self.assertTrue(memory_candidate_routes.isdisjoint(mcp_routes))
        self.assertTrue(memory_candidate_routes.isdisjoint(lab_or_legacy_routes))
        self.assertEqual(route_methods["/memory/candidates"], {"GET"})
        self.assertEqual(route_methods["/memory/candidates/manual"], {"POST"})
        self.assertEqual(route_methods["/memory/candidates/<candidate_id>"], {"GET", "DELETE"})
        self.assertEqual(route_methods["/memory/candidates/<candidate_id>/accept"], {"POST"})
        self.assertEqual(route_methods["/memory/candidates/<candidate_id>/edit"], {"POST"})
        self.assertEqual(route_methods["/memory/candidates/<candidate_id>/reject"], {"POST"})
        self.assertEqual(route_methods["/memory/candidates/<candidate_id>/archive"], {"POST"})
        self.assertEqual(route_methods["/memory/write"], {"POST"})
        self.assertEqual(route_methods["/memory/remove"], {"POST"})
        self.assertNotIn("/memory/candidates/generate", routes)
        self.assertNotIn("POST", route_methods["/memory/candidates"])

    def test_create_app_expose_le_coalescer_http_pour_shutdown(self):
        runtime = daemon_main.create_runtime()
        app = daemon_main.create_app(runtime)

        try:
            self.assertIsNotNone(app.runtime_event_coalescer)
            self.assertTrue(hasattr(app.runtime_event_coalescer, "close"))
        finally:
            app.runtime_event_coalescer.close()
            runtime.runtime_orchestrator.shutdown_runtime()

    def test_globals_legacy_restent_disponibles(self):
        self.assertIsNotNone(daemon_main.app)
        self.assertIsNotNone(daemon_main.bus)
        self.assertIsNotNone(daemon_main.runtime_state)
        self.assertIsNotNone(daemon_main.runtime_orchestrator)
        self.assertIsNotNone(daemon_main.runtime_event_coalescer)
        self.assertIs(daemon_main.runtime_event_coalescer, daemon_main.app.runtime_event_coalescer)

    def test_shutdown_draine_coalescer_avant_runtime_orchestrator(self):
        calls = []

        with patch.object(
            daemon_main.runtime_event_coalescer,
            "close",
            side_effect=lambda: calls.append("coalescer"),
        ) as close_coalescer, patch.object(
            daemon_main.runtime_orchestrator,
            "shutdown_runtime",
            side_effect=lambda: calls.append("runtime"),
        ) as shutdown_runtime:
            daemon_main._shutdown_runtime()

        close_coalescer.assert_called_once()
        shutdown_runtime.assert_called_once()
        self.assertEqual(calls, ["coalescer", "runtime"])

    def test_watchdog_shutdown_attend_la_grace_avant_exit(self):
        calls = []
        stale_ping = datetime.now() - timedelta(seconds=daemon_main.WATCHDOG_TIMEOUT_SEC + 5)

        def fake_sleep(delay):
            calls.append(("sleep", delay))

        def fake_exit(code):
            calls.append(("exit", code))
            raise SystemExit(code)

        with patch.object(daemon_main, "_is_launchd_child", return_value=False), \
             patch.object(daemon_main.runtime_state, "get_last_ping_at", return_value=stale_ping), \
             patch.object(daemon_main, "_shutdown_runtime", side_effect=lambda: calls.append("shutdown")), \
             patch.object(daemon_main.time, "sleep", side_effect=fake_sleep), \
             patch.object(daemon_main.os, "_exit", side_effect=fake_exit):
            with self.assertRaises(SystemExit):
                daemon_main._watchdog_loop()

        self.assertEqual(
            calls,
            [
                ("sleep", daemon_main.WATCHDOG_GRACE_SEC),
                ("sleep", 10),
                "shutdown",
                ("sleep", daemon_main.DAEMON_EXIT_GRACE_SEC),
                ("exit", 0),
            ],
        )

    def test_insights_uses_default_limit_of_twenty_five(self):
        with patch.object(daemon_main.bus, "recent", return_value=[]) as recent:
            response = self.client.get("/insights")

        self.assertEqual(response.status_code, 200)
        recent.assert_called_once_with(25)

    def test_insights_falls_back_to_default_limit_on_invalid_value(self):
        with patch.object(daemon_main.bus, "recent", return_value=[]) as recent:
            response = self.client.get("/insights?limit=abc")

        self.assertEqual(response.status_code, 200)
        recent.assert_called_once_with(25)

    def test_insights_clamps_limit_to_one_hundred(self):
        with patch.object(daemon_main.bus, "recent", return_value=[]) as recent:
            response = self.client.get("/insights?limit=500")

        self.assertEqual(response.status_code, 200)
        recent.assert_called_once_with(100)

    def test_llm_models_reports_inactive_when_ollama_is_offline(self):
        class _Provider:
            is_operational = True

        with patch("daemon.main.get_available_llm_models", return_value=["mistral"]), \
             patch("daemon.main.get_selected_command_llm_model", return_value="mistral"), \
             patch("daemon.main.get_selected_summary_llm_model", return_value="mistral"), \
             patch("daemon.main._ollama_ping", return_value=False), \
             patch("daemon.main._llm_provider", return_value=_Provider()):
            response = self.client.get("/llm/models")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["ollama_online"])
        self.assertEqual(payload["selected_model"], "mistral")
        self.assertTrue(payload["model_selected"])
        self.assertFalse(payload["llm_ready"])
        self.assertFalse(payload["llm_active"])

    def test_llm_models_reports_inactive_when_online_without_model_or_provider(self):
        class _Provider:
            is_operational = False

        with patch("daemon.main.get_available_llm_models", return_value=[]), \
             patch("daemon.main.get_selected_command_llm_model", return_value=""), \
             patch("daemon.main.get_selected_summary_llm_model", return_value=""), \
             patch("daemon.main._ollama_ping", return_value=True), \
             patch("daemon.main._llm_provider", return_value=_Provider()):
            response = self.client.get("/llm/models")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ollama_online"])
        self.assertEqual(payload["selected_model"], "")
        self.assertFalse(payload["model_selected"])
        self.assertFalse(payload["llm_ready"])
        self.assertFalse(payload["llm_active"])


    # ── C1 : double signal screen_locked ───────────────────────────────────────

    def test_mark_screen_locked_premier_signal_gagne(self):
        """
        Quand deux screen_locked arrivent (vrai lock + sleep écran),
        _last_screen_locked_at doit rester l'heure du PREMIER signal.
        Sans ce garde-fou, le second signal écraserait l'heure du vrai lock,
        faussant le calcul de sleep_min dans handle_event().
        """
        state = daemon_main.runtime_state
        state.reset_for_tests()

        from datetime import datetime, timedelta
        t_lock = datetime.now() - timedelta(minutes=35)
        t_sleep = datetime.now() - timedelta(minutes=30)  # 5 min après le vrai lock

        state.mark_screen_locked(when=t_lock)   # premier signal : vrai verrou
        state.mark_screen_locked(when=t_sleep)  # second signal : sommeil écran

        self.assertEqual(state.get_last_screen_locked_at(), t_lock,
            "Le second mark_screen_locked ne doit pas écraser l'heure du premier signal")
        self.assertTrue(state.is_screen_locked())

    def test_mark_screen_locked_accepte_heure_si_pas_encore_locké(self):
        """Comportement normal : si écran non verrouillé, l'heure est bien enregistrée."""
        state = daemon_main.runtime_state
        state.reset_for_tests()

        from datetime import datetime
        t = datetime.now()
        state.mark_screen_locked(when=t)

        self.assertEqual(state.get_last_screen_locked_at(), t)
        self.assertTrue(state.is_screen_locked())

    def test_mark_screen_locked_puis_unlock_reset_heure(self):
        """Après unlock + clear_sleep_markers, un nouveau lock repart de zéro."""
        state = daemon_main.runtime_state
        state.reset_for_tests()

        from datetime import datetime, timedelta
        t1 = datetime.now() - timedelta(minutes=60)
        state.mark_screen_locked(when=t1)
        state.mark_screen_unlocked()
        state.clear_sleep_markers()  # simule ce que handle_event fait après reset session

        t2 = datetime.now()
        state.mark_screen_locked(when=t2)  # nouveau cycle de lock

        self.assertEqual(state.get_last_screen_locked_at(), t2,
            "Après clear_sleep_markers, un nouveau lock doit enregistrer sa propre heure")


    # ── I5 : clipboard — contenu brut retiré avant publication ───────────────────

    def test_i5_clipboard_content_retire_du_payload_avant_publication(self):
        """
        Un event clipboard_updated contenant 'content' (client ancien ou test)
        doit avoir ce champ retiré avant publication dans le bus.
        Seul content_kind doit passer.
        """
        published_payloads = []

        def capture_publish(event_type, payload):
            published_payloads.append((event_type, dict(payload)))

        with patch.object(daemon_main.bus, "publish", side_effect=capture_publish):
            response = self.client.post("/event", json={
                "type": "clipboard_updated",
                "content": "api_key = 'sk-secret123'",  # donnée sensible
                "content_kind": "code",
                "char_count": "24",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(published_payloads), 1)
        _, payload = published_payloads[0]
        self.assertNotIn("content", payload,
            "Le contenu brut ne doit pas être publié dans le bus")
        self.assertEqual(payload.get("content_kind"), "code",
            "content_kind doit rester présent")
        self.assertEqual(payload.get("char_count"), "24",
            "char_count doit rester présent")

    def test_i5_clipboard_sans_content_passe_sans_modification(self):
        """
        Un event clipboard_updated sans 'content' (client Swift à jour)
        doit passer normalement sans erreur.
        """
        published_payloads = []

        def capture_publish(event_type, payload):
            published_payloads.append((event_type, dict(payload)))

        with patch.object(daemon_main.bus, "publish", side_effect=capture_publish):
            response = self.client.post("/event", json={
                "type": "clipboard_updated",
                "content_kind": "stacktrace",
                "char_count": "150",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(published_payloads), 1)
        _, payload = published_payloads[0]
        self.assertNotIn("content", payload)
        self.assertEqual(payload.get("content_kind"), "stacktrace")

    def test_i5_clipboard_pendant_screen_lock_filtre(self):
        """
        Pendant le verrou écran, les events clipboard ne passent pas du tout.
        Ce comportement pré-existant ne doit pas être affecté par le fix I5.
        """
        daemon_main.runtime_state.mark_screen_locked()

        with patch.object(daemon_main.bus, "publish") as mock_publish:
            response = self.client.post("/event", json={
                "type": "clipboard_updated",
                "content": "sensible",
                "content_kind": "text",
            })

        self.assertEqual(response.status_code, 200)
        mock_publish.assert_not_called()

        # Nettoyage
        daemon_main.runtime_state.mark_screen_unlocked()
        daemon_main.runtime_state.clear_sleep_markers()


if __name__ == "__main__":
    unittest.main()
