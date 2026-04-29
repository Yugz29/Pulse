import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path
import json
import tempfile

from daemon.core.restart_manager import RestartManager


class TestRestartManager(unittest.TestCase):

    def setUp(self):
        self.manager = RestartManager()
        self.tmpdir = tempfile.TemporaryDirectory()
        # Rediriger le chemin d'état vers un fichier temporaire
        import daemon.core.restart_manager as rm_module
        self._orig_path = rm_module._STATE_PATH
        rm_module._STATE_PATH = Path(self.tmpdir.name) / "restart_state.json"

    def tearDown(self):
        import daemon.core.restart_manager as rm_module
        rm_module._STATE_PATH = self._orig_path
        self.tmpdir.cleanup()

    def test_load_retourne_none_si_fichier_absent(self):
        state = self.manager.load()
        self.assertIsNone(state)

    def test_save_puis_load_restaure_le_projet(self):
        session_fsm = MagicMock()
        session_fsm.session_started_at = datetime(2026, 4, 29, 10, 0, 0)

        snapshot = {"active_project": "Pulse", "probable_task": "coding", "activity_level": "editing"}
        with patch("daemon.core.restart_manager._read_project_head_sha", return_value=None):
            self.manager.save(snapshot, session_fsm=session_fsm)

        state = self.manager.load()
        self.assertIsNotNone(state)
        self.assertEqual(state["active_project"], "Pulse")
        self.assertIn("elapsed_min", state)

    def test_apply_restart_state_resume_aussi_la_session_memory_sur_redemarrage_court(self):
        """
        Redémarrage < 5 min : session_memory.resume_session() doit être appelé
        avec le started_at original pour préserver la continuité de session.
        """
        original_start = datetime.now() - timedelta(minutes=2)
        session_fsm = MagicMock()
        session_memory = MagicMock()

        state = {
            "elapsed_min": 2.0,
            "active_project": "Pulse",
            "probable_task": "coding",
            "started_at": original_start.isoformat(),
        }

        self.manager.apply(state, session_fsm=session_fsm, session_memory=session_memory)

        session_fsm.restore_session_start.assert_called_once()
        session_memory.resume_session.assert_called_once()
        called_with = session_memory.resume_session.call_args
        self.assertIsNotNone(called_with)

    def test_apply_ignore_si_trop_ancien(self):
        session_fsm = MagicMock()
        session_memory = MagicMock()

        state = {
            "elapsed_min": 45.0,
            "active_project": "Pulse",
            "probable_task": "coding",
            "started_at": (datetime.now() - timedelta(minutes=45)).isoformat(),
        }

        self.manager.apply(state, session_fsm=session_fsm, session_memory=session_memory)

        session_fsm.restore_session_start.assert_not_called()
        session_memory.resume_session.assert_not_called()

    def test_apply_partiel_entre_5_et_30_min(self):
        """Redémarrage 5-30 min : contexte logué, timer non restauré."""
        session_fsm = MagicMock()
        session_memory = MagicMock()

        state = {
            "elapsed_min": 15.0,
            "active_project": "Pulse",
            "probable_task": "coding",
            "started_at": (datetime.now() - timedelta(minutes=15)).isoformat(),
        }

        self.manager.apply(state, session_fsm=session_fsm, session_memory=session_memory)

        session_fsm.restore_session_start.assert_not_called()
        session_memory.resume_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
