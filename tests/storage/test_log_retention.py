import os
import tempfile
import time
import unittest
from pathlib import Path

from daemon.storage.log_retention import (
    LogRetentionSafetyError,
    cleanup_pulse_logs,
)


class TestLogRetention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pulse_home = self.root / ".pulse"
        self.logs = self.pulse_home / "logs"
        self.archive = self.pulse_home / "archive"
        self.memory = self.pulse_home / "memory"
        self.logs.mkdir(parents=True)
        self.archive.mkdir(parents=True)
        self.memory.mkdir(parents=True)
        self.now = time.time()

    def _write(self, path: Path, content: bytes, *, age_days: float = 0) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        ts = self.now - age_days * 86400
        os.utime(path, (ts, ts))
        return path

    def _mkdir(self, path: Path, *, age_days: float = 0) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        self._age(path, age_days=age_days)
        return path

    def _age(self, path: Path, *, age_days: float) -> Path:
        ts = self.now - age_days * 86400
        os.utime(path, (ts, ts))
        return path

    def test_dry_run_reports_without_deleting(self):
        old_log = self._write(self.logs / "daemon.app.log.1", b"old-log", age_days=8)

        result = cleanup_pulse_logs(pulse_home=self.pulse_home, dry_run=True, now=self.now)

        self.assertTrue(old_log.exists())
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].bytes, len(b"old-log"))
        self.assertEqual(result.total_bytes_reclaimable, len(b"old-log"))
        self.assertEqual(result.total_bytes_deleted, 0)

    def test_cleanup_deletes_old_archived_logs(self):
        old_archive = self._mkdir(self.archive / "logs-2026-05-01", age_days=4)
        self._write(old_archive / "daemon.error.log", b"archived", age_days=4)
        self._age(old_archive, age_days=4)

        result = cleanup_pulse_logs(pulse_home=self.pulse_home, dry_run=False, now=self.now)

        self.assertFalse(old_archive.exists())
        self.assertEqual(len(result.deleted), 1)
        self.assertEqual(result.deleted[0].kind, "archive_log_dir")

    def test_cleanup_keeps_recent_archived_logs(self):
        recent_archive = self._mkdir(self.archive / "logs-2026-05-12", age_days=1)
        self._write(recent_archive / "daemon.error.log", b"recent", age_days=1)
        self._age(recent_archive, age_days=1)

        result = cleanup_pulse_logs(pulse_home=self.pulse_home, dry_run=False, now=self.now)

        self.assertTrue(recent_archive.exists())
        self.assertEqual(result.deleted, [])

    def test_cleanup_enforces_hard_max_seven_days_for_technical_logs(self):
        old_log = self._write(self.logs / "daemon.app.log.2", b"seven-days-old", age_days=8)
        recent_log = self._write(self.logs / "daemon.app.log.1", b"recent", age_days=6)
        debug_log = self._write(self.logs / "debug-runtime.log", b"debug", age_days=3)

        result = cleanup_pulse_logs(pulse_home=self.pulse_home, dry_run=False, now=self.now)

        self.assertFalse(old_log.exists())
        self.assertTrue(recent_log.exists())
        self.assertFalse(debug_log.exists())
        self.assertEqual({Path(item.path).name for item in result.deleted}, {"daemon.app.log.2", "debug-runtime.log"})

    def test_cleanup_preserves_active_logs_dbs_and_memory_files(self):
        active_error = self._write(self.logs / "daemon.error.log", b"active-error", age_days=30)
        active_stdout = self._write(self.logs / "daemon.stdout.log", b"active-stdout", age_days=30)
        session_db = self._write(self.pulse_home / "session.db", b"db", age_days=30)
        session_wal = self._write(self.pulse_home / "session.db-wal", b"wal", age_days=30)
        memory_file = self._write(self.memory / "daydreams" / "2026-05-01.md", b"memory", age_days=30)
        settings = self._write(self.pulse_home / "settings.json", b"{}", age_days=30)

        result = cleanup_pulse_logs(pulse_home=self.pulse_home, dry_run=False, now=self.now)

        self.assertTrue(active_error.exists())
        self.assertTrue(active_stdout.exists())
        self.assertTrue(session_db.exists())
        self.assertTrue(session_wal.exists())
        self.assertTrue(memory_file.exists())
        self.assertTrue(settings.exists())
        self.assertEqual(result.deleted, [])

    def test_cleanup_refuses_non_pulse_root(self):
        with self.assertRaises(LogRetentionSafetyError):
            cleanup_pulse_logs(pulse_home=self.root, dry_run=True, now=self.now)

    def test_cleanup_refuses_paths_outside_pulse_home(self):
        outside = self.root / "outside"
        outside.mkdir()
        symlink = self.logs / "linked-outside"
        symlink.symlink_to(outside)

        with self.assertRaises(LogRetentionSafetyError):
            cleanup_pulse_logs(pulse_home=self.pulse_home, dry_run=True, now=self.now)

    def test_size_accounting_includes_archived_directory_contents(self):
        old_archive = self._mkdir(self.archive / "logs-2026-05-01", age_days=4)
        self._write(old_archive / "one.log", b"12345", age_days=4)
        self._write(old_archive / "nested" / "two.log", b"678", age_days=4)
        self._age(old_archive, age_days=4)

        result = cleanup_pulse_logs(pulse_home=self.pulse_home, dry_run=True, now=self.now)

        self.assertEqual(result.total_bytes_reclaimable, 8)
        self.assertEqual(result.candidates[0].bytes, 8)


if __name__ == "__main__":
    unittest.main()
