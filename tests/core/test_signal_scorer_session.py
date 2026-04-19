"""
test_signal_scorer_session.py — Tests des limites de session du SignalScorer.

Principes de stabilité :
  - Chaque test fixe une `base = datetime.now()` en setUp().
  - Tous les timestamps sont dérivés via self._at(delta_min) depuis cette base.
  - Les gaps sont donc exactement `(delta_a - delta_b) minutes` — pas de dérive
    microseconde entre plusieurs appels datetime.now().
  - Les gaps choisis sont clairement au-dessus ou en dessous de SESSION_TIMEOUT_MIN,
    jamais à la frontière exacte.

Comportements vérifiés :
  - La première activité significative ancre le début de session réelle.
  - Inactivité > SESSION_TIMEOUT_MIN → réinitialisation de la session.
  - Pause courte (< SESSION_TIMEOUT_MIN) → session continue.
  - screen_locked entre deux activités → réinitialisation.
  - screen_locked sans activité suivante → session_start ne saute pas à now.
  - reset_session() efface _last_meaningful_activity_at.
  - Les vieux events dans le bus après un reset ne provoquent pas de double reset.
  - inactivity_reset_count s'incrémente sur reset réel, pas sur ancrage première activité.
"""

import unittest
from datetime import datetime, timedelta

from daemon.core.event_bus import Event
from daemon.core.signal_scorer import SignalScorer, SESSION_TIMEOUT_MIN


# ── Helpers de construction d'events ─────────────────────────────────────────

def _file_event(path: str, ts: datetime, kind: str = "file_modified") -> Event:
    e = Event(kind, {"path": path})
    e.timestamp = ts
    return e


def _app_event(app: str, ts: datetime) -> Event:
    e = Event("app_activated", {"app_name": app})
    e.timestamp = ts
    return e


def _screen_lock_event(ts: datetime) -> Event:
    e = Event("screen_locked", {})
    e.timestamp = ts
    return e


class FakeBus:
    """Bus minimal qui expose une liste d'events contrôlés."""

    def __init__(self, events: list):
        self._events = events

    def recent(self, limit: int) -> list:
        return self._events[-limit:]


# ── Suite de tests ────────────────────────────────────────────────────────────

class TestSessionBoundaries(unittest.TestCase):

    def setUp(self):
        self.base = datetime.now()

    def _at(self, delta_min: float) -> datetime:
        return self.base - timedelta(minutes=delta_min)

    def _make_scorer(self) -> SignalScorer:
        scorer = SignalScorer(FakeBus([]))
        scorer._session_start = self._at(120)
        return scorer

    # ── Première activité ancre le début de session ───────────────────────────

    def test_premiere_activite_significative_ancre_le_debut_de_session(self):
        """
        Quand le daemon tourne depuis longtemps sans activité (2h),
        la première activité significative doit définir le vrai début de session.
        """
        scorer = self._make_scorer()
        t_first = self._at(0)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_first)])
        signals = scorer.compute()

        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_first)

    # ── Inactivité longue → réinitialisation ─────────────────────────────────

    def test_inactivite_longue_reinitialise_la_session(self):
        """Gap de 25 min → reset, session repart de la nouvelle activité."""
        scorer = self._make_scorer()

        t_old = self._at(25)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_old)])
        scorer.compute()

        t_new = self._at(0)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_old),
            _file_event("/proj/main.py", t_new),
        ])
        signals = scorer.compute()

        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_new)

    # ── Pause courte → session continue ──────────────────────────────────────

    def test_pause_courte_ne_reinitialise_pas_la_session(self):
        """Gap de 5 min < SESSION_TIMEOUT_MIN → pas de reset."""
        scorer = self._make_scorer()

        t_first = self._at(20)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_first)])
        scorer.compute()

        t_second = self._at(15)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_first),
            _file_event("/proj/main.py", t_second),
        ])
        signals = scorer.compute()

        self.assertEqual(scorer._session_start, t_first)
        self.assertGreaterEqual(signals.session_duration_min, 18)

    def test_activite_continue_accumule_la_duree(self):
        """Plusieurs activités avec gap < seuil → durée accumule depuis la première."""
        scorer = self._make_scorer()

        t1 = self._at(30)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t1)])
        scorer.compute()

        t2 = self._at(21)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t1), _file_event("/proj/main.py", t2)])
        scorer.compute()

        t3 = self._at(12)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t1),
            _file_event("/proj/main.py", t2),
            _file_event("/proj/main.py", t3),
        ])
        signals = scorer.compute()

        self.assertEqual(scorer._session_start, t1)
        self.assertGreaterEqual(signals.session_duration_min, 27)

    # ── screen_locked → réinitialisation ─────────────────────────────────────

    def test_screen_lock_entre_deux_activites_reinitialise_la_session(self):
        """screen_locked entre deux activités → reset même si gap < timeout."""
        scorer = self._make_scorer()

        t_before = self._at(8)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_before)])
        scorer.compute()

        t_lock = self._at(4)
        t_after = self._at(0)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_before),
            _screen_lock_event(t_lock),
            _file_event("/proj/main.py", t_after),
        ])
        signals = scorer.compute()

        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_after)

    def test_screen_lock_sans_nouvelle_activite_ne_saute_pas_a_now(self):
        """screen_lock sans nouvelle activité → session_start reste sur dernière activité."""
        scorer = self._make_scorer()

        t_activity = self._at(15)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_activity)])
        scorer.compute()

        t_lock = self._at(5)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_activity),
            _screen_lock_event(t_lock),
        ])
        signals = scorer.compute()

        self.assertEqual(scorer._session_start, t_activity)
        self.assertGreaterEqual(signals.session_duration_min, 13)

    # ── reset_session() ───────────────────────────────────────────────────────

    def test_reset_session_efface_last_meaningful_activity_at(self):
        """Après reset_session(), _last_meaningful_activity_at est None."""
        scorer = self._make_scorer()

        t_old = self._at(30)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_old)])
        scorer.compute()
        self.assertIsNotNone(scorer._last_meaningful_activity_at)

        scorer.reset_session()
        self.assertIsNone(scorer._last_meaningful_activity_at)

    def test_reset_session_vieux_events_bus_ne_causent_pas_de_double_reset(self):
        """Après reset_session(), les vieux events du bus sont ignorés par le guard."""
        scorer = self._make_scorer()

        t_old = self._at(60)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_old)])
        scorer.compute()

        scorer.reset_session()
        session_start_post_reset = scorer._session_start

        signals = scorer.compute()

        self.assertEqual(scorer._session_start, session_start_post_reset)
        self.assertLessEqual(signals.session_duration_min, 1)

    # ── inactivity_reset_count ────────────────────────────────────────────────

    def test_inactivity_reset_count_incremente_sur_gap_long(self):
        """
        inactivity_reset_count s'incrémente sur un vrai reset (inactivité),
        mais PAS sur l'ancrage de la première activité.
        """
        scorer = self._make_scorer()
        self.assertEqual(scorer.inactivity_reset_count, 0)

        # Première activité — ancrage, pas un reset
        t_first = self._at(30)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_first)])
        scorer.compute()
        self.assertEqual(scorer.inactivity_reset_count, 0, "ancrage ne doit pas incrémenter")

        # Gap court (5 min) — pas de reset
        t_second = self._at(25)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_first),
            _file_event("/proj/main.py", t_second),
        ])
        scorer.compute()
        self.assertEqual(scorer.inactivity_reset_count, 0, "gap court ne doit pas incrémenter")

        # Gap long (25 min) — reset d'inactivité
        t_third = self._at(0)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_second),
            _file_event("/proj/main.py", t_third),
        ])
        scorer.compute()
        self.assertEqual(scorer.inactivity_reset_count, 1, "gap long doit incrémenter")

    def test_inactivity_reset_count_incremente_sur_screen_lock(self):
        """inactivity_reset_count s'incrémente sur screen_lock entre deux activités."""
        scorer = self._make_scorer()

        t_before = self._at(8)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_before)])
        scorer.compute()
        self.assertEqual(scorer.inactivity_reset_count, 0)

        t_lock = self._at(4)
        t_after = self._at(0)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_before),
            _screen_lock_event(t_lock),
            _file_event("/proj/main.py", t_after),
        ])
        scorer.compute()
        self.assertEqual(scorer.inactivity_reset_count, 1)

    def test_inactivity_reset_count_ne_incremente_pas_sans_activite_post_screen_lock(self):
        """screen_lock sans nouvelle activité ne doit pas incrémenter le compteur."""
        scorer = self._make_scorer()

        t_activity = self._at(15)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_activity)])
        scorer.compute()

        t_lock = self._at(5)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_activity),
            _screen_lock_event(t_lock),
        ])
        scorer.compute()
        # Pas de nouvelle activité → latest_meaningful = t_activity = prev → pas de reset
        self.assertEqual(scorer.inactivity_reset_count, 0)

    # ── Types d'activité ─────────────────────────────────────────────────────

    def test_app_de_dev_compte_comme_activite_significative(self):
        """Switch vers app de dev → compte comme activité, gap long → reset."""
        scorer = self._make_scorer()

        t_old = self._at(25)
        scorer.bus = FakeBus([_app_event("Cursor", t_old)])
        scorer.compute()

        t_new = self._at(0)
        scorer.bus = FakeBus([
            _app_event("Cursor", t_old),
            _file_event("/proj/main.py", t_new),
        ])
        signals = scorer.compute()

        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_new)

    def test_app_non_dev_ne_compte_pas_comme_activite_significative(self):
        """Safari ne définit pas _last_meaningful_activity_at."""
        scorer = self._make_scorer()

        t_safari = self._at(25)
        scorer.bus = FakeBus([_app_event("Safari", t_safari)])
        scorer.compute()
        self.assertIsNone(scorer._last_meaningful_activity_at)

        t_file = self._at(0)
        scorer.bus = FakeBus([
            _app_event("Safari", t_safari),
            _file_event("/proj/main.py", t_file),
        ])
        signals = scorer.compute()

        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_file)
        self.assertIsNotNone(scorer._last_meaningful_activity_at)


if __name__ == "__main__":
    unittest.main()
