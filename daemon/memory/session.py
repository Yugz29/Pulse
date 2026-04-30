import json
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.core.event_bus import Event
from daemon.core.file_classifier import file_signal_significance
from daemon.core.uid import new_uid
from daemon.runtime_state import PresentState
from daemon.memory.session_snapshot_builder import (
    build_session_snapshot as build_structured_session_snapshot,
    session_snapshot_to_legacy_dict,
)

_SESSION_TIMING_IGNORED_EVENT_TYPES = {
    "screen_locked",
    "screen_unlocked",
}

_FILE_EVENT_TYPES = {"file_created", "file_modified", "file_renamed", "file_deleted", "file_change"}
_APP_EVENT_TYPES = {"app_activated", "app_switch"}


class SessionMemory:
    """Persiste la session courante dans SQLite (tables: sessions, events)."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        self.db_path = Path(db_path or (Path.home() / ".pulse" / "session.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or new_uid()
        self.started_at = datetime.now()
        self._latest_observed_at: datetime | None = None
        self._has_observed_activity = False
        self._lock = threading.Lock()

        self._init_db()
        self._repair_stale_open_rows()
        self._ensure_current_session()

    def new_session(
        self,
        *,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
        close_reason: str = "session_end",
    ) -> None:
        """Clôture la session courante et en démarre une nouvelle."""
        self.close(ended_at=ended_at, close_reason=close_reason)
        self.session_id = new_uid()
        self.started_at = started_at or datetime.now()
        self._latest_observed_at = self.started_at if started_at is not None else None
        self._has_observed_activity = started_at is not None
        self._ensure_current_session()

    def resume_session(self, *, started_at: datetime) -> None:
        """Ré-aligne la session courante après un redémarrage court du daemon."""
        with self._lock:
            self.started_at = started_at
            if self._latest_observed_at is None or self._latest_observed_at < started_at:
                self._latest_observed_at = started_at
            self._has_observed_activity = True
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE sessions
                    SET started_at = ?,
                        updated_at = CASE
                            WHEN updated_at < ? THEN ?
                            ELSE updated_at
                        END,
                        session_duration_min = ?
                    WHERE id = ?
                    """,
                    (
                        started_at.isoformat(),
                        started_at.isoformat(),
                        started_at.isoformat(),
                        self._duration_min(),
                        self.session_id,
                    ),
                )
                conn.commit()

    def record_event(self, event: Event) -> None:
        payload_json = json.dumps(event.payload, ensure_ascii=True)
        payload_text = self._payload_to_text(event.payload)
        updates_session_timing = event.type not in _SESSION_TIMING_IGNORED_EVENT_TYPES

        with self._lock:
            if updates_session_timing:
                self._observe_timestamp(event.timestamp, bootstrap_if_empty=True)
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO events (session_id, event_type, payload_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self.session_id, event.type, payload_json, event.timestamp.isoformat()),
                )
                try:
                    conn.execute(
                        """
                        INSERT INTO events_fts
                            (rowid, session_id, event_type, payload_text, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (cursor.lastrowid, self.session_id, event.type, payload_text, event.timestamp.isoformat()),
                    )
                except Exception:
                    pass
                if updates_session_timing:
                    self._update_session_from_event(conn, event.timestamp)
                conn.commit()

    def update_present_snapshot(self, present: PresentState, *, signals) -> None:
        """Met à jour les champs de la session courante depuis l'état présent."""
        observed_at = present.updated_at or self._latest_observed_at or datetime.now()
        with self._lock:
            self._observe_timestamp(observed_at, bootstrap_if_empty=False)
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
                        self._effective_updated_at(observed_at).isoformat(),
                        present.session_duration_min,
                        present.active_project,
                        present.active_file,
                        present.probable_task,
                        present.focus_level,
                        getattr(signals, "friction_score", 0.0),
                        self.session_id,
                    ),
                )
                conn.commit()

    def search_events(self, query: str, limit: int = 20, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            if session_id:
                sql = """
                    SELECT e.event_type, e.payload_json, e.created_at, f.session_id
                    FROM events_fts f
                    JOIN events e ON e.id = f.rowid
                    WHERE events_fts MATCH ? AND f.session_id = ?
                    ORDER BY rank LIMIT ?
                """
                params = (query, session_id, limit)
            else:
                sql = """
                    SELECT e.event_type, e.payload_json, e.created_at, f.session_id
                    FROM events_fts f
                    JOIN events e ON e.id = f.rowid
                    WHERE events_fts MATCH ?
                    ORDER BY rank LIMIT ?
                """
                params = (query, limit)
            with self._lock:
                with self._connect() as conn:
                    rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "type": row["event_type"],
                    "payload": json.loads(row["payload_json"]),
                    "timestamp": row["created_at"],
                    "session_id": row["session_id"],
                }
                for row in rows
            ]
        except Exception as exc:
            import logging
            logging.getLogger("pulse").warning("search_events échoué (FTS5?) : %s", exc)
            return []

    def get_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        target_id = session_id or self.session_id
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM sessions WHERE id = ?", (target_id,)).fetchone()
        return dict(row) if row else {}

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT event_type, payload_json, created_at
                    FROM events
                    WHERE session_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (self.session_id, limit),
                ).fetchall()
        result = []
        for row in reversed(rows):
            result.append({
                "type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "timestamp": row["created_at"],
            })
        return result

    def get_recent_sessions(self, limit: int = 8) -> List[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM sessions
                    WHERE ended_at IS NOT NULL
                    ORDER BY ended_at DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._session_row_to_recent_session_payload(dict(row)) for row in rows]

    def get_today_summary(self) -> Dict[str, Any]:
        now = datetime.now()
        day_start = datetime.combine(now.date(), datetime.min.time())
        day_end = day_start + timedelta(days=1)

        with self._lock:
            with self._connect() as conn:
                event_rows = conn.execute(
                    """
                    SELECT event_type, payload_json, created_at
                    FROM events
                    WHERE created_at >= ? AND created_at < ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (day_start.isoformat(), day_end.isoformat()),
                ).fetchall()
                session = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (self.session_id,),
                ).fetchone()

        all_events = []
        work_events = []
        for row in event_rows:
            observed_at = _parse_iso_datetime(row["created_at"])
            if observed_at is None:
                continue
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                payload = {}
            event = {
                "type": row["event_type"],
                "payload": payload,
                "timestamp": observed_at,
            }
            all_events.append(event)
            if self._is_meaningful_work_event(event):
                work_events.append(event)

        windows = self._cluster_work_events(work_events)
        worked_min = sum(window["duration_min"] for window in windows)
        commit_count = self._commit_count_for_period(all_events, since=day_start, until=day_end)

        session_dict = dict(session) if session is not None else {}
        project = session_dict.get("active_project") or self._project_from_events(work_events or all_events)
        task = session_dict.get("probable_task") or "general"
        current_window = None
        if windows:
            last = windows[-1]
            current_window = {
                "id": f"work-{last['started_at']}",
                "started_at": last["started_at"],
                "updated_at": last["ended_at"],
                "project": project,
                "probable_task": task,
                "activity_level": "editing",
                "commit_count": commit_count,
            }

        work_blocks = []
        for index, window in enumerate(windows):
            work_blocks.append(
                {
                    "id": f"work-{window['started_at']}",
                    "started_at": window["started_at"],
                    "ended_at": window["ended_at"],
                    "duration_min": window["duration_min"],
                    "event_count": window["event_count"],
                    "project": project,
                    "probable_task": task,
                }
            )

        projects = []
        if project:
            projects.append(
                {
                    "name": project,
                    "worked_min": worked_min,
                    "active_min": worked_min,
                    "commit_count": commit_count,
                    "top_tasks": [task] if task else [],
                }
            )

        first_activity = windows[0]["started_at"] if windows else None
        last_activity = windows[-1]["ended_at"] if windows else None
        return {
            "date": now.date().isoformat(),
            "generated_at": now.isoformat(),
            "totals": {
                "worked_min": worked_min,
                "active_min": worked_min,
                "commit_count": commit_count,
                "window_count": len(windows),
                "project_count": len(projects),
            },
            "projects": projects,
            "work_blocks": work_blocks,
            "timeline": {
                "first_activity_at": first_activity,
                "last_activity_at": last_activity,
                "current_work_window_started_at": current_window["started_at"] if current_window else None,
            },
            "current_window": current_window,
        }

    def find_file_activity_window(
        self,
        files: List[str],
        *,
        before: datetime,
        lookback_hours: int = 6,
        gap_min: int = 20,
        repo_root: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        wanted_names = {Path(str(file)).name for file in files if Path(str(file)).name}
        if not wanted_names:
            return None

        cutoff = before - timedelta(hours=lookback_hours)
        repo_prefix = str(repo_root or "").rstrip("/")
        file_event_types = ("file_created", "file_modified", "file_renamed", "file_deleted", "file_change")
        placeholders = ",".join("?" for _ in file_event_types)

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT event_type, payload_json, created_at
                    FROM events
                    WHERE event_type IN ({placeholders})
                      AND created_at >= ?
                      AND created_at <= ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (*file_event_types, cutoff.isoformat(), before.isoformat()),
                ).fetchall()

        events: List[datetime] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                continue
            path = str(payload.get("path") or "")
            if not path:
                continue
            if repo_prefix and not (path == repo_prefix or path.startswith(repo_prefix + "/")):
                continue
            if Path(path).name not in wanted_names:
                continue
            if file_signal_significance(path) == "technical_noise":
                continue
            observed_at = _parse_iso_datetime(row["created_at"])
            if observed_at is not None:
                events.append(observed_at)

        if not events:
            return None

        max_gap = timedelta(minutes=gap_min)
        clusters: List[List[datetime]] = []
        current: List[datetime] = []
        for observed_at in events:
            if current and observed_at - current[-1] > max_gap:
                clusters.append(current)
                current = []
            current.append(observed_at)
        if current:
            clusters.append(current)

        cluster = clusters[-1]
        started_at = cluster[0]
        ended_at = cluster[-1]
        return {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_min": max(int((ended_at - started_at).total_seconds() / 60), 0),
            "event_count": len(cluster),
        }

    def build_session_snapshot(self):
        session = self.get_session()
        recent_events = self.get_recent_events(limit=200)
        return build_structured_session_snapshot(
            session=session,
            recent_events=recent_events,
            duration_fallback_min=self._duration_min(),
        )

    def export_session_data(self) -> Dict[str, Any]:
        from daemon.memory.session_snapshot_builder import session_snapshot_to_legacy_dict
        snapshot = self.build_session_snapshot()
        return session_snapshot_to_legacy_dict(snapshot)

    def export_memory_payload(self) -> Dict[str, Any]:
        """
        Construit le payload mémoire depuis les tables sessions + events.
        Remplace l'ancien système episodes/work_windows.
        """
        session = self.get_session()
        recent_events = self.get_recent_events(limit=200)

        # Extraire fichiers distincts depuis les events fichiers
        file_paths: List[str] = []
        seen_paths: set = set()
        for ev in recent_events:
            if ev["type"] in _FILE_EVENT_TYPES and ev["type"] != "file_deleted":
                path = ev["payload"].get("path", "")
                if path and path not in seen_paths and file_signal_significance(path) == "meaningful":
                    seen_paths.add(path)
                    file_paths.append(path)

        # Extraire apps récentes
        app_names: List[str] = []
        seen_apps: set = set()
        for ev in recent_events:
            if ev["type"] in _APP_EVENT_TYPES:
                app = ev["payload"].get("app_name", "")
                if app and app not in seen_apps:
                    seen_apps.add(app)
                    app_names.append(app)

        # Compter les commits via events COMMIT_EDITMSG
        commit_count = sum(
            1 for ev in recent_events
            if ev["type"] in {"file_modified", "file_created"}
            and "COMMIT_EDITMSG" in ev["payload"].get("path", "")
        )

        started_at = session.get("started_at") or self.started_at.isoformat()
        updated_at = session.get("updated_at") or datetime.now().isoformat()
        duration_min = int(session.get("session_duration_min") or 0) or self._duration_min()

        recent_sessions = self.get_recent_sessions(limit=3)
        payload = {
            "started_at": started_at,
            "ended_at": session.get("ended_at"),
            "updated_at": updated_at,
            "duration_min": duration_min,
            "active_project": session.get("active_project"),
            "active_file": session.get("active_file"),
            "probable_task": session.get("probable_task") or "general",
            "focus_level": session.get("focus_level") or "normal",
            "friction_score": float(session.get("friction_score") or 0.0),
            "top_files": file_paths[:10],
            "files_changed": len(seen_paths),
            "recent_apps": app_names[:10],
            "commit_count": commit_count,
            "work_block_started_at": started_at,
            "work_block_commit_count": commit_count,
            "recent_sessions": recent_sessions,
        }
        # Alias legacy pour l'extracteur mémoire et les anciennes ResumeCards.
        payload["work_window_started_at"] = payload["work_block_started_at"]
        payload["work_window_commit_count"] = payload["work_block_commit_count"]
        payload["closed_episodes"] = recent_sessions
        return payload

    def purge_old_events(self, keep_hours: int = 48) -> int:
        cutoff = (datetime.now() - timedelta(hours=keep_hours)).isoformat()
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM events
                    WHERE session_id IN (
                        SELECT id FROM sessions
                        WHERE ended_at IS NOT NULL AND ended_at < ?
                    )
                    """,
                    (cutoff,),
                )
                conn.execute(
                    """
                    DELETE FROM sessions
                    WHERE ended_at IS NOT NULL AND ended_at < ? AND id != ?
                    """,
                    (cutoff, self.session_id),
                )
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
                conn.execute("VACUUM")
                return cursor.rowcount

    def close(self, *, ended_at: Optional[datetime] = None, close_reason: str = "session_end") -> None:
        with self._lock:
            effective_end = ended_at or self._latest_observed_at or datetime.now()
            self._observe_timestamp(effective_end, bootstrap_if_empty=False)
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE sessions
                    SET updated_at = ?, ended_at = ?, session_duration_min = ?
                    WHERE id = ?
                    """,
                    (
                        effective_end.isoformat(),
                        effective_end.isoformat(),
                        self._duration_min(end_at=effective_end),
                        self.session_id,
                    ),
                )
                conn.commit()

    # ── Internals ──────────────────────────────────────────────────────────────

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
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                        session_id UNINDEXED,
                        event_type,
                        payload_text,
                        created_at UNINDEXED,
                        tokenize = 'unicode61'
                    )
                    """
                )
            except Exception as exc:
                import logging
                logging.getLogger("pulse").warning("FTS5 non disponible : %s", exc)
            conn.commit()

    def _repair_stale_open_rows(self) -> None:
        """Ferme les sessions restées ouvertes après un arrêt brutal."""
        with self._lock:
            with self._connect() as conn:
                stale_sessions = conn.execute(
                    "SELECT * FROM sessions WHERE ended_at IS NULL AND id != ? ORDER BY started_at ASC",
                    (self.session_id,),
                ).fetchall()
                if not stale_sessions:
                    return
                for row in stale_sessions:
                    session = dict(row)
                    repair_end = self._session_repair_end(session)
                    if repair_end is None:
                        continue
                    started_at = _parse_iso_datetime(session.get("started_at")) or repair_end
                    duration_min = max(int((repair_end - started_at).total_seconds() / 60), 0)
                    conn.execute(
                        "UPDATE sessions SET updated_at = ?, ended_at = ?, session_duration_min = ? WHERE id = ?",
                        (repair_end.isoformat(), repair_end.isoformat(), duration_min, session["id"]),
                    )
                conn.commit()

    def _ensure_current_session(self) -> None:
        now = self.started_at.isoformat()
        with self._connect() as conn:
            existing = conn.execute("SELECT id FROM sessions WHERE id = ?", (self.session_id,)).fetchone()
            if existing:
                return
            conn.execute(
                "INSERT INTO sessions (id, started_at, updated_at, session_duration_min) VALUES (?, ?, ?, ?)",
                (self.session_id, now, now, 0),
            )
            conn.commit()

    def _update_session_from_event(self, conn: sqlite3.Connection, observed_at: datetime) -> None:
        effective_updated_at = self._effective_updated_at(observed_at)
        conn.execute(
            """
            UPDATE sessions
            SET started_at = ?, updated_at = ?, session_duration_min = ?
            WHERE id = ?
            """,
            (
                self.started_at.isoformat(),
                effective_updated_at.isoformat(),
                self._duration_min(end_at=effective_updated_at),
                self.session_id,
            ),
        )

    @staticmethod
    def _payload_to_text(payload: dict) -> str:
        parts = []
        for v in payload.values():
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        return " ".join(parts)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _duration_min(self, *, end_at: Optional[datetime] = None) -> int:
        effective_end = end_at or self._latest_observed_at or datetime.now()
        delta_seconds = (effective_end - self.started_at).total_seconds()
        return max(int(delta_seconds / 60), 0)

    def _observe_timestamp(self, observed_at: datetime, *, bootstrap_if_empty: bool) -> None:
        if bootstrap_if_empty and not self._has_observed_activity:
            self.started_at = observed_at
            self._latest_observed_at = observed_at
            self._has_observed_activity = True
            return
        if observed_at < self.started_at:
            self.started_at = observed_at
        if self._latest_observed_at is None or observed_at > self._latest_observed_at:
            self._latest_observed_at = observed_at
        if bootstrap_if_empty:
            self._has_observed_activity = True

    def _effective_updated_at(self, observed_at: Optional[datetime] = None) -> datetime:
        if observed_at is not None and (
            self._latest_observed_at is None or observed_at > self._latest_observed_at
        ):
            return observed_at
        return self._latest_observed_at or observed_at or self.started_at

    @staticmethod
    def _session_repair_end(session: Dict[str, Any]) -> Optional[datetime]:
        updated_at = _parse_iso_datetime(session.get("updated_at"))
        started_at = _parse_iso_datetime(session.get("started_at"))
        if updated_at is not None and started_at is not None:
            return max(updated_at, started_at)
        return updated_at or started_at

    @staticmethod
    def _session_row_to_recent_session_payload(session: Dict[str, Any]) -> Dict[str, Any]:
        started_at = _parse_iso_datetime(session.get("started_at"))
        ended_at = _parse_iso_datetime(session.get("ended_at")) or _parse_iso_datetime(session.get("updated_at"))
        duration_sec = None
        if started_at is not None and ended_at is not None:
            duration_sec = max(int((ended_at - started_at).total_seconds()), 0)
        elif session.get("session_duration_min") is not None:
            duration_sec = max(int(session.get("session_duration_min") or 0), 0) * 60
        return {
            "id": f"session-{session.get('id')}",
            "session_id": session.get("id"),
            "started_at": session.get("started_at"),
            "ended_at": session.get("ended_at") or session.get("updated_at"),
            "boundary_reason": "session_end",
            "duration_sec": duration_sec,
            "active_project": session.get("active_project"),
            "probable_task": session.get("probable_task"),
            "activity_level": None,
            "task_confidence": None,
        }

    @staticmethod
    def _is_meaningful_work_event(event: Dict[str, Any]) -> bool:
        event_type = event["type"]
        if event_type in {"screen_locked", "screen_unlocked", "user_idle"}:
            return False
        if event_type in _FILE_EVENT_TYPES:
            path = str(event["payload"].get("path") or "")
            return bool(path) and file_signal_significance(path) == "meaningful"
        if event_type in {
            "terminal_command_finished",
            "mcp_command_received",
            "claude_desktop_session",
        }:
            return True
        return False

    @staticmethod
    def _cluster_work_events(
        events: List[Dict[str, Any]],
        *,
        gap_min: int = 30,
    ) -> List[Dict[str, Any]]:
        if not events:
            return []
        max_gap = timedelta(minutes=gap_min)
        clusters: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        for event in events:
            if current and event["timestamp"] - current[-1]["timestamp"] > max_gap:
                clusters.append(current)
                current = []
            current.append(event)
        if current:
            clusters.append(current)

        windows = []
        for cluster in clusters:
            started_at = cluster[0]["timestamp"]
            ended_at = cluster[-1]["timestamp"]
            duration_min = max(int((ended_at - started_at).total_seconds() / 60), 1)
            windows.append(
                {
                    "started_at": started_at.isoformat(),
                    "ended_at": ended_at.isoformat(),
                    "duration_min": duration_min,
                    "event_count": len(cluster),
                }
            )
        return windows

    @staticmethod
    def _project_from_events(events: List[Dict[str, Any]]) -> Optional[str]:
        for event in reversed(events):
            payload = event["payload"]
            for key in ("project", "active_project", "terminal_project"):
                value = payload.get(key)
                if value:
                    return str(value)
            path = payload.get("path")
            if path:
                parts = Path(str(path)).parts
                if "Projets" in parts:
                    idx = parts.index("Projets")
                    if idx + 1 < len(parts):
                        return parts[idx + 1]
        return None

    @classmethod
    def _commit_count_for_period(
        cls,
        events: List[Dict[str, Any]],
        *,
        since: datetime,
        until: datetime,
    ) -> int:
        event_count = cls._commit_event_count(events)
        git_hashes: set[str] = set()
        for root in cls._git_roots_from_events(events):
            try:
                result = subprocess.run(
                    [
                        "git",
                        "log",
                        f"--since={since.isoformat()}",
                        f"--until={until.isoformat()}",
                        "--format=%H",
                    ],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
            except Exception:
                continue
            if result.returncode != 0:
                continue
            git_hashes.update(line.strip() for line in result.stdout.splitlines() if line.strip())
        return max(event_count, len(git_hashes))

    @staticmethod
    def _commit_event_count(events: List[Dict[str, Any]]) -> int:
        count = 0
        for event in events:
            payload = event["payload"]
            if event["type"] in {"file_modified", "file_created"}:
                path = str(payload.get("path") or "")
                if "COMMIT_EDITMSG" in path:
                    count += 1
                    continue
            if event["type"] == "terminal_command_finished":
                command = str(payload.get("terminal_command") or "")
                base = str(payload.get("terminal_command_base") or "")
                success = payload.get("terminal_success")
                if success is not False and base == "git" and " commit" in f" {command} ":
                    count += 1
        return count

    @staticmethod
    def _git_roots_from_events(events: List[Dict[str, Any]], *, limit: int = 5) -> List[Path]:
        roots: List[Path] = []
        seen: set[str] = set()
        for event in events:
            payload = event["payload"]
            candidates = [
                payload.get("path"),
                payload.get("repo_root"),
                payload.get("project_root"),
                payload.get("terminal_workspace_root"),
                payload.get("terminal_cwd"),
                payload.get("cwd"),
            ]
            for raw in candidates:
                root = _find_git_root_from_path(raw)
                if root is None:
                    continue
                key = str(root)
                if key in seen:
                    continue
                seen.add(key)
                roots.append(root)
                if len(roots) >= limit:
                    return roots
        return roots


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _find_git_root_from_path(value: Any) -> Optional[Path]:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    search = path if path.suffix == "" else path.parent
    for candidate in (search, *search.parents):
        marker = candidate / ".git"
        if marker.exists():
            return candidate
    return None
