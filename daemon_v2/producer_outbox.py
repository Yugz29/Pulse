"""Durable SQLite outbox for local Pulse Core producers."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis.terminal import (
    is_pasted_prompt_command,
    pasted_prompt_placeholder,
)
from .git_context import read_git_context
from .ingest import filter_terminal_command, normalize_event, redact_command
from .models import CanonicalEvent
from .runtime_config import activities_url
from .workspace_context import read_workspace_context


DEFAULT_PRODUCER_NAME = "pulse-zsh"
DEFAULT_PRODUCER_VERSION = "1.0"
GIT_HOOK_PRODUCER_NAME = "pulse-git-hook"
GIT_HOOK_PRODUCER_VERSION = "1.0"
FILE_WATCHER_PRODUCER_NAME = "pulse-file-watcher"
FILE_WATCHER_PRODUCER_VERSION = "1.0"


@dataclass(frozen=True)
class PendingEvent:
    event_id: str
    payload_json: str
    created_at: str
    attempts: int
    last_attempt_at: str | None
    next_attempt_at: str | None
    last_error: str | None


class ProducerOutbox:
    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = str(database_path or default_outbox_path())
        Path(self.database_path).expanduser().parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        # WAL : 3 producteurs (hook zsh, hook git, observateur Swift) et le
        # worker écrivent ce fichier en parallèle ; en journal DELETE un
        # SQLITE_BUSY à l'enqueue = événement perdu avant la file durable.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT,
                    next_attempt_at TEXT,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_fifo
                    ON events(created_at);

                CREATE TABLE IF NOT EXISTS dead_letters (
                    event_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    error TEXT NOT NULL,
                    http_status INTEGER,
                    response_body TEXT,
                    failed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS producer_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def producer_instance_id(self) -> str:
        # Hot path (once per observed command): plain read, no write lock.
        # The write lock is only taken the very first time, and the re-read
        # inside BEGIN IMMEDIATE keeps concurrent first-runs single-valued.
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM producer_metadata WHERE key = 'instance_id'"
            ).fetchone()
        if row is not None and str(row["value"]).strip():
            return str(row["value"])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM producer_metadata WHERE key = 'instance_id'"
            ).fetchone()
            if row is not None and str(row["value"]).strip():
                return str(row["value"])
            instance_id = str(uuid.uuid4())
            # OR REPLACE: a blank stored value (schema allows it) would make a
            # plain INSERT hit the PK forever, failing every enqueue.
            connection.execute(
                """
                INSERT OR REPLACE INTO producer_metadata(key, value)
                VALUES ('instance_id', ?)
                """,
                (instance_id,),
            )
            return instance_id

    def enqueue_payload(self, payload_json: str, *, created_at: str | None = None) -> str:
        """Persist the exact canonical JSON that the worker will later send."""
        payload = _strict_json_object(payload_json)
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("payload event_id must be a non-empty string")
        timestamp = created_at or utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events(event_id, payload_json, created_at)
                VALUES (?, ?, ?)
                """,
                (event_id, payload_json, timestamp),
            )
        return event_id

    def oldest(self) -> PendingEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM events
                ORDER BY created_at ASC, rowid ASC
                LIMIT 1
                """
            ).fetchone()
        return _pending_from_row(row) if row is not None else None

    def delete(self, event_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM events WHERE event_id = ?",
                (event_id,),
            )

    def mark_retry(
        self,
        event_id: str,
        *,
        attempted_at: datetime,
        next_attempt_at: datetime,
        error: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE events
                SET attempts = attempts + 1,
                    last_attempt_at = ?,
                    next_attempt_at = ?,
                    last_error = ?
                WHERE event_id = ?
                """,
                (
                    attempted_at.isoformat(),
                    next_attempt_at.isoformat(),
                    error,
                    event_id,
                ),
            )

    def move_to_dead_letter(
        self,
        pending: PendingEvent,
        *,
        error: str,
        http_status: int | None,
        response_body: str | None,
        failed_at: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # OR REPLACE: a replayed event that fails again must overwrite its
            # previous dead-letter row, not crash the worker on the PK.
            # The body is capped — it is diagnostic context, not a payload.
            connection.execute(
                """
                INSERT OR REPLACE INTO dead_letters(
                    event_id, payload_json, error,
                    http_status, response_body, failed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    pending.event_id,
                    pending.payload_json,
                    error,
                    http_status,
                    response_body[:4096] if response_body else response_body,
                    failed_at.isoformat(),
                ),
            )
            connection.execute(
                "DELETE FROM events WHERE event_id = ?",
                (pending.event_id,),
            )

    def counts(self) -> tuple[int, int]:
        with self._connect() as connection:
            pending = connection.execute(
                "SELECT COUNT(*) FROM events"
            ).fetchone()[0]
            dead = connection.execute(
                "SELECT COUNT(*) FROM dead_letters"
            ).fetchone()[0]
        return int(pending), int(dead)

    def inspect_dead_letters(self, *, limit: int) -> list[dict[str, Any]]:
        """Return recent dead letters without modifying or replaying them."""
        if limit <= 0:
            raise ValueError("limit must be a strictly positive integer")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, payload_json, error, http_status
                FROM dead_letters
                ORDER BY failed_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        inspected: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = _strict_json_object(row["payload_json"])
                event_type = payload.get("type")
            except (json.JSONDecodeError, TypeError, ValueError):
                event_type = None
            inspected.append(
                {
                    "event_id": row["event_id"],
                    "type": event_type,
                    "last_error": row["error"],
                    "http_status": row["http_status"],
                    "payload_json": row["payload_json"],
                }
            )
        return inspected

    def clear_dead_letters(self, *, http_status: int | None = None) -> int:
        """Delete only dead letters, optionally restricted to one HTTP status."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if http_status is None:
                cursor = connection.execute("DELETE FROM dead_letters")
            else:
                cursor = connection.execute(
                    "DELETE FROM dead_letters WHERE http_status = ?",
                    (http_status,),
                )
            return int(cursor.rowcount)

    def replay_dead_letters(
        self,
        *,
        event_id: str | None = None,
        http_status: int | None = None,
    ) -> int:
        """Move selected dead letters back to the pending queue.

        The replayed event starts a fresh delivery cycle: attempts back to 0,
        no next_attempt_at, and created_at set to now so a replay joins the
        FIFO tail instead of jumping ahead of already-pending events. A
        replay → re-failure cycle is safe: move_to_dead_letter overwrites the
        previous dead-letter row (INSERT OR REPLACE).
        """
        if event_id is not None and http_status is not None:
            raise ValueError("event_id and http_status are mutually exclusive")
        if event_id is not None and not event_id.strip():
            raise ValueError("event_id must be a non-empty string")
        selection = {"event_id": event_id, "http_status": http_status}
        replayed_at = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # OR IGNORE: if the event is somehow already pending again, its
            # dead-letter row is a stale duplicate — dropping it is enough.
            connection.execute(
                """
                INSERT OR IGNORE INTO events(event_id, payload_json, created_at)
                SELECT event_id, payload_json, :replayed_at
                FROM dead_letters
                WHERE (:event_id IS NULL OR event_id = :event_id)
                  AND (:http_status IS NULL OR http_status = :http_status)
                """,
                {**selection, "replayed_at": replayed_at},
            )
            cursor = connection.execute(
                """
                DELETE FROM dead_letters
                WHERE (:event_id IS NULL OR event_id = :event_id)
                  AND (:http_status IS NULL OR http_status = :http_status)
                """,
                selection,
            )
            return int(cursor.rowcount)


def default_outbox_path() -> Path:
    configured = os.environ.get("PULSE_CORE_OUTBOX_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".pulse_core" / "outbox.sqlite3"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_terminal_payload(
    outbox: ProducerOutbox,
    *,
    command: str,
    cwd: str,
    exit_code: int,
    started_at: str,
    finished_at: str,
) -> str | None:
    """Build the final canonical event, redacting before SQLite persistence."""
    filtered_command = filter_terminal_command(command)
    if filtered_command is None:
        return None
    redacted_command = redact_command(filtered_command)
    # Same storage policy as ingestion, applied before SQLite persistence so
    # the full text of a mis-pasted prompt never reaches outbox.db either.
    if exit_code != 0 and is_pasted_prompt_command(redacted_command):
        redacted_command = pasted_prompt_placeholder(redacted_command)
    occurred_at = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    if occurred_at.tzinfo is None:
        raise ValueError("finished_at must include a timezone")
    details: dict[str, Any] = {
        "command": redacted_command,
        "exit_code": exit_code,
        "cwd": cwd,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    git_context = read_git_context(Path(cwd))
    if git_context is not None:
        details["git"] = git_context.as_details()
    workspace_context = read_workspace_context(
        Path(cwd),
        git_context=git_context,
    )
    if workspace_context is not None:
        details["workspace"] = workspace_context.as_details()
    event = CanonicalEvent(
        event_id=str(uuid.uuid4()),
        schema_version=1,
        event_type="terminal_finished",
        producer_name=DEFAULT_PRODUCER_NAME,
        producer_version=DEFAULT_PRODUCER_VERSION,
        producer_instance_id=outbox.producer_instance_id(),
        occurred_at=occurred_at,
        details=details,
    )
    payload: dict[str, Any] = {
        "event_id": event.event_id,
        "schema_version": event.schema_version,
        "type": event.event_type,
        "producer": {
            "name": event.producer_name,
            "version": event.producer_version,
            "instance_id": event.producer_instance_id,
        },
        "occurred_at": event.occurred_at.isoformat(),
        "details": event.details,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def build_file_event_payload(
    outbox: ProducerOutbox,
    *,
    path: str,
    event: str,
    workspace: str,
    occurred_at: datetime,
) -> str:
    """Build the canonical file_changed event for durable outbox persistence.

    Transport decision 2A-révisée: the file watcher enqueues here instead of
    POSTing straight to the daemon, so a stopped daemon no longer loses
    events — same durability contract as the terminal and git producers.
    """
    if occurred_at.tzinfo is None:
        raise ValueError("occurred_at must include a timezone")
    canonical = CanonicalEvent(
        event_id=str(uuid.uuid4()),
        schema_version=1,
        event_type="file_changed",
        producer_name=FILE_WATCHER_PRODUCER_NAME,
        producer_version=FILE_WATCHER_PRODUCER_VERSION,
        producer_instance_id=outbox.producer_instance_id(),
        occurred_at=occurred_at,
        details={"path": path, "event": event, "workspace": workspace},
    )
    payload: dict[str, Any] = {
        "event_id": canonical.event_id,
        "schema_version": canonical.schema_version,
        "type": canonical.event_type,
        "producer": {
            "name": canonical.producer_name,
            "version": canonical.producer_version,
            "instance_id": canonical.producer_instance_id,
        },
        "occurred_at": canonical.occurred_at.isoformat(),
        "details": canonical.details,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def enqueue_file_event(
    outbox: ProducerOutbox,
    *,
    path: str,
    event: str,
    workspace: str,
    occurred_at: datetime | None = None,
) -> str:
    payload = build_file_event_payload(
        outbox,
        path=path,
        event=event,
        workspace=workspace,
        occurred_at=occurred_at or utc_now(),
    )
    return outbox.enqueue_payload(payload)


def build_git_commit_payload(
    outbox: ProducerOutbox,
    *,
    commit_hash: str,
    repository: str,
    git_root: str,
    branch: str,
    message: str,
    occurred_at: str,
    files_changed: int | None = None,
    insertions: int | None = None,
    deletions: int | None = None,
) -> str:
    """Build the canonical git_commit event for durable outbox persistence.

    Intended to run from a post-commit hook, so the source client (terminal,
    an IDE, or any other Git porcelain) never matters: the commit object
    itself is the evidence.
    """
    parsed_occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    if parsed_occurred_at.tzinfo is None:
        raise ValueError("occurred_at must include a timezone")
    details: dict[str, Any] = {
        "commit_hash": commit_hash,
        "repository": repository,
        "git_root": git_root,
        "branch": branch,
        # Same secret shapes as terminal commands; redacted before the
        # payload ever reaches durable storage.
        "message": redact_command(message),
    }
    for key, value in (
        ("files_changed", files_changed),
        ("insertions", insertions),
        ("deletions", deletions),
    ):
        if value is not None:
            details[key] = value
    event = CanonicalEvent(
        event_id=str(uuid.uuid4()),
        schema_version=1,
        event_type="git_commit",
        producer_name=GIT_HOOK_PRODUCER_NAME,
        producer_version=GIT_HOOK_PRODUCER_VERSION,
        producer_instance_id=outbox.producer_instance_id(),
        occurred_at=parsed_occurred_at,
        details=details,
    )
    payload: dict[str, Any] = {
        "event_id": event.event_id,
        "schema_version": event.schema_version,
        "type": event.event_type,
        "producer": {
            "name": event.producer_name,
            "version": event.producer_version,
            "instance_id": event.producer_instance_id,
        },
        "occurred_at": event.occurred_at.isoformat(),
        "details": event.details,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def enqueue_git_commit_input(outbox: ProducerOutbox, raw_input: str) -> str:
    request = _strict_json_object(raw_input)
    required = ("commit_hash", "repository", "git_root", "branch", "message", "occurred_at")
    missing = [key for key in required if key not in request]
    if missing:
        raise ValueError(f"missing git_commit fields: {', '.join(missing)}")
    payload_json = build_git_commit_payload(
        outbox,
        commit_hash=str(request["commit_hash"]),
        repository=str(request["repository"]),
        git_root=str(request["git_root"]),
        branch=str(request["branch"]),
        message=str(request["message"]),
        occurred_at=str(request["occurred_at"]),
        files_changed=request.get("files_changed"),
        insertions=request.get("insertions"),
        deletions=request.get("deletions"),
    )
    return outbox.enqueue_payload(payload_json)


def enqueue_terminal_input(
    outbox: ProducerOutbox,
    raw_input: str,
) -> str | None:
    request = _strict_json_object(raw_input)
    required = ("command", "cwd", "exit_code", "started_at", "finished_at")
    missing = [key for key in required if key not in request]
    if missing:
        raise ValueError(f"missing terminal fields: {', '.join(missing)}")
    payload_json = build_terminal_payload(
        outbox,
        command=str(request["command"]),
        cwd=str(request["cwd"]),
        exit_code=int(request["exit_code"]),
        started_at=str(request["started_at"]),
        finished_at=str(request["finished_at"]),
    )
    if payload_json is None:
        return None
    return outbox.enqueue_payload(payload_json)


def enqueue_json_input(outbox: ProducerOutbox, raw_input: str) -> str:
    """Validate one canonical object, then persist its original JSON exactly."""
    payload = _strict_json_object(raw_input)
    required = {
        "event_id",
        "schema_version",
        "type",
        "producer",
        "occurred_at",
        "details",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"missing canonical fields: {', '.join(missing)}")
    normalize_event(payload)
    return outbox.enqueue_payload(raw_input)


def _strict_json_object(raw: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")

    parsed = json.loads(raw, parse_constant=reject_constant)
    if not isinstance(parsed, dict):
        raise ValueError("JSON payload must be an object")
    return parsed


def _pending_from_row(row: sqlite3.Row) -> PendingEvent:
    return PendingEvent(
        event_id=row["event_id"],
        payload_json=row["payload_json"],
        created_at=row["created_at"],
        attempts=row["attempts"],
        last_attempt_at=row["last_attempt_at"],
        next_attempt_at=row["next_attempt_at"],
        last_error=row["last_error"],
    )


def _http_status(value: str) -> int:
    try:
        status = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "HTTP status must be an integer between 100 and 599"
        ) from exc
    if not 100 <= status <= 599:
        raise argparse.ArgumentTypeError(
            "HTTP status must be an integer between 100 and 599"
        )
    return status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pulse producer outbox")
    parser.add_argument("--database", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "enqueue-terminal",
        help="read terminal observation JSON from stdin and enqueue it",
    )
    subparsers.add_parser(
        "enqueue-json",
        help="validate and enqueue one canonical JSON object from stdin",
    )
    subparsers.add_parser(
        "enqueue-git-commit",
        help="read git commit observation JSON from stdin and enqueue it",
    )
    subparsers.add_parser(
        "instance-id",
        help="print the stable producer instance identifier",
    )
    inspect_parser = subparsers.add_parser(
        "inspect-dead-letter",
        help="show recent dead letters without replaying them",
    )
    inspect_parser.add_argument("--limit", type=int, default=10)
    clear_parser = subparsers.add_parser(
        "clear-dead-letter",
        help="explicitly delete selected dead letters without touching pending events",
    )
    clear_selection = clear_parser.add_mutually_exclusive_group(required=True)
    clear_selection.add_argument("--http-status", type=_http_status)
    clear_selection.add_argument(
        "--all",
        action="store_true",
        help="delete every dead letter",
    )
    replay_parser = subparsers.add_parser(
        "replay-dead-letter",
        help="move selected dead letters back to the pending queue",
    )
    replay_selection = replay_parser.add_mutually_exclusive_group(required=True)
    replay_selection.add_argument("--event-id")
    replay_selection.add_argument("--http-status", type=_http_status)
    replay_selection.add_argument(
        "--all",
        action="store_true",
        help="replay every dead letter",
    )
    subparsers.add_parser("status", help="show pending and dead-letter counts")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    outbox = ProducerOutbox(args.database)
    try:
        if args.command == "enqueue-terminal":
            event_id = enqueue_terminal_input(outbox, sys.stdin.read())
            if event_id:
                print(event_id)
            return
        if args.command == "enqueue-json":
            print(enqueue_json_input(outbox, sys.stdin.read()))
            return
        if args.command == "enqueue-git-commit":
            print(enqueue_git_commit_input(outbox, sys.stdin.read()))
            return
        if args.command == "instance-id":
            print(outbox.producer_instance_id())
            return
        if args.command == "inspect-dead-letter":
            inspected = outbox.inspect_dead_letters(limit=args.limit)
            print(
                json.dumps(
                    inspected,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
            return
        if args.command == "clear-dead-letter":
            deleted = outbox.clear_dead_letters(
                http_status=None if args.all else args.http_status
            )
            print(f"Deleted dead-letters: {deleted}")
            return
        if args.command == "replay-dead-letter":
            replayed = outbox.replay_dead_letters(
                event_id=args.event_id,
                http_status=args.http_status,
            )
            print(f"Replayed dead-letters: {replayed}")
            return
    except Exception as exc:
        print(f"Pulse outbox: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    pending, dead = outbox.counts()
    print("Outbox")
    print(f"{pending} événement{'s' if pending != 1 else ''}")
    print("Dead-letter")
    print(f"{dead} événement{'s' if dead != 1 else ''}")
    print(f"Pending: {pending}")
    print(f"Dead-letter: {dead}")
    print(f"Outbox path: {Path(outbox.database_path).expanduser()}")
    print(f"Worker endpoint: {activities_url()}")


if __name__ == "__main__":
    main()
