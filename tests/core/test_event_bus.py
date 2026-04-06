import unittest
from daemon.core.event_bus import EventBus, Event


class TestEventBus(unittest.TestCase):

    def setUp(self):
        self.bus = EventBus(max_size=10)

    def test_publish_ajoute_un_event(self):
        self.bus.publish("file_change", {"path": "/test.py"})
        self.assertEqual(len(self.bus.recent()), 1)

    def test_recent_retourne_n_derniers(self):
        self.bus.publish("app_switch", {"app_name": "Xcode"})
        self.bus.publish("file_change", {"path": "/test.py"})
        self.bus.publish("app_switch", {"app_name": "Terminal"})
        # recent(2) doit retourner les 2 derniers
        self.assertEqual(len(self.bus.recent(2)), 2)
        self.assertEqual(self.bus.recent(2)[-1].type, "app_switch")

    def test_recent_of_type_filtre_par_type(self):
        self.bus.publish("app_switch", {"app_name": "Xcode"})
        self.bus.publish("file_change", {"path": "/test.py"})
        self.bus.publish("app_switch", {"app_name": "Terminal"})
        result = self.bus.recent_of_type("app_switch")
        self.assertEqual(len(result), 2)
        for e in result:
            self.assertEqual(e.type, "app_switch")

    def test_subscribe_recoit_les_events(self):
        received = []
        self.bus.subscribe(lambda e: received.append(e))
        self.bus.publish("file_change", {"path": "/test.py"})
        self.bus.publish("app_switch", {"app_name": "Xcode"})
        self.assertEqual(len(received), 2)

    def test_max_size_supprime_les_plus_vieux(self):
        # max_size=10 — on publie 12 events
        for i in range(12):
            self.bus.publish("event", {"i": i})
        # Seuls les 10 derniers doivent être gardés
        self.assertEqual(len(self.bus.recent()), 10)

    def test_clear_vide_la_queue(self):
        self.bus.publish("file_change", {"path": "/test.py"})
        self.bus.clear()
        self.assertEqual(len(self.bus.recent()), 0)

    def test_subscriber_erreur_ninterrompt_pas_les_autres(self):
        # Un abonné qui plante ne doit pas empêcher les autres de recevoir
        ok = []
        self.bus.subscribe(lambda e: (_ for _ in ()).throw(Exception("crash")))
        self.bus.subscribe(lambda e: ok.append(e))
        self.bus.publish("test", {})
        self.assertEqual(len(ok), 1)

    def test_payload_conserve(self):
        self.bus.publish("file_change", {"path": "/Users/yugz/test.py", "size": 1024})
        event = self.bus.recent(1)[0]
        self.assertEqual(event.payload["path"], "/Users/yugz/test.py")
        self.assertEqual(event.payload["size"], 1024)


if __name__ == "__main__":
    unittest.main()
