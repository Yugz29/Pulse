"""SQLite append-only activity store with versioned, idempotent events."""

import json
import sqlite3
from contextlib import closing
import uuid
from datetime import date, datetime, timezone, tzinfo
from pathlib import Path

from .models import (
    Activity,
    CanonicalEvent,
    IngestedEvent,
    StoredActivity,
    canonical_event_fingerprint,
)
from .private_files import ensure_private_directory, restrict_private_file


CREATE_ACTIVITIES_TABLE = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    type TEXT NOT NULL,
    producer_name TEXT NOT NULL,
    producer_version TEXT NULL,
    producer_instance_id TEXT NULL,
    occurred_at TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    details_json TEXT NOT NULL,
    event_fingerprint TEXT NULL,
    activity_type TEXT NOT NULL,
    source TEXT NOT NULL,
    summary TEXT NOT NULL
)
"""

INDEX_STATEMENTS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_event_id ON activities(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_activities_occurred_at_utc ON activities(occurred_at_utc)",
)

TRIGGER_STATEMENTS = (
    """
    CREATE TRIGGER IF NOT EXISTS activities_no_update
    BEFORE UPDATE ON activities
    BEGIN
        SELECT RAISE(ABORT, 'activities are append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS activities_no_delete
    BEFORE DELETE ON activities
    BEGIN
        SELECT RAISE(ABORT, 'activities are append-only');
    END
    """,
)


def utc_lexical(moment: datetime) -> str:
    """Canonical UTC form whose lexical order IS the chronological order.

    Fixed offset (+00:00) and fixed microsecond width: plain string
    comparisons on occurred_at_utc are correct and use the column index,
    unlike julianday(occurred_at) which forces a full scan. Naive legacy
    timestamps take the system timezone, exactly like every reader that
    calls .astimezone() on them.
    """
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


class EventConflictError(ValueError):
    """An event_id was reused with different canonical content."""

    def __init__(self, event_id: str) -> None:
        super().__init__(
            f"event_id already exists with different canonical content: {event_id}"
        )
        self.event_id = event_id


class TraceStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        ensure_private_directory(Path(self.database_path).parent)
        self._initialize()
        # La base contient des commandes et des messages de commit : 0600,
        # même si le processus appelant n'a pas posé l'umask 077.
        restrict_private_file(Path(self.database_path))

    # Every caller wraps this in closing(...): relying on the garbage
    # collector leaks one fd per operation and hits launchd's 256-fd
    # limit in minutes (2026-08-30 outage: worker down, EMFILE).
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        # WAL: Flask (lectures) et le worker (écritures) partagent ce fichier
        # sans se bloquer. busy_timeout explicite en plus du timeout=5.0.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        """Create or transactionally migrate the single activities table.

        Historical rows receive a deterministic ``legacy-migrated:<row id>``
        event_id, schema_version 0, producer ``pulse-legacy-migrated``, and
        ``type`` copied from ``activity_type``. The historical Core schema
        already recorded both timestamps, so those values are retained. If
        only one timestamp had existed, copying it to ``recorded_at`` would
        merely have been a documented migration approximation.
        """
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(CREATE_ACTIVITIES_TABLE)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(activities)")
            }

            # Legacy databases keep their historical column and values untouched.
            # New events only satisfy its NOT NULL constraint; no session is assigned.
            self._has_legacy_session_column = "session_id" in columns

            # Temporarily remove append-only guards only inside the migration
            # transaction; they are recreated before commit.
            connection.execute("DROP TRIGGER IF EXISTS activities_no_update")
            connection.execute("DROP TRIGGER IF EXISTS activities_no_delete")

            additions = {
                "event_id": "TEXT",
                "schema_version": "INTEGER",
                "type": "TEXT",
                "producer_name": "TEXT",
                "producer_version": "TEXT",
                "producer_instance_id": "TEXT",
                "event_fingerprint": "TEXT",
                "occurred_at_utc": "TEXT",
            }
            for name, sql_type in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE activities ADD COLUMN {name} {sql_type}"
                    )

            connection.execute(
                """
                UPDATE activities
                SET event_id = 'legacy-migrated:' || id
                WHERE event_id IS NULL OR event_id = ''
                """
            )
            connection.execute(
                "UPDATE activities SET schema_version = 0 WHERE schema_version IS NULL"
            )
            connection.execute(
                """
                UPDATE activities
                SET type = activity_type
                WHERE type IS NULL OR type = ''
                """
            )
            connection.execute(
                """
                UPDATE activities
                SET producer_name = 'pulse-legacy-migrated'
                WHERE producer_name IS NULL OR producer_name = ''
                """
            )
            # Backfill the lexical UTC column in Python: only fromisoformat
            # understands every historical offset form, and the canonical
            # fixed-width rendering must match what append_event writes.
            pending_utc = connection.execute(
                """
                SELECT id, occurred_at FROM activities
                WHERE occurred_at_utc IS NULL OR occurred_at_utc = ''
                """
            ).fetchall()
            for row in pending_utc:
                connection.execute(
                    "UPDATE activities SET occurred_at_utc = ? WHERE id = ?",
                    (
                        utc_lexical(datetime.fromisoformat(row["occurred_at"])),
                        row["id"],
                    ),
                )
            connection.execute("DROP INDEX IF EXISTS idx_activities_occurred_at")

            for statement in INDEX_STATEMENTS:
                connection.execute(statement)
            for statement in TRIGGER_STATEMENTS:
                connection.execute(statement)

    def append_event(self, ingested: IngestedEvent) -> StoredActivity:
        event = ingested.event
        activity = ingested.activity
        details_json = json.dumps(
            activity.details,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM activities WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                if existing["event_fingerprint"] != ingested.fingerprint:
                    raise EventConflictError(event.event_id)
                stored = self._row_to_stored_activity(existing)
                return StoredActivity(
                    id=stored.id,
                    activity=stored.activity,
                    event_id=stored.event_id,
                    schema_version=stored.schema_version,
                    producer_name=stored.producer_name,
                    producer_version=stored.producer_version,
                    producer_instance_id=stored.producer_instance_id,
                    recorded_at=stored.recorded_at,
                    duplicate=True,
                )

            recorded_at = datetime.now(timezone.utc)
            legacy_column = "session_id," if self._has_legacy_session_column else ""
            legacy_value = "''," if self._has_legacy_session_column else ""
            cursor = connection.execute(
                f"""
                INSERT INTO activities (
                    {legacy_column} event_id, schema_version, type,
                    producer_name, producer_version, producer_instance_id,
                    occurred_at, occurred_at_utc, recorded_at, details_json,
                    event_fingerprint, activity_type, source, summary
                ) VALUES ({legacy_value} ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.schema_version,
                    event.event_type,
                    event.producer_name,
                    event.producer_version,
                    event.producer_instance_id,
                    event.occurred_at.isoformat(),
                    utc_lexical(event.occurred_at),
                    recorded_at.isoformat(),
                    details_json,
                    ingested.fingerprint,
                    activity.activity_type,
                    activity.source,
                    activity.summary,
                ),
            )
            activity_id = int(cursor.lastrowid)

        return StoredActivity(
            id=activity_id,
            activity=activity,
            event_id=event.event_id,
            schema_version=event.schema_version,
            producer_name=event.producer_name,
            producer_version=event.producer_version,
            producer_instance_id=event.producer_instance_id,
            recorded_at=recorded_at,
        )

    def append(self, activity: Activity) -> StoredActivity:
        """Compatibility helper for existing internal callers and tests."""
        event = CanonicalEvent(
            event_id=str(uuid.uuid4()),
            schema_version=1,
            event_type=activity.activity_type,
            producer_name="pulse-internal-legacy",
            producer_version=None,
            producer_instance_id=None,
            occurred_at=activity.occurred_at,
            details=activity.details,
        )
        return self.append_event(
            IngestedEvent(
                event=event,
                activity=activity,
                fingerprint=canonical_event_fingerprint(event),
                legacy=True,
            )
        )

    def activities_between(self, start: datetime, end: datetime) -> list[StoredActivity]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT * FROM activities
                WHERE occurred_at_utc >= ?
                  AND occurred_at_utc < ?
                ORDER BY occurred_at_utc ASC, id ASC
                """,
                (utc_lexical(start), utc_lexical(end)),
            ).fetchall()
        return [self._row_to_stored_activity(row) for row in rows]

    def activity_dates(self, local_timezone: tzinfo) -> list[date]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT occurred_at FROM activities"
            ).fetchall()
        return sorted(
            {
                datetime.fromisoformat(row["occurred_at"])
                .astimezone(local_timezone)
                .date()
                for row in rows
            },
            reverse=True,
        )

    def latest_activity_of_type(
        self,
        activity_type: str,
        *,
        before: datetime,
        workspace_root: str | None = None,
    ) -> StoredActivity | None:
        """Most recent activity of ``activity_type`` occurred at or before ``before``.

        Read-only lookup without a window: the Context API needs the last
        ``agent_session`` even when it predates the requested window. The
        upper bound keeps the answer deterministic for a fixed reference
        instant — rows appended later, dated after it, never change it.
        """
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT * FROM activities
                WHERE type = ?
                  AND occurred_at_utc <= ?
                  AND (? IS NULL OR
                       CASE json_type(details_json, '$.workspace')
                         WHEN 'text' THEN rtrim(json_extract(details_json, '$.workspace'), '/')
                         ELSE rtrim(json_extract(details_json, '$.workspace.workspace_root'), '/')
                       END IS NULL OR
                       CASE json_type(details_json, '$.workspace')
                         WHEN 'text' THEN rtrim(json_extract(details_json, '$.workspace'), '/')
                         ELSE rtrim(json_extract(details_json, '$.workspace.workspace_root'), '/')
                       END = rtrim(?, '/'))
                ORDER BY occurred_at_utc DESC, id DESC
                LIMIT 1
                """,
                (activity_type, utc_lexical(before), workspace_root, workspace_root),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_stored_activity(row)

    def activity_by_event_id(self, event_id: str) -> StoredActivity | None:
        """One stored row by its producer ``event_id``, or ``None``.

        Read-only lookup for a consumer recovering its own state (audit
        2026-09-06, defect 3): the row exactly as written, never a
        reconstruction.
        """
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM activities WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_stored_activity(row)

    def latest_activity_id(self) -> int:
        """Watermark for append-only caches: MAX(id), 0 on an empty store."""
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT MAX(id) FROM activities").fetchone()
        return int(row[0]) if row[0] is not None else 0

    def occurred_at_since(self, rowid: int) -> list[datetime]:
        """Timestamps of rows appended after the given watermark id."""
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT occurred_at FROM activities WHERE id > ?",
                (rowid,),
            ).fetchall()
        return [datetime.fromisoformat(row["occurred_at"]) for row in rows]

    @staticmethod
    def _row_to_stored_activity(row: sqlite3.Row) -> StoredActivity:
        event_type = row["type"] or row["activity_type"]
        activity = Activity(
            activity_type=event_type,
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            source=row["source"],
            summary=row["summary"],
            details=json.loads(row["details_json"]),
        )
        return StoredActivity(
            id=row["id"],
            activity=activity,
            event_id=row["event_id"],
            schema_version=row["schema_version"],
            producer_name=row["producer_name"],
            producer_version=row["producer_version"],
            producer_instance_id=row["producer_instance_id"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
        )
