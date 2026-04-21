"""
Tests pour _should_publish_to_bus — filtre d'entrée de l'EventBus.

Cas critiques :
  - COMMIT_EDITMSG doit toujours passer (détection de commit)
  - Les fichiers système/pip/env sont bloqués
  - Les events non-fichier passent toujours
  - Les fichiers projet meaningful passent
"""

import os
import tempfile
import unittest

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ.setdefault("HOME", _TEST_HOME)

from daemon.routes.runtime import _should_publish_to_bus


class TestShouldPublishToBus(unittest.TestCase):

    # ── Events non-fichier — passent toujours ─────────────────────────────────

    def test_app_activated_passe(self):
        self.assertTrue(_should_publish_to_bus("app_activated", {"app_name": "Xcode"}))

    def test_screen_locked_passe(self):
        self.assertTrue(_should_publish_to_bus("screen_locked", {}))

    def test_screen_unlocked_passe(self):
        self.assertTrue(_should_publish_to_bus("screen_unlocked", {}))

    def test_clipboard_updated_passe(self):
        self.assertTrue(_should_publish_to_bus("clipboard_updated", {"content_kind": "text"}))

    def test_user_idle_passe(self):
        self.assertTrue(_should_publish_to_bus("user_idle", {}))

    def test_mcp_command_passe(self):
        self.assertTrue(_should_publish_to_bus("mcp_command_received", {"command": "ls"}))

    # ── COMMIT_EDITMSG — exception critique ───────────────────────────────────

    def test_commit_editmsg_file_modified_passe(self):
        """COMMIT_EDITMSG doit toujours entrer dans le bus — détection de commit."""
        self.assertTrue(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/.git/COMMIT_EDITMSG"},
        ))

    def test_commit_editmsg_file_created_passe(self):
        self.assertTrue(_should_publish_to_bus(
            "file_created",
            {"path": "/Users/yugz/Projets/Pulse/.git/COMMIT_EDITMSG"},
        ))

    def test_commit_editmsg_dans_worktree_passe(self):
        """Worktrees : COMMIT_EDITMSG peut être dans un chemin non standard."""
        self.assertTrue(_should_publish_to_bus(
            "file_modified",
            {"path": "/tmp/worktree-branch/.git/COMMIT_EDITMSG"},
        ))

    # ── Fichiers projet meaningful — passent ──────────────────────────────────

    def test_source_python_passe(self):
        self.assertTrue(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/daemon/main.py"},
        ))

    def test_source_swift_passe(self):
        self.assertTrue(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/App/App/PanelView.swift"},
        ))

    def test_config_projet_passe(self):
        self.assertTrue(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/MonApp/package.json"},
        ))

    def test_markdown_passe(self):
        self.assertTrue(_should_publish_to_bus(
            "file_created",
            {"path": "/Users/yugz/Projets/Pulse/README.md"},
        ))

    def test_test_file_passe(self):
        self.assertTrue(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/tests/test_main.py"},
        ))

    # ── Python site-packages — bloqués ────────────────────────────────────────

    def test_past_json_site_packages_bloque(self):
        """Cas réel à l'origine du bug de bruit."""
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/opt/homebrew/lib/python3.13/site-packages/past.json"},
        ))

    def test_altgraph_site_packages_bloque(self):
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/usr/local/lib/python3.11/site-packages/altgraph/altgraph.json"},
        ))

    def test_venv_lib_bloque(self):
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/MonApp/.venv/lib/python3.11/site-packages/flask/__init__.py"},
        ))

    # ── Librairies système — bloquées ──────────────────────────────────────────

    def test_homebrew_cellar_bloque(self):
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/opt/homebrew/Cellar/python@3.13/3.13.2/lib/python3.13/os.py"},
        ))

    def test_usr_local_lib_bloque(self):
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/usr/local/lib/python3.11/ssl.py"},
        ))

    def test_system_library_bloque(self):
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/System/Library/Frameworks/Python.framework/Versions/3.9/lib/python3.9/os.py"},
        ))

    # ── Git internals (hors COMMIT_EDITMSG) — bloqués ─────────────────────────

    def test_git_index_bloque(self):
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/.git/index"},
        ))

    def test_git_pack_bloque(self):
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/.git/objects/pack/pack-abc.idx"},
        ))

    def test_models_cache_json_bloque(self):
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/build/models_cache.json"},
        ))

    # ── Fichiers sans chemin — bloqués ────────────────────────────────────────

    def test_payload_sans_path_bloque(self):
        self.assertFalse(_should_publish_to_bus("file_modified", {}))

    def test_path_vide_bloque(self):
        self.assertFalse(_should_publish_to_bus("file_modified", {"path": ""}))

    # ── Tous les types d'events fichier sont couverts ─────────────────────────

    def test_file_created_filtre(self):
        self.assertFalse(_should_publish_to_bus(
            "file_created",
            {"path": "/usr/local/lib/python3.11/os.py"},
        ))

    def test_file_renamed_filtre(self):
        self.assertFalse(_should_publish_to_bus(
            "file_renamed",
            {"path": "/opt/homebrew/Cellar/something.py"},
        ))

    def test_file_deleted_filtre(self):
        self.assertFalse(_should_publish_to_bus(
            "file_deleted",
            {"path": "/usr/lib/python3/dist-packages/old.py"},
        ))

    def test_file_change_filtre(self):
        self.assertFalse(_should_publish_to_bus(
            "file_change",
            {"path": "/usr/local/lib/python3.11/ssl.py"},
        ))

    # ── Verrou écran — filtrage des events pendant le lock ─────────────────────────

    def _locked_state(self):
        """RuntimeState minimal avec écran verrouillé."""
        class FakeState:
            def is_screen_locked(self):
                return True
        return FakeState()

    def _unlocked_state(self):
        """RuntimeState minimal avec écran déverrouillé."""
        class FakeState:
            def is_screen_locked(self):
                return False
        return FakeState()

    def test_file_modified_bloque_pendant_lock(self):
        """Un file_modified ne doit pas entrer dans le bus pendant le verrou."""
        self.assertFalse(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/daemon/main.py"},
            self._locked_state(),
        ))

    def test_app_activated_bloque_pendant_lock(self):
        """Un app_activated ne doit pas entrer dans le bus pendant le verrou."""
        self.assertFalse(_should_publish_to_bus(
            "app_activated",
            {"app_name": "Cursor"},
            self._locked_state(),
        ))

    def test_clipboard_bloque_pendant_lock(self):
        """Un clipboard_updated ne doit pas entrer dans le bus pendant le verrou."""
        self.assertFalse(_should_publish_to_bus(
            "clipboard_updated",
            {"content": "hello"},
            self._locked_state(),
        ))

    def test_screen_unlocked_passe_pendant_lock(self):
        """screen_unlocked doit toujours passer, même quand écran marqué comme verrouillé."""
        self.assertTrue(_should_publish_to_bus(
            "screen_unlocked",
            {},
            self._locked_state(),
        ))

    def test_screen_locked_passe_pendant_lock(self):
        """screen_locked passe toujours (idempotence du verrou)."""
        self.assertTrue(_should_publish_to_bus(
            "screen_locked",
            {},
            self._locked_state(),
        ))

    def test_file_modified_passe_apres_unlock(self):
        """Après unlock, les events fichier meaningful doivent à nouveau passer."""
        self.assertTrue(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/daemon/main.py"},
            self._unlocked_state(),
        ))

    def test_sans_runtime_state_comportement_inchange(self):
        """Sans runtime_state (valeur None), le filtre se comporte comme avant."""
        self.assertTrue(_should_publish_to_bus(
            "app_activated",
            {"app_name": "Xcode"},
            None,
        ))
        self.assertTrue(_should_publish_to_bus(
            "file_modified",
            {"path": "/Users/yugz/Projets/Pulse/daemon/main.py"},
            None,
        ))


if __name__ == "__main__":
    unittest.main()
