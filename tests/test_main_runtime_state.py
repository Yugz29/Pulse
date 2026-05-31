import json
import os
from pathlib import Path
import subprocess
import sys
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


class _DummyThread:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True


class TestMainRuntimeState(unittest.TestCase):
    def setUp(self):
        daemon_main.runtime_state.reset_for_tests()
        daemon_main.runtime_orchestrator.reset_for_tests()
        daemon_main.bus.clear()
        self.client = daemon_main.get_app().test_client()

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

    def test_import_main_documente_les_effets_de_bord_boot_actuels(self):
        # C4b.1 audit: this documents current import-time debt; it does not fix it.
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="pulse-import-audit-home-") as temp_home:
            env = os.environ.copy()
            env["HOME"] = temp_home
            env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{env.get('PYTHONPATH', '')}"
            script = """
import json
from pathlib import Path
from unittest.mock import patch

with patch("flask.Flask.run") as flask_run:
    import daemon.main as main

home = Path.home()
pulse_dir = home / ".pulse"
pulse_dir_exists_at_import = pulse_dir.exists()
created_paths_at_import = []
if pulse_dir_exists_at_import:
    created_paths_at_import = sorted(
        str(path.relative_to(home))
        for path in pulse_dir.rglob("*")
    )

runtime_defined_at_import = "runtime" in main.__dict__
app_defined_at_import = "app" in main.__dict__
runtime_state_defined_at_import = "runtime_state" in main.__dict__
idle_heartbeat_created_at_import = main.__dict__.get("_idle_presence_heartbeat") is not None

runtime_obj = main.get_runtime()
app_obj = main.get_app()
routes = {
    rule.rule
    for rule in app_obj.url_map.iter_rules()
    if rule.endpoint != "static"
}
created_paths_after_access = []
if pulse_dir.exists():
    created_paths_after_access = sorted(
        str(path.relative_to(home))
        for path in pulse_dir.rglob("*")
    )

print(json.dumps({
    "runtime_defined_at_import": runtime_defined_at_import,
    "runtime_state_defined_at_import": runtime_state_defined_at_import,
    "runtime_type": type(runtime_obj).__name__,
    "get_runtime_returns_same_object": main.get_runtime() is runtime_obj,
    "get_runtime_returns_legacy_runtime": main.get_runtime() is main.runtime,
    "app_defined_at_import": app_defined_at_import,
    "app_type": type(app_obj).__name__,
    "get_app_returns_same_object": main.get_app() is app_obj,
    "get_app_returns_legacy_app": main.get_app() is main.app,
    "has_main_entrypoint": callable(getattr(main, "main", None)),
    "flask_run_called_on_import": flask_run.called,
    "pulse_dir_exists_at_import": pulse_dir_exists_at_import,
    "created_paths_at_import": created_paths_at_import,
    "pulse_dir_exists_after_access": pulse_dir.exists(),
    "created_paths_after_access": created_paths_after_access,
    "route_count": len(routes),
    "has_health_core": "/health/core" in routes,
    "has_state": "/state" in routes,
    "has_feed": "/feed" in routes,
    "has_memory_candidates": "/memory/candidates" in routes,
    "orchestrator_started": runtime_obj.runtime_orchestrator._started,
    "file_flush_worker_started": runtime_obj.runtime_orchestrator._file_flush_worker is not None,
    "periodic_sync_worker_started": runtime_obj.runtime_orchestrator._periodic_sync_worker is not None,
    "idle_heartbeat_created_at_import": idle_heartbeat_created_at_import,
}))
"""
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=repo_root,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        created_paths_at_import = set(payload["created_paths_at_import"])
        created_paths_after_access = set(payload["created_paths_after_access"])

        self.assertFalse(payload["runtime_defined_at_import"])
        self.assertFalse(payload["runtime_state_defined_at_import"])
        self.assertEqual(payload["runtime_type"], "RuntimeBundle")
        self.assertTrue(payload["get_runtime_returns_same_object"])
        self.assertTrue(payload["get_runtime_returns_legacy_runtime"])
        self.assertFalse(payload["app_defined_at_import"])
        self.assertEqual(payload["app_type"], "Flask")
        self.assertTrue(payload["get_app_returns_same_object"])
        self.assertTrue(payload["get_app_returns_legacy_app"])
        self.assertTrue(payload["has_main_entrypoint"])
        self.assertFalse(payload["flask_run_called_on_import"])
        self.assertFalse(payload["pulse_dir_exists_at_import"])
        self.assertEqual(created_paths_at_import, set())
        self.assertTrue(payload["pulse_dir_exists_after_access"])
        self.assertTrue(any(path.endswith(".db") for path in created_paths_after_access))
        self.assertIn(".pulse/memory/candidates.sqlite", created_paths_after_access)
        self.assertTrue(payload["has_health_core"])
        self.assertTrue(payload["has_state"])
        self.assertTrue(payload["has_feed"])
        self.assertTrue(payload["has_memory_candidates"])
        self.assertGreater(payload["route_count"], 0)
        self.assertFalse(payload["orchestrator_started"])
        self.assertFalse(payload["file_flush_worker_started"])
        self.assertFalse(payload["periodic_sync_worker_started"])
        self.assertFalse(payload["idle_heartbeat_created_at_import"])

    def test_main_entrypoint_delegue_le_lancement_executable_sans_changer_le_boot(self):
        _DummyThread.instances = []
        with patch.object(daemon_main, "start_runtime_services") as start_services, \
             patch.object(daemon_main.atexit, "register") as register_exit, \
             patch.object(daemon_main, "start_mcp_server") as start_mcp, \
             patch.object(daemon_main.threading, "Thread", side_effect=lambda *args, **kwargs: _DummyThread(*args, **kwargs)), \
             patch.object(daemon_main.get_app(), "run") as app_run:
            daemon_main.main()

        start_services.assert_called_once_with()
        register_exit.assert_called_once_with(daemon_main._shutdown_runtime)
        start_mcp.assert_called_once_with(host="127.0.0.1", port=8766)
        self.assertEqual(len(_DummyThread.instances), 2)
        self.assertEqual(
            {thread.kwargs.get("name") for thread in _DummyThread.instances},
            {"pulse-watchdog", "pulse-startup"},
        )
        self.assertTrue(all(thread.kwargs.get("daemon") is True for thread in _DummyThread.instances))
        self.assertTrue(all(thread.started for thread in _DummyThread.instances))
        app_run.assert_called_once_with(host="127.0.0.1", port=8765, debug=False, threaded=True)

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
        runtime = daemon_main.get_runtime()

        self.assertIs(daemon_main.bus, runtime.bus)
        self.assertIs(daemon_main.store, runtime.store)
        self.assertIs(daemon_main.scorer, runtime.scorer)
        self.assertIs(daemon_main.decision_engine, runtime.decision_engine)
        self.assertIs(daemon_main.summary_llm, runtime.summary_llm)
        self.assertIs(daemon_main.session_memory, runtime.session_memory)
        self.assertIs(daemon_main.memory_store, runtime.memory_store)
        self.assertIs(daemon_main.memory_candidate_store, runtime.memory_candidate_store)
        self.assertIs(daemon_main.runtime_state, runtime.runtime_state)
        self.assertIs(daemon_main.llm_runtime, runtime.llm_runtime)
        self.assertIs(daemon_main.runtime_orchestrator, runtime.runtime_orchestrator)

    def test_lazy_compat_accessors_return_existing_globals(self):
        self.assertIs(daemon_main.get_runtime(), daemon_main.runtime)
        self.assertIs(daemon_main.get_app(), daemon_main.app)
        self.assertIs(daemon_main.get_runtime(), daemon_main.get_runtime())
        self.assertIs(daemon_main.get_app(), daemon_main.get_app())

    def test_get_app_preserves_core_route_inventory(self):
        routes = {
            rule.rule
            for rule in daemon_main.get_app().url_map.iter_rules()
            if rule.endpoint != "static"
        }

        self.assertIn("/health/core", routes)
        self.assertIn("/state", routes)
        self.assertIn("/feed", routes)
        self.assertIn("/memory/candidates", routes)

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
        for rule in daemon_main.get_app().url_map.iter_rules():
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

    def test_route_inventory_documents_conditional_and_transverse_registrations(self):
        route_methods = {}
        route_endpoints = {}
        for rule in daemon_main.get_app().url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            route_methods.setdefault(rule.rule, set()).update(rule.methods - {"HEAD", "OPTIONS"})
            route_endpoints[rule.rule] = rule.endpoint

        self.assertEqual(route_methods["/llm/lightweight/status"], {"GET"})
        self.assertEqual(route_methods["/llm/lightweight/pending"], {"GET"})
        self.assertEqual(route_methods["/llm/lightweight/result"], {"POST"})
        self.assertEqual(route_methods["/scoring/status"], {"GET"})
        self.assertEqual(route_endpoints["/llm/lightweight/status"], "get_lightweight_status")
        self.assertEqual(route_endpoints["/llm/lightweight/pending"], "get_lightweight_pending")
        self.assertEqual(route_endpoints["/llm/lightweight/result"], "post_lightweight_result")
        self.assertEqual(route_endpoints["/scoring/status"], "scoring_status")

    def test_route_inventory_documents_assistant_probes_and_work_intent_as_non_core(self):
        route_methods = {}
        for rule in daemon_main.get_app().url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            route_methods.setdefault(rule.rule, set()).update(rule.methods - {"HEAD", "OPTIONS"})
        routes = set(route_methods)

        core_minimal_routes = {
            "/ping",
            "/health/core",
            "/state",
            "/event",
            "/feed",
        }
        assistant_legacy_routes = {
            "/ask",
            "/ask/stream",
            "/context",
            "/llm/model",
            "/llm/models",
        }
        context_probe_routes = {
            "/context-probes/request-preview",
            "/context-probes/requests",
            "/context-probes/requests/<request_id>",
            "/context-probes/requests/<request_id>/abort",
            "/context-probes/requests/<request_id>/approve",
            "/context-probes/requests/<request_id>/execute",
            "/context-probes/requests/<request_id>/refuse",
            "/context-probes/requests/<request_id>/result",
            "/context-probes/schema",
        }
        work_intent_routes = {
            "/work-intent/candidates",
            "/work-intent/candidates/<candidate_id>/accept",
            "/work-intent/candidates/<candidate_id>/refuse",
        }

        self.assertTrue(assistant_legacy_routes.issubset(routes))
        self.assertTrue(context_probe_routes.issubset(routes))
        self.assertTrue(work_intent_routes.issubset(routes))
        self.assertTrue(assistant_legacy_routes.isdisjoint(core_minimal_routes))
        self.assertTrue(context_probe_routes.isdisjoint(core_minimal_routes))
        self.assertTrue(work_intent_routes.isdisjoint(core_minimal_routes))
        self.assertEqual(route_methods["/ask"], {"POST"})
        self.assertEqual(route_methods["/ask/stream"], {"POST"})
        self.assertEqual(route_methods["/context"], {"GET"})
        self.assertEqual(route_methods["/llm/model"], {"POST"})
        self.assertEqual(route_methods["/llm/models"], {"GET"})
        self.assertEqual(route_methods["/context-probes/schema"], {"GET"})
        self.assertEqual(route_methods["/context-probes/request-preview"], {"POST"})
        self.assertEqual(route_methods["/context-probes/requests"], {"GET", "POST"})
        self.assertEqual(route_methods["/context-probes/requests/<request_id>"], {"GET"})
        self.assertEqual(route_methods["/context-probes/requests/<request_id>/approve"], {"POST"})
        self.assertEqual(route_methods["/context-probes/requests/<request_id>/refuse"], {"POST"})
        self.assertEqual(route_methods["/context-probes/requests/<request_id>/abort"], {"POST"})
        self.assertEqual(route_methods["/context-probes/requests/<request_id>/execute"], {"POST"})
        self.assertEqual(route_methods["/context-probes/requests/<request_id>/result"], {"POST"})
        self.assertEqual(route_methods["/work-intent/candidates"], {"GET"})
        self.assertEqual(route_methods["/work-intent/candidates/<candidate_id>/accept"], {"POST"})
        self.assertEqual(route_methods["/work-intent/candidates/<candidate_id>/refuse"], {"POST"})

    def test_lab_legacy_mutation_routes_remain_registered_but_blocked_in_core(self):
        with patch.dict(os.environ, {"PULSE_MODE": "core"}), \
             patch.object(daemon_main.memory_store, "write") as memory_write, \
             patch.object(daemon_main.memory_store, "remove") as memory_remove, \
             patch.object(daemon_main.runtime_orchestrator.fact_engine, "reinforce") as reinforce, \
             patch.object(daemon_main.runtime_orchestrator.fact_engine, "contradict") as contradict, \
             patch.object(daemon_main.runtime_orchestrator.fact_engine, "archive") as archive, \
             patch.object(
                 daemon_main.runtime_orchestrator,
                 "apply_lightweight_llm_result",
             ) as apply_lightweight_result:
            memory_write_response = self.client.post(
                "/memory/write",
                json={"content": "Projet Pulse", "tier": "persistent"},
            )
            memory_remove_response = self.client.post(
                "/memory/remove",
                json={"old_text": "Projet Pulse"},
            )
            reinforce_response = self.client.post("/facts/fact-1/reinforce")
            contradict_response = self.client.post("/facts/fact-1/contradict")
            archive_response = self.client.post("/facts/fact-1/archive")
            lightweight_response = self.client.post(
                "/llm/lightweight/result",
                json={"id": "req-1", "status": "generated", "text": "ignored"},
            )

        for response in (
            memory_write_response,
            memory_remove_response,
            reinforce_response,
            contradict_response,
            archive_response,
            lightweight_response,
        ):
            self.assertEqual(response.status_code, 403)
            payload = response.get_json()
            self.assertEqual(payload["error"], "lab_surface_disabled")
            self.assertEqual(payload["pulse_mode"], "core")
            self.assertTrue(payload["disabled_in_core"])

        memory_write.assert_not_called()
        memory_remove.assert_not_called()
        reinforce.assert_not_called()
        contradict.assert_not_called()
        archive.assert_not_called()
        apply_lightweight_result.assert_not_called()

    def test_facts_profile_is_registered_but_neutralized_in_core(self):
        with patch.dict(os.environ, {"PULSE_MODE": "core"}), \
             patch.object(daemon_main.runtime_orchestrator.fact_engine, "render_for_context") as render:
            response = self.client.get("/facts/profile")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["profile"], "")
        self.assertTrue(payload["lab_only"])
        self.assertTrue(payload["disabled_in_core"])
        render.assert_not_called()

    def test_health_core_from_full_app_does_not_depend_on_lab_services(self):
        with patch.dict(os.environ, {"PULSE_MODE": "core"}), \
             patch.object(daemon_main.memory_store, "usage") as memory_usage, \
             patch.object(daemon_main.runtime_orchestrator.fact_engine, "stats") as fact_stats, \
             patch.object(daemon_main.runtime_orchestrator.fact_engine, "render_for_context") as render_facts, \
             patch("daemon.main.build_context_snapshot") as build_context_snapshot, \
             patch.object(daemon_main.runtime_orchestrator, "get_frozen_memory") as get_frozen_memory, \
             patch.object(daemon_main.runtime_state, "set_work_intent") as set_work_intent, \
             patch.object(daemon_main.summary_llm, "complete", create=True) as llm_complete, \
             patch("daemon.memory.daydream.get_daydream_status") as daydream_status, \
             patch("daemon.memory.vector_store.VectorStore") as vector_store:
            response = self.client.get("/health/core")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pulse_mode"], "core")
        self.assertFalse(payload["experimental_enabled"])
        self.assertEqual(payload["checks"]["lab_services"], "not_required")
        memory_usage.assert_not_called()
        fact_stats.assert_not_called()
        render_facts.assert_not_called()
        build_context_snapshot.assert_not_called()
        get_frozen_memory.assert_not_called()
        set_work_intent.assert_not_called()
        llm_complete.assert_not_called()
        daydream_status.assert_not_called()
        vector_store.assert_not_called()

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
        self.assertIsNotNone(daemon_main.get_app())
        self.assertIsNotNone(daemon_main.get_runtime())
        self.assertIsNotNone(daemon_main.app)
        self.assertIsNotNone(daemon_main.bus)
        self.assertIsNotNone(daemon_main.runtime_state)
        self.assertIsNotNone(daemon_main.runtime_orchestrator)
        self.assertIsNotNone(daemon_main.runtime_event_coalescer)
        self.assertIs(daemon_main.runtime_event_coalescer, daemon_main.get_app().runtime_event_coalescer)

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
