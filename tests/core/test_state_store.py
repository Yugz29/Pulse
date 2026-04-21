import unittest
import tempfile
from pathlib import Path
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

    def test_extract_project_depuis_racine_git_hors_chemins_marqueurs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "work" / "client-repo"
            (repo_root / ".git").mkdir(parents=True)
            file_path = repo_root / "pkg" / "service.py"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("print('ok')\n")

            self.store.update(Event("file_change", {"path": str(file_path)}))

            self.assertEqual(self.store.get().active_project, "client-repo")

    def test_file_deleted_ne_remplace_pas_le_fichier_actif(self):
        active_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"
        deleted_path = "/Users/yugz/Projets/Pulse/Pulse/daemon/old.py"

        self.store.update(Event("file_modified", {"path": active_path}))
        self.store.update(Event("file_deleted", {"path": deleted_path}))

        self.assertEqual(self.store.get().active_file, active_path)
        self.assertEqual(self.store.get().active_project, "Pulse")

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

    def test_ignore_fichier_bruite_xcode(self):
        self.store.update(Event("file_modified", {
            "path": "/Users/yugz/Projets/Pulse/Pulse/App/App.xcodeproj/project.xcworkspace/xcuserdata/yugz.xcuserdatad/UserInterfaceState.xcuserstate"
        }))
        self.assertIsNone(self.store.get().active_file)
        self.assertIsNone(self.store.get().active_project)

    def test_ignore_fichiers_internes_pulse_dans_home(self):
        pulse_db = str(Path.home() / ".pulse" / "session.db")

        self.store.update(Event("file_modified", {"path": pulse_db}))

        self.assertIsNone(self.store.get().active_file)
        self.assertIsNone(self.store.get().active_project)

    def test_ignore_models_cache_json(self):
        self.store.update(Event("file_modified", {
            "path": "/Users/yugz/Projets/Pulse/build/models_cache.json"
        }))

        self.assertIsNone(self.store.get().active_file)
        self.assertIsNone(self.store.get().active_project)

    def test_ignore_capture_ecran(self):
        self.store.update(Event("file_created", {
            "path": "/Users/yugz/Desktop/Capture d’écran 2026-04-21 à 10.32.18.png"
        }))

        self.assertIsNone(self.store.get().active_file)
        self.assertIsNone(self.store.get().active_project)

    def test_ignore_fichier_dans_trash(self):
        self.store.update(Event("file_modified", {
            "path": "/Users/yugz/.Trash/logo-final.png"
        }))

        self.assertIsNone(self.store.get().active_file)
        self.assertIsNone(self.store.get().active_project)


if __name__ == "__main__":
    unittest.main()
