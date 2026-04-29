import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.core.contracts import ConsolidatedEpisode, Episode, SessionSnapshot
from daemon.core.event_bus import Event
from daemon.core.signal_scorer import Signals
from daemon.core.uid import new_uid
from daemon.runtime_state import PresentState
from daemon.memory.session_snapshot_builder import (
    build_session_snapshot as build_structured_session_snapshot,
    session_snapshot_to_legacy_dict,
)

WORKED_IDLE_GRACE_MIN = 15
_SESSION_TIMING_IGNORED_EVENT_TYPES = {
    "screen_locked",
    "screen_unlocked",
}


class SessionMemory:
    """Persiste la session courante dans SQLite."""

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
        self._backfill_work_windows_if_needed()

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
        """
        Ré-aligne la session courante après un redémarrage court du daemon.

        Contrairement à new_session(), on conserve le même session_id:
        on corrige simplement la fenêtre temporelle de la session live
        pour que les exports mémoire et le journal restent cohérents.
        """
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
                    (
                        self.session_id,
                        event.type,
                        payload_json,
                        event.timestamp.isoformat(),
                    ),
                )
                # Indexe dans FTS5 si la table existe
                try:
                    conn.execute(
                        """
                        INSERT INTO events_fts
                            (rowid, session_id, event_type, payload_text, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            cursor.lastrowid,
                            self.session_id,
                            event.type,
                            payload_text,
                            event.timestamp.isoformat(),
                        ),
                    )
                except Exception:
                    pass  # FTS5 indisponible — on continue sans planter
                if updates_session_timing:
                    self._update_session_from_event(conn, event.timestamp)
                conn.commit()

    def update_present_snapshot(
        self,
        present: PresentState,
        *,
        signals: Signals,
    ) -> None:
        duration = present.session_duration_min
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
                        duration,
                        present.active_project,
                        present.active_file,
                        present.probable_task,
                        present.focus_level,
                        signals.friction_score,
                        self.session_id,
                    ),
                )
                self._sync_work_window(
                    conn,
                    session_id=self.session_id,
                    started_at=self.started_at,
                    observed_at=self._effective_updated_at(observed_at),
                    active_project=present.active_project,
                    probable_task=present.probable_task,
                    activity_level=present.activity_level,
                    task_confidence=getattr(signals, "task_confidence", None),
                    allow_create=(present.session_status == "active"),
                )
                conn.commit()

    def search_events(
        self,
        query: str,
        limit: int = 20,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recherche FTS5 sur l'historique des events.
        Retourne les résultats triés par pertinence (rank FTS5).
        Si session_id est fourni, filtre sur cette session uniquement.
        """
        try:
            if session_id:
                sql = """
                    SELECT e.event_type, e.payload_json, e.created_at, f.session_id
                    FROM events_fts f
                    JOIN events e ON e.id = f.rowid
                    WHERE events_fts MATCH ? AND f.session_id = ?
                    ORDER BY rank
                    LIMIT ?
                """
                params = (query, session_id, limit)
            else:
                sql = """
                    SELECT e.event_type, e.payload_json, e.created_at, f.session_id
                    FROM events_fts f
                    JOIN events e ON e.id = f.rowid
                    WHERE events_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """
                params = (query, limit)

            with self._lock:
                with self._connect() as conn:
                    rows = conn.execute(sql, params).fetchall()

            return [
                {
                    "type":       row["event_type"],
                    "payload":    json.loads(row["payload_json"]),
                    "timestamp":  row["created_at"],
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
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (target_id,),
                ).fetchone()
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
            result.append(
                {
                    "type": row["event_type"],
                    "payload": json.loads(row["payload_json"]),
                    "timestamp": row["created_at"],
                }
            )
        return result

    def build_session_snapshot(self) -> SessionSnapshot:
        session = self.get_session()
        recent_events = self.get_recent_events(limit=200)
        return build_structured_session_snapshot(
            session=session,
            recent_events=recent_events,
            duration_fallback_min=self._duration_min(),
        )

    def export_session_data(self) -> Dict[str, Any]:
        snapshot = self.build_session_snapshot()
        return session_snapshot_to_legacy_dict(snapshot)

    def export_memory_payload(self, *, closed_episode_limit: int = 8) -> Dict[str, Any]:
        payload = self.export_session_data()
        with self._lock:
            with self._connect() as conn:
                row = self._get_latest_work_window_row(conn, session_id=self.session_id)
        if row is not None:
            payload["work_window_started_at"] = row["started_at"]
            payload["work_window_ended_at"] = row["ended_at"] or row["updated_at"]
            payload["work_window_status"] = row["status"]
            payload["work_window_commit_count"] = int(row["commit_count"] or 0)
            payload["work_window_active_sec"] = int(
                row["active_sec"] if row["active_sec"] is not None else int(row["active_min"] or 0) * 60
            )
        else:
            payload["work_window_started_at"] = payload.get("started_at")
            payload["work_window_ended_at"] = payload.get("updated_at") or payload.get("ended_at")
        payload["closed_episodes"] = [
            asdict(episode)
            for episode in self.get_recent_closed_episodes(limit=closed_episode_limit)
        ]
        return payload

    def save_episode(self, episode: Episode) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO episodes (
                        id, session_id, started_at, ended_at, boundary_reason, duration_sec,
                        active_project, probable_task, activity_level, task_confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        session_id = excluded.session_id,
                        started_at = excluded.started_at,
                        ended_at = excluded.ended_at,
                        boundary_reason = excluded.boundary_reason,
                        duration_sec = excluded.duration_sec,
                        active_project = excluded.active_project,
                        probable_task = excluded.probable_task,
                        activity_level = excluded.activity_level,
                        task_confidence = excluded.task_confidence
                    """,
                    (
                        episode.id,
                        episode.session_id,
                        episode.started_at,
                        episode.ended_at,
                        episode.boundary_reason,
                        episode.duration_sec,
                        episode.active_project,
                        episode.probable_task,
                        episode.activity_level,
                        episode.task_confidence,
                    ),
                )
                conn.commit()

    def get_current_episode(self, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        target_id = session_id or self.session_id
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT *
                    FROM episodes
                    WHERE session_id = ? AND ended_at IS NULL
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (target_id,),
                ).fetchone()
        return dict(row) if row else None

    def get_recent_episodes(
        self,
        *,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        target_id = session_id or self.session_id
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM episodes
                    WHERE session_id = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (target_id, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_closed_episodes(
        self,
        *,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[ConsolidatedEpisode]:
        target_id = session_id or self.session_id
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM episodes
                    WHERE session_id = ? AND ended_at IS NOT NULL
                    ORDER BY ended_at DESC, started_at DESC
                    LIMIT ?
                    """,
                    (target_id, limit),
                ).fetchall()

                # Fallback cross-session : après un redémarrage du daemon,
                # la session courante n'a aucun épisode clos. On lit les plus
                # récents toutes sessions confondues pour que le premier commit
                # post-redémarrage ait accès au contexte réel.
                if not rows:
                    rows = conn.execute(
                        """
                        SELECT *
                        FROM episodes
                        WHERE ended_at IS NOT NULL
                        ORDER BY ended_at DESC, started_at DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
        return [
            ConsolidatedEpisode(
                episode_id=row["id"],
                session_id=row["session_id"],
                active_project=row["active_project"],
                probable_task=row["probable_task"],
                activity_level=row["activity_level"],
                task_confidence=row["task_confidence"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                duration_sec=row["duration_sec"],
                boundary_reason=row["boundary_reason"],
            )
            for row in rows
        ]

    def purge_old_events(self, keep_hours: int = 48) -> int:
        """
        Purge les events plus vieux que keep_hours.
        Ne touche pas à la session courante.
        Retourne le nombre de lignes supprimées.
        Appeler au démarrage du daemon pour garder session.db compact.
        """
        cutoff = (datetime.now() - timedelta(hours=keep_hours)).isoformat()
        with self._lock:
            with self._connect() as conn:
                # Purge les events des sessions terminées (ended_at non null)
                # dont la fin est antérieure au cutoff.
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
                # Purge aussi les sessions elles-mêmes (sans events orphelins)
                conn.execute(
                    """
                    DELETE FROM sessions
                    WHERE ended_at IS NOT NULL
                    AND ended_at < ?
                    AND id != ?
                    """,
                    (cutoff, self.session_id),
                )
                # Purge les épisodes clos associés aux sessions supprimées
                conn.execute(
                    """
                    DELETE FROM episodes
                    WHERE ended_at IS NOT NULL
                    AND ended_at < ?
                    AND session_id != ?
                    """,
                    (cutoff, self.session_id),
                )
                conn.execute(
                    """
                    DELETE FROM work_windows
                    WHERE status = 'closed'
                    AND ended_at IS NOT NULL
                    AND ended_at < ?
                    AND session_id != ?
                    """,
                    (cutoff, self.session_id),
                )
                # Compacte la base après une purge importante
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
                conn.execute("VACUUM")
                return cursor.rowcount

    def close(self, *, ended_at: Optional[datetime] = None, close_reason: str = "session_end") -> None:
        with self._lock:
            effective_end = ended_at or self._latest_observed_at or datetime.now()
            self._observe_timestamp(effective_end, bootstrap_if_empty=False)
            with self._connect() as conn:
                self._close_work_window(
                    conn,
                    session_id=self.session_id,
                    ended_at=effective_end,
                    close_reason=close_reason,
                )
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

    def note_commit_for_current_work_window(
        self,
        *,
        when: Optional[datetime] = None,
        session_id: Optional[str] = None,
    ) -> None:
        target_id = session_id or self.session_id
        commit_at = when or datetime.now()
        with self._lock:
            with self._connect() as conn:
                row = self._get_open_work_window_row(conn, session_id=target_id)
                if row is None:
                    return
                previous_updated_at = _parse_iso_datetime(row["updated_at"]) or commit_at
                started_at = _parse_iso_datetime(row["started_at"]) or commit_at
                updated_at = max(previous_updated_at, commit_at)
                active_min = int(row["active_min"] or 0)
                active_sec = int(
                    row["active_sec"] if row["active_sec"] is not None else active_min * 60
                )
                if updated_at > previous_updated_at:
                    active_sec += max(int((updated_at - previous_updated_at).total_seconds()), 0)
                max_worked_sec = max(int((updated_at - started_at).total_seconds()), 0)
                active_sec = min(active_sec, max_worked_sec)
                active_min = self._seconds_to_minutes(active_sec)
                conn.execute(
                    """
                    UPDATE work_windows
                    SET updated_at = ?,
                        active_sec = ?,
                        active_min = ?,
                        commit_count = COALESCE(commit_count, 0) + 1
                    WHERE id = ?
                    """,
                    (updated_at.isoformat(), active_sec, active_min, row["id"]),
                )
                conn.commit()

    def rollover_work_window(
        self,
        *,
        ended_at: datetime,
        next_started_at: datetime,
        close_reason: str,
        session_id: Optional[str] = None,
        active_project: Optional[str] = None,
        probable_task: Optional[str] = None,
        activity_level: Optional[str] = None,
        task_confidence: Optional[float] = None,
    ) -> None:
        target_id = session_id or self.session_id
        with self._lock:
            with self._connect() as conn:
                self._close_work_window(
                    conn,
                    session_id=target_id,
                    ended_at=ended_at,
                    close_reason=close_reason,
                )
                self._sync_work_window(
                    conn,
                    session_id=target_id,
                    started_at=next_started_at,
                    observed_at=next_started_at,
                    active_project=active_project,
                    probable_task=probable_task,
                    activity_level=activity_level,
                    task_confidence=task_confidence,
                    allow_create=True,
                )
                conn.commit()

    def get_today_summary(self, *, now: Optional[datetime] = None) -> Dict[str, Any]:
        current_time = now or datetime.now()
        day_start = datetime.combine(current_time.date(), time.min)
        day_end = min(datetime.combine(current_time.date(), time.max), current_time)
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM work_windows
                    WHERE started_at <= ?
                      AND COALESCE(ended_at, updated_at) >= ?
                    ORDER BY started_at ASC
                    """,
                    (day_end.isoformat(), day_start.isoformat()),
                ).fetchall()

        windows = [dict(row) for row in rows]
        totals = {
            "worked_min": 0,
            "active_min": 0,
            "commit_count": 0,
            "window_count": 0,
            "project_count": 0,
        }
        projects: dict[str, dict[str, Any]] = {}
        first_activity_at: Optional[datetime] = None
        last_activity_at: Optional[datetime] = None
        current_window_payload: Optional[Dict[str, Any]] = None

        for window in windows:
            overlap = self._window_overlap(window, day_start=day_start, day_end=day_end)
            if overlap is None:
                continue

            active_min = overlap["active_min"]
            worked_min = self._counted_worked_minutes(overlap["worked_min"], active_min)
            totals["worked_min"] += worked_min
            totals["active_min"] += active_min
            totals["commit_count"] += int(window.get("commit_count") or 0)
            totals["window_count"] += 1

            overlap_started = overlap["started_at"]
            overlap_ended = overlap["ended_at"]
            if first_activity_at is None or overlap_started < first_activity_at:
                first_activity_at = overlap_started
            if last_activity_at is None or overlap_ended > last_activity_at:
                last_activity_at = overlap_ended

            project_name = str(window.get("active_project") or "inconnu")
            project_entry = projects.setdefault(
                project_name,
                {
                    "name": project_name,
                    "worked_min": 0,
                    "active_min": 0,
                    "commit_count": 0,
                    "top_tasks": {},
                },
            )
            project_entry["worked_min"] += worked_min
            project_entry["active_min"] += active_min
            project_entry["commit_count"] += int(window.get("commit_count") or 0)
            task_name = str(window.get("probable_task") or "general")
            project_entry["top_tasks"][task_name] = project_entry["top_tasks"].get(task_name, 0) + worked_min

            if str(window.get("status") or "") == "open":
                current_window_payload = {
                    "id": window.get("id"),
                    "started_at": overlap_started.isoformat(),
                    "updated_at": overlap_ended.isoformat(),
                    "project": window.get("active_project"),
                    "probable_task": window.get("probable_task"),
                    "activity_level": window.get("activity_level"),
                    "commit_count": int(window.get("commit_count") or 0),
                }

        project_payload = []
        for item in projects.values():
            tasks = sorted(
                item["top_tasks"].items(),
                key=lambda entry: (-entry[1], entry[0]),
            )
            project_payload.append(
                {
                    "name": item["name"],
                    "worked_min": item["worked_min"],
                    "active_min": item["active_min"],
                    "commit_count": item["commit_count"],
                    "top_tasks": [name for name, _ in tasks[:3]],
                }
            )
        project_payload.sort(key=lambda item: (-item["worked_min"], item["name"]))
        totals["project_count"] = len(project_payload)

        return {
            "date": current_time.date().isoformat(),
            "generated_at": current_time.isoformat(),
            "totals": totals,
            "projects": project_payload,
            "timeline": {
                "first_activity_at": first_activity_at.isoformat() if first_activity_at else None,
                "last_activity_at": last_activity_at.isoformat() if last_activity_at else None,
                "current_work_window_started_at": (
                    current_window_payload["started_at"] if current_window_payload else None
                ),
            },
            "current_window": current_window_payload,
        }

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    boundary_reason TEXT,
                    duration_sec INTEGER,
                    active_project TEXT,
                    probable_task TEXT,
                    activity_level TEXT,
                    task_confidence REAL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS work_windows (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    close_reason TEXT,
                    active_project TEXT,
                    probable_task TEXT,
                    activity_level TEXT,
                    task_confidence REAL,
                    active_sec INTEGER DEFAULT 0,
                    active_min INTEGER DEFAULT 0,
                    commit_count INTEGER DEFAULT 0,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_work_windows_session_started
                ON work_windows(session_id, started_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_work_windows_status_started
                ON work_windows(status, started_at DESC)
                """
            )
            self._ensure_column(conn, "episodes", "active_project", "TEXT")
            self._ensure_column(conn, "episodes", "probable_task", "TEXT")
            self._ensure_column(conn, "episodes", "activity_level", "TEXT")
            self._ensure_column(conn, "episodes", "task_confidence", "REAL")
            self._ensure_column(conn, "work_windows", "active_project", "TEXT")
            self._ensure_column(conn, "work_windows", "probable_task", "TEXT")
            self._ensure_column(conn, "work_windows", "activity_level", "TEXT")
            self._ensure_column(conn, "work_windows", "task_confidence", "REAL")
            self._ensure_column(conn, "work_windows", "active_sec", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "work_windows", "active_min", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "work_windows", "commit_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "work_windows", "close_reason", "TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_episodes_session_started
                ON episodes(session_id, started_at DESC)
                """
            )
            # Index FTS5 pour la session search.
            # payload_text = valeurs du payload en texte libre (paths, noms d'apps, etc.)
            # session_id et created_at sont UNINDEXED : utiles pour filtrer, pas à tokeniser.
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
            except Exception as exc:  # pragma: no cover — FTS5 indisponible
                import logging
                logging.getLogger("pulse").warning("FTS5 non disponible, session search désactivé : %s", exc)
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

    def _repair_stale_open_rows(self) -> None:
        """
        Répare au démarrage les sessions/épisodes/work_windows restés ouverts
        après un arrêt brutal ou un redémarrage du daemon.

        Important: on ne touche jamais à la session courante en mémoire.
        """
        with self._lock:
            with self._connect() as conn:
                stale_sessions = conn.execute(
                    """
                    SELECT *
                    FROM sessions
                    WHERE ended_at IS NULL
                      AND id != ?
                    ORDER BY started_at ASC
                    """,
                    (self.session_id,),
                ).fetchall()
                if not stale_sessions:
                    return

                for row in stale_sessions:
                    self._repair_open_session_rows(conn, session=dict(row))
                conn.commit()

    def _repair_open_session_rows(
        self,
        conn: sqlite3.Connection,
        *,
        session: Dict[str, Any],
    ) -> None:
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            return

        repair_end = self._session_repair_end(session)
        if repair_end is None:
            return

        started_at = _parse_iso_datetime(session.get("started_at")) or repair_end
        duration_min = max(int((repair_end - started_at).total_seconds() / 60), 0)

        conn.execute(
            """
            UPDATE sessions
            SET updated_at = ?,
                ended_at = ?,
                session_duration_min = ?
            WHERE id = ?
            """,
            (
                repair_end.isoformat(),
                repair_end.isoformat(),
                duration_min,
                session_id,
            ),
        )

        self._repair_open_episodes(
            conn,
            session_id=session_id,
            ended_at=repair_end,
            close_reason="restart_repair",
        )
        self._repair_open_work_windows(
            conn,
            session_id=session_id,
            ended_at=repair_end,
            close_reason="restart_repair",
        )

    def _repair_open_episodes(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        ended_at: datetime,
        close_reason: str,
    ) -> None:
        rows = conn.execute(
            """
            SELECT id, started_at
            FROM episodes
            WHERE session_id = ?
              AND ended_at IS NULL
            ORDER BY started_at ASC
            """,
            (session_id,),
        ).fetchall()
        for row in rows:
            started_at = _parse_iso_datetime(row["started_at"]) or ended_at
            effective_end = max(started_at, ended_at)
            duration_sec = max(int((effective_end - started_at).total_seconds()), 0)
            conn.execute(
                """
                UPDATE episodes
                SET ended_at = ?,
                    boundary_reason = ?,
                    duration_sec = ?
                WHERE id = ?
                """,
                (
                    effective_end.isoformat(),
                    close_reason,
                    duration_sec,
                    row["id"],
                ),
            )

    def _repair_open_work_windows(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        ended_at: datetime,
        close_reason: str,
    ) -> None:
        rows = conn.execute(
            """
            SELECT *
            FROM work_windows
            WHERE session_id = ?
              AND status = 'open'
            ORDER BY started_at ASC
            """,
            (session_id,),
        ).fetchall()
        for row in rows:
            started_at = _parse_iso_datetime(row["started_at"]) or ended_at
            updated_at = _parse_iso_datetime(row["updated_at"]) or started_at
            effective_end = max(started_at, updated_at, ended_at)
            worked_sec = max(int((effective_end - started_at).total_seconds()), 0)
            worked_min = max(int(worked_sec / 60), 0)
            active_sec = int(
                row["active_sec"] if row["active_sec"] is not None else int(row["active_min"] or 0) * 60
            )
            active_sec = min(active_sec, worked_sec)
            active_min = min(self._seconds_to_minutes(active_sec), worked_min)
            conn.execute(
                """
                UPDATE work_windows
                SET updated_at = ?,
                    ended_at = ?,
                    status = 'closed',
                    close_reason = ?,
                    active_sec = ?,
                    active_min = ?
                WHERE id = ?
                """,
                (
                    effective_end.isoformat(),
                    effective_end.isoformat(),
                    close_reason,
                    active_sec,
                    active_min,
                    row["id"],
                ),
            )

    def _backfill_work_windows_if_needed(self) -> None:
        with self._lock:
            with self._connect() as conn:
                sessions = conn.execute(
                    """
                    SELECT s.*
                    FROM sessions s
                    LEFT JOIN work_windows w ON w.session_id = s.id
                    GROUP BY s.id
                    HAVING COUNT(w.id) = 0
                    ORDER BY s.started_at ASC
                    """
                ).fetchall()
                if not sessions:
                    return

                session_rows = [dict(row) for row in sessions]
                for index, session in enumerate(session_rows):
                    next_started_at = None
                    if index + 1 < len(session_rows):
                        next_started_at = _parse_iso_datetime(session_rows[index + 1].get("started_at"))
                    self._backfill_session_work_windows(
                        conn,
                        session=session,
                        next_session_started_at=next_started_at,
                    )
                conn.commit()

    def _backfill_session_work_windows(
        self,
        conn: sqlite3.Connection,
        *,
        session: Dict[str, Any],
        next_session_started_at: Optional[datetime],
    ) -> None:
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            return

        episodes = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM episodes
                WHERE session_id = ?
                ORDER BY started_at ASC, ended_at ASC
                """,
                (session_id,),
            ).fetchall()
        ]

        if not episodes and not self._session_has_backfillable_activity(session):
            return

        session_start = _parse_iso_datetime(session.get("started_at"))
        if session_start is None:
            return
        session_end = self._session_effective_end(
            session=session,
            next_session_started_at=next_session_started_at,
        )
        session_is_open = (
            session.get("ended_at") in (None, "")
            and next_session_started_at is None
        )

        if not episodes:
            window_end = session_end or session_start
            worked_min = max(int((window_end - session_start).total_seconds() / 60), 0)
            active_sec = max(int((window_end - session_start).total_seconds()), 0) if self._session_looks_active(session) else 0
            active_min = self._seconds_to_minutes(active_sec)
            self._insert_backfilled_work_window(
                conn,
                session_id=session_id,
                started_at=session_start,
                updated_at=window_end,
                ended_at=None if session_is_open else window_end,
                status="open" if session_is_open else "closed",
                close_reason=None if session_is_open else "session_end",
                active_project=session.get("active_project"),
                probable_task=session.get("probable_task"),
                activity_level="executing" if active_min > 0 else "idle",
                task_confidence=None,
                active_sec=active_sec,
                active_min=active_min,
                commit_count=0,
            )
            return

        current_window: Dict[str, Any] | None = None
        for episode in episodes:
            episode_started_at = _parse_iso_datetime(episode.get("started_at"))
            if episode_started_at is None:
                continue
            episode_ended_at = _parse_iso_datetime(episode.get("ended_at")) or session_end or episode_started_at
            if current_window is None:
                current_window = self._new_backfilled_window(
                    session_id=session_id,
                    started_at=episode_started_at,
                    active_project=episode.get("active_project") or session.get("active_project"),
                    probable_task=episode.get("probable_task") or session.get("probable_task"),
                    activity_level=episode.get("activity_level"),
                    task_confidence=episode.get("task_confidence"),
                )

            current_window["updated_at"] = max(current_window["updated_at"], episode_ended_at)
            current_window["active_project"] = episode.get("active_project") or current_window["active_project"]
            current_window["probable_task"] = episode.get("probable_task") or current_window["probable_task"]
            current_window["activity_level"] = episode.get("activity_level") or current_window["activity_level"]
            current_window["task_confidence"] = (
                episode.get("task_confidence")
                if episode.get("task_confidence") is not None
                else current_window["task_confidence"]
            )
            if str(episode.get("activity_level") or "") != "idle":
                current_window["active_sec"] += max(
                    int((episode_ended_at - episode_started_at).total_seconds()),
                    0,
                )
            if str(episode.get("boundary_reason") or "") == "commit":
                current_window["commit_count"] += 1

            boundary_reason = str(episode.get("boundary_reason") or "")
            if boundary_reason in {"screen_lock", "idle_timeout", "project_change", "session_end"}:
                self._finalize_backfilled_work_window(
                    conn,
                    window=current_window,
                    ended_at=episode_ended_at,
                    close_reason=boundary_reason,
                    closed=True,
                )
                current_window = None

        if current_window is None:
            return

        final_end = session_end or current_window["updated_at"]
        close_reason = None if session_is_open else "session_end"
        self._finalize_backfilled_work_window(
            conn,
            window=current_window,
            ended_at=final_end,
            close_reason=close_reason,
            closed=not session_is_open,
        )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in existing:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _update_session_from_event(self, conn: sqlite3.Connection, observed_at: datetime) -> None:
        effective_updated_at = self._effective_updated_at(observed_at)
        conn.execute(
            """
            UPDATE sessions
            SET started_at = ?,
                updated_at = ?,
                session_duration_min = ?
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
        """
        Convertit un payload dict en texte libre pour l'index FTS5.
        On extrait uniquement les valeurs string : paths, noms d'apps, etc.
        Les clés JSON ("path", "app_name", …) sont exclues volontairement
        pour éviter le bruit dans les requêtes.
        """
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
    def _session_effective_end(
        *,
        session: Dict[str, Any],
        next_session_started_at: Optional[datetime],
    ) -> Optional[datetime]:
        ended_at = _parse_iso_datetime(session.get("ended_at"))
        updated_at = _parse_iso_datetime(session.get("updated_at"))
        candidates = [dt for dt in (ended_at, updated_at) if dt is not None]
        if next_session_started_at is not None:
            if candidates:
                return min(max(candidates), next_session_started_at)
            return next_session_started_at
        if candidates:
            return max(candidates)
        return _parse_iso_datetime(session.get("started_at"))

    @staticmethod
    def _session_repair_end(session: Dict[str, Any]) -> Optional[datetime]:
        updated_at = _parse_iso_datetime(session.get("updated_at"))
        started_at = _parse_iso_datetime(session.get("started_at"))
        if updated_at is not None and started_at is not None:
            return max(updated_at, started_at)
        return updated_at or started_at

    @staticmethod
    def _session_has_backfillable_activity(session: Dict[str, Any]) -> bool:
        duration = int(session.get("session_duration_min") or 0)
        if duration > 0:
            return True
        if session.get("active_project"):
            return True
        probable_task = str(session.get("probable_task") or "")
        return probable_task not in {"", "general"}

    @staticmethod
    def _session_looks_active(session: Dict[str, Any]) -> bool:
        probable_task = str(session.get("probable_task") or "")
        return probable_task not in {"", "general"}

    @staticmethod
    def _new_backfilled_window(
        *,
        session_id: str,
        started_at: datetime,
        active_project: Optional[str],
        probable_task: Optional[str],
        activity_level: Optional[str],
        task_confidence: Optional[float],
    ) -> Dict[str, Any]:
        return {
            "id": new_uid(),
            "session_id": session_id,
            "started_at": started_at,
            "updated_at": started_at,
            "active_project": active_project,
            "probable_task": probable_task,
            "activity_level": activity_level,
            "task_confidence": task_confidence,
            "active_sec": 0,
            "active_min": 0,
            "commit_count": 0,
        }

    def _finalize_backfilled_work_window(
        self,
        conn: sqlite3.Connection,
        *,
        window: Dict[str, Any],
        ended_at: datetime,
        close_reason: Optional[str],
        closed: bool,
    ) -> None:
        window["updated_at"] = max(window["updated_at"], ended_at)
        worked_min = max(
            int((window["updated_at"] - window["started_at"]).total_seconds() / 60),
            0,
        )
        worked_sec = max(
            int((window["updated_at"] - window["started_at"]).total_seconds()),
            0,
        )
        window["active_sec"] = min(int(window["active_sec"] or 0), worked_sec)
        window["active_min"] = min(self._seconds_to_minutes(window["active_sec"]), worked_min)
        self._insert_backfilled_work_window(
            conn,
            session_id=window["session_id"],
            started_at=window["started_at"],
            updated_at=window["updated_at"],
            ended_at=window["updated_at"] if closed else None,
            status="closed" if closed else "open",
            close_reason=close_reason,
            active_project=window["active_project"],
            probable_task=window["probable_task"],
            activity_level=window["activity_level"],
            task_confidence=window["task_confidence"],
            active_sec=window["active_sec"],
            active_min=window["active_min"],
            commit_count=window["commit_count"],
            work_window_id=window["id"],
        )

    @staticmethod
    def _insert_backfilled_work_window(
        conn: sqlite3.Connection,
        *,
        session_id: str,
        started_at: datetime,
        updated_at: datetime,
        ended_at: Optional[datetime],
        status: str,
        close_reason: Optional[str],
        active_project: Optional[str],
        probable_task: Optional[str],
        activity_level: Optional[str],
        task_confidence: Optional[float],
        active_sec: int,
        active_min: int,
        commit_count: int,
        work_window_id: Optional[str] = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO work_windows (
                id, session_id, started_at, updated_at, ended_at, status, close_reason,
                active_project, probable_task, activity_level, task_confidence, active_sec, active_min, commit_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                work_window_id or new_uid(),
                session_id,
                started_at.isoformat(),
                updated_at.isoformat(),
                ended_at.isoformat() if ended_at is not None else None,
                status,
                close_reason,
                active_project,
                probable_task,
                activity_level,
                task_confidence,
                active_sec,
                active_min,
                commit_count,
            ),
        )

    def _sync_work_window(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        started_at: datetime,
        observed_at: datetime,
        active_project: Optional[str],
        probable_task: Optional[str],
        activity_level: Optional[str],
        task_confidence: Optional[float],
        allow_create: bool,
    ) -> None:
        row = self._get_open_work_window_row(conn, session_id=session_id)
        if row is None and not allow_create:
            return

        if row is None:
            active_sec = 0
            if activity_level and activity_level != "idle":
                active_sec = max(int((observed_at - started_at).total_seconds()), 0)
            active_min = self._seconds_to_minutes(active_sec)
            conn.execute(
                """
                INSERT INTO work_windows (
                    id, session_id, started_at, updated_at, ended_at, status, close_reason,
                    active_project, probable_task, activity_level, task_confidence, active_sec, active_min, commit_count
                ) VALUES (?, ?, ?, ?, NULL, 'open', NULL, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    new_uid(),
                    session_id,
                    started_at.isoformat(),
                    observed_at.isoformat(),
                    active_project,
                    probable_task,
                    activity_level,
                    task_confidence,
                    active_sec,
                    active_min,
                ),
            )
            return

        window_started_at = _parse_iso_datetime(row["started_at"]) or started_at
        previous_updated_at = _parse_iso_datetime(row["updated_at"]) or window_started_at
        effective_updated_at = max(previous_updated_at, observed_at)
        active_sec = int(
            row["active_sec"] if row["active_sec"] is not None else int(row["active_min"] or 0) * 60
        )
        if activity_level and activity_level != "idle" and effective_updated_at > previous_updated_at:
            active_sec += max(int((effective_updated_at - previous_updated_at).total_seconds()), 0)
        max_worked_sec = max(int((effective_updated_at - window_started_at).total_seconds()), 0)
        active_sec = min(active_sec, max_worked_sec)
        active_min = self._seconds_to_minutes(active_sec)

        conn.execute(
            """
            UPDATE work_windows
            SET updated_at = ?,
                active_project = ?,
                probable_task = ?,
                activity_level = ?,
                task_confidence = ?,
                active_sec = ?,
                active_min = ?
            WHERE id = ?
            """,
            (
                effective_updated_at.isoformat(),
                active_project,
                probable_task,
                activity_level,
                task_confidence,
                active_sec,
                active_min,
                row["id"],
            ),
        )

    def _close_work_window(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        ended_at: datetime,
        close_reason: str,
    ) -> None:
        row = self._get_open_work_window_row(conn, session_id=session_id)
        if row is None:
            return

        started_at = _parse_iso_datetime(row["started_at"]) or ended_at
        updated_at = _parse_iso_datetime(row["updated_at"]) or started_at
        effective_end = max(started_at, updated_at, ended_at)
        max_worked_sec = max(int((effective_end - started_at).total_seconds()), 0)
        max_worked_min = max(int((effective_end - started_at).total_seconds() / 60), 0)
        active_sec = min(
            int(row["active_sec"] if row["active_sec"] is not None else int(row["active_min"] or 0) * 60),
            max_worked_sec,
        )
        active_min = min(self._seconds_to_minutes(active_sec), max_worked_min)

        conn.execute(
            """
            UPDATE work_windows
            SET updated_at = ?,
                ended_at = ?,
                status = 'closed',
                close_reason = ?,
                active_sec = ?,
                active_min = ?
            WHERE id = ?
            """,
            (
                effective_end.isoformat(),
                effective_end.isoformat(),
                close_reason,
                active_sec,
                active_min,
                row["id"],
            ),
        )

    @staticmethod
    def _get_open_work_window_row(
        conn: sqlite3.Connection,
        *,
        session_id: str,
    ) -> Optional[sqlite3.Row]:
        return conn.execute(
            """
            SELECT *
            FROM work_windows
            WHERE session_id = ? AND status = 'open'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()

    @staticmethod
    def _get_latest_work_window_row(
        conn: sqlite3.Connection,
        *,
        session_id: str,
    ) -> Optional[sqlite3.Row]:
        return conn.execute(
            """
            SELECT *
            FROM work_windows
            WHERE session_id = ?
            ORDER BY
                CASE WHEN status = 'open' THEN 0 ELSE 1 END,
                COALESCE(ended_at, updated_at) DESC,
                started_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()

    @staticmethod
    def _window_overlap(
        window: Dict[str, Any],
        *,
        day_start: datetime,
        day_end: datetime,
    ) -> Optional[Dict[str, Any]]:
        started_at = _parse_iso_datetime(window.get("started_at"))
        ended_at = _parse_iso_datetime(window.get("ended_at") or window.get("updated_at"))
        if started_at is None or ended_at is None:
            return None
        overlap_start = max(started_at, day_start)
        overlap_end = min(ended_at, day_end)
        if overlap_end <= overlap_start:
            return None

        overlap_sec = max(int((overlap_end - overlap_start).total_seconds()), 0)
        overlap_min = max(int(overlap_sec / 60), 0)
        total_duration_sec = max(int((ended_at - started_at).total_seconds()), 0)
        active_sec = int(window.get("active_sec") or 0)
        if active_sec <= 0 and window.get("active_min") is not None:
            active_sec = int(window.get("active_min") or 0) * 60
        if total_duration_sec > 0 and overlap_sec < total_duration_sec:
            active_sec = int(active_sec * (overlap_sec / total_duration_sec))
        active_sec = min(active_sec, overlap_sec)
        return {
            "started_at": overlap_start,
            "ended_at": overlap_end,
            "worked_min": overlap_min,
            "active_min": min(SessionMemory._seconds_to_minutes(active_sec), overlap_min),
        }

    @staticmethod
    def _counted_worked_minutes(worked_min: int, active_min: int) -> int:
        if worked_min <= 0:
            return 0
        if active_min <= 0:
            return min(worked_min, WORKED_IDLE_GRACE_MIN)
        return min(worked_min, active_min + WORKED_IDLE_GRACE_MIN)

    @staticmethod
    def _seconds_to_minutes(seconds: int) -> int:
        return max(int(seconds / 60), 0)


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
