import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.core.contracts import Episode, SessionSnapshot
from daemon.core.event_bus import Event
from daemon.core.signal_scorer import Signals
from daemon.core.uid import new_uid
from daemon.core.workspace_context import extract_project_name
from daemon.memory.session_snapshot_builder import (
    build_session_snapshot as build_structured_session_snapshot,
    session_snapshot_to_legacy_dict,
)


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
        self._lock = threading.Lock()

        self._init_db()
        self._ensure_current_session()

    def new_session(self) -> None:
        """Clôture la session courante et en démarre une nouvelle."""
        self.close()
        self.session_id = new_uid()
        self.started_at = datetime.now()
        self._ensure_current_session()

    def record_event(self, event: Event) -> None:
        payload_json = json.dumps(event.payload, ensure_ascii=True)
        payload_text = self._payload_to_text(event.payload)

        with self._lock:
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
                self._update_session_from_event(conn, event)
                conn.commit()

    def update_signals(self, signals: Signals) -> None:
        # Signals est la source de vérité pour la durée de session :
        # son horloge (_session_start) est resynchronisée sur chaque frontière
        # de session via reset_session(). self._duration_min() part du démarrage
        # de SessionMemory et peut être gonflé si les deux horloges divergent
        # (ex. update_signals appelé avec signals post-reset avant new_session).
        # Le max() était défensif mais pouvait écrire une durée fausse.
        duration = signals.session_duration_min

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

    def save_episode(self, episode: Episode) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO episodes (
                        id, session_id, started_at, ended_at, boundary_reason, duration_sec,
                        probable_task, activity_level, task_confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        session_id = excluded.session_id,
                        started_at = excluded.started_at,
                        ended_at = excluded.ended_at,
                        boundary_reason = excluded.boundary_reason,
                        duration_sec = excluded.duration_sec,
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
                        episode.probable_task,
                        episode.activity_level,
                        episode.task_confidence,
                    ),
                )
                conn.commit()

    def get_current_episode(self, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        target_id = session_id or self.session_id
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    boundary_reason TEXT,
                    duration_sec INTEGER,
                    probable_task TEXT,
                    activity_level TEXT,
                    task_confidence REAL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
                """
            )
            self._ensure_column(conn, "episodes", "probable_task", "TEXT")
            self._ensure_column(conn, "episodes", "activity_level", "TEXT")
            self._ensure_column(conn, "episodes", "task_confidence", "REAL")
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

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in existing:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _update_session_from_event(self, conn: sqlite3.Connection, event: Event) -> None:
        active_file = None
        active_project = None

        if event.type in {
            "file_created", "file_modified", "file_renamed", "file_deleted", "file_change"
        }:
            path = event.payload.get("path")
            if path and event.type != "file_deleted":
                active_file = path
                active_project = extract_project_name(active_file)

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
        return conn

    def _duration_min(self) -> int:
        return int((datetime.now() - self.started_at).total_seconds() / 60)
