import unittest
from datetime import datetime, timedelta

from daemon.core.event_bus import Event
from daemon.core.signal_scorer import SignalScorer


class FakeBus:
    def __init__(self, events: list):
        self._events = events

    def recent(self, limit: int) -> list:
        return self._events[-limit:]


def _file_event(path: str, ts: datetime) -> Event:
    event = Event("file_modified", {"path": path})
    event.timestamp = ts
    return event


class TestSignalScorerSessionDelegation(unittest.TestCase):
    def setUp(self):
        self.base = datetime.now()

    def _at(self, delta_min: float) -> datetime:
        return self.base - timedelta(minutes=delta_min)

    def test_compute_uses_session_started_at_fourni_par_exterieur(self):
        scorer = SignalScorer(FakeBus([_file_event("/proj/main.py", self._at(0))]))

        signals = scorer.compute(session_started_at=self._at(25))

        self.assertGreaterEqual(signals.session_duration_min, 24)

    def test_compute_sans_session_started_at_ne_maintient_pas_un_cycle_interne(self):
        scorer = SignalScorer(FakeBus([_file_event("/proj/main.py", self._at(0))]))

        signals = scorer.compute()

        self.assertLessEqual(signals.session_duration_min, 1)

    def test_reset_session_reste_compatible_mais_ne_change_pas_le_scoring(self):
        scorer = SignalScorer(FakeBus([_file_event("/proj/main.py", self._at(0))]))

        scorer.reset_session()
        signals = scorer.compute(session_started_at=self._at(10))

        self.assertGreaterEqual(signals.session_duration_min, 9)


if __name__ == "__main__":
    unittest.main()
