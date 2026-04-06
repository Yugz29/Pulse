import unittest
from daemon.core.event_bus import Event
from daemon.core.state_store import StateStore


class TestStateStore(unittest.TestCase):

    def setUp(self):
        self.store = StateStore()

    def test_etat_initial_vide(self):
        state = self.store.get()
        self.assertIsNone(state.active_app)
        self.assertIsNone(state.active_file)
        self.assertIsNone(state.active_project)

    def test_update_app_switch(self):
        self.store.update(Event("app_switch", {"app_name": "Xcode"}))
        self.assertEqual(self.store.get().active_app, "Xcode")

    def test_update_app_switch_multiple(self):
        # Le dernier app_switch doit écraser le précédent
        self.store.update(Event("app_switch", {"app_name": "Xcode"}))
        self.store.update(Event("app_switch", {"app_name": "Terminal"}))
        self.assertEqual(self.store.get().active_app, "Terminal")

    def test_update_file_change(self):
        path = "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"
        self.store.update(Event("file_change", {"path": path}))
        self.assertEqual(self.store.get().active_file, path)

    def test_extract_project_depuis_chemin(self):
        self.store.update(Event("file_change", {
            "path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"
        }))
        self.assertEqual(self.store.get().active_project, "Pulse")

    def test_extract_project_developer(self):
        self.store.update(Event("file_change", {
            "path": "/Users/yugz/Developer/MonApp/src/main.py"
        }))
        self.assertEqual(self.store.get().active_project, "MonApp")

    def test_extract_project_chemin_inconnu(self):
        self.store.update(Event("file_change", {"path": "/tmp/test.py"}))
        self.assertIsNone(self.store.get().active_project)

    def test_last_event_type_mis_a_jour(self):
        self.store.update(Event("app_switch", {"app_name": "Xcode"}))
        self.assertEqual(self.store.get().last_event_type, "app_switch")
        self.store.update(Event("file_change", {"path": "/test.py"}))
        self.assertEqual(self.store.get().last_event_type, "file_change")

    def test_to_dict_contient_les_cles(self):
        result = self.store.to_dict()
        expected_keys = [
            "active_app", "active_file", "active_project",
            "session_duration_min", "last_event_type", "last_activity"
        ]
        for key in expected_keys:
            self.assertIn(key, result)

    def test_to_dict_apres_events(self):
        self.store.update(Event("app_switch", {"app_name": "Cursor"}))
        self.store.update(Event("file_change", {
            "path": "/Users/yugz/Projets/Cortex/src/main.py"
        }))
        result = self.store.to_dict()
        self.assertEqual(result["active_app"], "Cursor")
        self.assertEqual(result["active_project"], "Cortex")


if __name__ == "__main__":
    unittest.main()
