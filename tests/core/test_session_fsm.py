import unittest
from datetime import datetime, timedelta

from daemon.core.event_bus import Event
from daemon.core.session_fsm import SessionFSM


def _file_event(path: str, ts: datetime, kind: str = "file_modified") -> Event:
    event = Event(kind, {"path": path})
    event.timestamp = ts
    return event


def _app_event(app: str, ts: datetime) -> Event:
    event = Event("app_activated", {"app_name": app})
    event.timestamp = ts
    return event


def _screen_lock_event(ts: datetime) -> Event:
    event = Event("screen_locked", {})
    event.timestamp = ts
    return event


class TestSessionFSM(unittest.TestCase):
    def setUp(self):
        self.fsm = SessionFSM()
        self.base = datetime.now()
        self.fsm._session_started_at = self._at(120)

    def _at(self, delta_min: float) -> datetime:
        return self.base - timedelta(minutes=delta_min)

    def test_premiere_activite_significative_ancre_la_session(self):
        t_first = self._at(0)

        transition = self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_first)],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(self.fsm.session_started_at, t_first)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_gap_long_declenche_une_nouvelle_frontiere(self):
        t_old = self._at(35)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_old)],
            now=self.base,
        )

        t_new = self._at(0)
        transition = self.fsm.observe_recent_events(
            recent_events=[
                _file_event("/proj/main.py", t_old),
                _file_event("/proj/main.py", t_new),
            ],
            now=self.base,
        )

        self.assertTrue(transition.boundary_detected)
        self.assertEqual(transition.boundary_reason, "idle")
        self.assertTrue(transition.should_start_new_session)
        self.assertEqual(self.fsm.session_started_at, t_new)

    def test_gap_court_ne_declenche_pas_de_frontiere(self):
        t_first = self._at(20)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_first)],
            now=self.base,
        )

        t_second = self._at(15)
        transition = self.fsm.observe_recent_events(
            recent_events=[
                _file_event("/proj/main.py", t_first),
                _file_event("/proj/main.py", t_second),
            ],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(self.fsm.session_started_at, t_first)

    def test_screen_lock_entre_activites_declenche_une_frontiere(self):
        t_before = self._at(8)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_before)],
            now=self.base,
        )

        t_lock = self._at(4)
        t_after = self._at(0)
        transition = self.fsm.observe_recent_events(
            recent_events=[
                _file_event("/proj/main.py", t_before),
                _screen_lock_event(t_lock),
                _file_event("/proj/main.py", t_after),
            ],
            now=self.base,
        )

        self.assertTrue(transition.boundary_detected)
        self.assertEqual(transition.boundary_reason, "screen_lock")
        self.assertEqual(self.fsm.session_started_at, t_after)

    def test_screen_lock_sans_nouvelle_activite_ne_declenche_pas_de_frontiere(self):
        t_activity = self._at(15)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_activity)],
            now=self.base,
        )

        transition = self.fsm.observe_recent_events(
            recent_events=[
                _file_event("/proj/main.py", t_activity),
                _screen_lock_event(self._at(5)),
            ],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(self.fsm.session_started_at, t_activity)

    def test_unlock_court_conserve_debut_de_session_sans_nouvelle_session(self):
        original_start = self.fsm.session_started_at
        locked_at = self._at(5)
        self.fsm.on_screen_locked(when=locked_at)

        transition = self.fsm.on_screen_unlocked(
            when=self.base,
            sleep_session_threshold_min=30,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertTrue(transition.should_reset_clock)
        self.assertFalse(transition.should_start_new_session)
        self.assertEqual(self.fsm.session_started_at, original_start)
        self.assertIsNone(self.fsm.last_screen_locked_at)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_unlock_long_declenche_nouvelle_session(self):
        original_start = self.fsm.session_started_at
        locked_at = self._at(35)
        self.fsm.on_screen_locked(when=locked_at)

        transition = self.fsm.on_screen_unlocked(
            when=self.base,
            sleep_session_threshold_min=30,
        )

        self.assertTrue(transition.boundary_detected)
        self.assertTrue(transition.should_start_new_session)
        self.assertEqual(transition.boundary_reason, "screen_lock")
        self.assertNotEqual(self.fsm.session_started_at, original_start)
        self.assertEqual(self.fsm.session_started_at, self.base)
        self.assertIsNone(self.fsm.last_screen_locked_at)

    def test_app_de_dev_est_une_activite_significative(self):
        t_first = self._at(0)

        self.fsm.observe_recent_events(
            recent_events=[_app_event("Cursor", t_first)],
            now=self.base,
        )

        self.assertEqual(self.fsm.session_started_at, t_first)


if __name__ == "__main__":
    unittest.main()
