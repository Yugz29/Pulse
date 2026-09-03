import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from daemon_v2.daily_trace import build_daily_trace, render_daily_trace_markdown
from daemon_v2.ingest import normalize_event
from daemon_v2.models import Activity
from daemon_v2.trace_store import EventConflictError, TraceStore


def activity(occurred_at):
    return Activity("file_changed", occurred_at, "filesystem", "Modified /tmp/a", {"path": "/tmp/a"})


def test_append_persists_activity_and_reuses_nearby_session(tmp_path):
    store = TraceStore(tmp_path / "pulse.sqlite3")
    first_at = datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc)

    first = store.append(activity(first_at))
    second = store.append(activity(first_at + timedelta(minutes=10)))
    rows = store.activities_between(first_at, first_at + timedelta(hours=1))

    assert first.session_id == second.session_id
    assert [row.id for row in rows] == [first.id, second.id]


def test_activities_are_append_only(tmp_path):
    database = tmp_path / "pulse.sqlite3"
    store = TraceStore(database)
    stored = store.append(activity(datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc)))

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE activities SET summary = 'changed' WHERE id = ?",
                (stored.id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM activities WHERE id = ?", (stored.id,))


def test_out_of_order_activity_reuses_session_containing_its_timestamp(tmp_path):
    store = TraceStore(tmp_path / "pulse.sqlite3")
    first_at = datetime(2026, 7, 3, 12, 28, tzinfo=timezone.utc)

    stored = [
        store.append(activity(first_at)),
        store.append(
            Activity(
                "app_activated",
                first_at + timedelta(minutes=22),
                "application",
                "Activated Code",
                {"app": "Code"},
            )
        ),
        store.append(
            Activity(
                "app_activated",
                first_at + timedelta(minutes=47),
                "application",
                "Activated Terminal",
                {"app": "Terminal"},
            )
        ),
        store.append(
            Activity(
                "app_activated",
                first_at + timedelta(minutes=57),
                "application",
                "Activated Code",
                {"app": "Code"},
            )
        ),
        store.append(
            Activity(
                "terminal_finished",
                first_at + timedelta(minutes=42),
                "terminal",
                "Command succeeded: pytest tests_v2",
                {"command": "pytest tests_v2", "exit_code": 0, "cwd": "/project"},
            )
        ),
    ]

    assert len({item.session_id for item in stored}) == 1
    trace = build_daily_trace(store, date(2026, 7, 3), timezone.utc)
    markdown = render_daily_trace_markdown(trace)
    assert trace["session_count"] == 1
    # Nouveau contrat (2026-08-30) : les deux événements forts isolés ne
    # forment plus des blocs Session — la session RAW du store, elle, reste une.
    assert "## Session " not in markdown
    assert "## Activités isolées" in markdown
    assert "- 12:28 ·" in markdown
    assert "- 13:10 · pytest tests\\_v2" in markdown
    assert "## Activité non attribuée" in markdown
    assert "- 12:50 · Code" in markdown
    assert "Apps actives : Terminal, Code" not in markdown
    assert "- 12:50 · Code, Terminal" in markdown
    assert "pytest tests_v2" in markdown


def canonical_ingested(event_id="019c-store", **details):
    return normalize_event(
        {
            "event_id": event_id,
            "schema_version": 1,
            "type": "file_changed",
            "producer": {
                "name": "pulse-test",
                "version": "1.0",
                "instance_id": "store-tests",
            },
            "occurred_at": "2026-07-23T14:32:10.123+02:00",
            "details": {
                "path": "/project/main.py",
                "event": "modified",
                **details,
            },
        }
    )


def create_historical_database(database):
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                source TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            CREATE INDEX idx_activities_occurred_at
                ON activities(occurred_at);
            CREATE INDEX idx_activities_session_id
                ON activities(session_id);
            CREATE TRIGGER activities_no_update
            BEFORE UPDATE ON activities
            BEGIN
                SELECT RAISE(ABORT, 'activities are append-only');
            END;
            CREATE TRIGGER activities_no_delete
            BEFORE DELETE ON activities
            BEGIN
                SELECT RAISE(ABORT, 'activities are append-only');
            END;
            """
        )
        connection.execute(
            """
            INSERT INTO activities (
                session_id, activity_type, occurred_at, recorded_at,
                source, summary, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "historical-session",
                "file_changed",
                "2026-07-22T10:00:00+00:00",
                "2026-07-22T10:00:01+00:00",
                "filesystem",
                "Modified /project/old.py",
                '{"event":"modified","path":"/project/old.py"}',
            ),
        )


def test_migrates_historical_schema_without_loss_and_is_idempotent(tmp_path):
    database = tmp_path / "historical.sqlite3"
    create_historical_database(database)

    TraceStore(database)
    store = TraceStore(database)
    rows = store.activities_between(
        datetime(2026, 7, 22, tzinfo=timezone.utc),
        datetime(2026, 7, 23, tzinfo=timezone.utc),
    )

    assert len(rows) == 1
    assert rows[0].event_id == "legacy-migrated:1"
    assert rows[0].schema_version == 0
    assert rows[0].producer_name == "pulse-legacy-migrated"
    assert rows[0].activity.details["path"] == "/project/old.py"
    assert rows[0].recorded_at.isoformat() == "2026-07-22T10:00:01+00:00"
    historical_trace = build_daily_trace(
        store,
        date(2026, 7, 22),
        timezone.utc,
    )
    exported = historical_trace["sessions"][0]["activities"][0]
    assert exported["event_id"] == "legacy-migrated:1"
    assert exported["schema_version"] == 0
    assert exported["producer"]["name"] == "pulse-legacy-migrated"
    assert exported["recorded_at"] == "2026-07-22T10:00:01+00:00"

    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(activities)")
        }
        indexes = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA index_list(activities)")
        }
        count = connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE activities SET summary = 'changed' WHERE id = 1"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM activities WHERE id = 1")

    assert {
        "event_id",
        "schema_version",
        "type",
        "producer_name",
        "producer_version",
        "producer_instance_id",
        "occurred_at",
        "occurred_at_utc",
        "recorded_at",
        "details_json",
    } <= columns
    assert indexes["idx_activities_event_id"] == 1
    assert "idx_activities_occurred_at_utc" in indexes
    # L'index sur la colonne brute est mort (les requêtes sont lexicales UTC).
    assert "idx_activities_occurred_at" not in indexes
    assert count == 1

    with sqlite3.connect(database) as connection:
        backfilled = connection.execute(
            "SELECT occurred_at_utc FROM activities WHERE id = 1"
        ).fetchone()[0]
    assert backfilled == "2026-07-22T10:00:00.000000+00:00"


def test_occurred_at_utc_is_canonical_and_orders_mixed_offsets(tmp_path):
    # "14:00+02:00" (12:00Z) précède lexicalement... rien du tout : comparé
    # brut à "13:00+00:00" il serait exclu à tort d'une fenêtre finissant à
    # 13:00Z. La colonne canonique rend l'ordre lexical == chronologique.
    database = tmp_path / "pulse.sqlite3"
    store = TraceStore(database)
    paris = timezone(timedelta(hours=2))
    later = store.append(activity(datetime(2026, 7, 3, 14, 0, tzinfo=paris)))
    earlier = store.append(
        activity(datetime(2026, 7, 3, 11, 30, tzinfo=timezone.utc))
    )

    rows = store.activities_between(
        datetime(2026, 7, 3, 11, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 3, 13, 0, tzinfo=timezone.utc),
    )

    assert [row.id for row in rows] == [earlier.id, later.id]
    with sqlite3.connect(database) as connection:
        raw, canonical = connection.execute(
            "SELECT occurred_at, occurred_at_utc FROM activities WHERE id = ?",
            (later.id,),
        ).fetchone()
    # La colonne brute garde l'offset d'origine ; la canonique est UTC à
    # largeur fixe (microsecondes explicites).
    assert raw == "2026-07-03T14:00:00+02:00"
    assert canonical == "2026-07-03T12:00:00.000000+00:00"


def test_same_event_id_with_different_payload_raises_conflict(tmp_path):
    database = tmp_path / "pulse.sqlite3"
    store = TraceStore(database)
    original = canonical_ingested(event_id="019c-conflict")
    conflicting = canonical_ingested(
        event_id="019c-conflict",
        path="/project/other.py",
    )

    store.append_event(original)
    with pytest.raises(EventConflictError):
        store.append_event(conflicting)

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT event_id, details_json
            FROM activities
            WHERE event_id = ?
            """,
            ("019c-conflict",),
        ).fetchall()

    assert len(rows) == 1
    assert "/project/main.py" in rows[0][1]
    assert "/project/other.py" not in rows[0][1]


def test_unique_new_event_and_concurrent_retry_create_one_row(tmp_path):
    database = tmp_path / "concurrent.sqlite3"
    store = TraceStore(database)
    ingested = canonical_ingested()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.append_event(ingested), range(2)))

    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM activities WHERE event_id = ?",
            (ingested.event.event_id,),
        ).fetchone()[0]

    assert count == 1
    assert sorted(item.duplicate for item in results) == [False, True]
    assert results[0].recorded_at == results[1].recorded_at


def test_store_uses_wal_and_survives_concurrent_writers(tmp_path):
    database = tmp_path / "pulse.sqlite3"
    store = TraceStore(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    def append_batch(offset):
        for index in range(10):
            store.append(
                Activity(
                    "terminal_finished",
                    datetime(2026, 7, 3, 12, offset, index, tzinfo=timezone.utc),
                    "terminal",
                    "Command succeeded: pwd",
                    {"command": "pwd", "exit_code": 0, "cwd": "/project"},
                )
            )

    threads = [threading.Thread(target=append_batch, args=(m,)) for m in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    assert count == 20


def test_every_store_operation_closes_its_connection(tmp_path, monkeypatch):
    # Panne du 2026-08-30 : une connexion par opération jamais fermée →
    # EMFILE sous launchd (limite 256 fd) en ~10 minutes de worker.
    opened = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(
        "daemon_v2.trace_store.sqlite3.connect", tracking_connect
    )
    store = TraceStore(tmp_path / "pulse.sqlite3")
    moment = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    store.append(activity(moment))
    store.activities_between(moment - timedelta(hours=1), moment + timedelta(hours=1))
    store.activity_dates(timezone.utc)
    store.latest_activity_id()
    store.occurred_at_since(0)

    assert len(opened) >= 6
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


def test_latest_activity_of_type_is_bounded_by_reference_instant(tmp_path):
    store = TraceStore(tmp_path / "pulse.sqlite3")
    base = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)

    def agent_session(moment, session_id):
        return Activity(
            "agent_session",
            moment,
            "agent",
            f"Agent session (claude-code): {session_id}",
            {"source_tool": "claude-code", "session_id": session_id},
        )

    store.append(activity(base))
    older = store.append(agent_session(base + timedelta(minutes=5), "older"))
    newer = store.append(agent_session(base + timedelta(hours=3), "newer"))

    assert store.latest_activity_of_type("agent_session", before=base) is None
    assert store.latest_activity_of_type("git_commit", before=base + timedelta(days=1)) is None

    bounded = store.latest_activity_of_type(
        "agent_session", before=base + timedelta(hours=1)
    )
    assert bounded is not None and bounded.id == older.id

    inclusive = store.latest_activity_of_type(
        "agent_session", before=base + timedelta(hours=3)
    )
    assert inclusive is not None and inclusive.id == newer.id


def test_latest_activity_of_type_prefers_highest_id_on_equal_instants(tmp_path):
    store = TraceStore(tmp_path / "pulse.sqlite3")
    moment = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    store.append(
        Activity(
            "agent_session", moment, "agent", "first",
            {"source_tool": "codex", "session_id": "a"},
        )
    )
    second = store.append(
        Activity(
            "agent_session", moment, "agent", "second",
            {"source_tool": "codex", "session_id": "b"},
        )
    )

    latest = store.latest_activity_of_type("agent_session", before=moment)

    assert latest is not None and latest.id == second.id


def test_every_stored_activity_has_a_non_empty_event_id(tmp_path):
    # Invariant de l'identité stable des sessions (Core 0.5.0) : le hash
    # est calculé sur les event_id. Le repli id:<rowid> de session_identity
    # n'existe que pour les fixtures sans event_id, jamais pour une ligne
    # stockée — quel que soit le chemin d'écriture.
    from daemon_v2.analysis.timeline import session_identity
    from daemon_v2.daily_trace import build_daily_trace

    database = tmp_path / "pulse.sqlite3"
    create_historical_database(database)  # ligne d'avant le contrat canonique
    store = TraceStore(database)
    moment = datetime(2026, 7, 22, 10, 5, tzinfo=timezone.utc)

    store.append(activity(moment))  # helper interne, event_id uuid4
    store.append_event(
        normalize_event(  # payload plat historique → adaptateur pulse-legacy
            {
                "type": "file_changed",
                "occurred_at": (moment + timedelta(minutes=1)).isoformat(),
                "path": "/project/legacy.py",
            }
        )
    )
    store.append_event(  # contrat canonique, event_id fourni par le producteur
        normalize_event(
            {
                "event_id": "producer-owned-id",
                "schema_version": 1,
                "type": "file_changed",
                "producer": {"name": "pulse-file-watcher"},
                "occurred_at": (moment + timedelta(minutes=2)).isoformat(),
                "details": {"path": "/project/canonical.py", "event": "modified"},
            }
        )
    )

    rows = store.activities_between(moment - timedelta(days=1), moment + timedelta(days=1))
    assert len(rows) == 4
    assert all(isinstance(row.event_id, str) and row.event_id for row in rows)
    assert rows[0].event_id == "legacy-migrated:1"
    with sqlite3.connect(database) as connection:
        empty = connection.execute(
            "SELECT COUNT(*) FROM activities WHERE event_id IS NULL OR event_id = ''"
        ).fetchone()[0]
    assert empty == 0

    trace = build_daily_trace(store, moment.date(), timezone.utc, now=moment + timedelta(hours=3))
    for session in trace["work_sessions"]:
        _identity, sources = session_identity(session["activities"])
        assert sources and not any(source.startswith("id:") for source in sources)


def test_fresh_schema_declares_event_id_not_null(tmp_path):
    database = tmp_path / "fresh.sqlite3"
    TraceStore(database)

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]: row[3] for row in connection.execute("PRAGMA table_info(activities)")
        }
    assert columns["event_id"] == 1  # notnull


def test_new_store_is_private_regardless_of_the_ambient_umask(tmp_path):
    import os
    import stat

    previous = os.umask(0o022)
    try:
        store = TraceStore(tmp_path / "private" / "trace.db")
    finally:
        os.umask(previous)

    directory_mode = stat.S_IMODE((tmp_path / "private").stat().st_mode)
    file_mode = stat.S_IMODE(Path(store.database_path).stat().st_mode)
    assert directory_mode == 0o700
    assert file_mode == 0o600
