import unittest
from datetime import datetime, timedelta

from daemon.core.event_bus import EventBus, Event
from daemon.core.signal_scorer import SignalScorer


class TestSignalScorer(unittest.TestCase):

    def setUp(self):
        self.bus = EventBus(max_size=50)
        self.scorer = SignalScorer(self.bus)

    def _push(self, event_type: str, payload: dict, minutes_ago: int = 0):
        event = Event(
            type=event_type,
            payload=payload,
            timestamp=datetime.now() - timedelta(minutes=minutes_ago),
        )
        self.bus._queue.append(event)

    def test_compute_retourne_signaux_de_base(self):
        self._push("app_activated", {"app_name": "Cursor"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})
        self._push("clipboard_updated", {"content_kind": "code"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_project, "Pulse")
        self.assertEqual(signals.active_file, "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py")
        self.assertEqual(signals.probable_task, "coding")
        self.assertEqual(signals.clipboard_context, "code")
        self.assertEqual(signals.edited_file_count_10m, 1)
        self.assertEqual(signals.file_type_mix_10m["source"], 1)
        self.assertEqual(signals.dominant_file_mode, "single_file")

    def test_detecte_debug_si_stacktrace(self):
        self._push("app_activated", {"app_name": "Terminal"})
        self._push("clipboard_updated", {"content_kind": "stacktrace"})

        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "debug")
        self.assertGreaterEqual(signals.friction_score, 0.3)

    def test_focus_deep_si_peu_de_switchs_et_plusieurs_edits(self):
        self._push("app_activated", {"app_name": "Cursor"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/a.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/b.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "deep")

    def test_focus_scattered_si_beaucoup_de_switchs(self):
        apps = ["Cursor", "Safari", "Terminal", "Notion", "Chrome", "Arc"]
        for app in apps:
            self._push("app_activated", {"app_name": app})

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "scattered")

    def test_compat_anciens_noms_devents(self):
        self._push("app_switch", {"app_name": "Xcode"})
        self._push("file_change", {"path": "/Users/yugz/Developer/MonApp/src/main.py"})
        self._push("clipboard_update", {"content_type": "text"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_project, "MonApp")
        self.assertIn("Xcode", signals.recent_apps)
        self.assertEqual(signals.clipboard_context, "text")

    def test_idle_prioritaire_si_evenement_idle_recent(self):
        self._push("app_activated", {"app_name": "Cursor"})
        self._push("user_idle", {"seconds": 420})

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "idle")

    def test_ignore_fichiers_bruites_xcode(self):
        self._push("file_modified", {
            "path": "/Users/yugz/Projets/Pulse/Pulse/App/App.xcodeproj/project.xcworkspace/xcuserdata/yugz.xcuserdatad/UserInterfaceState.xcuserstate"
        })
        self._push("file_modified", {
            "path": "/Users/yugz/Projets/Pulse/Pulse/App/App/SystemObserver.swift"
        })

        signals = self.scorer.compute()

        self.assertEqual(signals.active_file, "/Users/yugz/Projets/Pulse/Pulse/App/App/SystemObserver.swift")

    def test_derive_file_type_mix_and_feature_candidate(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/tests/test_main.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/README.md"})

        signals = self.scorer.compute()

        self.assertEqual(signals.edited_file_count_10m, 3)
        self.assertEqual(signals.file_type_mix_10m["source"], 1)
        self.assertEqual(signals.file_type_mix_10m["test"], 1)
        self.assertEqual(signals.file_type_mix_10m["docs"], 1)
        self.assertEqual(signals.dominant_file_mode, "few_files")
        self.assertEqual(signals.work_pattern_candidate, "feature_candidate")

    def test_detecte_refactor_candidate_avec_renommages(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/a.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/b.py"})
        self._push("file_renamed", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/c.py"})
        self._push("file_deleted", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/d.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.edited_file_count_10m, 4)
        self.assertGreaterEqual(signals.rename_delete_ratio_10m, 0.5)
        self.assertEqual(signals.dominant_file_mode, "few_files")
        self.assertEqual(signals.work_pattern_candidate, "refactor_candidate")

    def test_detecte_setup_candidate_sur_fichiers_config(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/package.json"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/pyproject.toml"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/.env"})

        signals = self.scorer.compute()

        self.assertEqual(signals.file_type_mix_10m["config"], 2)
        self.assertEqual(signals.work_pattern_candidate, "setup_candidate")

    def test_notes_transitoire_ne_force_pas_writing_si_activite_code_forte(self):
        self._push("app_activated", {"app_name": "Cursor"}, minutes_ago=2)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/a.py"}, minutes_ago=1)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/b.py"}, minutes_ago=1)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/tests/test_a.py"}, minutes_ago=1)
        self._push("app_activated", {"app_name": "Notes"})

        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "coding")

    def test_activite_code_multi_fichiers_promeut_coding_meme_sans_app_dev(self):
        self._push("app_activated", {"app_name": "Notes"}, minutes_ago=3)
        for index in range(8):
            self._push(
                "file_modified",
                {"path": f"/Users/yugz/Projets/Pulse/Pulse/daemon/module_{index}.py"},
                minutes_ago=1,
            )

        signals = self.scorer.compute()

        self.assertEqual(signals.edited_file_count_10m, 8)
        self.assertEqual(signals.probable_task, "coding")

    def test_general_reste_fallback_si_activite_est_trop_faible(self):
        self._push("app_activated", {"app_name": "Notes"})

        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "writing")
        self.bus._queue.clear()

        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/misc/data.json"})
        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "general")


if __name__ == "__main__":
    unittest.main()
