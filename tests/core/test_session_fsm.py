import unittest
from datetime import datetime, timedelta
from typing import Optional

from daemon.core.event_bus import Event
from daemon.core.session_fsm import SessionFSM


def _file_event(path: str, ts: datetime, kind: str = "file_modified") -> Event:
    event = Event(kind, {"path": path})
    event.timestamp = ts
    return event


def _app_event(app: str, ts: datetime, bundle_id: Optional[str] = None) -> Event:
    payload = {"app_name": app}
    if bundle_id:
        payload["bundle_id"] = bundle_id
    event = Event("app_activated", payload)
    event.timestamp = ts
    return event


def _screen_lock_event(ts: datetime) -> Event:
    event = Event("screen_locked", {})
    event.timestamp = ts
    return event


def _terminal_event(ts: datetime, kind: str = "terminal_command_finished") -> Event:
    event = Event(kind, {"terminal_action_category": "inspection"})
    event.timestamp = ts
    return event


def _local_exploration_event(ts: datetime) -> Event:
    event = Event("local_exploration", {"app_name": "Finder"})
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
        self.assertIsNone(transition.boundary_reason)
        self.assertFalse(transition.should_start_new_session)
        self.assertFalse(transition.should_reset_clock)
        self.assertIsNone(transition.sleep_minutes)
        self.assertEqual(self.fsm.session_started_at, t_first)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_first)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_active_retombe_idle_apres_timeout_sans_nouvelle_activite(self):
        t_first = self._at(35)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_first)],
            now=t_first,
        )

        transition = self.fsm.observe_recent_events(
            recent_events=[],
            now=self.base,
        )

        self.assertEqual(transition.state, SessionFSM.IDLE)
        self.assertFalse(transition.boundary_detected)
        self.assertIsNone(transition.boundary_reason)
        self.assertFalse(transition.should_start_new_session)
        self.assertFalse(transition.should_reset_clock)
        self.assertIsNone(transition.sleep_minutes)
        self.assertEqual(self.fsm.state, SessionFSM.IDLE)
        self.assertEqual(self.fsm.session_started_at, t_first)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_first)

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
        self.assertTrue(transition.should_reset_clock)
        self.assertTrue(transition.should_start_new_session)
        self.assertGreaterEqual(transition.sleep_minutes or 0, 35)
        self.assertEqual(transition.state, SessionFSM.ACTIVE)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)
        self.assertEqual(self.fsm.session_started_at, t_new)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_new)

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
        self.assertIsNone(transition.boundary_reason)
        self.assertFalse(transition.should_start_new_session)
        self.assertFalse(transition.should_reset_clock)
        self.assertIsNone(transition.sleep_minutes)
        self.assertEqual(transition.state, SessionFSM.ACTIVE)
        self.assertEqual(self.fsm.session_started_at, t_first)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_second)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_minuit_ne_declenche_pas_de_frontiere_si_l_activite_continue(self):
        before_midnight = datetime(2026, 4, 28, 23, 55, 0)
        after_midnight = datetime(2026, 4, 29, 0, 5, 0)
        self.fsm._session_started_at = before_midnight - timedelta(minutes=20)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", before_midnight)],
            now=before_midnight,
        )

        transition = self.fsm.observe_recent_events(
            recent_events=[
                _file_event("/proj/main.py", before_midnight),
                _file_event("/proj/main.py", after_midnight),
            ],
            now=after_midnight,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(self.fsm.session_started_at, before_midnight)

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
        self.assertIsNone(transition.boundary_reason)
        self.assertFalse(transition.should_start_new_session)
        self.assertFalse(transition.should_reset_clock)
        self.assertIsNone(transition.sleep_minutes)
        self.assertEqual(self.fsm.session_started_at, t_activity)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_activity)

    def test_screen_locked_met_la_fsm_en_locked_sans_frontiere(self):
        previous_activity = self._at(15)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", previous_activity)],
            now=previous_activity,
        )
        original_start = self.fsm.session_started_at
        locked_at = self._at(5)

        transition = self.fsm.on_screen_locked(when=locked_at)

        self.assertEqual(transition.state, SessionFSM.LOCKED)
        self.assertFalse(transition.boundary_detected)
        self.assertIsNone(transition.boundary_reason)
        self.assertFalse(transition.should_start_new_session)
        self.assertFalse(transition.should_reset_clock)
        self.assertIsNone(transition.sleep_minutes)
        self.assertEqual(self.fsm.state, SessionFSM.LOCKED)
        self.assertEqual(self.fsm.session_started_at, original_start)
        self.assertEqual(self.fsm.last_meaningful_activity_at, previous_activity)
        self.assertEqual(self.fsm.last_screen_locked_at, locked_at)

    def test_unlock_court_conserve_debut_de_session_sans_nouvelle_session(self):
        previous_activity = self._at(15)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", previous_activity)],
            now=previous_activity,
        )
        original_start = self.fsm.session_started_at
        locked_at = self._at(5)
        self.fsm.on_screen_locked(when=locked_at)

        transition = self.fsm.on_screen_unlocked(
            when=self.base,
            sleep_session_threshold_min=30,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertIsNone(transition.boundary_reason)
        self.assertTrue(transition.should_reset_clock)
        self.assertFalse(transition.should_start_new_session)
        self.assertTrue(transition.should_clear_sleep_markers)
        self.assertAlmostEqual(transition.sleep_minutes or 0, 5.0, places=2)
        self.assertEqual(transition.state, SessionFSM.ACTIVE)
        self.assertEqual(self.fsm.session_started_at, original_start)
        self.assertEqual(self.fsm.last_meaningful_activity_at, previous_activity)
        self.assertIsNone(self.fsm.last_screen_locked_at)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_unlock_court_puis_reprise_ne_cree_pas_de_nouvelle_session(self):
        t_before = self._at(15)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_before)],
            now=t_before,
        )
        original_start = self.fsm.session_started_at
        locked_at = self._at(5)
        self.fsm.on_screen_locked(when=locked_at)
        self.fsm.on_screen_unlocked(
            when=self._at(4),
            sleep_session_threshold_min=30,
        )

        t_after = self._at(0)
        transition = self.fsm.observe_recent_events(
            recent_events=[
                _file_event("/proj/main.py", t_before),
                _screen_lock_event(locked_at),
                _file_event("/proj/main.py", t_after),
            ],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertFalse(transition.should_start_new_session)
        self.assertEqual(self.fsm.session_started_at, original_start)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_after)

    def test_unlock_long_declenche_nouvelle_session(self):
        original_start = self.fsm.session_started_at
        locked_at = self._at(35)
        self.fsm.on_screen_locked(when=locked_at)

        transition = self.fsm.on_screen_unlocked(
            when=self.base,
            sleep_session_threshold_min=30,
        )

        self.assertTrue(transition.boundary_detected)
        self.assertTrue(transition.should_reset_clock)
        self.assertTrue(transition.should_start_new_session)
        self.assertTrue(transition.should_clear_sleep_markers)
        self.assertEqual(transition.boundary_reason, "screen_lock")
        self.assertAlmostEqual(transition.sleep_minutes or 0, 35.0, places=2)
        self.assertEqual(transition.state, SessionFSM.ACTIVE)
        self.assertNotEqual(self.fsm.session_started_at, original_start)
        self.assertEqual(self.fsm.session_started_at, self.base)
        self.assertIsNone(self.fsm.last_meaningful_activity_at)
        self.assertIsNone(self.fsm.last_screen_locked_at)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_unlock_sans_lock_prealable_n_active_pas_la_session(self):
        original_start = self.fsm.session_started_at

        transition = self.fsm.on_screen_unlocked(
            when=self.base,
            sleep_session_threshold_min=30,
        )

        self.assertEqual(transition.state, SessionFSM.IDLE)
        self.assertFalse(transition.boundary_detected)
        self.assertIsNone(transition.boundary_reason)
        self.assertFalse(transition.should_reset_clock)
        self.assertFalse(transition.should_start_new_session)
        self.assertFalse(transition.should_clear_sleep_markers)
        self.assertIsNone(transition.sleep_minutes)
        self.assertEqual(self.fsm.state, SessionFSM.IDLE)
        self.assertEqual(self.fsm.session_started_at, original_start)
        self.assertIsNone(self.fsm.last_meaningful_activity_at)
        self.assertIsNone(self.fsm.last_screen_locked_at)

    def test_app_de_dev_est_une_activite_significative(self):
        t_first = self._at(0)

        self.fsm.observe_recent_events(
            recent_events=[_app_event("Cursor", t_first)],
            now=self.base,
        )

        self.assertEqual(self.fsm.session_started_at, t_first)

    def test_code_app_ne_devient_pas_une_activite_strong_par_centralisation(self):
        t_first = self._at(0)

        transition = self.fsm.observe_recent_events(
            recent_events=[_app_event("Code", t_first)],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(self.fsm.state, SessionFSM.IDLE)
        self.assertIsNone(self.fsm.last_meaningful_activity_at)

    def test_unknown_dev_bundle_becomes_meaningful_activity(self):
        t_first = self._at(0)

        transition = self.fsm.observe_recent_events(
            recent_events=[
                _app_event("RandomIDE", t_first, bundle_id="dev.pulse.test.UnknownIDE"),
            ],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(self.fsm.session_started_at, t_first)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_first)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_unknown_ai_bundle_does_not_become_strong_dev_activity(self):
        t_first = self._at(0)

        transition = self.fsm.observe_recent_events(
            recent_events=[
                _app_event("RandomAssistant", t_first, bundle_id="dev.pulse.test.UnknownAI"),
            ],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(self.fsm.state, SessionFSM.IDLE)
        self.assertIsNone(self.fsm.last_meaningful_activity_at)

    def test_browser_bundle_becomes_supportive_activity(self):
        t_code = self._at(8)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_code)],
            now=t_code,
        )

        t_browser = self._at(0)
        transition = self.fsm.observe_recent_events(
            recent_events=[
                _file_event("/proj/main.py", t_code),
                _app_event("RandomBrowser", t_browser, bundle_id="com.apple.Safari"),
            ],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(self.fsm.session_started_at, t_code)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_browser)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_code_app_behavior_preserved_with_classification(self):
        t_first = self._at(0)

        transition = self.fsm.observe_recent_events(
            recent_events=[
                _app_event("Code", t_first, bundle_id="com.microsoft.VSCode"),
            ],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(self.fsm.state, SessionFSM.IDLE)
        self.assertIsNone(self.fsm.last_meaningful_activity_at)

    def test_evenement_terminal_est_une_activite_significative(self):
        t_first = self._at(0)

        self.fsm.observe_recent_events(
            recent_events=[_terminal_event(t_first)],
            now=self.base,
        )

        self.assertEqual(self.fsm.session_started_at, t_first)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_first)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_navigation_utile_prolonge_une_session_deja_ancree(self):
        t_code = self._at(8)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_code)],
            now=t_code,
        )

        t_browser = self._at(0)
        transition = self.fsm.observe_recent_events(
            recent_events=[
                _file_event("/proj/main.py", t_code),
                _app_event("Safari", t_browser),
            ],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertIsNone(transition.boundary_reason)
        self.assertFalse(transition.should_start_new_session)
        self.assertFalse(transition.should_reset_clock)
        self.assertIsNone(transition.sleep_minutes)
        self.assertEqual(transition.state, SessionFSM.ACTIVE)
        self.assertEqual(self.fsm.session_started_at, t_code)
        self.assertEqual(self.fsm.last_meaningful_activity_at, t_browser)
        self.assertEqual(self.fsm.state, SessionFSM.ACTIVE)

    def test_local_exploration_ne_demarre_pas_une_session_sans_ancrage(self):
        t_explore = self._at(0)

        transition = self.fsm.observe_recent_events(
            recent_events=[_local_exploration_event(t_explore)],
            now=self.base,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertIsNone(transition.boundary_reason)
        self.assertFalse(transition.should_start_new_session)
        self.assertFalse(transition.should_reset_clock)
        self.assertIsNone(transition.sleep_minutes)
        self.assertEqual(transition.state, SessionFSM.IDLE)
        self.assertEqual(self.fsm.session_started_at, self._at(120))
        self.assertIsNone(self.fsm.last_meaningful_activity_at)
        self.assertEqual(self.fsm.state, SessionFSM.IDLE)

    def test_screen_lock_hors_ordre_reste_detecte_par_timestamp(self):
        t_before = self._at(8)
        t_lock = self._at(4)
        t_after = self._at(0)
        self.fsm.observe_recent_events(
            recent_events=[_file_event("/proj/main.py", t_before)],
            now=self.base,
        )

        transition = self.fsm.observe_recent_events(
            recent_events=[
                _file_event("/proj/main.py", t_after),
                _screen_lock_event(t_lock),
                _file_event("/proj/main.py", t_before),
            ],
            now=self.base,
        )

        self.assertTrue(transition.boundary_detected)
        self.assertEqual(transition.boundary_reason, "screen_lock")
        self.assertEqual(self.fsm.session_started_at, t_after)


if __name__ == "__main__":
    unittest.main()
