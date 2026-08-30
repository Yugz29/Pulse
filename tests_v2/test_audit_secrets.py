"""Tests du contrat de scripts/audit_secrets.py (comptes + codes de sortie)."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from daemon_v2.models import Activity
from daemon_v2.producer_outbox import ProducerOutbox
from daemon_v2.trace_store import TraceStore
from scripts.audit_secrets import (
    AuditInfrastructureError,
    audit_outbox,
    audit_trace,
    main,
)


def _terminal_activity(command: str) -> Activity:
    return Activity(
        "terminal_finished",
        datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
        "terminal",
        f"Command succeeded: {command}",
        {"command": command, "exit_code": 0, "cwd": "/project"},
    )


def _raw_insert_unredacted(database: Path, command: str) -> None:
    """Insère une ligne NON rédigée directement (l'ingestion normale rédige)."""
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER IF EXISTS activities_no_update")
        connection.execute(
            """
            INSERT INTO activities (
                session_id, event_id, schema_version, type, producer_name,
                occurred_at, recorded_at, details_json, activity_type,
                source, summary
            ) VALUES ('s', 'raw-' || ?, 1, 'terminal_finished', 'test',
                      '2026-07-03T12:00:00+00:00', '2026-07-03T12:00:00+00:00',
                      ?, 'terminal_finished', 'terminal', ?)
            """,
            (command[:8], json.dumps({"command": command}), f"Command: {command}"),
        )


def test_audit_trace_counts_only_secret_bearing_rows(tmp_path):
    database = tmp_path / "trace.db"
    store = TraceStore(database)
    store.append(_terminal_activity("git status"))
    store.append(_terminal_activity('git commit -m "add basic logging support"'))
    # Simule une ligne passée par l'ingestion : déjà rédigée → non suspecte.
    store.append(_terminal_activity("mysql -u root -p[REDACTED]"))
    assert audit_trace(database) == 0

    # Une ligne insérée en contournant la rédaction est détectée.
    _raw_insert_unredacted(database, "mysql -u root -phunter2secret")
    assert audit_trace(database) == 1


def test_audit_scans_git_commit_messages(tmp_path):
    database = tmp_path / "trace.db"
    TraceStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO activities (
                session_id, event_id, schema_version, type, producer_name,
                occurred_at, recorded_at, details_json, activity_type,
                source, summary
            ) VALUES ('s', 'msg-1', 1, 'git_commit', 'test',
                      '2026-07-03T12:00:00+00:00', '2026-07-03T12:00:00+00:00',
                      ?, 'git_commit', 'git', 'Commit abc1234')
            """,
            (json.dumps({"message": "rotate key AKIAIOSFODNN7EXAMPLE"}),),
        )
    assert audit_trace(database) == 1


def test_audit_ignores_innocent_multiline_continuations(tmp_path):
    # Régression du 2026-08-29 : 5 lignes historiques flaggées à tort parce
    # que le repli des continuations comptait comme « la rédaction change ».
    database = tmp_path / "trace.db"
    TraceStore(database)
    _raw_insert_unredacted(
        database,
        "git add backend/models.py \\\n  backend/views.py \\\n  backend/api.py",
    )
    assert audit_trace(database) == 0


def test_audit_handles_missing_databases(tmp_path):
    assert audit_trace(tmp_path / "absent.db") == 0
    assert audit_outbox(tmp_path / "absent.sqlite3") == 0


def test_audit_tolerates_malformed_json_rows(tmp_path):
    database = tmp_path / "trace.db"
    TraceStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER IF EXISTS activities_no_update")
        connection.execute(
            """
            INSERT INTO activities (
                session_id, event_id, schema_version, type, producer_name,
                occurred_at, recorded_at, details_json, activity_type,
                source, summary
            ) VALUES ('s', 'bad-json', 1, 'terminal_finished', 'test',
                      '2026-07-03T12:00:00+00:00', '2026-07-03T12:00:00+00:00',
                      'not json{{{', 'terminal_finished', 'terminal', 'ok')
            """
        )
    assert audit_trace(database) == 0


def test_audit_outbox_counts_pending_and_dead_letters(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    clean = json.dumps(
        {"event_id": "clean", "details": {"command": "git status"}}
    )
    leaky = json.dumps(
        {"event_id": "leaky", "details": {"command": "sshpass -p hunter2 ssh h"}}
    )
    outbox.enqueue_payload(clean)
    outbox.enqueue_payload(leaky)
    assert audit_outbox(database) == 1


def test_infrastructure_error_is_distinct_from_findings(tmp_path):
    # Un fichier qui n'est pas une base SQLite → erreur d'infrastructure.
    bogus = tmp_path / "bogus.db"
    bogus.write_text("pas une base sqlite")
    with pytest.raises(AuditInfrastructureError):
        audit_trace(bogus)


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    database = tmp_path / "trace.db"
    TraceStore(database)
    monkeypatch.setenv("PULSE_V2_DB_PATH", str(database))
    monkeypatch.setenv("PULSE_CORE_OUTBOX_PATH", str(tmp_path / "outbox.sqlite3"))
    monkeypatch.setattr("sys.argv", ["audit_secrets"])
    # Les défauts argparse sont évalués à l'import : passer par les args CLI.
    monkeypatch.setattr(
        "sys.argv",
        [
            "audit_secrets",
            "--trace", str(database),
            "--outbox", str(tmp_path / "outbox.sqlite3"),
        ],
    )
    with pytest.raises(SystemExit) as first:
        main()
    assert first.value.code == 0

    _raw_insert_unredacted(database, "export SECRET_KEY=leakyvalue123")
    with pytest.raises(SystemExit) as second:
        main()
    assert second.value.code == 1
    output = capsys.readouterr().out
    assert "leakyvalue123" not in output  # jamais la valeur elle-même
