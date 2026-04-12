"""
MemoryStore — stockage structuré et temporel de la mémoire de Pulse.

Tiers
─────
  ephemeral  : données de la session courante, expire après EPHEMERAL_TTL_HOURS
  session    : faits récents, expire après SESSION_TTL_DAYS sans mise à jour
  persistent : mémoire longue durée, jamais expirée automatiquement

Chaque entrée porte
───────────────────
  created_at / updated_at / expires_at
  source : 'daemon' | 'llm' | 'user'
  topic  : 'project' | 'habit' | 'preference' | 'fact' | 'general'

Limites par tier (caractères)
──────────────────────────────
  ephemeral  :   500
  session    : 1 500
  persistent : 2 200

Sécurité
────────
  Chaque entrée est scannée avant écriture :
  - Unicode invisible (zero-width, etc.)
  - Patterns d'injection de prompt
  - Patterns de credentials / exfiltration
"""

import re
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from daemon.core.uid import new_uid

# ── Limites par tier ──────────────────────────────────────────────────────────
TIER_CHAR_LIMITS: dict[str, int] = {
    "ephemeral":  500,
    "session":    1_500,
    "persistent": 2_200,
}

# ── TTL par tier ──────────────────────────────────────────────────────────────
EPHEMERAL_TTL_HOURS = 4
SESSION_TTL_DAYS    = 7

# ── Patterns de sécurité ──────────────────────────────────────────────────────
_INVISIBLE_UNICODE = re.compile(
    r"[\u200b\u200c\u200d\u2060\ufeff\u00ad\u034f\u115f\u1160\u17b4\u17b5]"
)
_SECURITY_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"system\s+prompt",
    r"disregard\s+(all\s+)?instructions?",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+(a\s+)?(?:different|unrestricted|evil)",
    r"jailbreak",
    r"sk-[A-Za-z0-9]{20,}",              # clés OpenAI-style
    r"password\s*[:=]\s*\S{4,}",
    r"api[_\-]?key\s*[:=]\s*\S{4,}",
    r"(?:token|secret)\s*[:=]\s*\S{4,}",
]]

VALID_TIERS   = {"ephemeral", "session", "persistent"}
VALID_SOURCES = {"daemon", "llm", "user"}
VALID_TOPICS  = {"project", "habit", "preference", "fact", "summary", "general"}


class SecurityError(ValueError):
    pass


class CapacityError(ValueError):
    pass


class MemoryStore:
    """
    Stockage SQLite structuré et temporel de la mémoire de Pulse.
    Thread-safe. Toutes les méthodes publiques acquièrent le lock interne.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (Path.home() / ".pulse" / "memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ── API publique ──────────────────────────────────────────────────────────

    def write(
        self,
        content: str,
        tier: str = "session",
        topic: str = "general",
        source: str = "daemon",
        old_text: Optional[str] = None,
    ) -> dict:
        """
        Écrit ou met à jour une entrée mémoire.

        Si old_text est fourni, remplace l'entrée dont le contenu contient
        ce sous-string (substring matching, comme Hermes).

        Retourne {"ok": True, "id": <id>} ou {"ok": False, "error": <msg>}.
        """
        if tier not in VALID_TIERS:
            return {"ok": False, "error": f"Tier inconnu : {tier}"}

        scan_error = self._security_scan(content)
        if scan_error:
            return {"ok": False, "error": scan_error}

        now        = datetime.now().isoformat()
        expires_at = self._compute_expiry(tier)

        with self._lock:
            with self._connect() as conn:
                if old_text:
                    return self._replace(conn, tier, topic, content, old_text, source, now, expires_at)
                return self._insert(conn, tier, topic, content, source, now, expires_at)

    def remove(self, tier: str, old_text: str) -> dict:
        """
        Supprime l'entrée dont le contenu contient old_text.
        Retourne une erreur si la correspondance est absente ou ambiguë.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id FROM memory_entries WHERE tier = ? AND content LIKE ?",
                    (tier, f"%{old_text}%"),
                ).fetchall()

        if not rows:
            return {"ok": False, "error": f"Aucune entrée contenant '{old_text}'"}
        if len(rows) > 1:
            return {"ok": False, "error": f"Correspondance ambiguë ({len(rows)} entrées) — précise davantage"}

        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM memory_entries WHERE id = ?", (rows[0]["id"],))
                conn.commit()
        return {"ok": True}

    def list_entries(self, tier: Optional[str] = None) -> list[dict]:
        """Retourne toutes les entrées valides (non expirées), triées par tier puis date."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            if tier:
                rows = conn.execute(
                    """SELECT * FROM memory_entries
                       WHERE tier = ? AND (expires_at IS NULL OR expires_at > ?)
                       ORDER BY created_at""",
                    (tier, now),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM memory_entries
                       WHERE expires_at IS NULL OR expires_at > ?
                       ORDER BY tier, created_at""",
                    (now,),
                ).fetchall()
        return [dict(r) for r in rows]

    def render(self, captured_at: Optional[datetime] = None) -> str:
        """
        Rend la mémoire en texte structuré pour le system prompt.

        Format :
          ══ Mémoire Pulse [11 avr 2026 09:32] ══
          [Session — 42% — 634/1500 car.]
          § Projet Pulse actif : daemon Python + UI Swift notch  [il y a 2h]
          § Focus majoritairement en deep work le matin          [il y a 3j]
        """
        entries = self.list_entries()
        if not entries:
            return ""

        cap_str = (captured_at or datetime.now()).strftime("%d %b %Y %H:%M")
        lines   = [f"══ Mémoire Pulse [{cap_str}] ══"]

        tier_labels = {
            "ephemeral":  "Éphémère",
            "session":    "Session",
            "persistent": "Persistant",
        }

        for tier in ("ephemeral", "session", "persistent"):
            tier_entries = [e for e in entries if e["tier"] == tier]
            if not tier_entries:
                continue

            total = sum(len(e["content"]) for e in tier_entries)
            limit = TIER_CHAR_LIMITS[tier]
            pct   = int(total / limit * 100)
            lines.append(f"\n[{tier_labels[tier]} — {pct}% — {total}/{limit} car.]")

            for e in tier_entries:
                age_str = self._age_label(e["created_at"], e["updated_at"])
                lines.append(f"§ {e['content'].strip()}  [{age_str}]")

        return "\n".join(lines)

    def purge_expired(self) -> int:
        """
        Supprime toutes les entrées dont expires_at est dépassé.
        À appeler au démarrage du daemon.
        Retourne le nombre d'entrées supprimées.
        """
        now = datetime.now().isoformat()
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM memory_entries WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (now,),
                )
                conn.commit()
        return cursor.rowcount

    def usage(self) -> dict:
        """Retourne l'usage par tier : chars / limit / pct."""
        entries = self.list_entries()
        return {
            tier: {
                "chars": sum(len(e["content"]) for e in entries if e["tier"] == tier),
                "limit": limit,
                "pct":   round(
                    sum(len(e["content"]) for e in entries if e["tier"] == tier) / limit * 100,
                    1,
                ),
            }
            for tier, limit in TIER_CHAR_LIMITS.items()
        }

    # ── Internes ──────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id               TEXT PRIMARY KEY,
                    tier             TEXT NOT NULL,
                    topic            TEXT NOT NULL DEFAULT 'general',
                    content          TEXT NOT NULL,
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL,
                    last_accessed_at TEXT,
                    expires_at       TEXT,
                    source           TEXT DEFAULT 'daemon'
                )
            """)
            conn.commit()
        self._migrate_legacy_schema()

    def _migrate_legacy_schema(self) -> None:
        """
        Migration du schéma legacy INTEGER AUTOINCREMENT → TEXT PRIMARY KEY.

        Détecte si la colonne `id` est de type INTEGER (ancien schéma) et
        si c'est le cas recopie toutes les lignes avec un UUIDv7 neuf dans
        une table temporaire, puis remplace atomiquement.
        Aucun effet sur un schéma déjà migré.
        """
        with self._connect() as conn:
            cols = conn.execute(
                "PRAGMA table_info(memory_entries)"
            ).fetchall()
            id_col = next((c for c in cols if c["name"] == "id"), None)
            if id_col is None or id_col["type"].upper() != "INTEGER":
                return  # Déjà migré ou table vide

            import logging as _logging
            _logging.getLogger("pulse").warning(
                "MemoryStore : migration schéma legacy INTEGER → TEXT"
            )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_entries_new (
                    id               TEXT PRIMARY KEY,
                    tier             TEXT NOT NULL,
                    topic            TEXT NOT NULL DEFAULT 'general',
                    content          TEXT NOT NULL,
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL,
                    last_accessed_at TEXT,
                    expires_at       TEXT,
                    source           TEXT DEFAULT 'daemon'
                )
            """)

            rows = conn.execute("SELECT * FROM memory_entries").fetchall()
            for row in rows:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO memory_entries_new
                        (id, tier, topic, content, created_at, updated_at,
                         last_accessed_at, expires_at, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_uid(),
                        row["tier"],
                        row["topic"] or "general",
                        row["content"],
                        row["created_at"],
                        row["updated_at"],
                        row["last_accessed_at"],
                        row["expires_at"],
                        row["source"] or "daemon",
                    ),
                )

            conn.execute("DROP TABLE memory_entries")
            conn.execute("ALTER TABLE memory_entries_new RENAME TO memory_entries")
            conn.commit()
            _logging.getLogger("pulse").warning(
                "MemoryStore : migration terminée (%d entrée(s) migrée(s))", len(rows)
            )

    def _insert(self, conn, tier, topic, content, source, now, expires_at) -> dict:
        # Capacité
        err = self._check_capacity(conn, tier, len(content))
        if err:
            return {"ok": False, "error": err}

        # Dédupe exacte
        dup = conn.execute(
            "SELECT id FROM memory_entries WHERE tier = ? AND content = ?",
            (tier, content),
        ).fetchone()
        if dup:
            return {"ok": True, "id": dup["id"], "note": "duplicate_skipped"}

        entry_id = new_uid()
        conn.execute(
            """INSERT INTO memory_entries
               (id, tier, topic, content, created_at, updated_at, expires_at, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, tier, topic, content, now, now, expires_at, source),
        )
        conn.commit()
        return {"ok": True, "id": entry_id}

    def _replace(self, conn, tier, topic, content, old_text, source, now, expires_at) -> dict:
        rows = conn.execute(
            "SELECT id FROM memory_entries WHERE tier = ? AND content LIKE ?",
            (tier, f"%{old_text}%"),
        ).fetchall()

        if not rows:
            return {"ok": False, "error": f"Aucune entrée contenant '{old_text}'"}
        if len(rows) > 1:
            return {"ok": False, "error": f"Correspondance ambiguë ({len(rows)} entrées) — précise davantage"}

        conn.execute(
            """UPDATE memory_entries
               SET content = ?, topic = ?, updated_at = ?, expires_at = ?, source = ?
               WHERE id = ?""",
            (content, topic, now, expires_at, source, rows[0]["id"]),
        )
        conn.commit()
        return {"ok": True, "id": rows[0]["id"]}

    def _check_capacity(self, conn, tier: str, new_chars: int) -> Optional[str]:
        limit = TIER_CHAR_LIMITS.get(tier, 2_200)
        now   = datetime.now().isoformat()
        row   = conn.execute(
            """SELECT COALESCE(SUM(LENGTH(content)), 0) AS total
               FROM memory_entries
               WHERE tier = ? AND (expires_at IS NULL OR expires_at > ?)""",
            (tier, now),
        ).fetchone()
        current = row["total"] if row else 0
        if current + new_chars > limit:
            return (
                f"Mémoire '{tier}' à {current}/{limit} car. "
                f"L'entrée ({new_chars} car.) dépasserait la limite. "
                f"Utilise remove ou replace pour faire de la place."
            )
        return None

    @staticmethod
    def _compute_expiry(tier: str) -> Optional[str]:
        if tier == "ephemeral":
            return (datetime.now() + timedelta(hours=EPHEMERAL_TTL_HOURS)).isoformat()
        if tier == "session":
            return (datetime.now() + timedelta(days=SESSION_TTL_DAYS)).isoformat()
        return None  # persistent → jamais

    @staticmethod
    def _security_scan(content: str) -> Optional[str]:
        if _INVISIBLE_UNICODE.search(content):
            return "Contenu rejeté : caractères Unicode invisibles détectés"
        for pattern in _SECURITY_PATTERNS:
            if pattern.search(content):
                return "Contenu rejeté : pattern suspect (injection ou credential)"
        return None

    @staticmethod
    def _age_label(created_at: str, updated_at: str) -> str:
        try:
            created = datetime.fromisoformat(created_at)
            updated = datetime.fromisoformat(updated_at)
            was_updated = updated_at != created_at  # strings identiques à la création, divergent après replace

            ref   = updated if was_updated else created
            delta = datetime.now() - ref
            mins  = int(delta.total_seconds() / 60)

            if mins < 60:
                age = f"{mins} min"
            elif mins < 1440:
                age = f"{mins // 60}h"
            elif mins < 43_200:
                age = f"{mins // 1440}j"
            else:
                age = f"{mins // 43_200} mois"

            return f"modifié il y a {age}" if was_updated else f"il y a {age}"
        except Exception:
            return "?"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
