"""
facts.py — Moteur de faits utilisateur de Pulse.

Pipeline
────────
  Observation brute → Signal (N occurrences) → Fait consolidé
  Fait → Renforcement / Contradiction → Archivage si confiance < seuil
  Faits accumulés → Compression LLM → Profil utilisateur persistant

Le pipeline est entièrement déterministe jusqu'à la compression finale.
Le LLM ne décide jamais quoi stocker — il compresse seulement des faits
déjà validés par le compteur d'observations.

Intégration
───────────
  • Appelé par extractor.update_memories_from_session() à chaque session
  • Stockage dans facts.db (SQLite local, deux tables : observations + facts)
  • Export human-readable dans ~/.pulse/memory/facts.md
  • Compatible avec MemoryStore pour l'injection dans le contexte LLM

Schéma de confiance
───────────────────
  Création  : 0.50
  +confirm  : min(conf + 0.08, 0.95)
  +contredit: max(conf - 0.12, 0.05)
  decay/jour: max(conf - DECAY_PER_DAY, 0.05)  si pas vu depuis > 3j
  Archive   : conf < ARCHIVE_THRESHOLD → archivé (jamais supprimé)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Seuils et constantes ──────────────────────────────────────────────────────

SIGNAL_THRESHOLD   = 3     # observations → signal (pas encore un fait)
FACT_THRESHOLD     = 5     # observations → fait consolidé
DECAY_START_DAYS   = 3     # jours sans observation avant que le decay commence
DECAY_PER_DAY      = 0.02  # perte de confiance par jour de silence
ARCHIVE_THRESHOLD  = 0.30  # confidence en-dessous → archivé
COMPRESS_THRESHOLD = 6     # faits actifs par catégorie → compression LLM
CONFIDENCE_INIT    = 0.50
CONFIDENCE_MAX     = 0.95
CONFIDENCE_CONFIRM = 0.08
CONFIDENCE_CONTRA  = 0.12

VALID_CATEGORIES = {"environment", "workflow", "cognitive", "preference"}

DEFAULT_DB_PATH = Path.home() / ".pulse" / "facts.db"
DEFAULT_MD_PATH = Path.home() / ".pulse" / "memory" / "facts.md"


# ── FactEngine ────────────────────────────────────────────────────────────────

class FactEngine:
    """
    Moteur principal de gestion des faits utilisateur.
    Thread-safe. Toutes les écritures passent par le lock interne.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        md_path: Optional[Path] = None,
    ) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self.md_path = md_path or DEFAULT_MD_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ── API publique ──────────────────────────────────────────────────────────

    def observe_session(self, session_data: Dict[str, Any]) -> List[str]:
        """
        Point d'entrée principal. Extrait des observations depuis les données
        de session, met à jour les compteurs, et tente une promotion en faits.

        Retourne les IDs des faits nouvellement créés (peut être vide).
        """
        observations = _extract_observations(session_data)
        if not observations:
            return []

        newly_promoted: List[str] = []
        now = datetime.now().isoformat()

        with self._lock:
            with self._connect() as conn:
                for key, category, obs_desc, fact_desc, context in observations:
                    self._upsert_observation(conn, key, category, obs_desc, fact_desc, context, now)

                newly_promoted = self._promote_pending(conn, now)
                conn.commit()

        if newly_promoted:
            self.export_markdown()

        return newly_promoted

    def reinforce(self, fact_id: str) -> Dict[str, Any]:
        """
        Confirme un fait (validation explicite ou action acceptée par l'user).
        Augmente la confiance et incrémente autonomy_level si seuil atteint.
        """
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM facts WHERE id = ? AND archived = 0", (fact_id,)
                ).fetchone()
                if not row:
                    return {"ok": False, "error": "Fait introuvable"}

                new_conf = min(row["confidence"] + CONFIDENCE_CONFIRM, CONFIDENCE_MAX)
                new_confirms = row["confirmations"] + 1
                # Promotion autonomy_level : tous les 5 renforcements
                new_level = min(row["autonomy_level"] + (1 if new_confirms % 5 == 0 else 0), 3)

                conn.execute(
                    """UPDATE facts SET confidence = ?, confirmations = ?,
                       autonomy_level = ?, updated_at = ? WHERE id = ?""",
                    (new_conf, new_confirms, new_level, datetime.now().isoformat(), fact_id),
                )
                conn.commit()

        self.export_markdown()
        return {"ok": True, "confidence": new_conf, "autonomy_level": new_level}

    def contradict(self, fact_id: str) -> Dict[str, Any]:
        """
        Contredit un fait (override manuel, refus d'action, correction).
        Un override compte double — signal plus fort qu'un refus passif.
        """
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM facts WHERE id = ? AND archived = 0", (fact_id,)
                ).fetchone()
                if not row:
                    return {"ok": False, "error": "Fait introuvable"}

                new_conf = max(row["confidence"] - CONFIDENCE_CONTRA, 0.05)
                new_contra = row["contradictions"] + 1
                # Rétrogradation autonomy_level si contradiction
                new_level = max(row["autonomy_level"] - 1, 0)
                archived = 1 if new_conf < ARCHIVE_THRESHOLD else 0

                conn.execute(
                    """UPDATE facts SET confidence = ?, contradictions = ?,
                       autonomy_level = ?, archived = ?, updated_at = ? WHERE id = ?""",
                    (new_conf, new_contra, new_level, archived,
                     datetime.now().isoformat(), fact_id),
                )
                conn.commit()

        self.export_markdown()
        return {"ok": True, "confidence": new_conf, "archived": bool(archived)}

    def archive(self, fact_id: str) -> Dict[str, Any]:
        """Archive un fait directement (correction manuelle)."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM facts WHERE id = ? AND archived = 0", (fact_id,)
                ).fetchone()
                if not row:
                    return {"ok": False, "error": "Fait introuvable"}
                conn.execute(
                    "UPDATE facts SET archived = 1, updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), fact_id),
                )
                conn.commit()
        self.export_markdown()
        return {"ok": True, "archived": True}

    def decay_all(self) -> int:
        """
        Applique le decay temporel sur tous les faits actifs non vus depuis
        plus de DECAY_START_DAYS jours. À appeler une fois par jour au réveil
        du daemon.

        Retourne le nombre de faits dont la confiance a diminué.
        """
        now = datetime.now()
        cutoff = (now - timedelta(days=DECAY_START_DAYS)).isoformat()
        decayed = 0

        with self._lock:
            with self._connect() as conn:
                stale = conn.execute(
                    """SELECT id, confidence, last_seen FROM facts
                       WHERE archived = 0 AND last_seen < ?""",
                    (cutoff,),
                ).fetchall()

                for row in stale:
                    days_silent = (
                        now - datetime.fromisoformat(row["last_seen"])
                    ).days - DECAY_START_DAYS
                    loss = DECAY_PER_DAY * max(days_silent, 1)
                    new_conf = max(row["confidence"] - loss, 0.05)
                    archived = 1 if new_conf < ARCHIVE_THRESHOLD else 0

                    conn.execute(
                        """UPDATE facts SET confidence = ?, archived = ?,
                           updated_at = ? WHERE id = ?""",
                        (new_conf, archived, now.isoformat(), row["id"]),
                    )
                    decayed += 1

                conn.commit()

        if decayed:
            self.export_markdown()

        return decayed

    def get_facts(
        self,
        category: Optional[str] = None,
        min_confidence: float = 0.0,
        include_archived: bool = False,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retourne les faits actifs triés par confiance décroissante."""
        with self._connect() as conn:
            conditions = []
            params: List[Any] = []

            if not include_archived:
                conditions.append("archived = 0")
            if category:
                conditions.append("category = ?")
                params.append(category)
            if min_confidence > 0:
                conditions.append("confidence >= ?")
                params.append(min_confidence)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.append(limit)

            rows = conn.execute(
                f"SELECT * FROM facts {where} ORDER BY confidence DESC LIMIT ?",
                params,
            ).fetchall()

        return [dict(r) for r in rows]

    def render_for_context(self, limit: int = 8) -> str:
        """
        Génère un bloc texte compact pour injection dans le system prompt.

        Filtre uniquement sur confidence >= 0.60.
        `autonomy_level` n'intervient pas ici — il est réservé au futur
        système d'action autonome.

        Format :
          ── Profil utilisateur ──
          • [workflow] Tendance à travailler le soir en mode développement  (conf 0.82)
          • [cognitive] Focus soutenu fréquent le soir                      (conf 0.74)
        """
        facts = self.get_facts(min_confidence=0.60, limit=limit)
        if not facts:
            return ""

        lines = ["── Profil utilisateur ──"]
        category_labels = {
            "environment": "env",
            "workflow":    "workflow",
            "cognitive":   "cognitif",
            "preference":  "préf",
        }
        for f in facts:
            label = category_labels.get(f["category"], f["category"])
            conf  = f["confidence"]
            lines.append(f"• [{label}] {f['description']}  (conf {conf:.2f})")

        return "\n".join(lines)

    def compress(self, llm: Any, category: str) -> Optional[str]:
        """
        Compression LLM : fusionne les faits d'une catégorie en un résumé
        persistant. Déclenché automatiquement quand COMPRESS_THRESHOLD est
        atteint dans une catégorie.

        Le LLM reçoit uniquement des faits déjà validés — pas d'observations
        brutes. Retourne l'ID de l'entrée compressée ou None si échec.
        """
        facts = self.get_facts(category=category, min_confidence=0.5)
        if len(facts) < COMPRESS_THRESHOLD:
            return None

        descriptions = [f["description"] for f in facts]
        facts_block  = "\n".join(f"- {d}" for d in descriptions)

        prompt = f"""\
Voici des faits observés sur les habitudes de l'utilisateur ({category}) :

{facts_block}

Écris 1 à 2 phrases en français qui résument le pattern général.
Sois factuel et précis. N'invente rien qui ne soit pas dans les faits.
Ne mentionne pas de pourcentages ni de chiffres qui ne sont pas dans les données."""

        try:
            summary = _llm_complete(llm, prompt, max_tokens=100)
        except Exception:
            return None

        # Archive les faits sources pour éviter la redondance
        now = datetime.now().isoformat()
        with self._lock:
            with self._connect() as conn:
                ids = [f["id"] for f in facts]
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE facts SET archived = 1, updated_at = ? WHERE id IN ({placeholders})",
                    [now] + ids,
                )
                # Crée le fait de synthèse
                new_id = _new_uid()
                conn.execute(
                    """INSERT INTO facts
                       (id, key, category, description, context_json, confidence,
                        observations, confirmations, contradictions, autonomy_level,
                        created_at, updated_at, last_seen, archived)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (
                        new_id,
                        f"compressed:{category}:{now[:10]}",
                        category,
                        summary.strip(),
                        json.dumps({"source": "llm_compression", "facts_count": len(facts)}),
                        0.75,          # confiance initiale élevée — synthèse validée
                        len(facts),    # hérite du total d'observations
                        0, 0, 1,       # autonomy_level=1 : déjà validé par compression
                        now, now, now,
                    ),
                )
                conn.commit()

        self.export_markdown()
        return new_id

    def export_markdown(self) -> None:
        """
        Exporte les faits actifs en Markdown human-readable.
        Remplace habits.md pour la transparence utilisateur.
        """
        self.md_path.parent.mkdir(parents=True, exist_ok=True)
        facts = self.get_facts(limit=50)

        lines = [
            "# Faits utilisateur Pulse",
            "",
            f"_Mis à jour le {datetime.now().strftime('%Y-%m-%d %H:%M')}_",
            "",
        ]

        by_category: Dict[str, List[Dict]] = {}
        for f in facts:
            by_category.setdefault(f["category"], []).append(f)

        category_titles = {
            "workflow":    "## Workflow",
            "cognitive":   "## Style cognitif",
            "environment": "## Environnement",
            "preference":  "## Préférences",
        }

        for cat, title in category_titles.items():
            cat_facts = by_category.get(cat, [])
            if not cat_facts:
                continue
            lines.append(title)
            lines.append("")
            for f in cat_facts:
                bar   = _confidence_bar(f["confidence"])
                obs   = f["observations"]
                level = f["autonomy_level"]
                lines.append(
                    f"- {f['description']}  "
                    f"`{bar}` conf={f['confidence']:.2f} "
                    f"obs={obs} autonomie={level}"
                )
            lines.append("")

        self.md_path.write_text("\n".join(lines), encoding="utf-8")

    def stats(self) -> Dict[str, Any]:
        """Statistiques rapides pour debug et monitoring."""
        with self._connect() as conn:
            # Somme des observations portées par les faits actifs
            # (pas le COUNT des lignes brutes dans la table observations)
            total_obs = conn.execute(
                "SELECT COALESCE(SUM(observations), 0) FROM facts WHERE archived = 0"
            ).fetchone()[0]
            total_facts = conn.execute("SELECT COUNT(*) FROM facts WHERE archived = 0").fetchone()[0]
            archived    = conn.execute("SELECT COUNT(*) FROM facts WHERE archived = 1").fetchone()[0]
            by_cat      = conn.execute(
                "SELECT category, COUNT(*) as n FROM facts WHERE archived = 0 GROUP BY category"
            ).fetchall()
        return {
            "observations": total_obs,
            "active_facts": total_facts,
            "archived_facts": archived,
            "by_category": {r["category"]: r["n"] for r in by_cat},
        }

    # ── Internes ──────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS observations (
                    key         TEXT PRIMARY KEY,
                    category    TEXT NOT NULL,
                    description TEXT NOT NULL,
                    context_json TEXT,
                    count       INTEGER DEFAULT 1,
                    first_seen  TEXT NOT NULL,
                    last_seen   TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id              TEXT PRIMARY KEY,
                    key             TEXT UNIQUE NOT NULL,
                    category        TEXT NOT NULL,
                    description     TEXT NOT NULL,
                    context_json    TEXT,
                    confidence      REAL DEFAULT 0.50,
                    observations    INTEGER DEFAULT 0,
                    confirmations   INTEGER DEFAULT 0,
                    contradictions  INTEGER DEFAULT 0,
                    autonomy_level  INTEGER DEFAULT 0,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    last_seen       TEXT NOT NULL,
                    archived        INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    def _upsert_observation(
        self,
        conn: sqlite3.Connection,
        key: str,
        category: str,
        obs_description: str,
        fact_description: str,
        context: Dict[str, Any],
        now: str,
    ) -> None:
        existing = conn.execute(
            "SELECT count FROM observations WHERE key = ?", (key,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE observations SET count = count + 1, last_seen = ? WHERE key = ?",
                (now, key),
            )
            # Si le fait correspondant existe déjà, renforcer sa confiance
            fact = conn.execute(
                "SELECT id FROM facts WHERE key = ? AND archived = 0", (key,)
            ).fetchone()
            if fact:
                conn.execute(
                    """UPDATE facts SET
                       observations = observations + 1,
                       last_seen = ?,
                       confidence = MIN(confidence + ?, ?)
                       WHERE id = ?""",
                    (now, CONFIDENCE_CONFIRM / 2, CONFIDENCE_MAX, fact["id"]),
                )
        else:
            # Stocke obs_description comme description lisible de l'observation.
            # fact_description est rangée dans context_json sous _fact_description
            # pour être utilisée par _promote_pending() à la création du fait.
            context_with_fact = {**context, "_fact_description": fact_description}
            conn.execute(
                """INSERT INTO observations (key, category, description, context_json, count, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (key, category, obs_description, json.dumps(context_with_fact), now, now),
            )

    def _promote_pending(self, conn: sqlite3.Connection, now: str) -> List[str]:
        """
        Parcourt les observations qui atteignent FACT_THRESHOLD et n'ont pas
        encore de fait correspondant. Crée les faits manquants.
        """
        candidates = conn.execute(
            """SELECT o.* FROM observations o
               LEFT JOIN facts f ON f.key = o.key
               WHERE o.count >= ? AND f.id IS NULL""",
            (FACT_THRESHOLD,),
        ).fetchall()

        created = []
        for obs in candidates:
            fact_id = _new_uid()
            # Utilise fact_description si disponible (stockée dans context_json),
            # fallback sur description (observation brute) pour les entrées legacy.
            ctx = json.loads(obs["context_json"] or "{}")
            fact_description = ctx.pop("_fact_description", obs["description"])
            conn.execute(
                """INSERT INTO facts
                   (id, key, category, description, context_json, confidence,
                    observations, confirmations, contradictions, autonomy_level,
                    created_at, updated_at, last_seen, archived)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?, 0)""",
                (
                    fact_id,
                    obs["key"],
                    obs["category"],
                    fact_description,
                    json.dumps(ctx),
                    CONFIDENCE_INIT,
                    obs["count"],
                    now, now, now,
                ),
            )
            created.append(fact_id)

        return created

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn


# ── Extraction des observations depuis session_data ───────────────────────────

# Noms de processus système macOS pouvant apparaître dans recent_apps
# via des events app_activated au moment du lock/unlock ou au démarrage.
# Ces processus ne représentent pas une vraie utilisation d'application.
# Défense en profondeur : le filtre Swift (shouldTrackApp) bloque leur bundle ID
# à la source, mais des données antérieures peuvent rester dans session.db.
_SYSTEM_PROCESS_NAMES: frozenset = frozenset({
    "loginwindow",    # gestionnaire de session macOS (lock/unlock)
    "SystemUIServer", # menu bar système
    "Finder",         # déjà filtré côté Swift, défense en profondeur
})


def _extract_observations(
    session_data: Dict[str, Any],
) -> List[Tuple[str, str, str, str, Dict]]:
    """
    Traduit les données brutes d'une session en observations nommées.

    Retourne une liste de (key, category, obs_description, fact_description, context).
    Chaque key est un identifiant stable et déterministe.

    obs_description  : formulation sessionnelle et neutre (niveau 3)
                       Décrit ce qui s'est passé dans cette session.
                       Stockée dans la table `observations`.

    fact_description : formulation comportementale (niveau 5)
                       Décrit le pattern qui se dégage si l'observation se confirme.
                       Utilisée par `_promote_pending()` lors de la création du fait.

    Principe : on n'observe QUE ce qu'on peut vraiment affirmer.
    Pas d'inférence sur des sessions uniques — le compteur fait le travail.
    """
    obs: List[Tuple[str, str, str, str, Dict]] = []
    now  = datetime.now()
    slot = _time_slot(now.hour)

    task         = session_data.get("probable_task", "general")
    focus        = session_data.get("focus_level", "normal")
    duration     = session_data.get("duration_min", 0)
    friction     = float(session_data.get("max_friction", 0.0))
    apps         = [a for a in (session_data.get("recent_apps") or []) if a]
    project      = session_data.get("active_project") or "inconnu"

    # 1. Créneau + type de tâche ──────────────────────────────────────────────
    if task != "general":
        obs.append((
            f"slot:{slot}:task:{task}",
            "workflow",
            f"Session {_slot_label(slot)} — mode {_task_label(task)}",
            f"Tendance à travailler {_slot_label(slot)} en mode {_task_label(task)}",
            {"time_slot": slot, "task": task},
        ))

    # 2. Focus profond par créneau ────────────────────────────────────────────
    if focus == "deep":
        obs.append((
            f"focus:deep:{slot}",
            "cognitive",
            f"Focus soutenu observé — session {_slot_label(slot)}",
            f"Focus soutenu fréquent {_slot_label(slot)}",
            {"time_slot": slot, "focus": "deep"},
        ))

    # 3. Sessions longues ─────────────────────────────────────────────────────
    if duration >= 60:
        obs.append((
            f"session:long:{slot}",
            "cognitive",
            f"Session longue (1h+) — {_slot_label(slot)}",
            f"Sessions souvent longues (1h+) {_slot_label(slot)}",
            {"time_slot": slot, "duration_min": duration},
        ))

    # 4. Friction élevée récurrente ───────────────────────────────────────────
    if friction >= 0.7:
        obs.append((
            f"friction:high:project:{project}",
            "cognitive",
            f"Friction élevée observée — projet {project}",
            f"Friction récurrente sur le projet {project}",
            {"project": project, "friction": friction},
        ))

    return obs


# ── Helpers ───────────────────────────────────────────────────────────────────

def _time_slot(hour: int) -> str:
    if 6 <= hour < 12:  return "matin"
    if 12 <= hour < 18: return "après-midi"
    return "soir"


def _slot_label(slot: str) -> str:
    return {"matin": "le matin", "après-midi": "l'après-midi", "soir": "le soir"}.get(slot, slot)


def _task_label(task: str) -> str:
    return {
        "coding":   "développement",
        "debug":    "débogage",
        "writing":  "rédaction",
        "browsing": "navigation",
        "general":  "général",
    }.get(task, task)


def _confidence_bar(confidence: float, width: int = 8) -> str:
    filled = round(confidence * width)
    return "█" * filled + "░" * (width - filled)


def _new_uid() -> str:
    """Génère un ID unique. Réutilise uid.py si disponible."""
    try:
        from daemon.core.uid import new_uid
        return new_uid()
    except ImportError:
        import uuid
        return str(uuid.uuid4())


def _llm_complete(llm: Any, prompt: str, max_tokens: int = 100) -> str:
    if hasattr(llm, "complete"):
        return llm.complete(prompt, max_tokens=max_tokens)
    raise TypeError("LLM provider incompatible")
