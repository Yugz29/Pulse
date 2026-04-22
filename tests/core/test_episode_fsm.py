import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from daemon.core.episode_fsm import EPISODE_TIMEOUT_MIN, EpisodeFSM


class TestEpisodeFSM(unittest.TestCase):
    def setUp(self):
        self.fsm = EpisodeFSM()
        self.base = datetime.now()

    def _at(self, delta_min: float) -> datetime:
        return self.base - timedelta(minutes=delta_min)

    def test_first_meaningful_activity_opens_episode(self):
        with patch("daemon.core.episode_fsm.new_uid", return_value="ep-1"):
            transition = self.fsm.ensure_active(
                session_id="session-1",
                started_at=self.base,
            )

        self.assertIsNotNone(transition.opened_episode)
        self.assertEqual(transition.current_episode.id, "ep-1")
        self.assertEqual(transition.current_episode.session_id, "session-1")
        self.assertEqual(self.fsm.state, EpisodeFSM.ACTIVE)

    def test_short_lock_suspends_then_resumes_same_episode(self):
        with patch("daemon.core.episode_fsm.new_uid", return_value="ep-1"):
            self.fsm.ensure_active(session_id="session-1", started_at=self._at(5))

        self.fsm.on_screen_locked(when=self._at(1))
        transition = self.fsm.on_screen_unlocked(
            session_id="session-1",
            when=self.base,
            boundary_detected=False,
        )

        self.assertFalse(transition.boundary_detected)
        self.assertEqual(transition.current_episode.id, "ep-1")
        self.assertEqual(self.fsm.state, EpisodeFSM.ACTIVE)

    def test_long_lock_closes_current_and_opens_new_episode(self):
        with patch("daemon.core.episode_fsm.new_uid", side_effect=["ep-1", "ep-2"]):
            self.fsm.ensure_active(session_id="session-1", started_at=self._at(40))
            self.fsm.on_screen_locked(when=self._at(35))
            transition = self.fsm.on_screen_unlocked(
                session_id="session-2",
                when=self.base,
                boundary_detected=True,
            )

        self.assertTrue(transition.boundary_detected)
        self.assertEqual(transition.boundary_reason, "screen_lock")
        self.assertEqual(transition.closed_episode.id, "ep-1")
        self.assertEqual(transition.closed_episode.ended_at, self._at(35).isoformat())
        self.assertEqual(transition.closed_episode.boundary_reason, "screen_lock")
        self.assertEqual(transition.opened_episode.id, "ep-2")
        self.assertEqual(transition.opened_episode.session_id, "session-2")

    def test_idle_timeout_uses_threshold_expiry_as_ended_at(self):
        last_meaningful = self._at(30)
        resumed_at = self.base
        expected_end = last_meaningful + timedelta(minutes=EPISODE_TIMEOUT_MIN)

        with patch("daemon.core.episode_fsm.new_uid", side_effect=["ep-1", "ep-2"]):
            self.fsm.ensure_active(session_id="session-1", started_at=self._at(45))
            transition = self.fsm.on_idle_timeout(
                session_id="session-2",
                last_meaningful_activity_at=last_meaningful,
                resumed_at=resumed_at,
            )

        self.assertEqual(transition.closed_episode.ended_at, expected_end.isoformat())
        self.assertEqual(transition.closed_episode.boundary_reason, "idle_timeout")
        self.assertEqual(transition.opened_episode.started_at, resumed_at.isoformat())

    def test_commit_splits_episode_immediately(self):
        with patch("daemon.core.episode_fsm.new_uid", side_effect=["ep-1", "ep-2"]):
            self.fsm.ensure_active(session_id="session-1", started_at=self._at(10))
            transition = self.fsm.on_commit(
                session_id="session-1",
                when=self.base,
            )

        self.assertTrue(transition.boundary_detected)
        self.assertEqual(transition.closed_episode.boundary_reason, "commit")
        self.assertEqual(transition.closed_episode.ended_at, self.base.isoformat())
        self.assertEqual(transition.opened_episode.started_at, self.base.isoformat())

    def test_close_current_leaves_no_active_episode(self):
        with patch("daemon.core.episode_fsm.new_uid", return_value="ep-1"):
            self.fsm.ensure_active(session_id="session-1", started_at=self._at(5))

        transition = self.fsm.close_current(
            ended_at=self.base,
            boundary_reason="session_end",
        )

        self.assertIsNotNone(transition.closed_episode)
        self.assertIsNone(transition.current_episode)
        self.assertIsNone(self.fsm.current_episode)
        self.assertEqual(self.fsm.state, EpisodeFSM.CLOSED)


if __name__ == "__main__":
    unittest.main()
