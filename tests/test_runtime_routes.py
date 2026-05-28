import unittest
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path
from types import SimpleNamespace

from flask import Flask

from daemon.core.contracts import SessionContext
from daemon.core.event_bus import Event
from daemon.core.decision_engine import Decision
from daemon.core.signal_scorer import Signals
from daemon.core.file_event_coalescer import FileEventCoalescer as _FileEventCoalescer
from daemon.routes.runtime import register_runtime_routes
from daemon.routes.runtime_daemon_routes import DAEMON_EXIT_GRACE_SEC
from daemon.runtime_state import RuntimeState, WorkIntent


class _DummyThread:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False

    def start(self):
        self.started = True


class _ImmediateThread:
    def __init__(self, *args, **kwargs):
        self.target = kwargs.get("target")
        self.args = kwargs.get("args", ())
        self.kwargs = kwargs.get("kwargs", {})
        self.started = False

    def start(self):
        self.started = True
        if self.target is not None:
            self.target(*self.args, **self.kwargs)


class _ManualTimer:
    def __init__(self, interval, callback, args=None, kwargs=None):
        self.interval = interval
        self.callback = callback
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.daemon = False
        self.cancelled = False
        self.started = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.callback(*self.args, **self.kwargs)


class TestRuntimeRoutes(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.bus = MagicMock()
        self.store = MagicMock()
        self.runtime_state = RuntimeState()
        self.llm_unload_background = MagicMock()
        self.llm_warmup_background = MagicMock()
        self.shutdown_runtime = MagicMock()
        self.log = MagicMock()

        self.coalescer = register_runtime_routes(
            self.app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        self.client = self.app.test_client()

    def test_daydreams_expose_etat_meme_sans_fichier(self):
        with patch("pathlib.Path.home", return_value=Path("/tmp/pulse-home")), \
             patch("daemon.memory.daydream.get_daydream_status", return_value={
                 "status": "skipped",
                 "pending": False,
                 "target_date": "2026-04-27",
                 "done_for_date": "2026-04-27",
                 "last_reason": "no_journal_entries",
                 "last_error": None,
                 "last_attempt_at": "2026-04-28T00:05:16",
                 "last_completed_at": "2026-04-28T00:05:16",
                 "last_output_path": None,
             }):
            response = self.client.get("/daydreams")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["daydreams"], [])
        self.assertEqual(payload["status"]["status"], "skipped")
        self.assertEqual(payload["status"]["last_reason"], "no_journal_entries")

    def test_daydreams_expose_narrative_non_canonical_metadata(self):
        with tempfile.TemporaryDirectory() as temp_home:
            daydream_dir = Path(temp_home) / ".pulse" / "memory" / "daydreams"
            daydream_dir.mkdir(parents=True)
            (daydream_dir / "2026-04-27.md").write_text("# DayDream\n\nSynthèse.", encoding="utf-8")

            with patch("pathlib.Path.home", return_value=Path(temp_home)), \
                 patch("daemon.memory.daydream.get_daydream_status", return_value={"status": "generated"}):
                response = self.client.get("/daydreams")

        self.assertEqual(response.status_code, 200)
        entry = response.get_json()["daydreams"][0]
        self.assertEqual(entry["memory_role"], "narrative_summary")
        self.assertFalse(entry["canonical_memory"])
        self.assertEqual(entry["source_type"], "narrative")
        self.assertTrue(entry["requires_confirmation"])
        self.assertEqual(entry["generated_from"], "journals")

    def test_today_summary_expose_un_aggregate_persiste(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_summary=lambda: {
                "date": "2026-04-28",
                "generated_at": "2026-04-28T12:50:00",
                "totals": {
                    "worked_min": 95,
                    "active_min": 72,
                    "commit_count": 3,
                    "window_count": 2,
                    "project_count": 1,
                },
                "projects": [
                    {
                        "name": "Pulse",
                        "worked_min": 95,
                        "active_min": 72,
                        "commit_count": 3,
                        "top_tasks": ["coding", "debug"],
                    }
                ],
                "timeline": {
                    "first_activity_at": "2026-04-28T11:10:00",
                    "last_activity_at": "2026-04-28T12:49:00",
                },
                "current_window": {
                    "id": "ww-1",
                    "started_at": "2026-04-28T12:36:00",
                    "updated_at": "2026-04-28T12:49:00",
                    "project": "Pulse",
                    "probable_task": "coding",
                    "activity_level": "executing",
                    "commit_count": 2,
                },
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/today_summary")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["totals"]["worked_min"], 95)
        self.assertEqual(payload["projects"][0]["name"], "Pulse")
        self.assertEqual(payload["current_window"]["id"], "ww-1")

    def test_debug_resume_card_reste_deterministe_meme_si_llm_configure(self):
        class CountingLLM:
            def __init__(self):
                self.calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return "{}"

        llm = CountingLLM()
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=MagicMock(),
            store=self.store,
            runtime_state=self.runtime_state,
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
            resume_card_llm=llm,
        )
        client = app.test_client()

        response = client.post("/debug/resume-card", json={"sleep_minutes": 35})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["mode"], "deterministic")
        self.assertEqual(payload["card"]["generated_by"], "deterministic")
        self.assertEqual(llm.calls, 0)

    def test_debug_resume_card_llm_appelle_llm_explicitement(self):
        class CountingLLM:
            def __init__(self):
                self.calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return (
                    '{"title":"Reprise","summary":"Résumé LLM.",'
                    '"last_objective":"Reprendre le contexte.",'
                    '"next_action":"Continuer prudemment.","confidence":0.8}'
                )

        llm = CountingLLM()
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=MagicMock(),
            store=self.store,
            runtime_state=self.runtime_state,
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
            resume_card_llm=llm,
        )
        client = app.test_client()

        with patch("daemon.routes.runtime_resume_card_routes.require_heavy_llm", return_value=True):
            response = client.post("/debug/resume-card/llm", json={"sleep_minutes": 35})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["mode"], "llm")
        self.assertTrue(payload["debug"]["llm_called"])
        self.assertEqual(payload["card"]["generated_by"], "llm")
        self.assertEqual(llm.calls, 1)

    def test_debug_resume_card_llm_refuse_si_policy_refuse(self):
        class CountingLLM:
            def __init__(self):
                self.calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return "{}"

        llm = CountingLLM()
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=MagicMock(),
            store=self.store,
            runtime_state=self.runtime_state,
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
            resume_card_llm=llm,
        )
        client = app.test_client()

        with patch("daemon.routes.runtime_resume_card_routes.require_heavy_llm", return_value=False):
            response = client.post("/debug/resume-card/llm", json={"sleep_minutes": 35})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["mode"], "deterministic_fallback")
        self.assertFalse(payload["llm_available"])
        self.assertFalse(payload["debug"]["llm_called"])
        self.assertEqual(payload["card"]["generated_by"], "deterministic")
        self.assertEqual(llm.calls, 0)

    def test_debug_work_episodes_expose_les_episodes_du_jour(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_work_episodes=lambda: {
                "date": "2026-05-05",
                "generated_at": "2026-05-05T15:30:00",
                "episode_count": 1,
                "episodes": [
                    {
                        "id": "work-episode-1",
                        "project": "Pulse",
                        "probable_task": "coding",
                        "activity_level": "editing",
                        "started_at": "2026-05-05T15:02:15",
                        "ended_at": "2026-05-05T15:02:41",
                        "duration_min": 1,
                        "work_block_ids": ["work-block-1"],
                        "evidence_count": 2,
                        "confidence": 0.75,
                        "boundary_reason": "end_of_events",
                        "uncertainty_flags": ["short_episode"],
                    }
                ],
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/debug/work-episodes")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["date"], "2026-05-05")
        self.assertEqual(payload["episode_count"], 1)
        self.assertEqual(payload["episodes"][0]["project"], "Pulse")
        self.assertEqual(payload["episodes"][0]["work_block_ids"], ["work-block-1"])

    def test_debug_work_episodes_supporte_le_query_param_date(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_work_episodes=lambda date=None: {
                "date": date.date().isoformat() if date else "today",
                "generated_at": "2026-05-05T15:30:00",
                "episode_count": 0,
                "episodes": [],
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/debug/work-episodes?date=2026-05-05")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["date"], "2026-05-05")

    def test_debug_journal_candidates_expose_les_candidats_dry_run(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_journal_candidates=lambda: {
                "date": "2026-05-05",
                "generated_at": "2026-05-05T15:45:00",
                "candidate_count": 1,
                "ignored_count": 1,
                "candidates": [
                    {
                        "id": "journal-candidate-1",
                        "episode_id": "work-episode-1",
                        "project": "Pulse",
                        "probable_task": "coding",
                        "dominant_scope": "source",
                        "started_at": "2026-05-05T15:02:15",
                        "ended_at": "2026-05-05T15:12:41",
                        "duration_min": 10,
                        "boundary_reason": "screen_locked",
                        "strong_event_count": 2,
                        "weak_event_count": 0,
                        "confidence": 0.9,
                        "status": "candidate",
                        "ignored": False,
                        "ignore_reason": None,
                        "debug_reason": "split on boundary event screen_locked",
                    }
                ],
                "ignored": [
                    {
                        "id": "journal-candidate-2",
                        "episode_id": "work-episode-2",
                        "project": "Pulse",
                        "probable_task": "coding",
                        "dominant_scope": "source",
                        "started_at": "2026-05-05T15:15:00",
                        "ended_at": "2026-05-05T15:20:00",
                        "duration_min": 5,
                        "boundary_reason": "end_of_events",
                        "strong_event_count": 1,
                        "weak_event_count": 0,
                        "confidence": 0.75,
                        "status": "ignored",
                        "ignored": True,
                        "ignore_reason": "open_episode_end_of_events",
                        "debug_reason": "episode open until end of observed events",
                    }
                ],
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/debug/journal-candidates")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["date"], "2026-05-05")
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["ignored_count"], 1)
        self.assertEqual(payload["candidates"][0]["episode_id"], "work-episode-1")
        self.assertEqual(payload["ignored"][0]["ignore_reason"], "open_episode_end_of_events")

    def test_debug_journal_candidates_supporte_le_query_param_date(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_journal_candidates=lambda date=None: {
                "date": date.date().isoformat() if date else "today",
                "generated_at": "2026-05-05T15:45:00",
                "candidate_count": 0,
                "ignored_count": 0,
                "candidates": [],
                "ignored": [],
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/debug/journal-candidates?date=2026-05-05")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["date"], "2026-05-05")

    def test_debug_journal_candidates_fallback_when_callback_absent(self):
        response = self.client.get("/debug/journal-candidates")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(payload["ignored_count"], 0)
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["ignored"], [])

    def test_debug_journal_comparison_expose_les_ecarts_dry_run(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_journal_comparison=lambda: {
                "date": "2026-05-05",
                "generated_at": "2026-05-05T16:00:00",
                "journal_entry_count": 1,
                "candidate_count": 1,
                "matches": [
                    {
                        "journal_entry_id": "journal-1",
                        "candidate_id": "candidate-1",
                        "project": "Pulse",
                        "journal_started_at": "2026-05-05T11:00:00",
                        "journal_ended_at": "2026-05-05T11:20:00",
                        "candidate_started_at": "2026-05-05T11:01:00",
                        "candidate_ended_at": "2026-05-05T11:19:00",
                        "start_delta_min": 1,
                        "end_delta_min": -1,
                        "duration_delta_min": -2,
                        "flags": ["time_aligned", "journal_longer"],
                    }
                ],
                "unmatched_journal_entries": [],
                "unmatched_candidates": [],
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/debug/journal-comparison")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["date"], "2026-05-05")
        self.assertEqual(payload["journal_entry_count"], 1)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["matches"][0]["candidate_id"], "candidate-1")
        self.assertIn("time_aligned", payload["matches"][0]["flags"])

    def test_debug_journal_comparison_supporte_le_query_param_date(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_journal_comparison=lambda date=None: {
                "date": date.date().isoformat() if date else "today",
                "generated_at": "2026-05-05T16:00:00",
                "journal_entry_count": 0,
                "candidate_count": 0,
                "matches": [],
                "unmatched_journal_entries": [],
                "unmatched_candidates": [],
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/debug/journal-comparison?date=2026-05-05")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["date"], "2026-05-05")

    def test_debug_date_invalide_retourne_400(self):
        response = self.client.get("/debug/journal-comparison?date=2026-99-99")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error"], "invalid_date")
        self.assertEqual(payload["message"], "date must use YYYY-MM-DD")

    def test_debug_journal_comparison_fallback_when_callback_absent(self):
        response = self.client.get("/debug/journal-comparison")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["journal_entry_count"], 0)
        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(payload["matches"], [])
        self.assertEqual(payload["unmatched_journal_entries"], [])
        self.assertEqual(payload["unmatched_candidates"], [])

    def test_debug_commit_episode_links_expose_les_liens_dry_run(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_commit_episode_links=lambda: {
                "date": "2026-05-05",
                "generated_at": "2026-05-05T16:30:00",
                "commit_count": 1,
                "linked_count": 1,
                "unlinked_count": 0,
                "links": [
                    {
                        "id": "commit-link-journal-1-1",
                        "entry_id": "journal-1",
                        "commit_subject": "feat: dry run",
                        "commit_message": "feat: dry run",
                        "delivered_at": None,
                        "journal_started_at": "2026-05-05T12:00:00",
                        "journal_ended_at": "2026-05-05T12:10:00",
                        "episode_id": "episode-1",
                        "candidate_id": "candidate-1",
                        "episode_started_at": "2026-05-05T12:01:00",
                        "episode_ended_at": "2026-05-05T12:09:00",
                        "project": "Pulse",
                        "confidence": 0.88,
                        "status": "linked",
                        "link_reason": "journal_candidate_overlap",
                        "flags": ["linked_by_overlap"],
                    }
                ],
                "unlinked_commits": [],
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/debug/commit-episode-links")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["commit_count"], 1)
        self.assertEqual(payload["linked_count"], 1)
        self.assertEqual(payload["links"][0]["episode_id"], "episode-1")

    def test_debug_commit_episode_links_supporte_le_query_param_date(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_today_commit_episode_links=lambda date=None: {
                "date": date.date().isoformat() if date else "today",
                "generated_at": "2026-05-05T16:30:00",
                "commit_count": 0,
                "linked_count": 0,
                "unlinked_count": 0,
                "links": [],
                "unlinked_commits": [],
            },
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        response = client.get("/debug/commit-episode-links?date=2026-05-05")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["date"], "2026-05-05")

    def test_debug_commit_episode_links_date_invalide_retourne_400(self):
        response = self.client.get("/debug/commit-episode-links?date=bad-date")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error"], "invalid_date")

    def test_debug_commit_episode_links_fallback_when_callback_absent(self):
        response = self.client.get("/debug/commit-episode-links")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["commit_count"], 0)
        self.assertEqual(payload["linked_count"], 0)
        self.assertEqual(payload["unlinked_count"], 0)
        self.assertEqual(payload["links"], [])
        self.assertEqual(payload["unlinked_commits"], [])

    def test_state_golden_legacy_json_output_exact(self):
        self.runtime_state.set_paused(True)
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
            activity_level="editing",
            task_confidence=0.81,
        )
        decision = Decision(
            action="notify",
            level=2,
            reason="high_friction",
            payload={"file": "PanelView.swift"},
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
            updated_at=datetime(2026, 4, 23, 10, 0, 0),
        )
        self.runtime_state.set_analysis(
            signals=signals,
            decision=decision,
        )

        self.store.to_dict.return_value = {
            "active_app": "Xcode",
            "session_duration_min": 96,
        }
        self.runtime_state.set_latest_active_app("Xcode")

        with patch("daemon.routes.runtime_state_payloads.last_session_context", return_value="Dernière session Pulse : hier (développement, 45 min)"):
            response = self.client.get("/state")

        self.assertEqual(response.status_code, 200)

        payload = response.get_json()

        self.assertEqual(payload["active_app"], "Xcode")
        self.assertEqual(payload["active_project"], "Pulse")
        self.assertEqual(
            payload["active_file"],
            "/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
        )
        self.assertEqual(payload["session_duration_min"], 96)
        self.assertEqual(payload["last_event_type"], None)
        self.assertTrue(payload["runtime_paused"])

        present = payload["present"]

        self.assertEqual(present["session_status"], "active")
        self.assertTrue(present["awake"])
        self.assertFalse(present["locked"])
        self.assertEqual(present["probable_task"], "coding")
        self.assertEqual(present["activity_level"], "editing")
        self.assertEqual(present["focus_level"], "deep")

        signals_payload = payload["signals"]

        self.assertEqual(signals_payload["active_project"], "Pulse")
        self.assertEqual(signals_payload["probable_task"], "coding")
        self.assertEqual(signals_payload["task_confidence"], 0.81)
        self.assertEqual(signals_payload["friction_score"], 0.42)
        self.assertEqual(signals_payload["focus_level"], "deep")

        decision_payload = payload["decision"]

        self.assertEqual(decision_payload["action"], "notify")
        self.assertEqual(decision_payload["reason"], "high_friction")
        self.assertEqual(
            decision_payload["payload"],
            {"file": "PanelView.swift"},
        )

        self.assertNotIn("debug", payload)

    def test_state_present_boundary_omits_confidence_while_legacy_signals_expose_it(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/pulse.py",
            probable_task="debug",
            friction_score=0.1,
            focus_level="normal",
            session_duration_min=12,
            recent_apps=["Terminal"],
            clipboard_context=None,
            activity_level="executing",
            task_confidence=0.32,
            terminal_action_category="testing",
            terminal_summary="pytest failed",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Terminal")
        self.store.to_dict.return_value = {"last_event_type": "terminal_command_finished"}

        with patch("daemon.routes.runtime_state_payloads.last_session_context", return_value=None):
            response = self.client.get("/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertNotIn("debug", payload)
        self.assertEqual(payload["present"]["probable_task"], "debug")
        self.assertNotIn("task_confidence", payload["present"])
        self.assertEqual(payload["signals"]["probable_task"], "debug")
        self.assertEqual(payload["signals"]["task_confidence"], 0.32)
        self.assertEqual(payload["signals"]["terminal_summary"], "pytest failed")

    def test_state_include_debug_query_exposes_legacy_debug_block(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift",
            probable_task="coding",
            friction_score=0.42,
            focus_level="deep",
            session_duration_min=96,
            recent_apps=["Xcode", "Codex", "Safari"],
            clipboard_context="text",
            activity_level="editing",
            task_confidence=0.81,
        )
        decision = Decision(
            action="notify",
            level=2,
            reason="high_friction",
            payload={"file": "PanelView.swift"},
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=decision)
        self.runtime_state.set_latest_active_app("Xcode")
        self.store.to_dict.return_value = {
            "active_app": "Xcode",
            "session_duration_min": 96,
        }

        with patch("daemon.routes.runtime_state_payloads.last_session_context", return_value=None):
            response = self.client.get("/state?include_debug=true")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("debug", payload)

        debug = payload["debug"]

        self.assertIn("store", debug)
        self.assertIn("runtime", debug)
        self.assertIn("signals", debug)
        self.assertIn("decision", debug)
        self.assertEqual(debug["surface"], "debug_state")
        self.assertTrue(debug["legacy_in_state"])

    def test_debug_state_route_exposes_debug_payload_explicitly(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/current.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=24,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )
        decision = Decision("silent", 0, "nothing_relevant")
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=decision)
        self.runtime_state.set_latest_active_app("Xcode")
        self.store.to_dict.return_value = {
            "active_app": "Xcode",
            "last_event_type": "file_modified",
        }

        with patch("daemon.routes.runtime_state_payloads.last_session_context", return_value=None):
            response = self.client.get("/debug/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["surface"], "debug_state")
        self.assertFalse(payload["legacy_in_state"])
        self.assertEqual(payload["store"]["last_event_type"], "file_modified")
        self.assertEqual(payload["runtime"]["latest_active_app"], "Xcode")
        self.assertEqual(payload["signals"]["active_project"], "Pulse")
        self.assertEqual(payload["decision"]["action"], "silent")

    def test_debug_state_route_exposes_debug_surface_separate_from_state(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/current.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=24,
            recent_apps=["Xcode"],
            clipboard_context="text",
            activity_level="editing",
            task_confidence=0.81,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Xcode")
        self.store.to_dict.return_value = {
            "active_app": "Xcode",
            "last_event_type": "file_modified",
        }

        with patch("daemon.routes.runtime_state_payloads.last_session_context", return_value=None):
            state_response = self.client.get("/state")
            debug_response = self.client.get("/debug/state")

        self.assertEqual(state_response.status_code, 200)
        self.assertEqual(debug_response.status_code, 200)
        state_payload = state_response.get_json()
        debug_payload = debug_response.get_json()
        self.assertNotIn("debug", state_payload)
        self.assertNotIn("store", state_payload)
        self.assertNotIn("runtime", state_payload)
        self.assertEqual(debug_payload["surface"], "debug_state")
        self.assertFalse(debug_payload["legacy_in_state"])
        self.assertEqual(debug_payload["store"]["last_event_type"], "file_modified")
        self.assertEqual(debug_payload["runtime"]["latest_active_app"], "Xcode")
        self.assertEqual(debug_payload["signals"]["task_confidence"], 0.81)

    def test_state_and_debug_state_expose_session_boundaries_from_runtime_not_markdown(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/current.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=17,
            recent_apps=["Xcode"],
            clipboard_context="text",
            activity_level="editing",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
            updated_at=datetime(2026, 5, 6, 10, 17, 0),
        )
        self.runtime_state.set_paused(True)
        self.store.to_dict.return_value = {"session_duration_min": 999}

        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_session_fsm=lambda: SimpleNamespace(
                state="active",
                session_started_at=datetime(2026, 5, 6, 10, 0, 0),
                last_meaningful_activity_at=datetime(2026, 5, 6, 10, 16, 0),
                last_screen_locked_at=None,
            ),
            get_recent_sessions=lambda limit: [
                {
                    "id": "closed-session",
                    "started_at": "2026-05-06T08:00:00",
                    "ended_at": "2026-05-06T08:45:00",
                    "active_project": "Pulse",
                }
            ],
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()

        with patch("daemon.routes.runtime_state_payloads.last_session_context", side_effect=AssertionError("Markdown session context must not define session state")):
            state_response = client.get("/state")
            debug_response = client.get("/debug/state")

        self.assertEqual(state_response.status_code, 200)
        self.assertEqual(debug_response.status_code, 200)
        state_payload = state_response.get_json()
        debug_payload = debug_response.get_json()

        self.assertTrue(state_payload["runtime_paused"])
        self.assertEqual(state_payload["present"]["session_status"], "active")
        self.assertEqual(state_payload["session_fsm"]["state"], "active")
        self.assertEqual(state_payload["session_duration_min"], 17)
        self.assertEqual(state_payload["present"]["session_duration_min"], 17)
        self.assertEqual(state_payload["recent_sessions"][0]["ended_at"], "2026-05-06T08:45:00")
        self.assertEqual(debug_payload["surface"], "debug_state")
        self.assertEqual(debug_payload["session_fsm"]["session_started_at"], "2026-05-06T10:00:00")
        self.assertEqual(debug_payload["recent_sessions"][0]["id"], "closed-session")

    def test_state_fallbacks_to_builder_when_current_context_absent(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/main.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=24,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.store.to_dict.return_value = {
            "active_project": None,
            "active_file": None,
            "active_app": "Xcode",
            "session_duration_min": 0,
        }

        with patch("daemon.routes.runtime_ingestion.find_workspace_root", return_value=None), \
             patch("daemon.routes.runtime_state_payloads.last_session_context", return_value="Dernière session Pulse : hier (développement, 45 min)"):
            response = self.client.get("/state")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["active_project"], "Pulse")
        self.assertEqual(payload["active_file"], "/tmp/main.py")
        self.assertEqual(payload["signals"]["active_project"], "Pulse")
        self.assertEqual(payload["signals"]["active_file"], "/tmp/main.py")
        self.assertEqual(payload["signals"]["session_duration_min"], 24)
        self.assertNotIn("debug", payload)

    def test_state_builder_ignores_store_active_file_and_project(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/current.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=24,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("RuntimeApp")
        self.store.to_dict.return_value = {
            "active_project": "OldProject",
            "active_file": "/tmp/stale.py",
            "active_app": "Xcode",
            "session_duration_min": 999,
        }

        with patch("daemon.routes.runtime_state_payloads.last_session_context", return_value=None):
            response = self.client.get("/state?include_debug=1")

        payload = response.get_json()
        self.assertEqual(payload["active_project"], "Pulse")
        self.assertEqual(payload["active_file"], "/tmp/current.py")
        self.assertEqual(payload["active_app"], "RuntimeApp")
        self.assertEqual(payload["session_duration_min"], 24)
        self.assertEqual(payload["signals"]["active_project"], "Pulse")
        self.assertEqual(payload["signals"]["active_file"], "/tmp/current.py")
        self.assertEqual(payload["signals"]["session_duration_min"], 24)
        self.assertEqual(payload["debug"]["store"]["active_project"], "OldProject")
        self.assertEqual(payload["debug"]["store"]["active_file"], "/tmp/stale.py")
        self.assertEqual(payload["debug"]["store"]["active_app"], "Xcode")
        self.assertEqual(payload["debug"]["store"]["session_duration_min"], 999)

    def test_state_uses_atomic_runtime_snapshot_read_path(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/current.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=24,
            recent_apps=["Xcode"],
            clipboard_context="text",
        )
        decision = Decision("silent", 0, "nothing_relevant")
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=decision)
        self.store.to_dict.return_value = {
            "active_app": "Xcode",
            "last_event_type": "file_modified",
        }

        with patch.object(self.runtime_state, "get_signal_snapshot", side_effect=AssertionError("legacy signal snapshot must not be used")), \
             patch.object(self.runtime_state, "get_present_snapshot", side_effect=AssertionError("legacy present snapshot must not be used")), \
             patch("daemon.routes.runtime_state_payloads.last_session_context", return_value=None):
            response = self.client.get("/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["present"]["active_project"], "Pulse")
        self.assertEqual(payload["signals"]["active_project"], "Pulse")

    def test_state_exposes_current_context_and_recent_sessions_when_getters_are_provided(self):
        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_current_context=lambda: SessionContext(
                id="ep-1",
                session_id="session-1",
                started_at="2026-04-22T10:00:00",
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.81,
            ),
            get_recent_sessions=lambda limit: [
                {
                    "id": "ep-1",
                    "session_id": "session-1",
                    "started_at": "2026-04-22T10:00:00",
                    "ended_at": None,
                    "boundary_reason": None,
                    "duration_sec": None,
                    "active_project": "Pulse",
                    "probable_task": "coding",
                    "activity_level": "editing",
                    "task_confidence": 0.81,
                }
            ],
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()
        self.store.to_dict.return_value = {}

        response = client.get("/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["current_context"]["id"], "ep-1")
        self.assertEqual(payload["current_context"]["active_project"], "Pulse")
        self.assertEqual(payload["current_context"]["probable_task"], "coding")
        self.assertEqual(payload["recent_sessions"][0]["id"], "ep-1")
        self.assertEqual(payload["recent_sessions"][0]["active_project"], "Pulse")
        self.assertEqual(payload["recent_sessions"][0]["activity_level"], "editing")
        self.assertNotIn("current_episode", payload)
        self.assertNotIn("recent_episodes", payload)

        debug_response = client.get("/debug/state")
        self.assertEqual(debug_response.status_code, 200)
        debug_payload = debug_response.get_json()
        self.assertEqual(debug_payload["surface"], "debug_state")
        self.assertFalse(debug_payload["legacy_in_state"])
        self.assertEqual(debug_payload["current_context"]["id"], "ep-1")
        self.assertEqual(debug_payload["recent_sessions"][0]["id"], "ep-1")

    def test_state_keeps_product_hierarchy_with_present_context_and_signals(self):
        signals = Signals(
            active_project="SignalsProject",
            active_file="/tmp/signals.py",
            probable_task="general",
            activity_level="reading",
            task_confidence=0.22,
            friction_score=0.61,
            focus_level="scattered",
            session_duration_min=12,
            recent_apps=["Chrome"],
            clipboard_context="text",
        )
        self.runtime_state.update_present(
            signals=Signals(
                active_project="Pulse",
                active_file="/tmp/live.py",
                probable_task="debug",
                activity_level="executing",
                task_confidence=0.88,
                friction_score=0.18,
                focus_level="deep",
                session_duration_min=33,
                recent_apps=["Terminal"],
                clipboard_context="code",
            ),
            session_status="active",
            awake=True,
            locked=False,
            updated_at=datetime(2026, 4, 23, 12, 0, 0),
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)

        app = Flask(__name__)
        register_runtime_routes(
            app,
            bus=self.bus,
            store=self.store,
            runtime_state=self.runtime_state,
            get_current_context=lambda: SessionContext(
                id="ep-1",
                session_id="session-1",
                started_at="2026-04-23T11:50:00",
                active_project="Pulse",
                probable_task="coding",
                activity_level="editing",
                task_confidence=0.86,
            ),
            llm_unload_background=self.llm_unload_background,
            llm_warmup_background=self.llm_warmup_background,
            shutdown_runtime=self.shutdown_runtime,
            log=self.log,
        )
        client = app.test_client()
        self.store.to_dict.return_value = {"active_app": "Terminal"}

        with patch("daemon.routes.runtime_state_payloads.last_session_context", return_value=None):
            response = client.get("/state")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["current_context"]["active_project"], "Pulse")
        self.assertEqual(payload["current_context"]["probable_task"], "coding")
        self.assertEqual(payload["present"]["active_project"], "Pulse")
        self.assertEqual(payload["present"]["probable_task"], "debug")
        self.assertIn("signals", payload)
        self.assertEqual(payload["signals"]["probable_task"], "debug")
        self.assertEqual(payload["signals"]["focus_level"], "deep")
        self.assertEqual(payload["signals"]["friction_score"], 0.61)
        self.assertEqual(payload["active_project"], payload["present"]["active_project"])
        self.assertEqual(payload["active_file"], payload["present"]["active_file"])

    def test_ping_returns_status_and_pause_state(self):
        self.runtime_state.set_paused(True)
        response = self.client.get("/ping")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"status": "ok", "version": "0.1.0", "paused": True},
        )

    def test_health_core_returns_minimal_core_status(self):
        with patch.dict("os.environ", {"PULSE_MODE": "core"}):
            response = self.client.get("/health/core")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pulse_mode"], "core")
        self.assertFalse(payload["experimental_enabled"])
        self.assertEqual(payload["checks"]["runtime"], "ok")
        self.assertEqual(payload["checks"]["ping"], "ok")
        self.assertEqual(payload["checks"]["runtime_state"], "ok")
        self.assertEqual(payload["checks"]["event_bus"], "ok")
        self.assertEqual(payload["checks"]["feed_source"], "ok")
        self.assertEqual(payload["checks"]["scoring"], "available")
        self.assertEqual(payload["checks"]["session_fsm"], "not_checked")
        self.assertEqual(payload["checks"]["lab_services"], "not_required")
        self.assertEqual(payload["failed"], {})

    def test_health_core_lab_mode_marks_lab_services_enabled(self):
        with patch.dict("os.environ", {"PULSE_MODE": "lab"}):
            response = self.client.get("/health/core")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pulse_mode"], "lab")
        self.assertTrue(payload["experimental_enabled"])
        self.assertEqual(payload["checks"]["lab_services"], "enabled")

    def test_core_routes_ping_state_and_feed_work_in_core_mode(self):
        self.store.to_dict.return_value = {}
        self.bus.recent.return_value = []

        with patch.dict("os.environ", {"PULSE_MODE": "core"}):
            ping_response = self.client.get("/ping")
            state_response = self.client.get("/state")
            feed_response = self.client.get("/feed")

        self.assertEqual(ping_response.status_code, 200)
        self.assertEqual(ping_response.get_json()["status"], "ok")

        self.assertEqual(state_response.status_code, 200)
        state_payload = state_response.get_json()
        self.assertEqual(state_payload["pulse_mode"], "core")
        self.assertFalse(state_payload["experimental_enabled"])

        self.assertEqual(feed_response.status_code, 200)
        self.assertEqual(feed_response.get_json(), [])
        self.bus.recent.assert_called_with(200)

    def test_feed_contract_is_not_a_complete_raw_event_journal(self):
        now = datetime(2026, 5, 28, 10, 0, 0)
        self.bus.recent.return_value = [
            Event("app_activated", {"app_name": "Code"}, now),
            Event("file_modified", {"path": "/Users/tester/workspace/acme/app.py"}, now),
            Event("user_presence", {"state": "active", "idle_seconds": 0}, now),
            Event("screen_locked", {}, now),
            Event("screen_unlocked", {}, now),
            Event(
                "terminal_command_finished",
                {
                    "terminal_command": "pytest tests/test_runtime_routes.py -q",
                    "terminal_command_base": "pytest",
                    "terminal_success": True,
                    "terminal_summary": "✓ pytest tests/test_runtime_routes.py",
                },
                now,
            ),
        ]

        response = self.client.get("/feed")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["kind"], "terminal")
        self.assertEqual(payload[0]["label"], "pytest test_runtime_routes")
        self.assertEqual(payload[0]["command"], "pytest tests/test_runtime_routes.py -q")
        self.bus.recent.assert_called_with(200)

    def test_health_core_ne_depend_pas_des_services_lab(self):
        with patch.dict("os.environ", {"PULSE_MODE": "core"}), \
             patch("daemon.memory.daydream.get_daydream_status") as daydream_status, \
             patch("daemon.memory.extractor.get_fact_engine") as get_fact_engine, \
             patch("daemon.memory.extractor.embeddings_enabled") as embeddings_enabled, \
             patch("daemon.memory.vector_store.VectorStore") as vector_store:
            response = self.client.get("/health/core")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["checks"]["lab_services"], "not_required")
        daydream_status.assert_not_called()
        get_fact_engine.assert_not_called()
        embeddings_enabled.assert_not_called()
        vector_store.assert_not_called()

    def test_event_endpoint_ignores_events_while_runtime_is_paused(self):
        self.runtime_state.set_paused(True)
        response = self.client.post("/event", json={"type": "file_modified", "path": "/tmp/test.py"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "paused": True, "ignored": True},
        )
        self.bus.publish.assert_not_called()

    def test_event_endpoint_normalizes_terminal_event_and_drops_raw_command(self):
        response = self.client.post(
            "/event",
            json={
                "type": "terminal_command_finished",
                "command": "git status",
                "cwd": "/Users/yugz/Projets/Pulse/Pulse",
                "shell": "zsh",
                "terminal_program": "Apple_Terminal",
                "exit_code": 0,
                "duration_ms": 1200,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        self.bus.publish.assert_called_once()
        event_type, payload = self.bus.publish.call_args.args
        self.assertEqual(event_type, "terminal_command_finished")
        self.assertEqual(payload["source"], "terminal")
        self.assertEqual(payload["kind"], "finished")
        self.assertEqual(payload["terminal_action_category"], "vcs")
        self.assertEqual(payload["terminal_project"], "Pulse")
        self.assertEqual(payload["terminal_cwd"], "/Users/yugz/Projets/Pulse/Pulse")
        self.assertEqual(payload["terminal_exit_code"], 0)
        self.assertEqual(payload["terminal_duration_ms"], 1200)
        self.assertNotIn("command", payload)

    def test_event_endpoint_adds_test_result_for_testing_terminal_event(self):
        response = self.client.post(
            "/event",
            json={
                "type": "terminal_command_finished",
                "command": "python -m pytest tests/core/test_signal_scorer.py",
                "cwd": "/Users/yugz/Projets/Pulse/Pulse",
                "exit_code": 1,
                "stdout": "full stacktrace should not be forwarded",
                "stdout_summary": "1 error, 3 failed, 20 passed, 2 skipped in 5.1s",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.bus.publish.assert_called_once()
        event_type, payload = self.bus.publish.call_args.args
        self.assertEqual(event_type, "terminal_command_finished")
        self.assertNotIn("stdout", payload)
        self.assertEqual(payload["test_result"]["framework"], "pytest")
        self.assertEqual(payload["test_result"]["error_count"], 1)
        self.assertEqual(payload["test_result"]["failed_count"], 3)
        self.assertEqual(payload["test_result"]["passed_count"], 20)
        self.assertEqual(payload["test_result"]["skipped_count"], 2)
        self.assertEqual(payload["test_result"]["target"], "tests/core/test_signal_scorer.py")

    def test_event_endpoint_adds_git_context_for_terminal_cwd_in_repo(self):
        git_context = {
            "repo_root": "/Users/yugz/Projets/Pulse/Pulse",
            "repo_name": "Pulse",
            "branch": "main",
            "head_sha": "abc1234",
            "is_dirty": True,
            "staged_count": 2,
            "unstaged_count": 1,
            "untracked_count": 0,
        }

        with patch("daemon.core.git_context.read_git_context", return_value=git_context):
            response = self.client.post(
                "/event",
                json={
                    "type": "terminal_command_finished",
                    "command": "git status",
                    "cwd": "/Users/yugz/Projets/Pulse/Pulse",
                    "exit_code": 0,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.bus.publish.assert_called_once()
        _, payload = self.bus.publish.call_args.args
        self.assertEqual(payload["git_context"], git_context)
        self.assertNotIn("files", payload["git_context"])
        self.assertNotIn("diff", payload["git_context"])

    def test_event_endpoint_omits_git_context_when_unavailable(self):
        with patch("daemon.core.git_context.read_git_context", return_value=None):
            response = self.client.post(
                "/event",
                json={
                    "type": "terminal_command_finished",
                    "command": "git status",
                    "cwd": "/tmp/not-a-repo",
                    "exit_code": 0,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.bus.publish.assert_called_once()
        _, payload = self.bus.publish.call_args.args
        self.assertNotIn("git_context", payload)

    def test_event_endpoint_transmet_le_timestamp_source_au_bus(self):
        source_ts = "2026-04-23T10:15:30"

        response = self.client.post(
            "/event",
            json={
                "type": "app_activated",
                "app_name": "Cursor",
                "timestamp": source_ts,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.bus.publish.assert_called_once()
        event_type, payload, observed_at = self.bus.publish.call_args.args
        self.assertEqual(event_type, "app_activated")
        self.assertEqual(payload, {"app_name": "Cursor"})
        self.assertEqual(observed_at.isoformat(), "2026-04-23T10:15:30")

    def test_event_actor_uses_latest_active_app_bundle_id_for_tool_assisted(self):
        self.bus.recent.return_value = []

        response = self.client.post(
            "/event",
            json={
                "type": "app_activated",
                "app_name": "RandomTool",
                "bundle_id": "dev.pulse.test.ToolAssistant",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.bus.publish.assert_called_once()
        self.bus.publish.reset_mock()

        response = self.client.post(
            "/event",
            json={
                "type": "file_modified",
                "path": "/tmp/acme-api/src/handler.py",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.coalescer.close()

        self.bus.publish.assert_called_once()
        event_type, payload = self.bus.publish.call_args.args[:2]
        self.assertEqual(event_type, "file_modified")
        self.assertEqual(payload["_actor"], "tool_assisted")
        self.assertGreater(payload["_automation_score"], 0.5)

    def test_event_endpoint_stores_latest_active_app_system_category(self):
        response = self.client.post(
            "/event",
            json={
                "type": "app_activated",
                "app_name": "RandomIDE",
                "bundle_id": "dev.pulse.test.UnknownIDE",
                "system_category": "public.app-category.developer-tools",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.runtime_state.get_latest_active_app(), "RandomIDE")
        self.assertEqual(self.runtime_state.get_latest_active_app_bundle_id(), "dev.pulse.test.UnknownIDE")
        self.assertEqual(
            self.runtime_state.get_latest_active_app_system_category(),
            "public.app-category.developer-tools",
        )

    def test_event_actor_does_not_treat_ai_support_bundle_as_tool_assisted(self):
        self.bus.recent.return_value = []

        response = self.client.post(
            "/event",
            json={
                "type": "app_activated",
                "app_name": "RandomAssistant",
                "bundle_id": "dev.pulse.test.UnknownAI",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.bus.publish.assert_called_once()
        self.bus.publish.reset_mock()

        response = self.client.post(
            "/event",
            json={
                "type": "file_modified",
                "path": "/tmp/acme-api/src/handler.py",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.coalescer.close()

        self.bus.publish.assert_called_once()
        event_type, payload = self.bus.publish.call_args.args[:2]
        self.assertEqual(event_type, "file_modified")
        self.assertNotEqual(payload["_actor"], "tool_assisted")
        self.assertLessEqual(payload["_automation_score"], 0.5)

    def test_event_file_pending_dans_coalescer_est_publie_au_close(self):
        response = self.client.post(
            "/event",
            json={
                "type": "file_modified",
                "path": "/tmp/Pulse/daemon/main.py",
                "timestamp": "2026-04-23T10:15:30",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        self.bus.publish.assert_not_called()

        self.coalescer.close()

        self.bus.publish.assert_called_once()
        event_type, payload, observed_at = self.bus.publish.call_args.args
        self.assertEqual(event_type, "file_modified")
        self.assertEqual(payload["path"], "/tmp/Pulse/daemon/main.py")
        self.assertEqual(observed_at.isoformat(), "2026-04-23T10:15:30")

    def test_insights_uses_default_limit_of_twenty_five(self):
        self.bus.recent.return_value = []
        response = self.client.get("/insights")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        self.bus.recent.assert_called_once_with(25)

    def test_insights_falls_back_to_default_limit_on_invalid_value(self):
        self.bus.recent.return_value = []
        response = self.client.get("/insights?limit=abc")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        self.bus.recent.assert_called_once_with(25)

    def test_insights_clamps_limit_to_one_hundred(self):
        self.bus.recent.return_value = []
        response = self.client.get("/insights?limit=500")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        self.bus.recent.assert_called_once_with(100)

    def test_insights_contract_is_debug_raw_recent_event_payloads(self):
        self.bus.recent.return_value = [
            Event(
                "terminal_command_finished",
                {
                    "terminal_command": "curl -H 'Authorization: Bearer SECRET_TOKEN' https://example.test",
                    "terminal_cwd": "/Users/yugz/Projets/Pulse/Pulse",
                    "git_context": {
                        "repo_root": "/Users/yugz/Projets/Pulse/Pulse",
                        "repo_name": "Pulse",
                        "branch": "main",
                    },
                },
                timestamp=datetime(2026, 5, 1, 16, 0, 0),
            ),
            Event(
                "window_title_poll",
                {
                    "window_title": "Pulse notes yugz@example.com /Users/yugz/private",
                    "app_name": "Code",
                },
                timestamp=datetime(2026, 5, 1, 16, 1, 0),
            ),
        ]

        response = self.client.get("/insights")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["payload"]["terminal_command"], self.bus.recent.return_value[0].payload["terminal_command"])
        self.assertEqual(payload[0]["payload"]["git_context"]["repo_root"], "/Users/yugz/Projets/Pulse/Pulse")
        self.assertEqual(payload[1]["payload"]["window_title"], "Pulse notes yugz@example.com /Users/yugz/private")

    def test_events_debug_describes_recent_events_without_raw_payload_values(self):
        self.bus.recent.return_value = [
            Event(
                "file_modified",
                {"path": "/tmp/Pulse/daemon/main.py", "_actor": "user"},
                timestamp=datetime(2026, 5, 1, 16, 0, 0),
            ),
            Event(
                "clipboard_updated",
                {"clipboard_context": "text", "length": 42},
                timestamp=datetime(2026, 5, 1, 16, 1, 0),
            ),
        ]

        response = self.client.get("/events/debug")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["events"][0]["type"], "file_modified")
        self.assertEqual(payload["events"][0]["source"], "filesystem")
        self.assertEqual(payload["events"][0]["bucket"], "filesystem")
        self.assertEqual(payload["events"][0]["privacy"], "path_sensitive")
        self.assertEqual(payload["events"][0]["retention"], "session")
        self.assertEqual(payload["events"][0]["payload_keys"], ["_actor", "path"])
        self.assertNotIn("payload", payload["events"][0])
        self.assertNotIn("/tmp/Pulse/daemon/main.py", str(payload["events"][0]))

        self.assertEqual(payload["events"][1]["type"], "clipboard_updated")
        self.assertEqual(payload["events"][1]["source"], "clipboard")
        self.assertEqual(payload["events"][1]["bucket"], "clipboard_activity")
        self.assertEqual(payload["events"][1]["privacy"], "content_sensitive")
        self.assertEqual(payload["events"][1]["retention"], "ephemeral")
        self.assertEqual(payload["events"][1]["payload_keys"], ["clipboard_context", "length"])
        self.assertNotIn("payload", payload["events"][1])
        self.bus.recent.assert_called_once_with(50)

    def test_events_debug_clamps_limit_and_filters_since(self):
        self.bus.recent.return_value = [
            Event(
                "file_modified",
                {"path": "/tmp/old.py"},
                timestamp=datetime(2026, 5, 1, 15, 59, 0),
            ),
            Event(
                "app_activated",
                {"app_name": "Code"},
                timestamp=datetime(2026, 5, 1, 16, 1, 0),
            ),
        ]

        response = self.client.get("/events/debug?limit=500&since=2026-05-01T16:00:00")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["events"][0]["type"], "app_activated")
        self.assertEqual(payload["events"][0]["source"], "app")
        self.assertEqual(payload["events"][0]["privacy"], "public")
        self.bus.recent.assert_called_once_with(200)

    def test_events_debug_invalid_limit_uses_default(self):
        self.bus.recent.return_value = []

        response = self.client.get("/events/debug?limit=abc")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"events": [], "count": 0})
        self.bus.recent.assert_called_once_with(50)

    def test_events_debug_filters_by_event_metadata(self):
        self.bus.recent.return_value = [
            Event(
                "file_modified",
                {"path": "/tmp/Pulse/daemon/main.py"},
                timestamp=datetime(2026, 5, 1, 16, 0, 0),
            ),
            Event(
                "clipboard_updated",
                {"clipboard_context": "text", "length": 42},
                timestamp=datetime(2026, 5, 1, 16, 1, 0),
            ),
            Event(
                "app_activated",
                {"app_name": "Code"},
                timestamp=datetime(2026, 5, 1, 16, 2, 0),
            ),
        ]

        response = self.client.get(
            "/events/debug?source=clipboard&bucket=clipboard_activity&privacy=content_sensitive&retention=ephemeral"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["events"][0]["type"], "clipboard_updated")
        self.assertEqual(payload["events"][0]["source"], "clipboard")
        self.assertEqual(payload["events"][0]["bucket"], "clipboard_activity")
        self.assertEqual(payload["events"][0]["privacy"], "content_sensitive")
        self.assertEqual(payload["events"][0]["retention"], "ephemeral")
        self.bus.recent.assert_called_once_with(50)

    def test_events_schema_exposes_event_metadata_enums(self):
        response = self.client.get("/events/schema")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertIn("filesystem", payload["sources"])
        self.assertIn("terminal", payload["sources"])
        self.assertIn("unknown", payload["sources"])

        self.assertIn("filesystem", payload["buckets"])
        self.assertIn("terminal_activity", payload["buckets"])
        self.assertIn("unknown", payload["buckets"])

        self.assertIn("public", payload["privacy_classes"])
        self.assertIn("path_sensitive", payload["privacy_classes"])
        self.assertIn("content_sensitive", payload["privacy_classes"])
        self.assertIn("secret_sensitive", payload["privacy_classes"])
        self.assertIn("unknown", payload["privacy_classes"])

        self.assertIn("ephemeral", payload["retention_classes"])
        self.assertIn("session", payload["retention_classes"])
        self.assertIn("persistent", payload["retention_classes"])
        self.assertIn("debug_only", payload["retention_classes"])

    def test_timeline_preview_builds_span_from_current_context_when_signals_exist(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/Pulse/daemon/runtime.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=30,
            recent_apps=["Code"],
            clipboard_context="text",
            activity_level="editing",
            task_confidence=0.82,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Code")

        with patch("daemon.routes.runtime_debug_routes.find_workspace_root", return_value=None):
            response = self.client.get("/timeline/preview")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        span = payload["span"]
        debug = payload["debug"]
        self.assertEqual(span["kind"], "work")
        self.assertEqual(span["title"], "Pulse — coding")
        self.assertEqual(span["project"], "Pulse")
        self.assertEqual(span["activity_level"], "editing")
        self.assertEqual(span["probable_task"], "coding")
        self.assertEqual(span["confidence"], 0.82)
        self.assertEqual(span["buckets"], ["filesystem"])
        self.assertEqual(span["privacy"], "path_sensitive")
        self.assertEqual(span["retention"], "session")
        self.assertEqual(span["evidence_event_count"], 0)
        self.assertEqual(span["metadata"], {"source": "current_context"})
        self.assertEqual(span["duration_min"], 30)
        self.assertEqual(debug["kind"], "work")
        self.assertEqual(debug["title"], "Pulse — coding")
        self.assertEqual(debug["policy"], {
            "privacy": "Path-sensitive span",
            "retention": "Session-scoped by default",
            "confidence": "High confidence",
        })
        self.assertEqual(debug["metadata_keys"], ["source"])
        self.assertNotIn("metadata", debug)

    def test_timeline_preview_falls_back_to_present_when_no_signals_exist(self):
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="debug",
            friction_score=0.2,
            focus_level="normal",
            session_duration_min=5,
            recent_apps=["Terminal"],
            clipboard_context=None,
            activity_level="executing",
            task_confidence=0.91,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )

        response = self.client.get("/timeline/preview")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        span = payload["span"]
        debug = payload["debug"]
        self.assertEqual(span["kind"], "debug")
        self.assertEqual(span["title"], "Pulse — debug")
        self.assertEqual(span["project"], "Pulse")
        self.assertEqual(span["activity_level"], "executing")
        self.assertEqual(span["probable_task"], "debug")
        self.assertEqual(span["confidence"], 0.0)
        self.assertEqual(span["buckets"], ["terminal_activity"])
        self.assertEqual(span["privacy"], "content_sensitive")
        self.assertEqual(span["duration_min"], 5)
        self.assertEqual(debug["kind"], "debug")
        self.assertEqual(debug["title"], "Pulse — debug")
        self.assertEqual(debug["policy"], {
            "privacy": "Content-sensitive span",
            "retention": "Session-scoped by default",
            "confidence": "No confidence score",
        })
        self.assertEqual(debug["metadata_keys"], ["source"])
        self.assertNotIn("metadata", debug)

    def test_timeline_schema_exposes_span_kinds(self):
        response = self.client.get("/timeline/schema")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertIn("work", payload["span_kinds"])
        self.assertIn("break", payload["span_kinds"])
        self.assertIn("debug", payload["span_kinds"])
        self.assertIn("reading", payload["span_kinds"])
        self.assertIn("execution", payload["span_kinds"])
        self.assertIn("system", payload["span_kinds"])
        self.assertIn("memory", payload["span_kinds"])
        self.assertIn("unknown", payload["span_kinds"])


    def test_work_context_route_builds_passive_card_from_current_runtime_context(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/Pulse/daemon/work_context_card.py",
            probable_task="debug",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=42,
            recent_apps=["Code", "Terminal", "ChatGPT"],
            clipboard_context="text",
            edited_file_count_10m=3,
            activity_level="editing",
            task_confidence=0.78,
            window_title="Pulse — work_context_card.py — Visual Studio Code",
            window_title_app="Code",
        )
        decision = Decision(
            action="context_ready",
            level=1,
            reason="context_available",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_work_intent(WorkIntent(
            summary="réduire les coûts cachés du modèle local",
            source="manual",
            confidence=0.9,
            project="Pulse",
        ))
        self.runtime_state.set_analysis(signals=signals, decision=decision)
        self.runtime_state.set_latest_active_app("Code")

        with patch("daemon.routes.runtime_debug_routes.find_workspace_root", return_value=None):
            response = self.client.get("/work-context")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        card = payload["card"]

        self.assertEqual(card["project"], "Pulse")
        self.assertEqual(card["project_hint"], None)
        self.assertEqual(card["project_hint_confidence"], 0.0)
        self.assertEqual(card["project_hint_source"], None)
        self.assertEqual(card["activity_level"], "editing")
        self.assertEqual(card["probable_task"], "debug")
        self.assertEqual(card["work_intent"]["summary"], "réduire les coûts cachés du modèle local")
        self.assertEqual(card["confidence"], 0.78)
        self.assertEqual(card["project_status"], "observed")
        self.assertEqual(card["task_status"], "probable")
        self.assertIn("Projet actif observé : Pulse", card["evidence"])
        self.assertIn("Niveau d'activité : editing", card["evidence"])
        self.assertIn("Tâche probable : debug", card["evidence"])
        self.assertIn("Application active : Code", card["evidence"])
        self.assertIn("Titre de fenêtre disponible", card["evidence"])
        self.assertIn("Fichiers modifiés récemment : 3", card["evidence"])
        self.assertIn("Applications récentes : Code, Terminal, ChatGPT", card["evidence"])
        self.assertIn("Décision runtime récente : context_ready", card["evidence"])
        self.assertEqual(card["missing_context"], [])
        self.assertEqual(card["safe_next_probes"], [])
        self.assertNotIn("active_file", card)
        self.assertNotIn("/tmp/Pulse/daemon/work_context_card.py", str(card))

    def test_expired_work_intent_is_cleared_from_runtime_state(self):
        self.runtime_state.set_work_intent(WorkIntent(
            summary="Note de test pour voir si le projet est bien présent.",
            source="manual_context_note",
            confidence=0.9,
            project="Pulse",
            expires_at=datetime.now() - timedelta(minutes=1),
        ))

        present = self.runtime_state.get_present()

        self.assertIsNone(present.work_intent)
        self.assertIsNone(self.runtime_state.get_present_snapshot()["work_intent"])

    def test_non_expired_work_intent_remains_active(self):
        self.runtime_state.set_work_intent(WorkIntent(
            summary="réduire les coûts cachés du modèle local",
            source="manual_context_note",
            confidence=0.9,
            project="Pulse",
            expires_at=datetime.now() + timedelta(hours=1),
        ))

        present = self.runtime_state.get_present()

        self.assertIsNotNone(present.work_intent)
        self.assertEqual(present.work_intent.summary, "réduire les coûts cachés du modèle local")

    def test_state_route_does_not_expose_expired_work_intent(self):
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="coding",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=12,
            recent_apps=[],
            clipboard_context=None,
            activity_level="editing",
            task_confidence=0.8,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_work_intent(WorkIntent(
            summary="Note de test pour voir si le projet est bien présent.",
            source="manual_context_note",
            confidence=0.9,
            project="Pulse",
            expires_at=datetime.now() - timedelta(minutes=1),
        ))
        self.store.to_dict.return_value = {}

        response = self.client.get("/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNone(payload["present"]["work_intent"])
        self.assertNotIn("work_intent", payload["signals"])

    def test_work_context_route_does_not_expose_expired_work_intent(self):
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="coding",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=12,
            recent_apps=[],
            clipboard_context=None,
            activity_level="editing",
            task_confidence=0.8,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_work_intent(WorkIntent(
            summary="Note de test pour voir si le projet est bien présent.",
            source="manual_context_note",
            confidence=0.9,
            project="Pulse",
            expires_at=datetime.now() - timedelta(minutes=1),
        ))

        response = self.client.get("/work-context")

        self.assertEqual(response.status_code, 200)
        card = response.get_json()["card"]
        self.assertIsNone(card["work_intent"])
        self.assertNotIn("Objectif de travail :", " ".join(card["evidence"]))

    def test_work_context_route_falls_back_to_present_without_signals(self):
        signals = Signals(
            active_project=None,
            active_file=None,
            probable_task="general",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=5,
            recent_apps=[],
            clipboard_context=None,
            activity_level="unknown",
            task_confidence=None,
            window_title=None,
            window_title_app=None,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )

        response = self.client.get("/work-context")

        self.assertEqual(response.status_code, 200)
        card = response.get_json()["card"]
        self.assertEqual(card["project"], None)
        self.assertEqual(card["project_hint"], None)
        self.assertEqual(card["project_hint_confidence"], 0.0)
        self.assertEqual(card["project_hint_source"], None)
        self.assertEqual(card["activity_level"], "unknown")
        self.assertEqual(card["probable_task"], "general")
        self.assertEqual(card["confidence"], 0.0)
        self.assertEqual(card["project_status"], "unknown")
        self.assertEqual(card["task_status"], "unknown")
        self.assertEqual(card["evidence"], [])
        self.assertEqual(card["missing_context"], [
            "Projet actif non identifié",
            "Tâche utilisateur encore générale",
            "Niveau d'activité incertain",
            "Titre de fenêtre non disponible",
        ])
        self.assertEqual(card["safe_next_probes"], ["app_context", "window_title"])


    def test_work_context_route_exposes_strong_project_context_with_cautious_task(self):
        signals = Signals(
            active_project="AlphaApp",
            active_file=None,
            probable_task="general",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=12,
            recent_apps=["Codex", "ChatGPT", "Code"],
            clipboard_context=None,
            activity_level="executing",
            task_confidence=0.32,
            terminal_cwd="/tmp/workspace/AlphaApp",
            terminal_action_category="testing",
            terminal_project="AlphaApp",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_work_intent(WorkIntent(
            summary="stabiliser les tests locaux",
            source="manual_context_note",
            confidence=0.9,
            project="AlphaApp",
        ))
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("ChatGPT")

        response = self.client.get("/work-context")

        self.assertEqual(response.status_code, 200)
        card = response.get_json()["card"]
        self.assertEqual(card["project"], "AlphaApp")
        self.assertEqual(card["probable_task"], "general")
        self.assertEqual(card["confidence"], 0.32)
        self.assertGreaterEqual(card["project_confidence"], 0.8)
        self.assertEqual(card["project_status"], "observed")
        self.assertEqual(card["task_status"], "unknown")
        self.assertEqual(card["project_source"], "active_project")
        self.assertIn("Codex", card["support_apps"])
        self.assertIn("ChatGPT", card["support_apps"])
        self.assertIn("Projet explicite détecté", card["project_evidence"])
        self.assertNotIn("/tmp/workspace/AlphaApp", str(card))


    def test_work_context_route_exposes_weak_project_hint_without_promoting_project(self):
        signals = Signals(
            active_project=None,
            active_file=None,
            probable_task="general",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=5,
            recent_apps=["Code"],
            clipboard_context=None,
            activity_level="reading",
            task_confidence=0.35,
            window_title="Pulse — DashboardRootView.swift — Visual Studio Code",
            window_title_app="Code",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Code")

        with patch("daemon.routes.runtime_debug_routes.find_workspace_root", return_value=None):
            response = self.client.get("/work-context")

        self.assertEqual(response.status_code, 200)
        card = response.get_json()["card"]
        self.assertEqual(card["project"], None)
        self.assertEqual(card["project_hint"], "Pulse")
        self.assertEqual(card["project_hint_confidence"], 0.35)
        self.assertEqual(card["project_hint_source"], "window_title")
        self.assertNotIn("Projet actif détecté : Pulse", card["evidence"])
        self.assertEqual(card["project_status"], "unknown")
        self.assertIn("project_hint_uncorroborated", card["project_warnings"])
        self.assertIn("Projet actif non identifié", card["missing_context"])

    def test_work_context_route_marks_low_confidence_task_as_weak(self):
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="debug",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=5,
            recent_apps=["Terminal"],
            clipboard_context=None,
            activity_level="executing",
            task_confidence=0.32,
            terminal_action_category="testing",
            terminal_summary="pytest failed",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Terminal")

        response = self.client.get("/work-context")

        self.assertEqual(response.status_code, 200)
        card = response.get_json()["card"]
        self.assertEqual(card["project"], "Pulse")
        self.assertEqual(card["project_status"], "observed")
        self.assertEqual(card["probable_task"], "debug")
        self.assertEqual(card["confidence"], 0.32)
        self.assertEqual(card["task_status"], "weak")
        self.assertIn("Tâche possible : debug", card["evidence"])
        self.assertNotIn("Tâche probable : debug", card["evidence"])
        self.assertNotIn("Tâche inférée : debug", card["evidence"])

    def test_work_context_route_does_not_expose_raw_paths_commands_or_window_title(self):
        secret = "SECRET_TOKEN"
        full_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/runtime_state.py"
        raw_title = "Pulse notes yugz@example.com /Users/yugz/private"
        command = f"curl -H 'Authorization: Bearer {secret}' https://example.test"
        signals = Signals(
            active_project="Pulse",
            active_file=full_path,
            probable_task="debug",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=5,
            recent_apps=["Code", "Terminal"],
            clipboard_context=None,
            activity_level="executing",
            task_confidence=0.66,
            terminal_action_category="testing",
            terminal_command=command,
            terminal_summary="pytest failed",
            terminal_project="Pulse",
            terminal_success=False,
            window_title=raw_title,
            window_title_app="Code",
            edited_file_count_10m=2,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Code")

        response = self.client.get("/work-context")

        self.assertEqual(response.status_code, 200)
        card = response.get_json()["card"]
        card_text = str(card)
        self.assertEqual(card["project"], "Pulse")
        self.assertIn("Titre de fenêtre disponible", card["evidence"])
        self.assertIn("Terminal : pytest failed", card["evidence"])
        self.assertNotIn(full_path, card_text)
        self.assertNotIn(command, card_text)
        self.assertNotIn(secret, card_text)
        self.assertNotIn(raw_title, card_text)
        self.assertNotIn("yugz@example.com", card_text)

    def test_context_probes_schema_exposes_default_safety_policies(self):
        response = self.client.get("/context-probes/schema")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertIn("app_context", payload["probe_kinds"])
        self.assertIn("window_title", payload["probe_kinds"])
        self.assertIn("focused_element_text", payload["probe_kinds"])
        self.assertIn("selected_text", payload["probe_kinds"])
        self.assertIn("clipboard_sample", payload["probe_kinds"])
        self.assertIn("screen_snapshot", payload["probe_kinds"])
        self.assertIn("unknown", payload["probe_kinds"])

        self.assertIn("implicit_session", payload["consent_levels"])
        self.assertIn("explicit_each_time", payload["consent_levels"])
        self.assertIn("blocked", payload["consent_levels"])

        policies = payload["default_policies"]
        self.assertEqual(policies["app_context"]["consent"], "implicit_session")
        self.assertEqual(policies["app_context"]["privacy"], "public")
        self.assertEqual(policies["app_context"]["retention"], "session")
        self.assertFalse(policies["app_context"]["allow_raw_value"])
        self.assertFalse(policies["app_context"]["allow_persistent_storage"])

        self.assertEqual(policies["selected_text"]["consent"], "explicit_each_time")
        self.assertEqual(policies["selected_text"]["privacy"], "content_sensitive")
        self.assertEqual(policies["selected_text"]["retention"], "ephemeral")
        self.assertFalse(policies["selected_text"]["allow_raw_value"])
        self.assertFalse(policies["selected_text"]["allow_persistent_storage"])

        self.assertEqual(policies["focused_element_text"]["consent"], "explicit_each_time")
        self.assertEqual(policies["focused_element_text"]["privacy"], "content_sensitive")
        self.assertEqual(policies["focused_element_text"]["retention"], "ephemeral")
        self.assertEqual(policies["focused_element_text"]["max_chars"], 2000)
        self.assertFalse(policies["focused_element_text"]["allow_raw_value"])
        self.assertFalse(policies["focused_element_text"]["allow_persistent_storage"])

        self.assertEqual(policies["screen_snapshot"]["consent"], "explicit_each_time")
        self.assertEqual(policies["screen_snapshot"]["privacy"], "content_sensitive")
        self.assertEqual(policies["screen_snapshot"]["retention"], "ephemeral")
        self.assertFalse(policies["screen_snapshot"]["allow_raw_value"])
        self.assertFalse(policies["screen_snapshot"]["allow_persistent_storage"])

        self.assertEqual(payload["unknown_policy"], {
            "kind": "unknown",
            "consent": "blocked",
            "privacy": "unknown",
            "retention": "debug_only",
            "allow_raw_value": False,
            "allow_persistent_storage": False,
            "requires_user_visible_reason": True,
            "max_chars": None,
        })


    def test_context_probe_request_preview_creates_debuggable_non_persistent_request(self):
        response = self.client.post(
            "/context-probes/request-preview",
            json={
                "kind": "selected_text",
                "reason": "Explain selected error",
                "ttl_sec": 120,
                "metadata": {
                    "raw_selection": "SECRET",
                    "source": "dashboard",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        request_payload = payload["request"]
        debug = payload["debug"]

        self.assertEqual(request_payload["kind"], "selected_text")
        self.assertEqual(request_payload["reason"], "Explain selected error")
        self.assertEqual(request_payload["status"], "pending")
        self.assertEqual(request_payload["policy"]["consent"], "explicit_each_time")
        self.assertEqual(request_payload["policy"]["privacy"], "content_sensitive")
        self.assertEqual(request_payload["policy"]["retention"], "ephemeral")
        self.assertFalse(request_payload["policy"]["allow_raw_value"])
        self.assertFalse(request_payload["policy"]["allow_persistent_storage"])
        self.assertEqual(request_payload["metadata_keys"], ["raw_selection", "source"])
        self.assertNotIn("metadata", request_payload)
        self.assertNotIn("SECRET", str(payload))

        self.assertEqual(debug["kind"], "selected_text")
        self.assertEqual(debug["status"], "pending")
        self.assertEqual(debug["labels"], {
            "kind": "Selected text",
            "consent": "Requires explicit approval every time",
            "privacy": "Content-sensitive context",
            "retention": "Ephemeral by default",
            "risk": "Sensitive",
        })
        self.assertEqual(debug["metadata_keys"], ["raw_selection", "source"])
        self.assertNotIn("metadata", debug)

    def test_context_probe_request_preview_unknown_kind_is_blocked(self):
        response = self.client.post(
            "/context-probes/request-preview",
            json={
                "kind": "not_a_probe",
                "reason": "Try unknown probe",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        request_payload = payload["request"]
        debug = payload["debug"]

        self.assertEqual(request_payload["kind"], "unknown")
        self.assertEqual(request_payload["policy"]["consent"], "blocked")
        self.assertEqual(request_payload["policy"]["privacy"], "unknown")
        self.assertEqual(request_payload["policy"]["retention"], "debug_only")
        self.assertEqual(debug["labels"]["risk"], "Blocked")
        self.assertEqual(debug["labels"]["consent"], "Blocked by default")


    def test_context_probe_request_preview_invalid_ttl_and_metadata_use_safe_defaults(self):
        response = self.client.post(
            "/context-probes/request-preview",
            json={
                "kind": "app_context",
                "reason": "",
                "ttl_sec": "invalid",
                "metadata": "not-a-dict",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        request_payload = payload["request"]

        self.assertEqual(request_payload["kind"], "app_context")
        self.assertEqual(request_payload["reason"], "Context probe requested")
        self.assertEqual(request_payload["policy"]["consent"], "implicit_session")
        self.assertEqual(request_payload["policy"]["privacy"], "public")
        self.assertEqual(request_payload["policy"]["retention"], "session")
        self.assertEqual(request_payload["metadata_keys"], [])

        created_at = datetime.fromisoformat(request_payload["created_at"])
        expires_at = datetime.fromisoformat(request_payload["expires_at"])
        self.assertEqual(int((expires_at - created_at).total_seconds()), 300)


    def test_context_probe_requests_create_and_list_stored_requests(self):
        create_response = self.client.post(
            "/context-probes/requests",
            json={
                "kind": "selected_text",
                "reason": "Explain selected error",
                "ttl_sec": 120,
                "metadata": {
                    "raw_selection": "SECRET",
                    "source": "dashboard",
                },
            },
        )

        self.assertEqual(create_response.status_code, 200)
        created_payload = create_response.get_json()
        request_id = created_payload["request"]["request_id"]
        self.assertEqual(created_payload["request"]["kind"], "selected_text")
        self.assertEqual(created_payload["request"]["status"], "pending")
        self.assertEqual(created_payload["request"]["metadata_keys"], ["raw_selection", "source"])
        self.assertNotIn("metadata", created_payload["request"])
        self.assertNotIn("SECRET", str(created_payload))

        list_response = self.client.get("/context-probes/requests")

        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.get_json()
        self.assertEqual(list_payload["count"], 1)
        self.assertEqual(list_payload["requests"][0]["request_id"], request_id)
        self.assertEqual(list_payload["requests"][0]["kind"], "selected_text")
        self.assertEqual(list_payload["debug"][0]["request_id"], request_id)
        self.assertEqual(list_payload["debug"][0]["labels"]["risk"], "Sensitive")
        self.assertNotIn("result", str(list_payload["requests"][0]))
        self.assertNotIn("redacted_value", str(list_payload))
        self.assertNotIn("SECRET", str(list_payload))

        detail_response = self.client.get(f"/context-probes/requests/{request_id}")
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.get_json()
        self.assertEqual(detail_payload["request"]["request_id"], request_id)
        self.assertIsNone(detail_payload["result"])
        self.assertNotIn("SECRET", str(detail_payload))

    def test_context_probe_requests_list_filters_status_and_include_terminal(self):
        first = self.client.post(
            "/context-probes/requests",
            json={"kind": "app_context", "reason": "Need app context"},
        ).get_json()["request"]
        second = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Need clipboard sample"},
        ).get_json()["request"]

        refuse_response = self.client.post(
            f"/context-probes/requests/{second['request_id']}/refuse",
            json={"reason": "Too sensitive"},
        )

        self.assertEqual(refuse_response.status_code, 200)

        pending_response = self.client.get("/context-probes/requests?status=pending")
        self.assertEqual(pending_response.status_code, 200)
        pending_payload = pending_response.get_json()
        self.assertEqual(pending_payload["count"], 1)
        self.assertEqual(pending_payload["requests"][0]["request_id"], first["request_id"])

        active_response = self.client.get("/context-probes/requests?include_terminal=false")
        self.assertEqual(active_response.status_code, 200)
        active_payload = active_response.get_json()
        self.assertEqual(active_payload["count"], 1)
        self.assertEqual(active_payload["requests"][0]["request_id"], first["request_id"])

        refused_response = self.client.get("/context-probes/requests?status=refused")
        self.assertEqual(refused_response.status_code, 200)
        refused_payload = refused_response.get_json()
        self.assertEqual(refused_payload["count"], 1)
        self.assertEqual(refused_payload["requests"][0]["request_id"], second["request_id"])

    def test_context_probe_requests_list_respects_limit(self):
        for index in range(3):
            self.client.post(
                "/context-probes/requests",
                json={"kind": "app_context", "reason": f"Need app context {index}"},
            )

        response = self.client.get("/context-probes/requests?limit=2")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 2)
        self.assertLessEqual(len(payload["requests"]), 2)
        self.assertLessEqual(len(payload["debug"]), 2)

    def test_context_probe_requests_list_invalid_limit_uses_safe_default(self):
        for index in range(3):
            self.client.post(
                "/context-probes/requests",
                json={"kind": "app_context", "reason": f"Need app context {index}"},
            )

        response = self.client.get("/context-probes/requests?limit=invalid")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 3)

    def test_context_probe_requests_list_applies_filters_before_limit(self):
        first = self.client.post(
            "/context-probes/requests",
            json={"kind": "app_context", "reason": "Need app context"},
        ).get_json()["request"]
        second = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Need clipboard sample"},
        ).get_json()["request"]
        third = self.client.post(
            "/context-probes/requests",
            json={"kind": "manual_context_note", "reason": "Need manual note"},
        ).get_json()["request"]

        self.client.post(f"/context-probes/requests/{second['request_id']}/refuse")

        active_response = self.client.get("/context-probes/requests?include_terminal=false&limit=1")
        self.assertEqual(active_response.status_code, 200)
        active_payload = active_response.get_json()
        self.assertEqual(active_payload["count"], 1)
        self.assertIn(
            active_payload["requests"][0]["request_id"],
            {first["request_id"], third["request_id"]},
        )

        refused_response = self.client.get("/context-probes/requests?status=refused&limit=1")
        self.assertEqual(refused_response.status_code, 200)
        refused_payload = refused_response.get_json()
        self.assertEqual(refused_payload["count"], 1)
        self.assertEqual(refused_payload["requests"][0]["request_id"], second["request_id"])

    def test_context_probe_requests_approve_and_refuse_update_stored_status(self):
        approve_candidate = self.client.post(
            "/context-probes/requests",
            json={"kind": "window_title", "reason": "Need window title"},
        ).get_json()["request"]
        refuse_candidate = self.client.post(
            "/context-probes/requests",
            json={"kind": "screen_snapshot", "reason": "Need visual context"},
        ).get_json()["request"]

        approve_response = self.client.post(
            f"/context-probes/requests/{approve_candidate['request_id']}/approve",
            json={"reason": "User accepted"},
        )
        refuse_response = self.client.post(
            f"/context-probes/requests/{refuse_candidate['request_id']}/refuse",
            json={"reason": "Too sensitive"},
        )

        self.assertEqual(approve_response.status_code, 200)
        approved = approve_response.get_json()
        self.assertEqual(approved["request"]["status"], "approved")
        self.assertEqual(approved["request"]["decision_reason"], "User accepted")
        self.assertEqual(approved["debug"]["labels"]["kind"], "Window title")

        self.assertEqual(refuse_response.status_code, 200)
        refused = refuse_response.get_json()
        self.assertEqual(refused["request"]["status"], "refused")
        self.assertEqual(refused["request"]["decision_reason"], "Too sensitive")
        self.assertEqual(refused["debug"]["labels"]["risk"], "Sensitive")

        list_response = self.client.get("/context-probes/requests")
        statuses = {
            item["request_id"]: item["status"]
            for item in list_response.get_json()["requests"]
        }
        self.assertEqual(statuses[approve_candidate["request_id"]], "approved")
        self.assertEqual(statuses[refuse_candidate["request_id"]], "refused")

    def test_context_probe_requests_abort_approved_request(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Need next clipboard text"},
        ).get_json()["request"]
        approve_response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "Approved"},
        )
        self.assertEqual(approve_response.status_code, 200)

        abort_response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/abort",
            json={"reason": "User cancelled clipboard capture"},
        )

        self.assertEqual(abort_response.status_code, 200)
        payload = abort_response.get_json()
        self.assertEqual(payload["request"]["status"], "aborted")
        self.assertTrue(payload["request"]["is_terminal"])
        self.assertIsNone(payload["request"]["executed_at"])
        self.assertEqual(payload["request"]["decision_reason"], "User cancelled clipboard capture")

        detail_payload = self.client.get(f"/context-probes/requests/{created['request_id']}").get_json()
        self.assertEqual(detail_payload["request"]["status"], "aborted")
        self.assertIsNone(detail_payload["result"])

    def test_context_probe_requests_abort_rejects_invalid_transitions(self):
        pending = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Need clipboard sample"},
        ).get_json()["request"]
        pending_abort = self.client.post(f"/context-probes/requests/{pending['request_id']}/abort")
        self.assertEqual(pending_abort.status_code, 409)
        self.assertEqual(pending_abort.get_json()["error"], "invalid_transition")

        refused = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Need clipboard sample"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{refused['request_id']}/refuse")
        refused_abort = self.client.post(f"/context-probes/requests/{refused['request_id']}/abort")
        self.assertEqual(refused_abort.status_code, 409)

        executed = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Need clipboard sample"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{executed['request_id']}/approve")
        self.client.post(
            f"/context-probes/requests/{executed['request_id']}/result",
            json={"source": "next_clipboard_text", "text": "safe context", "char_count": 12},
        )
        executed_abort = self.client.post(f"/context-probes/requests/{executed['request_id']}/abort")
        self.assertEqual(executed_abort.status_code, 409)

        expired = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Need clipboard sample", "ttl_sec": 0},
        ).get_json()["request"]
        self.client.get("/context-probes/requests")
        expired_abort = self.client.post(f"/context-probes/requests/{expired['request_id']}/abort")
        self.assertEqual(expired_abort.status_code, 409)

        approved = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Need clipboard sample"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{approved['request_id']}/approve")
        self.client.post(f"/context-probes/requests/{approved['request_id']}/abort")
        aborted_again = self.client.post(f"/context-probes/requests/{approved['request_id']}/abort")
        self.assertEqual(aborted_again.status_code, 409)

    def test_context_probe_requests_list_filters_aborted_status(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Need next clipboard text"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{created['request_id']}/approve")
        self.client.post(f"/context-probes/requests/{created['request_id']}/abort")

        approved_response = self.client.get("/context-probes/requests?status=approved")
        self.assertEqual(approved_response.status_code, 200)
        self.assertEqual(approved_response.get_json()["count"], 0)

        aborted_response = self.client.get("/context-probes/requests?status=aborted")
        self.assertEqual(aborted_response.status_code, 200)
        aborted_payload = aborted_response.get_json()
        self.assertEqual(aborted_payload["count"], 1)
        self.assertEqual(aborted_payload["requests"][0]["request_id"], created["request_id"])

    def test_context_probe_request_routes_return_not_found_for_unknown_request(self):
        approve_response = self.client.post("/context-probes/requests/missing/approve")
        refuse_response = self.client.post("/context-probes/requests/missing/refuse")
        abort_response = self.client.post("/context-probes/requests/missing/abort")
        detail_response = self.client.get("/context-probes/requests/missing")

        self.assertEqual(approve_response.status_code, 404)
        self.assertEqual(approve_response.get_json(), {"error": "not_found"})
        self.assertEqual(refuse_response.status_code, 404)
        self.assertEqual(refuse_response.get_json(), {"error": "not_found"})
        self.assertEqual(abort_response.status_code, 404)
        self.assertEqual(abort_response.get_json(), {"error": "not_found"})
        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(detail_response.get_json(), {"error": "not_found"})

    def test_context_probe_request_routes_reject_invalid_transitions(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "selected_text", "reason": "Need selected text"},
        ).get_json()["request"]
        request_id = created["request_id"]

        refuse_response = self.client.post(
            f"/context-probes/requests/{request_id}/refuse",
            json={"reason": "No"},
        )
        approve_response = self.client.post(
            f"/context-probes/requests/{request_id}/approve",
            json={"reason": "Too late"},
        )

        self.assertEqual(refuse_response.status_code, 200)
        self.assertEqual(approve_response.status_code, 409)
        self.assertEqual(approve_response.get_json()["error"], "invalid_transition")


    def test_context_probe_requests_list_invalid_status_returns_400(self):
        response = self.client.get("/context-probes/requests?status=not_a_status")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "invalid_status"})


    def test_context_probe_request_execute_runs_approved_app_context_probe(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/Pulse/daemon/secret.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=12,
            recent_apps=["Code"],
            clipboard_context="text",
            activity_level="editing",
            task_confidence=0.82,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Code")

        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "app_context", "reason": "Need app context"},
        ).get_json()["request"]
        approve_response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User accepted"},
        )
        self.assertEqual(approve_response.status_code, 200)

        with patch("daemon.routes.runtime_probe_routes.find_workspace_root", return_value=None):
            execute_response = self.client.post(
                f"/context-probes/requests/{created['request_id']}/execute"
            )

        self.assertEqual(execute_response.status_code, 200)
        payload = execute_response.get_json()
        result = payload["result"]
        request_payload = payload["request"]
        debug = payload["debug"]

        self.assertTrue(result["captured"])
        self.assertEqual(result["kind"], "app_context")
        self.assertEqual(result["privacy"], "public")
        self.assertEqual(result["retention"], "session")
        self.assertEqual(result["blocked_reason"], None)
        self.assertEqual(result["data"], {
            "active_app": "Code",
            "active_project": "Pulse",
            "activity_level": "editing",
            "probable_task": "coding",
        })
        self.assertNotIn("active_file", result["data"])
        self.assertNotIn("/tmp/Pulse/daemon/secret.py", str(payload))

        self.assertEqual(request_payload["status"], "executed")
        self.assertEqual(debug["status"], "executed")
        self.assertTrue(debug["is_terminal"])
        self.bus.publish.assert_called_once_with("context_probe_executed", {
            "request_id": created["request_id"],
            "kind": "app_context",
            "captured": True,
            "privacy": "public",
            "retention": "session",
            "data_keys": ["active_app", "active_project", "activity_level", "probable_task"],
        })
        published_payload = self.bus.publish.call_args.args[1]
        self.assertNotIn("data", published_payload)
        self.assertNotIn("Code", str(published_payload))
        self.assertNotIn("Pulse", str(published_payload))
        self.assertNotIn("coding", str(published_payload))

        detail_response = self.client.get(f"/context-probes/requests/{created['request_id']}")
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.get_json()
        self.assertEqual(detail_payload["request"]["status"], "executed")
        self.assertEqual(detail_payload["result"]["data"]["active_app"], "Code")
        self.assertNotIn("/tmp/Pulse/daemon/secret.py", str(detail_payload))

    def test_context_probe_request_execute_runs_approved_window_title_probe_redacted(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/Pulse/daemon/secret.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=12,
            recent_apps=["Code"],
            clipboard_context="text",
            activity_level="editing",
            task_confidence=0.82,
            window_title="Pulse notes for yugz@example.com — https://example.com/private — /Users/yugz/Projects/Pulse",
            window_title_app="Code",
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Code")

        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "window_title", "reason": "Need window title"},
        ).get_json()["request"]
        approve_response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User accepted"},
        )
        self.assertEqual(approve_response.status_code, 200)

        with patch("daemon.routes.runtime_probe_routes.find_workspace_root", return_value=None):
            execute_response = self.client.post(
                f"/context-probes/requests/{created['request_id']}/execute"
            )

        self.assertEqual(execute_response.status_code, 200)
        payload = execute_response.get_json()
        result = payload["result"]
        request_payload = payload["request"]
        debug = payload["debug"]

        self.assertTrue(result["captured"])
        self.assertEqual(result["kind"], "window_title")
        self.assertEqual(result["privacy"], "path_sensitive")
        self.assertEqual(result["retention"], "session")
        self.assertEqual(result["blocked_reason"], None)
        self.assertEqual(result["data"], {
            "redacted_value": "Pulse notes for [REDACTED_EMAIL] — [REDACTED_URL] — /Users/[REDACTED_USER]/Projects/Pulse",
            "redaction_flags": ["email", "url", "home_path"],
            "original_length": 91,
            "redacted_length": 89,
            "was_redacted": True,
        })
        self.assertNotIn("yugz@example.com", str(payload))
        self.assertNotIn("https://example.com/private", str(payload))
        self.assertNotIn("/Users/yugz", str(payload))
        self.assertNotIn("/tmp/Pulse/daemon/secret.py", str(payload))

        self.assertEqual(request_payload["status"], "executed")
        self.assertEqual(debug["status"], "executed")
        self.assertTrue(debug["is_terminal"])
        self.bus.publish.assert_called_once_with("context_probe_executed", {
            "request_id": created["request_id"],
            "kind": "window_title",
            "captured": True,
            "privacy": "path_sensitive",
            "retention": "session",
            "data_keys": ["original_length", "redacted_length", "redacted_value", "redaction_flags", "was_redacted"],
        })
        published_payload = self.bus.publish.call_args.args[1]
        self.assertNotIn("data", published_payload)
        self.assertNotIn("yugz@example.com", str(published_payload))
        self.assertNotIn("example.com", str(published_payload))
        self.assertNotIn("/Users/yugz", str(published_payload))

        detail_response = self.client.get(f"/context-probes/requests/{created['request_id']}")
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.get_json()
        self.assertEqual(
            detail_payload["result"]["data"]["redacted_value"],
            "Pulse notes for [REDACTED_EMAIL] — [REDACTED_URL] — /Users/[REDACTED_USER]/Projects/Pulse",
        )
        self.assertNotIn("yugz@example.com", str(detail_payload))
        self.assertNotIn("https://example.com/private", str(detail_payload))

    def test_context_probe_request_execute_window_title_without_signal_is_blocked(self):
        signals = Signals(
            active_project="Pulse",
            active_file="/tmp/Pulse/daemon/secret.py",
            probable_task="coding",
            friction_score=0.15,
            focus_level="normal",
            session_duration_min=12,
            recent_apps=["Code"],
            clipboard_context="text",
            activity_level="editing",
            task_confidence=0.82,
            window_title=None,
            window_title_app=None,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        self.runtime_state.set_latest_active_app("Code")

        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "window_title", "reason": "Need window title"},
        ).get_json()["request"]
        approve_response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User accepted"},
        )
        self.assertEqual(approve_response.status_code, 200)

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/execute"
        )

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["error"], "probe_blocked")
        self.assertEqual(payload["blocked_reason"], "missing_window_title")
        self.assertFalse(payload["result"]["captured"])
        self.assertEqual(payload["result"]["kind"], "window_title")
        self.assertEqual(payload["result"]["data"], {})
        self.assertEqual(payload["request"]["status"], "approved")
        self.bus.publish.assert_not_called()

    def test_context_probe_request_execute_blocks_pending_request(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "app_context", "reason": "Need app context"},
        ).get_json()["request"]

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/execute"
        )

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["error"], "probe_blocked")
        self.assertEqual(payload["blocked_reason"], "request_not_approved:pending")
        self.assertFalse(payload["result"]["captured"])
        self.assertEqual(payload["request"]["status"], "pending")
        self.bus.publish.assert_not_called()

    def test_context_probe_request_execute_blocks_unsupported_approved_kind(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "selected_text", "reason": "Need selected text"},
        ).get_json()["request"]
        approve_response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User accepted"},
        )
        self.assertEqual(approve_response.status_code, 200)

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/execute"
        )

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["error"], "probe_blocked")
        self.assertEqual(payload["blocked_reason"], "unsupported_probe_kind")
        self.assertEqual(payload["result"]["kind"], "selected_text")
        self.assertFalse(payload["result"]["captured"])
        self.assertEqual(payload["request"]["status"], "approved")
        self.assertNotIn("selected_text", payload["result"].get("data", {}))
        self.bus.publish.assert_not_called()

    def test_context_probe_request_execute_unknown_request_returns_404(self):
        response = self.client.post("/context-probes/requests/missing/execute")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "not_found"})
        self.bus.publish.assert_not_called()

    def test_context_probe_result_route_rejects_unapproved_request(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "focused_element_text", "reason": "Read focused text"},
        ).get_json()["request"]

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "role": "AXTextArea",
                "source": "focused_element_text",
                "text": "Secret draft",
            },
        )

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["blocked_reason"], "request_not_approved:pending")
        self.assertFalse(payload["result"]["captured"])
        self.assertNotIn("Secret draft", str(payload))
        self.bus.publish.assert_not_called()

    def test_context_probe_result_route_accepts_approved_result_redacts_and_emits_metadata_only(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "focused_element_text", "reason": "Read focused text"},
        ).get_json()["request"]
        self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User accepted"},
        )

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "app_name": "Code",
                "bundle_id": "com.example.code",
                "role": "AXTextArea",
                "source": "focused_element_text",
                "char_count": 2400,
                "truncated": True,
                "text": "https://example.com/private sk-abcdefghijklmnopqrstuvwxyz123456 " + ("mot " * 700),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload["result"]
        self.assertTrue(result["captured"])
        self.assertEqual(result["kind"], "focused_element_text")
        self.assertEqual(result["retention"], "ephemeral")
        self.assertEqual(result["data"]["role"], "AXTextArea")
        self.assertIn("url", result["data"]["redaction_flags"])
        self.assertIn("token", result["data"]["redaction_flags"])
        self.assertIn("truncated", result["data"]["redaction_flags"])
        self.assertNotIn("https://example.com/private", str(payload))
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", str(payload))
        self.assertEqual(payload["request"]["status"], "executed")
        self.bus.publish.assert_called_once()
        published = self.bus.publish.call_args.args[1]
        self.assertEqual(published["kind"], "focused_element_text")
        self.assertIn("redacted_value", published["data_keys"])
        self.assertNotIn("data", published)
        self.assertNotIn("example.com", str(published))
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", str(published))

    def test_context_probe_result_route_accepts_approved_next_clipboard_text(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Use next copied text"},
        ).get_json()["request"]
        self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User selected next copied text"},
        )

        secret = "clipboard draft sk-abcdefghijklmnopqrstuvwxyz123456 " + ("mot " * 1_200)
        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "source": "next_clipboard_text",
                "content_kind": "text",
                "char_count": len(secret),
                "truncated": True,
                "text": secret,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload["result"]
        self.assertTrue(result["captured"])
        self.assertEqual(result["kind"], "clipboard_sample")
        self.assertEqual(result["data"]["source"], "next_clipboard_text")
        self.assertIn("token", result["data"]["redaction_flags"])
        self.assertIn("truncated", result["data"]["redaction_flags"])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", str(payload))
        self.assertEqual(payload["request"]["status"], "executed")
        published = self.bus.publish.call_args.args[1]
        self.assertEqual(published["kind"], "clipboard_sample")
        self.assertIn("redacted_value", published["data_keys"])
        self.assertNotIn("data", published)
        self.assertNotIn("clipboard draft", str(published))

        detail_response = self.client.get(f"/context-probes/requests/{created['request_id']}")
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.get_json()
        self.assertEqual(detail_payload["result"]["kind"], "clipboard_sample")
        self.assertEqual(detail_payload["result"]["data"]["source"], "next_clipboard_text")
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", str(detail_payload))

        list_payload = self.client.get("/context-probes/requests").get_json()
        self.assertNotIn("redacted_value", str(list_payload))
        self.assertNotIn("clipboard draft", str(list_payload))

    def test_clipboard_context_probe_creates_work_intent_candidate_only(self):
        self.runtime_state.update_present(
            signals=Signals(
                active_project="Pulse",
                active_file=None,
                probable_task="coding",
                friction_score=0.0,
                focus_level="normal",
                session_duration_min=12,
                recent_apps=[],
                clipboard_context=None,
            ),
            session_status="active",
            awake=True,
            locked=False,
        )
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Use next copied text"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{created['request_id']}/approve")

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "source": "next_clipboard_text",
                "content_kind": "text",
                "text": "réduire les coûts cachés du modèle local sk-abcdefghijklmnopqrstuvwxyz123456",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.runtime_state.get_present().work_intent)
        candidates_payload = self.client.get("/work-intent/candidates").get_json()
        self.assertEqual(candidates_payload["count"], 1)
        candidate = candidates_payload["candidates"][0]
        self.assertEqual(candidate["source"], "clipboard_sample")
        self.assertEqual(candidate["confidence"], 0.65)
        self.assertEqual(candidate["project"], "Pulse")
        self.assertEqual(candidate["evidence_refs"], [f"context_probe:{created['request_id']}"])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", str(candidate))

    def test_context_probe_result_route_accepts_approved_manual_context_note(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "manual_context_note", "reason": "Write quick note"},
        ).get_json()["request"]
        self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User wrote note"},
        )

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "source": "manual_context_note",
                "char_count": 55,
                "truncated": False,
                "text": "Context note with sk-abcdefghijklmnopqrstuvwxyz123456",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["result"]["captured"])
        self.assertEqual(payload["result"]["kind"], "manual_context_note")
        self.assertEqual(payload["result"]["data"]["source"], "manual_context_note")
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", str(payload))
        self.assertEqual(payload["request"]["status"], "executed")
        published = self.bus.publish.call_args.args[1]
        self.assertEqual(published["kind"], "manual_context_note")
        self.assertNotIn("data", published)
        self.assertNotIn("Context note", str(published))

        detail_response = self.client.get(f"/context-probes/requests/{created['request_id']}")
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.get_json()
        self.assertEqual(detail_payload["result"]["kind"], "manual_context_note")
        self.assertEqual(detail_payload["result"]["data"]["source"], "manual_context_note")
        self.assertEqual(detail_payload["result"]["data"]["char_count"], 55)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", str(detail_payload))

    def test_manual_context_probe_candidate_accept_sets_work_intent_and_work_context(self):
        signals = Signals(
            active_project="Pulse",
            active_file=None,
            probable_task="coding",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=12,
            recent_apps=[],
            clipboard_context=None,
            activity_level="editing",
            task_confidence=0.8,
        )
        self.runtime_state.update_present(
            signals=signals,
            session_status="active",
            awake=True,
            locked=False,
        )
        self.runtime_state.set_analysis(signals=signals, decision=None)
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "manual_context_note", "reason": "Write quick note"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{created['request_id']}/approve")
        self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "source": "manual_context_note",
                "text": "réduire les coûts cachés du modèle local",
            },
        )
        candidate_id = self.client.get("/work-intent/candidates").get_json()["candidates"][0]["candidate_id"]

        accept_response = self.client.post(f"/work-intent/candidates/{candidate_id}/accept")

        self.assertEqual(accept_response.status_code, 200)
        active_intent = self.runtime_state.get_present().work_intent
        self.assertIsNotNone(active_intent)
        self.assertEqual(active_intent.summary, "réduire les coûts cachés du modèle local")
        self.assertEqual(active_intent.source, "manual_context_note")
        self.assertEqual(active_intent.project, "Pulse")
        work_context = self.client.get("/work-context").get_json()["card"]
        self.assertEqual(work_context["work_intent"]["summary"], "réduire les coûts cachés du modèle local")
        self.assertEqual(work_context["work_intent"]["project"], "Pulse")

    def test_manual_context_probe_candidate_uses_request_metadata_project_fallback(self):
        created = self.client.post(
            "/context-probes/requests",
            json={
                "kind": "manual_context_note",
                "reason": "Write quick note",
                "metadata": {"project": "Pulse"},
            },
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{created['request_id']}/approve")

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "source": "manual_context_note",
                "text": "réduire les coûts cachés du modèle local",
            },
        )

        self.assertEqual(response.status_code, 200)
        candidate = self.client.get("/work-intent/candidates").get_json()["candidates"][0]
        self.assertEqual(candidate["project"], "Pulse")

    def test_manual_context_probe_candidate_project_stays_null_without_project_context(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "manual_context_note", "reason": "Write quick note"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{created['request_id']}/approve")

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "source": "manual_context_note",
                "text": "réduire les coûts cachés du modèle local",
            },
        )

        self.assertEqual(response.status_code, 200)
        candidate = self.client.get("/work-intent/candidates").get_json()["candidates"][0]
        self.assertIsNone(candidate["project"])

    def test_focused_element_context_probe_does_not_create_work_intent_candidate(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "focused_element_text", "reason": "Read focused text"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{created['request_id']}/approve")

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "app_name": "Code",
                "bundle_id": "com.example.code",
                "role": "AXTextArea",
                "source": "focused_element_text",
                "text": "réduire les coûts cachés du modèle local",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/work-intent/candidates").get_json()["count"], 0)

    def test_refused_work_intent_candidate_cannot_be_accepted(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "manual_context_note", "reason": "Write quick note"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{created['request_id']}/approve")
        self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={"source": "manual_context_note", "text": "stabiliser le journal"},
        )
        candidate_id = self.client.get("/work-intent/candidates").get_json()["candidates"][0]["candidate_id"]

        refuse_response = self.client.post(f"/work-intent/candidates/{candidate_id}/refuse")
        accept_response = self.client.post(f"/work-intent/candidates/{candidate_id}/accept")

        self.assertEqual(refuse_response.status_code, 200)
        self.assertEqual(accept_response.status_code, 409)
        self.assertIsNone(self.runtime_state.get_present().work_intent)

    def test_active_work_intent_prevents_new_probe_candidate(self):
        self.runtime_state.set_work_intent(WorkIntent(
            summary="objectif déjà validé",
            source="manual",
            project="Pulse",
        ))
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "manual_context_note", "reason": "Write quick note"},
        ).get_json()["request"]
        self.client.post(f"/context-probes/requests/{created['request_id']}/approve")

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={"source": "manual_context_note", "text": "nouvel objectif"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/work-intent/candidates").get_json()["count"], 0)

    def test_context_probe_result_route_rejects_source_mismatch(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "clipboard_sample", "reason": "Use next copied text"},
        ).get_json()["request"]
        self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User accepted"},
        )

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "source": "manual_context_note",
                "text": "SHOULD_NOT_LEAK",
            },
        )

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["blocked_reason"], "kind_source_mismatch")
        self.assertFalse(payload["result"]["captured"])
        self.assertNotIn("SHOULD_NOT_LEAK", str(payload))
        self.bus.publish.assert_not_called()

    def test_context_probe_result_route_rejects_expired_content_request(self):
        created = self.client.post(
            "/context-probes/requests",
            json={
                "kind": "manual_context_note",
                "reason": "Write quick note",
                "ttl_sec": 0,
            },
        ).get_json()["request"]
        self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User accepted"},
        )

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "source": "manual_context_note",
                "text": "EXPIRED_SECRET",
            },
        )

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["blocked_reason"], "request_expired")
        self.assertFalse(payload["result"]["captured"])
        self.assertNotIn("EXPIRED_SECRET", str(payload))
        self.bus.publish.assert_not_called()

    def test_context_probe_result_route_rejects_forbidden_role(self):
        created = self.client.post(
            "/context-probes/requests",
            json={"kind": "focused_element_text", "reason": "Read focused text"},
        ).get_json()["request"]
        self.client.post(
            f"/context-probes/requests/{created['request_id']}/approve",
            json={"reason": "User accepted"},
        )

        response = self.client.post(
            f"/context-probes/requests/{created['request_id']}/result",
            json={
                "role": "AXSecureTextField",
                "source": "focused_element_text",
                "text": "SECRET",
            },
        )

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["blocked_reason"], "forbidden_role")
        self.assertFalse(payload["result"]["captured"])
        self.assertNotIn("SECRET", str(payload))
        self.bus.publish.assert_not_called()

    def test_daemon_pause_returns_legacy_payload(self):
        with patch("daemon.routes.runtime_daemon_routes.threading.Thread", side_effect=lambda *a, **k: _DummyThread(*a, **k)):
            response = self.client.post("/daemon/pause")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "action": "pause", "paused": True},
        )
        self.assertTrue(self.runtime_state.is_paused())

    def test_daemon_resume_returns_legacy_payload(self):
        self.runtime_state.set_paused(True)
        with patch("daemon.routes.runtime_daemon_routes.threading.Thread", side_effect=lambda *a, **k: _DummyThread(*a, **k)):
            response = self.client.post("/daemon/resume")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "action": "resume", "paused": False},
        )
        self.assertFalse(self.runtime_state.is_paused())

    def test_daemon_resume_ne_warm_pas_ollama_par_defaut(self):
        self.runtime_state.set_paused(True)
        with patch.dict("os.environ", {}, clear=True), \
             patch("daemon.routes.runtime_daemon_routes.threading.Thread", side_effect=lambda *a, **k: _ImmediateThread(*a, **k)):
            response = self.client.post("/daemon/resume")

        self.assertEqual(response.status_code, 200)
        self.llm_warmup_background.assert_not_called()
        self.bus.publish.assert_not_called()

    def test_daemon_resume_warm_ollama_si_autowarm_active(self):
        self.runtime_state.set_paused(True)
        with patch.dict("os.environ", {"PULSE_HEAVY_LLM_AUTOWARM": "1"}), \
             patch("daemon.routes.runtime_daemon_routes.threading.Thread", side_effect=lambda *a, **k: _ImmediateThread(*a, **k)):
            response = self.client.post("/daemon/resume")

        self.assertEqual(response.status_code, 200)
        self.llm_warmup_background.assert_called_once()

    def test_daemon_shutdown_returns_legacy_payload(self):
        with patch("daemon.routes.runtime_daemon_routes.threading.Thread", side_effect=lambda *a, **k: _DummyThread(*a, **k)):
            response = self.client.post("/daemon/shutdown")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "action": "shutdown"},
        )
        self.shutdown_runtime.assert_called_once()

    def test_daemon_shutdown_exit_attend_la_grace_apres_shutdown(self):
        calls = []
        self.shutdown_runtime.side_effect = lambda: calls.append("shutdown")

        def fake_sleep(delay):
            calls.append(("sleep", delay))

        def fake_exit(code):
            calls.append(("exit", code))

        with patch("daemon.routes.runtime_daemon_routes.threading.Thread", side_effect=lambda *a, **k: _ImmediateThread(*a, **k)), \
             patch("daemon.routes.runtime_daemon_routes.time.sleep", side_effect=fake_sleep), \
             patch("daemon.routes.runtime_daemon_routes.os._exit", side_effect=fake_exit):
            response = self.client.post("/daemon/shutdown")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["shutdown", ("sleep", DAEMON_EXIT_GRACE_SEC), ("exit", 0)])

    def test_daemon_restart_returns_legacy_payload(self):
        with patch("daemon.routes.runtime_daemon_routes.threading.Thread", side_effect=lambda *a, **k: _DummyThread(*a, **k)):
            response = self.client.post("/daemon/restart")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "action": "restart"},
        )
        self.shutdown_runtime.assert_called_once()

    def test_daemon_restart_exit_attend_la_grace_apres_shutdown(self):
        calls = []
        self.shutdown_runtime.side_effect = lambda: calls.append("shutdown")

        def fake_sleep(delay):
            calls.append(("sleep", delay))

        def fake_exit(code):
            calls.append(("exit", code))

        with patch("daemon.routes.runtime_daemon_routes.threading.Thread", side_effect=lambda *a, **k: _ImmediateThread(*a, **k)), \
             patch("daemon.routes.runtime_daemon_routes.time.sleep", side_effect=fake_sleep), \
             patch("daemon.routes.runtime_daemon_routes.os._exit", side_effect=fake_exit):
            response = self.client.post("/daemon/restart")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["shutdown", ("sleep", DAEMON_EXIT_GRACE_SEC), ("exit", 1)])


class TestFileEventCoalescer(unittest.TestCase):
    def setUp(self):
        self.emitted = []
        self.now = 100.0

        self.coalescer = _FileEventCoalescer(
            publisher=lambda event_type, payload, timestamp=None: self.emitted.append(
                (event_type, dict(payload), timestamp)
            ),
            time_fn=lambda: self.now,
            start_worker=False,
        )

    def _flush_last_pending(self):
        self.now += 2.0
        for emitted in self.coalescer._flush_due():
            self.emitted.append(emitted)

    def test_heterogeneous_burst_created_then_modified_emits_one_created(self):
        path = "/tmp/screenshot.png"

        self.coalescer.publish("file_created", {"path": path})
        self.coalescer.publish("file_modified", {"path": path})
        self._flush_last_pending()

        self.assertEqual(self.emitted, [("file_created", {"path": path}, None)])

    def test_heterogeneous_burst_renamed_then_modified_emits_one_renamed(self):
        path = "/tmp/screenshot.png"

        self.coalescer.publish("file_renamed", {"path": path})
        self.coalescer.publish("file_modified", {"path": path})
        self._flush_last_pending()

        self.assertEqual(self.emitted, [("file_renamed", {"path": path}, None)])

    def test_screenshot_burst_created_modified_renamed_emits_one_created(self):
        path = "/Users/yugz/Desktop/Capture d’écran 2026-05-02 à 12.34.12.png"

        self.coalescer.publish("file_created", {"path": path, "seq": 1})
        self.coalescer.publish("file_modified", {"path": path, "seq": 2})
        self.coalescer.publish("file_renamed", {"path": path, "seq": 3})
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [("file_created", {"path": path, "seq": 1}, None)],
        )

    def test_normal_file_burst_created_then_renamed_keeps_renamed_priority(self):
        path = "/tmp/Pulse/daemon/runtime.py"

        self.coalescer.publish("file_created", {"path": path, "seq": 1})
        self.coalescer.publish("file_renamed", {"path": path, "seq": 2})
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [("file_renamed", {"path": path, "seq": 2}, None)],
        )

    def test_events_outside_window_remain_distinct(self):
        path = "/tmp/screenshot.png"

        self.coalescer.publish("file_created", {"path": path})
        self._flush_last_pending()

        self.now += 1.2
        self.coalescer.publish("file_modified", {"path": path})
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [
                ("file_created", {"path": path}, None),
                ("file_modified", {"path": path}, None),
            ],
        )

    def test_successive_modify_events_are_not_fused_by_new_rule(self):
        path = "/tmp/main.py"

        self.coalescer.publish("file_modified", {"path": path, "seq": 1})
        self.coalescer.publish("file_modified", {"path": path, "seq": 2})
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [
                ("file_modified", {"path": path, "seq": 1}, None),
                ("file_modified", {"path": path, "seq": 2}, None),
            ],
        )

    def test_coalescer_conserve_le_timestamp_source_retenu(self):
        path = "/tmp/main.py"
        created_at = datetime(2026, 4, 23, 9, 0, 0)
        modified_at = datetime(2026, 4, 23, 9, 0, 1)

        self.coalescer.publish("file_created", {"path": path}, created_at)
        self.coalescer.publish("file_modified", {"path": path}, modified_at)
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [("file_created", {"path": path}, created_at)],
        )

    def test_coalescer_reste_base_sur_fenetre_locale_pas_sur_ecart_source(self):
        path = "/tmp/main.py"
        created_at = datetime(2026, 4, 23, 9, 0, 0)
        modified_at = datetime(2026, 4, 23, 9, 15, 0)

        self.coalescer.publish("file_created", {"path": path}, created_at)
        self.coalescer.publish("file_modified", {"path": path}, modified_at)
        self._flush_last_pending()

        self.assertEqual(
            self.emitted,
            [("file_created", {"path": path}, created_at)],
        )

    def test_close_draine_les_events_pending_meme_avant_echeance(self):
        path = "/tmp/main.py"
        created_at = datetime(2026, 4, 23, 9, 0, 0)

        self.coalescer.publish("file_modified", {"path": path}, created_at)
        self.assertEqual(self.emitted, [])

        self.coalescer.close()

        self.assertEqual(
            self.emitted,
            [("file_modified", {"path": path}, created_at)],
        )


if __name__ == "__main__":
    unittest.main()
