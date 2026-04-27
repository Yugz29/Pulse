"""
vector_store.py — Mémoire vectorielle de Pulse
================================================

Stocke des moments observés (sessions, commits, titres de fenêtres, events)
sous forme de vecteurs sémantiques dans SQLite via sqlite-vec.

Permet à Pulse de retrouver des moments similaires par sens, pas par mots-clés.

Modèle d'embedding : nomic-embed-text via Ollama (local, 274 MB)
Backend         : SQLite + sqlite-vec (même base que session.db)

Usage :
    store = VectorStore()
    store.index_text("pytest a échoué sur extractor.py", kind="terminal", project="Pulse")
    results = store.search("bug dans la fusion des sessions", k=5)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import struct
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Chemin de la base vectorielle — séparée de session.db pour ne pas la polluer.
_DEFAULT_DB_PATH = Path.home() / ".pulse" / "vectors.db"

# Dimension du modèle nomic-embed-text
_EMBEDDING_DIM = 768

# Modèle sentence-transformers — tourne directement dans le process Python,
# indépendamment d'Ollama. Pas de conflit avec gemma4.
_EMBED_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"

# Cache du modèle — chargé une seule fois au premier appel.
_model = None
_model_lock = threading.Lock()


def _get_model():
    """Charge le modèle d'embedding une seule fois (lazy loading)."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
            import os
            log.info("Chargement du modèle d'embedding %s…", _EMBED_MODEL_NAME)
            # TRANSFORMERS_OFFLINE=1 après le premier téléchargement
            # pour éviter les vérifications réseau à chaque démarrage.
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "0")
            _model = SentenceTransformer(_EMBED_MODEL_NAME, trust_remote_code=True)
            # Une fois chargé, on passe en mode offline pour les prochains calls.
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            log.info("Modèle d'embedding chargé (mode offline actif).")
        except Exception as exc:
            log.warning("Impossible de charger le modèle d'embedding : %s", exc)
    return _model


def _serialize_vector(vec: list[float]) -> bytes:
    """Sérialise un vecteur float en bytes pour sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


def _embed(text: str) -> Optional[list[float]]:
    """
    Génère un embedding via sentence-transformers (local, sans Ollama).
    Retourne None si le modèle n'est pas disponible.
    """
    model = _get_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    except Exception as exc:
        log.debug("Embedding échoué : %s", exc)
    return None


class VectorStore:
    """
    Mémoire vectorielle de Pulse.

    Chaque entrée est un moment observé avec :
    - text     : le texte source (commit, résumé de session, titre de fenêtre...)
    - kind     : le type ("session", "commit", "window_title", "terminal")
    - project  : le projet associé (ex: "Pulse")
    - metadata : dict JSON libre pour stocker des infos supplémentaires
    - vec      : le vecteur sémantique (768 dimensions)
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Ouvre une connexion SQLite avec sqlite-vec chargé."""
        import sqlite_vec
        conn = sqlite3.connect(str(self._db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    def _init_db(self) -> None:
        """Crée les tables si elles n'existent pas encore."""
        with self._lock:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS moments (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        kind        TEXT NOT NULL,
                        project     TEXT,
                        text        TEXT NOT NULL,
                        metadata    TEXT DEFAULT '{}',
                        created_at  TEXT NOT NULL
                    )
                """)
                # Table vectorielle sqlite-vec
                conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS moments_vec
                    USING vec0(
                        moment_id INTEGER PRIMARY KEY,
                        embedding FLOAT[{_EMBEDDING_DIM}]
                    )
                """)
                conn.commit()
        log.debug("VectorStore initialisé : %s", self._db_path)

    def index_text(
        self,
        text: str,
        kind: str,
        project: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[int]:
        """
        Indexe un texte dans la mémoire vectorielle.

        Args:
            text     : le contenu à indexer
            kind     : "session", "commit", "window_title", "terminal"
            project  : projet associé (ex: "Pulse")
            metadata : infos supplémentaires (fichiers, apps, durée...)

        Returns:
            L'id du moment indexé, ou None si l'embedding a échoué.
        """
        if not text or not text.strip():
            return None

        vec = _embed(text.strip())
        if vec is None:
            log.debug("Embedding ignoré (Ollama indisponible) : %.60s…", text)
            return None

        if len(vec) != _EMBEDDING_DIM:
            log.warning("Dimension inattendue : %d (attendu %d)", len(vec), _EMBEDDING_DIM)
            return None

        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        now = datetime.now().isoformat()

        with self._lock:
            with self._connect() as conn:
                # Déduplication : ne pas réindexer le même texte pour le même projet/kind.
                existing = conn.execute(
                    "SELECT id FROM moments WHERE kind=? AND project IS ? AND text=?",
                    (kind, project, text.strip()),
                ).fetchone()
                if existing:
                    log.debug("Déjà indexé id=%d, ignoré.", existing[0])
                    return existing[0]
                cursor = conn.execute(
                    """
                    INSERT INTO moments (kind, project, text, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (kind, project, text.strip(), meta_json, now),
                )
                moment_id = cursor.lastrowid
                conn.execute(
                    "INSERT INTO moments_vec (moment_id, embedding) VALUES (?, ?)",
                    (moment_id, _serialize_vector(vec)),
                )
                conn.commit()

        log.debug("Indexé [%s/%s] id=%d : %.60s…", kind, project or "?", moment_id, text)
        return moment_id

    def search(
        self,
        query: str,
        k: int = 5,
        kind: Optional[str] = None,
        project: Optional[str] = None,
    ) -> list[dict]:
        """
        Retrouve les k moments les plus proches sémantiquement de la requête.

        Args:
            query   : texte de recherche
            k       : nombre de résultats
            kind    : filtre optionnel sur le type
            project : filtre optionnel sur le projet

        Returns:
            Liste de dicts {id, kind, project, text, metadata, created_at, distance}
            triée par distance croissante (plus proche = plus similaire).
        """
        if not query or not query.strip():
            return []

        vec = _embed(query.strip())
        if vec is None:
            return []

        with self._lock:
            with self._connect() as conn:
                # Recherche vectorielle — sqlite-vec retourne les plus proches
                sql = """
                    SELECT
                        m.id, m.kind, m.project, m.text, m.metadata, m.created_at,
                        v.distance
                    FROM moments_vec v
                    JOIN moments m ON m.id = v.moment_id
                    WHERE v.embedding MATCH ?
                      AND k = ?
                """
                params: list = [_serialize_vector(vec), k * 3]  # marge pour filtrer

                # Filtres appliqués après la recherche vectorielle
                rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            rid, rkind, rproject, rtext, rmeta, rcreated, rdist = row
            if kind and rkind != kind:
                continue
            if project and rproject != project:
                continue
            try:
                meta = json.loads(rmeta or "{}")
            except Exception:
                meta = {}
            results.append({
                "id": rid,
                "kind": rkind,
                "project": rproject,
                "text": rtext,
                "metadata": meta,
                "created_at": rcreated,
                "distance": round(rdist, 4),
            })

        return results[:k]

    def index_journal_entry(self, entry: dict) -> Optional[int]:
        """
        Indexe une entrée de journal de session.
        Construit un texte descriptif depuis les champs de l'entrée.
        """
        parts = []
        if entry.get("commit_message"):
            parts.append(f"Commit : {entry['commit_message']}")
        if entry.get("body"):
            parts.append(entry["body"])
        if entry.get("top_files"):
            parts.append(f"Fichiers : {', '.join(entry['top_files'][:5])}")
        if entry.get("probable_task"):
            parts.append(f"Tâche : {entry['probable_task']}")

        if not parts:
            return None

        text = " | ".join(parts)
        metadata = {
            "duration_min": entry.get("duration_min"),
            "activity_level": entry.get("activity_level"),
            "started_at": entry.get("started_at"),
            "ended_at": entry.get("ended_at"),
            "top_files": entry.get("top_files", []),
            "recent_apps": entry.get("recent_apps", []),
        }

        return self.index_text(
            text=text,
            kind="session",
            project=entry.get("active_project"),
            metadata=metadata,
        )

    def stats(self) -> dict:
        """Retourne des stats sur la base vectorielle."""
        with self._lock:
            with self._connect() as conn:
                total = conn.execute("SELECT COUNT(*) FROM moments").fetchone()[0]
                by_kind = conn.execute(
                    "SELECT kind, COUNT(*) FROM moments GROUP BY kind"
                ).fetchall()
                by_project = conn.execute(
                    "SELECT project, COUNT(*) FROM moments WHERE project IS NOT NULL GROUP BY project"
                ).fetchall()

        return {
            "total": total,
            "by_kind": dict(by_kind),
            "by_project": dict(by_project),
            "db_path": str(self._db_path),
        }

    def close(self) -> None:
        """Rien à fermer — connexions ouvertes/fermées par opération."""
        pass
