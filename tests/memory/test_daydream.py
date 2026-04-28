import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from daemon.memory import daydream


class TestDayDream(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.memory_dir = Path(self.temp_dir.name) / "memory"
        self.sessions_dir = self.memory_dir / "sessions"
        self.daydream_dir = Path(self.temp_dir.name) / "daydreams"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        daydream._daydream_pending = False
        daydream._daydream_done_for_date = None
        daydream._daydream_target_date = None
        daydream._daydream_status = "idle"
        daydream._daydream_last_reason = None
        daydream._daydream_last_error = None
        daydream._daydream_last_attempt_at = None
        daydream._daydream_last_completed_at = None
        daydream._daydream_last_output_path = None

    def _write_journal(self, ref_date: date) -> None:
        journal = self.sessions_dir / f"{ref_date}.md"
        journal.write_text(
            "\n".join(
                [
                    "# Journal",
                    "<!-- pulse-journal-data:start",
                    (
                        '[{"started_at":"2026-04-27T21:00:00","duration_min":42,'
                        '"probable_task":"coding","active_project":"Pulse",'
                        '"top_files":["daemon/core/signal_scorer.py"],'
                        '"body":"Fix du scorer focus."}]'
                    ),
                    "pulse-journal-data:end -->",
                ]
            ),
            encoding="utf-8",
        )

    def test_trigger_apres_minuit_utilise_la_date_marquee_la_veille(self):
        ref_date = date(2026, 4, 27)
        self._write_journal(ref_date)

        with patch("daemon.memory.extractor.MEMORY_DIR", self.memory_dir), patch.object(
            daydream,
            "DAYDREAM_DIR",
            self.daydream_dir,
        ), patch.object(daydream, "_vectorize_daydream", return_value=None):
            daydream.mark_daydream_pending(ref_date=ref_date)
            output_path = daydream.trigger_daydream(today=date(2026, 4, 28))

        self.assertIsNotNone(output_path)
        assert output_path is not None
        self.assertEqual(output_path.name, "2026-04-27.md")
        self.assertTrue(output_path.exists())
        content = output_path.read_text(encoding="utf-8")
        self.assertIn("27", content)
        self.assertIn("Pulse", content)
        self.assertFalse(daydream.should_trigger_daydream())
        status = daydream.get_daydream_status()
        self.assertEqual(status["status"], "generated")
        self.assertEqual(status["target_date"], None)
        self.assertEqual(status["done_for_date"], "2026-04-27")
        self.assertEqual(status["last_reason"], "generated")

    def test_mark_pending_idempotent_pour_meme_date(self):
        ref_date = date(2026, 4, 27)
        first = daydream.mark_daydream_pending(ref_date=ref_date)
        second = daydream.mark_daydream_pending(ref_date=ref_date)

        self.assertTrue(first)
        self.assertFalse(second)
        status = daydream.get_daydream_status()
        self.assertEqual(status["status"], "pending")
        self.assertEqual(status["target_date"], "2026-04-27")
        self.assertEqual(status["last_reason"], "awaiting_screen_lock")

    def test_claim_daydream_run_est_idempotent(self):
        ref_date = date(2026, 4, 27)
        daydream.mark_daydream_pending(ref_date=ref_date)

        first = daydream.claim_daydream_run()
        second = daydream.claim_daydream_run()

        self.assertEqual(first, ref_date)
        self.assertIsNone(second)
        status = daydream.get_daydream_status()
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["target_date"], "2026-04-27")

    def test_trigger_ignore_si_fichier_existe_deja(self):
        ref_date = date(2026, 4, 27)
        self.daydream_dir.mkdir(parents=True, exist_ok=True)
        existing = self.daydream_dir / "2026-04-27.md"
        existing.write_text("# Existing", encoding="utf-8")

        with patch.object(daydream, "DAYDREAM_DIR", self.daydream_dir):
            daydream.mark_daydream_pending(ref_date=ref_date)
            output_path = daydream.trigger_daydream(today=date(2026, 4, 28))

        self.assertIsNone(output_path)
        status = daydream.get_daydream_status()
        self.assertEqual(status["status"], "generated")
        self.assertEqual(status["last_reason"], "already_exists")
        self.assertEqual(status["last_output_path"], str(existing))

    def test_trigger_sans_journal_est_skipped_visible(self):
        ref_date = date(2026, 4, 27)
        with patch("daemon.memory.extractor.MEMORY_DIR", self.memory_dir), patch.object(
            daydream,
            "DAYDREAM_DIR",
            self.daydream_dir,
        ):
            daydream.mark_daydream_pending(ref_date=ref_date)
            output_path = daydream.trigger_daydream(today=date(2026, 4, 28))

        self.assertIsNone(output_path)
        status = daydream.get_daydream_status()
        self.assertEqual(status["status"], "skipped")
        self.assertEqual(status["done_for_date"], "2026-04-27")
        self.assertEqual(status["last_reason"], "no_journal_entries")


if __name__ == "__main__":
    unittest.main()
