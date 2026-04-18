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
        # Un seul appel datetime.now() par test.
        # Tous les timestamps dérivent de cette base — gap toujours exact.
        self.base = datetime.now()

    def _at(self, delta_min: float) -> datetime:
        """Timestamp à exactement `delta_min` minutes avant la base du test."""
        return self.base - timedelta(minutes=delta_min)

    def _make_scorer(self) -> SignalScorer:
        """
        Crée un SignalScorer avec un bus vide et un _session_start ancré
        très loin dans le passé (120 min), afin que tous les events de test
        (qui sont dans les 60 dernières minutes) passent le guard
        `latest_meaningful >= _session_start` sans ambiguïté.
        """
        scorer = SignalScorer(FakeBus([]))
        scorer._session_start = self._at(120)
        return scorer

    # ── Première activité ancre le début de session ───────────────────────────

    def test_premiere_activite_significative_ancre_le_debut_de_session(self):
        """
        Quand le daemon tourne depuis longtemps sans activité (2h),
        la première activité significative doit définir le vrai début de session.
        Avant le fix : duration ≈ 120 min. Après : duration ≈ 0 min.
        """
        scorer = self._make_scorer()
        # Daemon démarré il y a 2h, première activité fichier maintenant
        t_first = self._at(0)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_first)])

        signals = scorer.compute()

        # _session_start doit avoir été déplacé à t_first
        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_first)

    # ── Inactivité longue → réinitialisation ─────────────────────────────────

    def test_inactivite_longue_reinitialise_la_session(self):
        """
        Gap de 25 min entre deux activités (bien au-dessus du seuil de 10 min).
        La session doit redémarrer à la reprise d'activité.
        """
        scorer = self._make_scorer()

        # Première activité il y a 25 min
        t_old = self._at(25)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_old)])
        scorer.compute()  # ancre _session_start et _last_meaningful_activity_at à t_old

        # Reprise d'activité maintenant — gap exact = 25 min > SESSION_TIMEOUT_MIN (10)
        t_new = self._at(0)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_old),
            _file_event("/proj/main.py", t_new),
        ])
        signals = scorer.compute()

        # Session réinitialisée à t_new → durée ≈ 0
        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_new)

    # ── Pause courte → session continue ──────────────────────────────────────

    def test_pause_courte_ne_reinitialise_pas_la_session(self):
        """
        Gap de 5 min entre deux activités (bien en dessous du seuil de 10 min).
        La session continue depuis la première activité.
        """
        scorer = self._make_scorer()

        # Première activité il y a 20 min — ancre _session_start à _at(20)
        t_first = self._at(20)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_first)])
        scorer.compute()

        # Deuxième activité il y a 15 min — gap exact = 5 min < SESSION_TIMEOUT_MIN
        t_second = self._at(15)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_first),
            _file_event("/proj/main.py", t_second),
        ])
        signals = scorer.compute()

        # Pas de reset — session_start reste à t_first = _at(20)
        self.assertEqual(scorer._session_start, t_first)
        self.assertGreaterEqual(signals.session_duration_min, 18)

    def test_activite_continue_accumule_la_duree(self):
        """
        Plusieurs activités avec gap de 9 min (< seuil) entre chacune.
        La durée s'accumule depuis la première activité, sans reset.
        """
        scorer = self._make_scorer()

        t1 = self._at(30)  # première activité il y a 30 min
        scorer.bus = FakeBus([_file_event("/proj/main.py", t1)])
        scorer.compute()  # _session_start = t1

        t2 = self._at(21)  # gap = 9 min < SESSION_TIMEOUT_MIN
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t1),
            _file_event("/proj/main.py", t2),
        ])
        scorer.compute()  # pas de reset

        t3 = self._at(12)  # gap = 9 min < SESSION_TIMEOUT_MIN
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t1),
            _file_event("/proj/main.py", t2),
            _file_event("/proj/main.py", t3),
        ])
        signals = scorer.compute()  # pas de reset

        # _session_start = t1, durée ≈ 30 min
        self.assertEqual(scorer._session_start, t1)
        self.assertGreaterEqual(signals.session_duration_min, 27)

    # ── screen_locked → réinitialisation ─────────────────────────────────────

    def test_screen_lock_entre_deux_activites_reinitialise_la_session(self):
        """
        screen_locked entre deux activités → reset, même si le gap temporel
        est inférieur au timeout d'inactivité (8 min < 10 min).
        """
        scorer = self._make_scorer()

        # Première activité il y a 8 min
        t_before = self._at(8)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_before)])
        scorer.compute()  # _session_start = t_before

        # Screen lock il y a 4 min, reprise maintenant
        t_lock = self._at(4)
        t_after = self._at(0)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_before),
            _screen_lock_event(t_lock),
            _file_event("/proj/main.py", t_after),
        ])
        signals = scorer.compute()

        # Reset déclenché par le screen_lock → _session_start = t_after
        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_after)

    def test_screen_lock_sans_nouvelle_activite_ne_saute_pas_a_now(self):
        """
        screen_locked suivi d'aucune nouvelle activité ne déplace pas
        _session_start vers now (0 min). L'invariant : la session reste
        ancrée à la dernière activité connue, pas réinitialisée à now.
        """
        scorer = self._make_scorer()

        # Unique activité il y a 15 min
        t_activity = self._at(15)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_activity)])
        scorer.compute()  # _session_start = t_activity

        # Screen lock il y a 5 min, AUCUNE nouvelle activité fichier
        t_lock = self._at(5)
        scorer.bus = FakeBus([
            _file_event("/proj/main.py", t_activity),
            _screen_lock_event(t_lock),
        ])
        signals = scorer.compute()

        # latest_meaningful = t_activity (aucun nouvel event) → reset à t_activity (inchangé)
        # La session ne saute PAS à now → durée doit rester proche de 15 min
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
        """
        Après reset_session(), les events antérieurs à _session_start dans le bus
        ne doivent pas déclencher de reset parasite : le guard
        `latest_meaningful >= _session_start` les bloque.
        """
        scorer = self._make_scorer()

        # Première activité il y a 60 min → ancre _session_start
        t_old = self._at(60)
        scorer.bus = FakeBus([_file_event("/proj/main.py", t_old)])
        scorer.compute()

        # reset_session() → _session_start = datetime.now() ≈ self.base
        scorer.reset_session()
        session_start_post_reset = scorer._session_start

        # Même vieux event encore dans le bus (antérieur à _session_start)
        signals = scorer.compute()

        # _session_start n'a pas bougé — l'event est ignoré par le guard
        self.assertEqual(scorer._session_start, session_start_post_reset)
        self.assertLessEqual(signals.session_duration_min, 1)

    # ── Types d'activité ─────────────────────────────────────────────────────

    def test_app_de_dev_compte_comme_activite_significative(self):
        """
        Un switch vers une app de dev (Cursor, Xcode, etc.) compte
        comme activité significative pour les limites de session.
        Gap de 25 min → reset attendu.
        """
        scorer = self._make_scorer()

        t_old = self._at(25)
        scorer.bus = FakeBus([_app_event("Cursor", t_old)])
        scorer.compute()  # ancre via app de dev

        t_new = self._at(0)
        scorer.bus = FakeBus([
            _app_event("Cursor", t_old),
            _file_event("/proj/main.py", t_new),
        ])
        signals = scorer.compute()

        # Gap 25 min > SESSION_TIMEOUT_MIN → reset → durée ≈ 0
        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_new)

    def test_app_non_dev_ne_compte_pas_comme_activite_significative(self):
        """
        Safari ne compte pas comme activité significative.
        _last_meaningful_activity_at reste None après un event Safari.
        La première activité fichier qui suit ancre bien la session (else branch).
        """
        scorer = self._make_scorer()

        # Seule activité : Safari il y a 25 min — non significatif
        t_safari = self._at(25)
        scorer.bus = FakeBus([_app_event("Safari", t_safari)])
        scorer.compute()

        # _last_meaningful_activity_at doit rester None
        self.assertIsNone(scorer._last_meaningful_activity_at)

        # Première activité fichier maintenant
        t_file = self._at(0)
        scorer.bus = FakeBus([
            _app_event("Safari", t_safari),
            _file_event("/proj/main.py", t_file),
        ])
        signals = scorer.compute()

        # else branch : _session_start = t_file → durée ≈ 0
        self.assertLessEqual(signals.session_duration_min, 1)
        self.assertEqual(scorer._session_start, t_file)
        self.assertIsNotNone(scorer._last_meaningful_activity_at)


if __name__ == "__main__":
    unittest.main()
