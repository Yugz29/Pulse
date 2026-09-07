"""One reconstruction owns work sessions; persistence only knows events."""

import copy
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from daemon_v2.analysis.timeline import RECONSTRUCTION_VERSION, reconstruct_session_views
from daemon_v2.context_snapshot import build_context_snapshot, build_day_sessions
from daemon_v2.daily_trace import build_daily_trace, render_daily_trace_markdown
from daemon_v2.ingest import normalize_event
from daemon_v2.trace_store import EventConflictError, TraceStore
from test_trace_store import create_historical_database

BASE = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)


def observed(key, minute=0, kind="file_changed", **details):
    if kind == "file_changed":
        details = {"path": "/project/a.py", "event": "modified", "workspace": "/project", **details}
    return normalize_event({
        "event_id": key, "schema_version": 1, "type": kind,
        "producer": {"name": "pulse-authority-test"},
        "occurred_at": (BASE + timedelta(minutes=minute)).isoformat(),
        "details": details,
    })


def test_insert_and_replay_have_bounded_sql_work_with_a_large_history(tmp_path, monkeypatch):
    store = TraceStore(tmp_path / "trace.db")
    store.append_event(observed("seed"))
    with sqlite3.connect(store.database_path) as db:
        columns = [r[1] for r in db.execute("PRAGMA table_info(activities)") if r[1] != "id"]
        assert "session_id" not in columns
        template = dict(zip(columns, db.execute("SELECT " + ",".join(columns) + " FROM activities").fetchone()))
        db.executemany(
            "INSERT INTO activities (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")",
            [tuple({**template, "event_id": f"old-{n}"}[c] for c in columns) for n in range(10_000)],
        )
    connect = store._connect
    statements = []

    def bounded_connection():
        db = connect()
        # An historical scan exceeds this instruction budget, independently
        # of machine speed. Indexed lookup + insertion has ample headroom.
        db.set_progress_handler(lambda: 1, 5000)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(store, "_connect", bounded_connection)
    event = observed("new")
    created = store.append_event(event)
    replayed = store.append_event(event)
    assert replayed.duplicate and replayed.id == created.id
    with pytest.raises(EventConflictError):
        store.append_event(observed("new", path="/project/different.py"))
    reads = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(reads) == 3
    assert all("WHERE event_id =" in sql for sql in reads)


def test_old_storage_ids_are_preserved_but_do_not_participate_in_reconstruction(tmp_path):
    database = tmp_path / "old.db"
    create_historical_database(database)
    with sqlite3.connect(database) as db:
        before = db.execute("SELECT * FROM activities").fetchall()
        old_columns = [r[1] for r in db.execute("PRAGMA table_info(activities)")]
    store = TraceStore(database)
    store.append_event(observed("new", 10))
    now = BASE + timedelta(hours=2)
    first = build_daily_trace(store, BASE.date(), timezone.utc, now=now)
    second = build_daily_trace(TraceStore(database), BASE.date(), timezone.utc, now=now)
    assert first == second
    assert first["work_sessions"][0]["source_event_ids"] == ["legacy-migrated:1", "new"]
    assert first["work_session_count"] == 1
    assert all("session_id" not in row for row in first["activities"])
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT " + ",".join(old_columns) + " FROM activities WHERE id=1").fetchall() == before
        assert db.execute("SELECT session_id FROM activities ORDER BY id").fetchall() == [("historical-session",), ("",)]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE activities SET session_id='rewritten' WHERE id=1")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM activities WHERE id=1")


def test_reconstruction_is_deterministic_for_permutations_of_stored_events(tmp_path):
    store = TraceStore(tmp_path / "trace.db")
    for item in (
        observed("a"), observed("app", 2, "app_activated", app="Terminal"),
        observed("b", 5), observed("lock", 6, "screen_locked"),
        observed("background", 7), observed("unlock", 8, "screen_unlocked"),
        observed("c", 10), observed("d", 10), observed("isolated", 60),
    ):
        store.append_event(item)
    now = BASE + timedelta(hours=3)
    trace = build_daily_trace(store, BASE.date(), timezone.utc, now=now)
    expected = (trace["work_sessions"], trace["unresolved_sessions"])
    for seed in range(20):
        shuffled = copy.deepcopy(trace["activities"])
        random.Random(seed).shuffle(shuffled)
        unmodified = copy.deepcopy(shuffled)
        assert reconstruct_session_views(shuffled, day=BASE.date(), zone=timezone.utc, now=now) == expected
        assert shuffled == unmodified
    assert {s["reconstruction_version"] for s in expected[0]} == {RECONSTRUCTION_VERSION}
    assert {s["activity_kind"] for s in expected[0]} == {"work", "background", "isolated"}


@pytest.mark.parametrize("zone", [timezone.utc, ZoneInfo("Europe/Paris")])
def test_journal_context_and_listing_share_identity_and_bounds(tmp_path, zone):
    store = TraceStore(tmp_path / "trace.db")
    for item in (observed("a"), observed("b", 5), observed("lock", 6, "screen_locked")):
        store.append_event(item)
    now = BASE + timedelta(minutes=7)
    day = BASE.astimezone(zone).date()
    journal = build_daily_trace(store, day, zone, now=now)
    listing = build_day_sessions(store, day=day, reference_at=now, local_timezone=zone)
    context = build_context_snapshot(store, reference_at=now, local_timezone=zone)
    work, listed = journal["work_sessions"][0], listing["sessions"][0]
    for key in ("id", "label", "source_event_ids", "reconstruction_version"):
        assert work[key] == listed[key] == context["recent_sessions"][0][key]
    assert datetime.fromisoformat(work["started_at"]) == datetime.fromisoformat(listed["started_at"])
    assert datetime.fromisoformat(work["ended_at"]) == datetime.fromisoformat(listed["last_activity_at"])
    assert context["current_session"] is None and listed["is_open"] is False
    assert journal["work_session_count"] == 1
    assert "## Session 1" in render_daily_trace_markdown(journal, archive_mode=True)
    assert journal["schema_version"] == 2
    assert not {"sessions", "session_count", "passive_sessions"}.intersection(journal)


def test_all_consumers_use_the_same_observation_horizon(tmp_path):
    store = TraceStore(tmp_path / "trace.db")
    for item in (observed("a"), observed("b", 5), observed("future", 20)):
        store.append_event(item)
    now = BASE + timedelta(minutes=10)
    trace = build_daily_trace(store, BASE.date(), timezone.utc, now=now)
    context = build_context_snapshot(store, reference_at=now, local_timezone=timezone.utc)
    assert [row["event_id"] for row in trace["activities"]] == ["a", "b"]
    assert trace["work_sessions"][0]["id"] == context["current_session"]["id"]
    assert store.activity_by_event_id("future") is not None
