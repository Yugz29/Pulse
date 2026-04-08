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


if __name__ == "__main__":
    unittest.main()
