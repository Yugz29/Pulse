import logging
import os
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-tests-home-")
os.environ["HOME"] = _TEST_HOME

import daemon.main as daemon_main


class TestMainLogging(unittest.TestCase):
    @staticmethod
    def _record(message: str, level: int = logging.INFO) -> logging.LogRecord:
        return logging.LogRecord(
            name="werkzeug",
            level=level,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )

    def test_routine_polling_gets_are_suppressed(self):
        log_filter = daemon_main._RoutineGetLogFilter()

        self.assertFalse(
            log_filter.filter(
                self._record('127.0.0.1 - - [13/May/2026 09:00:00] "GET /mcp/pending HTTP/1.1" 204 -')
            )
        )
        self.assertFalse(
            log_filter.filter(
                self._record(
                    '127.0.0.1 - - [13/May/2026 09:00:00] "GET /feed?since=2026-05-13T08%3A59%3A59 HTTP/1.1" 200 -'
                )
            )
        )
        self.assertFalse(
            log_filter.filter(
                self._record(
                    '127.0.0.1 - - [13/May/2026 09:00:00] "\x1b[35m\x1b[1mGET /mcp/pending HTTP/1.1\x1b[0m" 204 -'
                )
            )
        )
        self.assertFalse(
            log_filter.filter(
                self._record(
                    '127.0.0.1 - - [13/May/2026 09:00:00] "GET /context-probes/requests?status=pending&include_terminal=false HTTP/1.1" 200 -'
                )
            )
        )
        self.assertFalse(
            log_filter.filter(
                self._record(
                    '[Daemon 09:49:40] INFO 127.0.0.1 - - [13/May/2026 09:49:40] "GET /llm/models HTTP/1.1" 200 -'
                )
            )
        )
        self.assertFalse(
            log_filter.filter(
                self._record(
                    '[Daemon 09:49:40] INFO 127.0.0.1 - - [13/May/2026 09:49:40] "POST /event HTTP/1.1" 200 -'
                )
            )
        )

    def test_non_routine_access_logs_and_warnings_remain_visible(self):
        log_filter = daemon_main._RoutineGetLogFilter()

        self.assertTrue(
            log_filter.filter(
                self._record('127.0.0.1 - - [13/May/2026 09:00:00] "GET /assistant/context HTTP/1.1" 200 -')
            )
        )
        self.assertTrue(
            log_filter.filter(
                self._record(
                    '127.0.0.1 - - [13/May/2026 09:00:00] "GET /feed?since=latest HTTP/1.1" 500 -'
                )
            )
        )
        self.assertTrue(
            log_filter.filter(
                self._record(
                    '[Daemon 09:49:40] INFO 127.0.0.1 - - [13/May/2026 09:49:40] "GET /llm/models HTTP/1.1" 500 -'
                )
            )
        )
        self.assertTrue(
            log_filter.filter(
                self._record(
                    '[Daemon 09:49:40] INFO 127.0.0.1 - - [13/May/2026 09:49:40] "POST /event HTTP/1.1" 500 -'
                )
            )
        )
        self.assertTrue(
            log_filter.filter(
                self._record(
                    '[Daemon 09:49:40] INFO 127.0.0.1 - - [13/May/2026 09:49:40] "POST /event HTTP/1.1" 400 -'
                )
            )
        )

    def test_default_log_level_is_info_and_debug_can_be_explicit(self):
        self.assertEqual(daemon_main._resolve_daemon_log_level({}), logging.INFO)
        self.assertEqual(daemon_main._resolve_daemon_log_level({"PULSE_DEBUG": "1"}), logging.DEBUG)
        self.assertEqual(daemon_main._resolve_daemon_log_level({"PULSE_LOG_LEVEL": "DEBUG"}), logging.DEBUG)

    def test_logging_handlers_include_bounded_rotating_app_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handlers = daemon_main._build_logging_handlers(Path(tmpdir))

        rotating_handlers = [handler for handler in handlers if isinstance(handler, RotatingFileHandler)]
        self.assertEqual(len(rotating_handlers), 1)
        handler = rotating_handlers[0]
        self.assertEqual(handler.maxBytes, daemon_main._APP_LOG_MAX_BYTES)
        self.assertEqual(handler.backupCount, daemon_main._APP_LOG_BACKUP_COUNT)
        self.assertTrue(str(handler.baseFilename).endswith("daemon.app.log"))


if __name__ == "__main__":
    unittest.main()
