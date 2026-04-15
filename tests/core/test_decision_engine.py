import unittest

from daemon.core.decision_engine import DecisionEngine
from daemon.core.event_bus import Event
from daemon.core.signal_scorer import Signals


class TestDecisionEngine(unittest.TestCase):

    def setUp(self):
        self.engine = DecisionEngine()

    def _signals(self, **overrides):
        base = Signals(
            active_project=None,
            active_file=None,
            probable_task="general",
            friction_score=0.0,
            focus_level="normal",
            session_duration_min=5,
            recent_apps=[],
            clipboard_context=None,
        )
        for key, value in overrides.items():
            setattr(base, key, value)
        return base

    def test_silent_en_deep_focus(self):
        decision = self.engine.evaluate(self._signals(focus_level="deep"))
        self.assertEqual(decision.action, "silent")
        self.assertEqual(decision.reason, "deep_focus")

    def test_mcp_prioritaire_sur_deep_focus(self):
        trigger = Event("mcp_command_received", {"command": "rm -rf tmp"})
        decision = self.engine.evaluate(
            self._signals(focus_level="deep"),
            trigger_event=trigger,
        )
        self.assertEqual(decision.action, "translate")
        self.assertEqual(decision.reason, "mcp_interception")
        self.assertEqual(decision.payload["command"], "rm -rf tmp")

    def test_debug_context_detected(self):
        decision = self.engine.evaluate(
            self._signals(
                probable_task="debug",
                clipboard_context="stacktrace",
            )
        )
        self.assertEqual(decision.action, "silent")
        self.assertEqual(decision.reason, "debug_signal_only")

    def test_high_friction_declenche_notification(self):
        decision = self.engine.evaluate(
            self._signals(
                probable_task="coding",
                friction_score=0.9,
                active_file="/tmp/main.py",
            )
        )
        self.assertEqual(decision.action, "silent")
        self.assertEqual(decision.reason, "friction_signal_only")
        self.assertIsNone(decision.payload)

    def test_idle_longue_session_declenche_resume(self):
        decision = self.engine.evaluate(
            self._signals(
                focus_level="idle",
                session_duration_min=60,
            )
        )
        self.assertEqual(decision.action, "silent")
        self.assertEqual(decision.reason, "summary_signal_only")

    def test_context_ready_declenche_injection(self):
        trigger = Event("file_modified", {"path": "/tmp/main.py"})
        decision = self.engine.evaluate(
            self._signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                focus_level="normal",
                session_duration_min=25,
            ),
            trigger_event=trigger,
        )
        self.assertEqual(decision.action, "inject_context")
        self.assertEqual(decision.reason, "context_ready")
        self.assertEqual(decision.payload["project"], "Pulse")

    def test_context_ready_ne_declenche_pas_en_deep_focus(self):
        trigger = Event("file_modified", {"path": "/tmp/main.py"})
        decision = self.engine.evaluate(
            self._signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                focus_level="deep",
                session_duration_min=25,
            ),
            trigger_event=trigger,
        )
        self.assertEqual(decision.action, "silent")
        self.assertEqual(decision.reason, "deep_focus")

    def test_context_ready_ne_declenche_pas_sans_evenement_fichier(self):
        trigger = Event("app_activated", {"app_name": "Xcode"})
        decision = self.engine.evaluate(
            self._signals(
                active_project="Pulse",
                active_file="/tmp/main.py",
                probable_task="coding",
                focus_level="normal",
                session_duration_min=25,
            ),
            trigger_event=trigger,
        )
        self.assertEqual(decision.action, "silent")
        self.assertEqual(decision.reason, "nothing_relevant")

    def test_context_ready_ne_declenche_pas_sans_fichier_actif(self):
        trigger = Event("file_modified", {"path": "/tmp/main.py"})
        decision = self.engine.evaluate(
            self._signals(
                active_project="Pulse",
                active_file=None,
                probable_task="coding",
                focus_level="normal",
                session_duration_min=25,
            ),
            trigger_event=trigger,
        )
        self.assertEqual(decision.action, "silent")
        self.assertEqual(decision.reason, "nothing_relevant")

    def test_defaut_silent(self):
        decision = self.engine.evaluate(self._signals())
        self.assertEqual(decision.action, "silent")
        self.assertEqual(decision.reason, "nothing_relevant")


if __name__ == "__main__":
    unittest.main()
