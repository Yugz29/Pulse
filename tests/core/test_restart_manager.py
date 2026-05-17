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

    def test_recover_missed_commits_utilise_fallback_deterministe_par_defaut(self):
        summary_llm = MagicMock()
        state = {
            "last_head_sha": "old",
            "last_sha_project": "AlphaApp",
            "active_project": "AlphaApp",
            "probable_task": "coding",
            "shutdown_at": "2026-05-17T10:00:00",
            "started_at": "2026-05-17T09:55:00",
        }

        with patch("daemon.core.workspace_context.find_workspace_root", return_value="/tmp/AlphaApp"), \
             patch("daemon.memory.extractor.find_git_root", return_value="/tmp/AlphaApp"), \
             patch("daemon.memory.extractor.read_head_sha", return_value="new"), \
             patch("daemon.memory.extractor.read_commit_message", return_value="fix: missed commit"), \
             patch("daemon.core.git_diff.read_commit_diff_summary", return_value="Diff en cours : app.py (+1 -0)"), \
             patch("daemon.memory.extractor.read_commit_file_names", return_value=["app.py"]), \
             patch("daemon.memory.extractor.update_memories_from_session") as update:
            self.manager.recover_missed_commits(state, summary_llm=summary_llm)

        update.assert_called_once()
        self.assertIsNone(update.call_args.kwargs["llm"])
        summary_llm.complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
