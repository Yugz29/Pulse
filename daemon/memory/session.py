import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.core.event_bus import Event
from daemon.core.signal_scorer import Signals


class SessionMemory:
    """Persiste la session courante dans SQLite."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        self.db_path = Path(db_path or (Path.home() / ".pulse" / "session.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or str(uuid.uuid4())
        self.started_at = datetime.now()
        self._lock = threading.Lock()

        self._init_db()
        self._ensure_current_session()

    def record_event(self, event: Event) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO events (session_id, event_type, payload_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        self.session_id,
                        event.type,
                        json.dumps(event.payload, ensure_ascii=True),
                        event.timestamp.isoformat(),
                    ),
                )
                self._update_session_from_event(conn, event)
                conn.commit()

    def update_signals(self, signals: Signals) -> None:
        duration = max(signals.session_duration_min, self._duration_min())

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE sessions
                    SET updated_at = ?,
                        session_duration_min = ?,
                        active_project = ?,
                        active_file = ?,
                        probable_task = ?,
                        focus_level = ?,
                        friction_score = ?
                    WHERE id = ?
                    """,
                    (
                        datetime.now().isoformat(),
                        duration,
                        signals.active_project,
                        signals.active_file,
                        signals.probable_task,
                        signals.focus_level,
                        signals.friction_score,
                        self.session_id,
                    ),
                )
                conn.commit()

    def get_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        target_id = session_id or self.session_id
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (target_id,),
            ).fetchone()
        return dict(row) if row else {}

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_type, payload_json, created_at
                FROM events
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (self.session_id, limit),
            ).fetchall()

        result = []
        for row in reversed(rows):
            result.append(
                {
                    "type": row["event_type"],
                    "payload": json.loads(row["payload_json"]),
                    "timestamp": row["created_at"],
                }
            )
        return result

    def export_session_data(self) -> Dict[str, Any]:
        session = self.get_session()
        recent_events = self.get_recent_events(limit=200)

        apps = []
        files = []
        seen_apps = set()
        max_friction = float(session.get("friction_score") or 0.0)

        for event in recent_events:
            payload = event["payload"]
            if event["type"] in {"app_activated", "app_switch"}:
                app_name = payload.get("app_name")
                if app_name and app_name not in seen_apps:
                    seen_apps.add(app_name)
                    apps.append(app_name)
            if event["type"] in {
                "file_created", "file_modified", "file_renamed", "file_deleted", "file_change"
            }:
                path = payload.get("path")
                if path:
                    files.append(path)

        return {
            "session_id": session.get("id"),
            "started_at": session.get("started_at"),
            "updated_at": session.get("updated_at"),
            "ended_at": session.get("ended_at"),
            "active_project": session.get("active_project"),
            "active_file": session.get("active_file"),
            "probable_task": session.get("probable_task"),
            "focus_level": session.get("focus_level"),
            "duration_min": session.get("session_duration_min") or self._duration_min(),
            "recent_apps": apps[-10:],
            "files_changed": len(set(files)),
            "event_count": len(recent_events),
            "max_friction": max_friction,
        }

    def close(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE sessions
                    SET updated_at = ?, ended_at = ?, session_duration_min = ?
                    WHERE id = ?
                    """,
                    (
                        datetime.now().isoformat(),
                        datetime.now().isoformat(),
                        self._duration_min(),
                        self.session_id,
                    ),
                )
                conn.commit()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ended_at TEXT,
                    session_duration_min INTEGER DEFAULT 0,
                    active_project TEXT,
                    active_file TEXT,
                    probable_task TEXT,
                    focus_level TEXT,
                    friction_score REAL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
                """
            )
            conn.commit()

    def _ensure_current_session(self) -> None:
        now = self.started_at.isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM sessions WHERE id = ?",
                (self.session_id,),
            ).fetchone()
            if existing:
                return
            conn.execute(
                """
                INSERT INTO sessions (
                    id, started_at, updated_at, session_duration_min
                ) VALUES (?, ?, ?, ?)
                """,
                (self.session_id, now, now, 0),
            )
            conn.commit()

    def _update_session_from_event(self, conn: sqlite3.Connection, event: Event) -> None:
        active_file = None
        active_project = None

        if event.type in {
            "file_created", "file_modified", "file_renamed", "file_deleted", "file_change"
        }:
            active_file = event.payload.get("path")
            active_project = self._extract_project(active_file)

        conn.execute(
            """
            UPDATE sessions
            SET updated_at = ?,
                session_duration_min = ?,
                active_project = COALESCE(?, active_project),
                active_file = COALESCE(?, active_file)
            WHERE id = ?
            """,
            (
                datetime.now().isoformat(),
                self._duration_min(),
                active_project,
                active_file,
                self.session_id,
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _duration_min(self) -> int:
        return int((datetime.now() - self.started_at).total_seconds() / 60)

    def _extract_project(self, file_path: Optional[str]) -> Optional[str]:
        if not file_path:
            return None

        parts = file_path.split("/")
        for marker in ("Projets", "Projects", "Developer", "src", "workspace"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        return None
