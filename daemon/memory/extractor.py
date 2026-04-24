"""
extractor.py — Génération des rapports de session Pulse.

Déclencheurs
────────────
  1. Commit git (signal principal — LLM activé)
  2. screen_lock / user_idle (fallback déterministe uniquement)
  3. Manuel (fallback déterministe uniquement)

Anti-doublon
────────────
  Curseur par projet dans _CooldownState : un rapport ne se génère pas
  si un autre a été écrit il y a moins de REPORT_COOLDOWN_MIN minutes
  pour le même projet. Le curseur est persisté dans cooldown.json pour
  survivre aux redémarrages du daemon — c'est la cause principale de
  l'explosion de fichiers de session.

Qualité LLM
────────────
  Prompt inspiré de awaySummary.ts (Leak Claude) :
  1-3 phrases, tâche de haut niveau (pas les détails d'implémentation),
  prochaine étape concrète. Le LLM est désactivé pour les triggers
  screen_lock / user_idle — le fallback déterministe est plus honnête.
"""

import json
import logging
import re
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.memory.facts import FactEngine

log = logging.getLogger("pulse")

# Instance partagée du moteur de faits (initialisée une seule fois)
_fact_engine: Optional[FactEngine] = None


def get_fact_engine() -> FactEngine:
    """Retourne l'instance partagée du FactEngine (lazy init)."""
    global _fact_engine
    if _fact_engine is None:
        _fact_engine = FactEngine()
    return _fact_engine


def reset_fact_engine_for_tests() -> None:
    """Réinitialise le singleton partagé pour isoler les suites de tests."""
    global _fact_engine
    _fact_engine = None


def reset_cooldown_for_tests() -> None:
    """Réinitialise le curseur anti-doublon pour isoler les suites de tests."""
    _cooldown.reset()


MEMORY_DIR = Path.home() / ".pulse" / "memory"

# Cooldown minimum entre deux rapports pour un même projet (en minutes).
REPORT_COOLDOWN_MIN = 30

# Durée maximum d'une session rapportée.
# Au-delà, la donnée est aberrante (daemon jamais redémarré, veille longue, etc.)
MAX_SESSION_DURATION_MIN = 480  # 8h

# Fichier de persistance du curseur anti-doublon.
# Survit aux redémarrages du daemon — fix principal pour l'explosion de fichiers.
_COOLDOWN_FILE = Path.home() / ".pulse" / "cooldown.json"

# Suffixes à exclure des top_files
_NOISE_SUFFIXES = {
    ".tmp", ".swp", ".swo", ".orig", ".bak",
    ".xcuserstate", ".DS_Store", "~",
    # Images et médias — jamais du code source
    ".png", ".jpg", ".jpeg", ".gif", ".tiff", ".heic", ".webp",
    ".mp4", ".mov", ".avi", ".pdf", ".zip", ".tar", ".gz",
}
_NOISE_PATTERNS = {
    "COMMIT_EDITMSG", "MERGE_MSG", "FETCH_HEAD", "ORIG_HEAD",
    "packed-refs", "index",
    # Fichiers système macOS
    "loginwindow", "Desktop", "Downloads", "Documents",
}
_NOISE_SUBSTRINGS = {
    ".sb-", "__pycache__", "DerivedData", "xcuserdata",
    # Captures d'écran macOS (deux variantes typographiques)
    "Capture d’écran", "Capture d'écran", "Screenshot",
}

# Curseur anti-doublon encapsulé pour permettre le reset en test.
class _CooldownState:
    def __init__(self) -> None:
        self.last_report_at: Dict[str, datetime] = {}
        self.loaded: bool = False

    def reset(self) -> None:
        self.last_report_at = {}
        self.loaded = False


_cooldown = _CooldownState()
_memory_write_lock = threading.Lock()
_JOURNAL_DATA_START = "<!-- pulse-journal-data:start"
_JOURNAL_DATA_END = "pulse-journal-data:end -->"
_JOURNAL_HIDDEN_RE = re.compile(
    rf"\n?{re.escape(_JOURNAL_DATA_START)}\n(.*?)\n{re.escape(_JOURNAL_DATA_END)}\s*\Z",
    re.DOTALL,
)
_TECHNICAL_FILE_PATTERNS = (
    "cache",
    ".json",
    ".sqlite",
    ".db",
    ".lock",
    ".log",
    ".tmp",
)


def _load_cooldown() -> None:
    """Charge le curseur depuis le fichier JSON (une seule fois par processus)."""
    if _cooldown.loaded:
        return
    _cooldown.loaded = True
    try:
        if _COOLDOWN_FILE.exists():
            raw = json.loads(_COOLDOWN_FILE.read_text())
            cutoff = datetime.now() - timedelta(minutes=REPORT_COOLDOWN_MIN)
            for project, iso in raw.items():
                try:
                    dt = datetime.fromisoformat(iso)
                    if dt > cutoff:  # ignorer les entrées expirées
                        _cooldown.last_report_at[project] = dt
                except ValueError:
                    pass
    except Exception:
        pass  # cooldown.json corrompu ou absent — on repart de zéro


def _save_cooldown() -> None:
    """Persiste le curseur dans cooldown.json."""
    try:
        _COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {p: dt.isoformat() for p, dt in _cooldown.last_report_at.items()}
        _COOLDOWN_FILE.write_text(json.dumps(data))
    except Exception:
        pass  # non-bloquant


# ── Correction de tâche par préfixe de commit ─────────────────────────────────

# Mappage préfixe conventionnel → tâche cible.
# None = pas de correction (chore, build, ci sont trop ambigus).
_COMMIT_PREFIX_TASK: Dict[str, Optional[str]] = {
    "fix":      "debug",
    "feat":     "coding",
    "docs":     "writing",
    "refactor": "coding",
    "test":     "coding",
    "perf":     "coding",
    "style":    "coding",
    "chore":    None,
    "build":    None,
    "ci":       None,
}

# Tâches source compatibles avec chaque tâche cible.
# La correction s'applique uniquement si la tâche actuelle est ambiguë
# (general, exploration) ou compatible avec la cible.
_COMMIT_CORRECTION_FROM: Dict[str, set] = {
    "debug":   {"general", "exploration", "coding"},
    "coding":  {"general", "exploration"},
    "writing": {"general", "exploration"},
}


def _commit_task_correction(commit_message: str, current_task: str) -> str:
    """
    Retourne la tâche corrigée selon le préfixe du message de commit.

    Corrections applicables :
      fix:      → debug   (si session coding/general/exploration)
      feat:     → coding  (si session general/exploration)
      docs:     → writing (si session general/exploration)
      refactor: → coding  (si session general/exploration)
      test/perf/style: → coding  (si session general/exploration)
      chore/build/ci: pas de correction

    La correction est rétroactive — appliquée lors de l'écriture mémoire,
    pas en temps réel. Elle n'écrase jamais une tâche contradictoire
    (ex. writing → debug sur un commit fix: dans une session docs).
    """
    if not commit_message or not current_task:
        return current_task

    match = re.match(r'^(\w+)(?:\([^)]*\))?!?:', commit_message.strip().lower())
    if not match:
        return current_task

    prefix = match.group(1)
    target = _COMMIT_PREFIX_TASK.get(prefix)
    if target is None:
        return current_task

    compatible = _COMMIT_CORRECTION_FROM.get(target, set())
    if current_task in compatible:
        return target

    return current_task


# ── API publique ───────────────────────────────────────────────────────────────

def update_memories_from_session(
    session_data: Dict[str, Any],
    llm: Optional[Any] = None,
    memory_dir: Optional[Path] = None,
    commit_message: Optional[str] = None,
    trigger: str = "screen_lock",
    diff_summary: Optional[str] = None,
    defer_llm_enrichment: bool = False,
):
    """
    Met à jour la mémoire de session et génère un rapport si nécessaire.

    Le LLM n'est utilisé que pour les triggers 'commit'.
    Pour 'screen_lock', 'user_idle' et 'manual', le fallback déterministe
    est appliqué directement — plus honnête et sans risque d'hallucination.

    Le curseur _last_report_at garantit qu'un rapport ne se génère pas deux
    fois en moins de REPORT_COOLDOWN_MIN minutes pour le même projet.
    """
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    # Charge le curseur persisté (une fois par processus)
    _load_cooldown()

    # Cap de durée — évite les sessions aberrantes (766 min, 2628 min, etc.)
    if "duration_min" in session_data:
        session_data = dict(session_data)
        session_data["duration_min"] = min(
            session_data["duration_min"], MAX_SESSION_DURATION_MIN
        )

    # Correction rétroactive de la tâche selon le préfixe du commit.
    # Appliquée uniquement sur trigger commit et si la tâche actuelle est compatible.
    # Mutualise la copie de session_data déjà faite au-dessus si nécessaire.
    if trigger == "commit" and commit_message:
        corrected = _commit_task_correction(
            commit_message,
            session_data.get("probable_task", "general"),
        )
        if corrected != session_data.get("probable_task"):
            session_data = dict(session_data)  # ne pas muter le dict de l'appelant
            session_data["probable_task"] = corrected
            session_data["task_source"] = "commit_correction"

    consolidation = _build_consolidation_frame(
        session_data,
        commit_message=commit_message,
    )

    _update_projects(base_dir, session_data, consolidation=consolidation)

    # Moteur de faits : observe la session et tente une promotion
    try:
        engine = get_fact_engine()
        new_facts = engine.observe_session(session_data)
        engine.clear_runtime_error()
        if new_facts:
            log.info("Facts : %d nouveau(x) fait(s) consolidé(s)", len(new_facts))
    except Exception as exc:
        engine = get_fact_engine()
        info = engine.mark_runtime_error(exc)
        if info["recoverable"]:
            log.warning("Facts : erreur récupérable observe_session : %s", info["reason"])
        else:
            log.error("Facts : erreur structurelle observe_session : %s", info["reason"])

    project  = consolidation["active_project"] or "inconnu"
    duration = consolidation["duration_min"]
    top_files = _clean_files(session_data.get("top_files", []))
    files_count = session_data.get("files_changed", 0)
    substantive_commit = trigger == "commit" and _has_substantive_commit_signal(
        commit_message=commit_message,
        diff_summary=diff_summary,
        top_files=top_files,
        files_count=files_count,
    )

    # Vérifie si un rapport est nécessaire
    should_write = (duration >= 15 or substantive_commit)
    if not should_write:
        _update_index(base_dir)
        return None

    # Curseur anti-doublon — pas deux rapports en moins de REPORT_COOLDOWN_MIN
    # pour le même projet, sauf sur commit (unité de travail explicite).
    if trigger != "commit":
        last = _cooldown.last_report_at.get(project)
        if last is not None:
            elapsed = (datetime.now() - last).total_seconds() / 60
            if elapsed < REPORT_COOLDOWN_MIN:
                _update_index(base_dir)
                return None

    # LLM uniquement sur commit — seul trigger avec assez de signal.
    # En mode defer, on écrit d'abord une version déterministe immédiate,
    # puis le LLM enrichit l'entrée existante hors chemin critique.
    effective_llm = (
        llm
        if trigger == "commit"
        and substantive_commit
        and should_use_llm_for_commit(
            diff_summary=diff_summary,
            top_files=top_files,
            files_count=files_count,
        )
        and not defer_llm_enrichment
        else None
    )

    report_ref = _write_session_report(
        base_dir,
        session_data,
        consolidation=consolidation,
        llm=effective_llm,
        commit_message=commit_message,
        trigger=trigger,
        diff_summary=diff_summary,
    )

    # Avance le curseur après écriture réussie et le persiste sur disque
    _cooldown.last_report_at[project] = datetime.now()
    _save_cooldown()

    _update_index(base_dir)
    return report_ref


def enrich_session_report(
    report_ref,
    session_data: Dict[str, Any],
    llm: Any,
    *,
    commit_message: Optional[str] = None,
    diff_summary: Optional[str] = None,
) -> bool:
    """
    Enrichit a posteriori une entrée de journal déjà écrite.
    Utilisé pour les commits : le fallback déterministe est immédiat,
    puis le LLM remplace le corps quand sa réponse complète arrive.
    """
    if report_ref is None or llm is None:
        return False

    journal_file, entry_id = report_ref
    project     = session_data.get("active_project") or "inconnu"
    duration    = session_data.get("duration_min", 0)
    task        = session_data.get("probable_task", "general")
    focus       = session_data.get("focus_level", "normal")
    friction    = float(session_data.get("max_friction", 0.0))
    apps        = session_data.get("recent_apps", [])
    top_files   = _clean_files(session_data.get("top_files", []))
    files_count = session_data.get("files_changed", 0)

    body = _llm_summary(
        llm,
        project,
        duration,
        task,
        focus,
        friction,
        apps,
        top_files,
        files_count,
        commit_message,
        diff_summary,
    )
    return _replace_journal_entry(journal_file, entry_id, body)


def last_session_context(
    project: str,
    memory_dir: Optional[Path] = None,
    today: Optional["date"] = None,
) -> Optional[str]:
    """
    Retourne une ligne de contexte sur la dernière session connue pour ce projet.

    Lit projects.md (déjà écrit par _update_projects) — aucune nouvelle donnée.
    Exemple : "Dernière session Pulse : hier (développement, 45 min)"

    Retourne None si le projet est inconnu, si les données sont absentes,
    ou si le parsing échoue. Ne lève jamais d'exception.

    Paramètres :
      project    : nom du projet actif
      memory_dir : répertoire mémoire (défaut : MEMORY_DIR)
      today      : date de référence pour le calcul d'âge (défaut : aujourd'hui)
                   injecté pour les tests sans mock de datetime
    """
    from datetime import date as _date

    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    sections = _parse_project_sections(base_dir / "projects.md")
    entry = sections.get(project)
    if not entry or not entry.get("last_session"):
        return None

    try:
        last_date = datetime.strptime(entry["last_session"], "%Y-%m-%d").date()
        ref_today = today if today is not None else datetime.now().date()
        delta = (ref_today - last_date).days

        if delta < 0:
            return None  # date future — donnée corrompue
        elif delta == 0:
            age = "aujourd'hui"
        elif delta == 1:
            age = "hier"
        elif delta <= 6:
            age = f"il y a {delta} jours"
        elif delta <= 13:
            age = "la semaine dernière"
        else:
            age = f"il y a {delta // 7} semaine(s)"

        _task_labels = {
            "coding":   "développement",
            "debug":    "débogage",
            "writing":  "rédaction",
            "exploration": "exploration",
            "browsing": "exploration",
        }
        raw_task = entry.get("last_task") or entry.get("task") or "general"
        task = _task_labels.get(raw_task, raw_task)
        duration = int(entry.get("last_duration") or 0)

        return f"Dernière session {project} : {age} ({task}, {duration} min)"

    except (ValueError, TypeError, AttributeError):
        return None


def load_memory_context(memory_dir: Optional[Path] = None) -> str:
    """Fallback legacy : lit projects.md uniquement (habits.md = bruit pur)."""
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    parts = []
    for filename in ("projects.md", "preferences.md"):
        path = base_dir / filename
        if path.exists():
            parts.append(path.read_text())
    return "\n---\n".join(parts)[:2000]


def render_project_memory(memory_dir: Optional[Path] = None) -> str:
    """
    Rend la mémoire projet consolidée pour l'assistant.

    Source principale : projects.md, désormais nourri par les épisodes clos.
    Retourne une chaîne vide si aucune projection projet n'existe encore.
    """
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    path = base_dir / "projects.md"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def find_git_root(file_path: str) -> Optional[Path]:
    """
    Remonte l'arborescence depuis file_path pour trouver un dépôt git.
    Supporte les worktrees et submodules (où .git est un fichier, pas un dossier).
    """
    path = Path(file_path)
    if path.is_file():
        path = path.parent
    for candidate in [path, *path.parents]:
        git = candidate / ".git"
        if git.is_dir() or git.is_file():
            return candidate
    return None


def _resolve_git_dir(git_root: Path) -> Optional[Path]:
    """
    Résout le vrai répertoire git pour un dépôt standard ou un worktree.
    Supporte:
      - .git dossier
      - .git fichier contenant 'gitdir: ...'
      - chemin relatif vers le vrai gitdir
    Retourne None si la résolution échoue.
    """
    try:
        git_entry = git_root / ".git"
        if git_entry.is_dir():
            return git_entry
        if not git_entry.is_file():
            return None

        content = git_entry.read_text(encoding="utf-8").strip()
        if not content.startswith("gitdir:"):
            return None

        gitdir_text = content[7:].strip()
        if not gitdir_text:
            return None

        gitdir = Path(gitdir_text)
        if not gitdir.is_absolute():
            gitdir = (git_entry.parent / gitdir).resolve()
        return gitdir if gitdir.exists() else None
    except Exception:
        return None


def read_head_sha(git_root: Path) -> Optional[str]:
    """Lit le SHA courant de HEAD. Retourne None si indisponible."""
    try:
        git_dir = _resolve_git_dir(git_root)
        if git_dir is None:
            return None

        head_file = git_dir / "HEAD"
        if not head_file.exists():
            return None

        ref = head_file.read_text().strip()
        if ref.startswith("ref: "):
            ref_path = git_dir / ref[5:]
            if not ref_path.exists():
                return None
            return ref_path.read_text().strip()
        return ref if len(ref) == 40 else None
    except Exception:
        return None


def read_commit_message(git_root: Path) -> Optional[str]:
    """Lit le message du dernier commit depuis COMMIT_EDITMSG."""
    try:
        git_dir = _resolve_git_dir(git_root)
        if git_dir is None:
            return None
        commit_msg_file = git_dir / "COMMIT_EDITMSG"
        content = commit_msg_file.read_text(encoding="utf-8").strip()
        lines = [l for l in content.splitlines() if not l.startswith("#")]
        msg = "\n".join(lines).strip()
        return msg if msg else None
    except Exception:
        return None


# ── Rapport de session ────────────────────────────────────────────────────────

def _write_session_report(
    base_dir: Path,
    session: Dict[str, Any],
    *,
    consolidation: Dict[str, Any],
    llm: Optional[Any],
    commit_message: Optional[str],
    trigger: str,
    diff_summary: Optional[str] = None,
):
    """
    Journal quotidien : un seul fichier par jour (YYYY-MM-DD.md).
    Les entrées brutes sont stockées dans un bloc caché, puis rendues
    comme une lecture projet-first / épisode-first de la journée.
    """
    now      = datetime.now()
    today    = now.strftime("%Y-%m-%d")

    sessions_dir = base_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    journal_file = sessions_dir / f"{today}.md"

    project     = consolidation["active_project"] or "inconnu"
    duration    = consolidation["duration_min"]
    task        = consolidation["probable_task"]
    focus       = session.get("focus_level", "normal")
    friction    = float(session.get("max_friction", 0.0))
    apps        = session.get("recent_apps", [])
    top_files   = _clean_files(session.get("top_files", []))
    files_count = session.get("files_changed", 0)

    if llm is not None:
        try:
            body = _llm_summary(
                llm, project, duration, task, focus, friction,
                apps, top_files, files_count, commit_message, diff_summary,
            )
        except Exception as exc:
            log.warning("Memory : erreur résumé LLM, fallback déterministe utilisé : %s", exc)
            body = _deterministic_summary(
                duration, task, focus, friction, top_files, files_count, commit_message,
            )
    else:
        body = _deterministic_summary(
            duration, task, focus, friction, top_files, files_count, commit_message,
        )

    entry_id = _new_entry_id(now)
    episode = consolidation.get("episode") or {}
    ended_at = str(episode.get("ended_at") or now.isoformat())
    started_at = str(
        episode.get("started_at")
        or (now - timedelta(minutes=max(duration, 0))).isoformat()
    )
    entry = _build_journal_entry(
        entry_id=entry_id,
        active_project=project,
        probable_task=task,
        activity_level=consolidation.get("activity_level"),
        task_confidence=consolidation.get("task_confidence"),
        duration_min=duration,
        body=body,
        commit_message=commit_message,
        top_files=top_files,
        files_count=files_count,
        started_at=started_at,
        ended_at=ended_at,
        boundary_reason=str(episode.get("boundary_reason") or trigger or "unknown"),
    )

    with _memory_write_lock:
        entries = _load_journal_entries(journal_file)
        entries.append(entry)
        _write_journal_document(journal_file, today, entries)

    return (journal_file, entry_id)


def _llm_summary(
    llm: Any,
    project: str,
    duration: int,
    task: str,
    focus: str,
    friction: float,
    apps: List[str],
    top_files: List[str],
    files_count: int,
    commit_message: Optional[str],
    diff_summary: Optional[str],
) -> str:
    """
    Prompt de résumé LLM uniquement sur commit.
    Exploit le diff réel du commit pour un résumé vraiment informatif.

    Contraintes :
    - 1 à 2 phrases maximum
    - Ce qui a été livré, pas comment
    - Aucun fait inventé
    """
    facts: List[str] = [
        f"Projet : {project}",
        f"Durée : {duration} minutes",
    ]

    if commit_message:
        facts.append(f'Commit : "{commit_message.splitlines()[0]}"')

    # Diff du commit — source la plus fiable de ce qui a changé
    if diff_summary:
        for line in diff_summary.splitlines():
            facts.append(line)
    elif top_files:
        facts.append(f"Fichiers modifiés : {', '.join(top_files[:5])}")
    elif files_count:
        facts.append(f"Fichiers modifiés : {files_count}")

    if friction >= 0.7:
        facts.append("Friction : élevée")

    facts_block = "\n".join(f"- {f}" for f in facts)

    prompt = f"""\
Voici les données factuelles du commit livré :

{facts_block}

Écris 1 à 2 phrases courtes en français.
Adopte un ton de note de journal concise et factuelle.
Dis ce qui a été livré et la portée principale — pas comment ni les détails techniques.
Évite les tournures emphatiques comme « Ce commit améliore... ».
Si le message de commit est explicite, reformule-le naturellement dans ce ton.
N'invente aucun fait absent des données ci-dessus."""

    return _llm_complete(llm, prompt, max_tokens=256, think=False)


def _deterministic_summary(
    duration: int,
    task: str,
    focus: str,
    friction: float,
    top_files: List[str],
    files_count: int,
    commit_message: Optional[str],
) -> str:
    """
    Résumé honnête sans LLM.
    Préfère le commit quand il existe, sinon décrit l'activité observée.
    """
    focus_str = {
        "deep":      "focus profond",
        "scattered": "travail dispersé",
        "idle":      "session légère",
        "normal":    "",
    }.get(focus, "")

    parts = []

    # Commit — signal le plus fort, on le met en avant
    if commit_message:
        parts.append(f"Livraison : « {commit_message.splitlines()[0]} ».")

    # Portée principale touchée
    if top_files:
        main_file = top_files[0]
        if len(top_files) > 1:
            others = f" (+{len(top_files) - 1})"
        else:
            others = ""
        parts.append(f"Portée : {main_file}{others}.")
    elif files_count:
        parts.append(f"Portée : {files_count} fichier(s) modifié(s).")

    # Focus et friction
    if focus_str:
        parts.append(f"Rythme : {focus_str}.")
    if friction >= 0.7:
        parts.append("Friction : élevée.")

    # Fallback si rien à dire
    if not parts:
        parts.append(f"Session de {duration} min.")

    return " ".join(parts)


def _has_substantive_commit_signal(
    *,
    commit_message: Optional[str],
    diff_summary: Optional[str],
    top_files: List[str],
    files_count: int,
) -> bool:
    if diff_summary and diff_summary.strip():
        return True
    if len(top_files) >= 2 or files_count >= 2:
        return True
    if commit_message and len(commit_message.split()) >= 3:
        return True
    return False


def should_use_llm_for_commit(
    *,
    diff_summary: Optional[str],
    top_files: List[str],
    files_count: int,
) -> bool:
    if diff_summary and diff_summary.strip():
        return True
    if len(top_files) >= 2 or files_count >= 3:
        return True
    return False


# ── Nettoyage des fichiers ────────────────────────────────────────────────────

def _clean_files(files: List[str]) -> List[str]:
    result = []
    for f in files:
        name = Path(f).name
        if name in _NOISE_PATTERNS:
            continue
        if any(name.endswith(s) for s in _NOISE_SUFFIXES):
            continue
        if any(s in f for s in _NOISE_SUBSTRINGS):
            continue
        result.append(name)
    return result


def _replace_journal_entry(journal_file: Path, entry_id: str, body: str) -> bool:
    with _memory_write_lock:
        if not journal_file.exists():
            return False

        entries = _load_journal_entries(journal_file)
        updated = False
        for entry in entries:
            if entry.get("entry_id") == entry_id:
                entry["body"] = body.strip()
                updated = True
                break
        if not updated:
            return False

        journal_date = _journal_date_from_path(journal_file)
        _write_journal_document(journal_file, journal_date, entries)
        return True


def _new_entry_id(now: datetime) -> str:
    return now.strftime("%Y%m%d%H%M%S%f")


def _build_journal_entry(
    *,
    entry_id: str,
    active_project: str,
    probable_task: str,
    activity_level: Optional[str],
    task_confidence: Optional[float],
    duration_min: int,
    body: str,
    commit_message: Optional[str],
    top_files: List[str],
    files_count: int,
    started_at: str,
    ended_at: str,
    boundary_reason: str,
) -> Dict[str, Any]:
    return {
        "entry_id": entry_id,
        "active_project": active_project or "Autre",
        "probable_task": probable_task or "general",
        "activity_level": activity_level or "unknown",
        "task_confidence": task_confidence,
        "duration_min": int(max(duration_min, 0)),
        "body": body.strip(),
        "commit_message": (commit_message or "").strip(),
        "top_files": list(top_files[:5]),
        "files_count": int(max(files_count or 0, 0)),
        "started_at": started_at,
        "ended_at": ended_at,
        "boundary_reason": boundary_reason or "unknown",
    }


def _load_journal_entries(journal_file: Path) -> List[Dict[str, Any]]:
    if not journal_file.exists():
        return []
    content = journal_file.read_text(encoding="utf-8")
    match = _JOURNAL_HIDDEN_RE.search(content)
    if match is not None:
        try:
            raw_entries = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
        return [
            entry for entry in raw_entries
            if isinstance(entry, dict) and entry.get("entry_id")
        ]
    return []


def _journal_date_from_path(journal_file: Path) -> str:
    return journal_file.stem


def _write_journal_document(journal_file: Path, journal_date: str, entries: List[Dict[str, Any]]) -> None:
    rendered = _render_journal_document(journal_date, entries)
    payload = json.dumps(entries, ensure_ascii=False, indent=2)
    hidden_block = "\n".join([
        "",
        _JOURNAL_DATA_START,
        payload,
        _JOURNAL_DATA_END,
        "",
    ])
    journal_file.write_text(rendered.rstrip() + hidden_block, encoding="utf-8")


def _render_journal_document(journal_date: str, entries: List[Dict[str, Any]]) -> str:
    ordered_entries = sorted(entries, key=_journal_entry_sort_key)
    merged_entries = _merge_journal_entries(ordered_entries)

    project_sections: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    noise_entries: List[Dict[str, Any]] = []
    for entry in merged_entries:
        if _is_noise_journal_entry(entry):
            noise_entries.append(entry)
            continue
        project = entry.get("active_project") or "Autre"
        project_sections.setdefault(project, []).append(entry)

    lines = [f"# Journal Pulse — {journal_date}"]
    for project, project_entries in project_sections.items():
        lines.extend(["", f"## {project}", ""])
        for index, entry in enumerate(project_entries):
            lines.extend(_render_journal_project_entry(entry))
            if index < len(project_entries) - 1:
                lines.extend(["", "---", ""])

    if noise_entries:
        lines.extend(["", "## Activité faible / bruit", ""])
        for entry in noise_entries:
            lines.append(f"- {_render_noise_line(entry)}")

    return "\n".join(lines).rstrip() + "\n"


def _render_journal_project_entry(entry: Dict[str, Any]) -> List[str]:
    title = _journal_entry_title(entry)
    duration = int(entry.get("duration_min") or 0)
    time_range = _journal_entry_time_range(entry)
    lines = [f"### {time_range} — {title} ({duration} min)"]

    description = _journal_entry_description(entry)
    if description:
        lines.extend(description.splitlines())

    scope = _journal_entry_scope(entry)
    lines.append(f"Portée : {scope}")
    return lines


def _render_noise_line(entry: Dict[str, Any]) -> str:
    project = entry.get("active_project") or "Autre"
    title = _journal_entry_title(entry)
    duration = int(entry.get("duration_min") or 0)
    scope = _journal_entry_scope(entry)
    return f"{_journal_entry_time_range(entry)} — {project} / {title} ({duration} min) — {scope}"


def _journal_entry_sort_key(entry: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("started_at") or ""),
        str(entry.get("ended_at") or ""),
        str(entry.get("entry_id") or ""),
    )


def _merge_journal_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for raw_entry in entries:
        entry = _normalize_journal_entry(raw_entry)
        if merged and _can_merge_journal_entries(merged[-1], entry):
            merged[-1] = _merge_journal_pair(merged[-1], entry)
        else:
            merged.append(entry)
    return merged


def _normalize_journal_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(entry)
    normalized["active_project"] = normalized.get("active_project") or "Autre"
    normalized["probable_task"] = normalized.get("probable_task") or "general"
    normalized["top_files"] = [
        str(item) for item in normalized.get("top_files", [])
        if isinstance(item, str) and item.strip()
    ]
    normalized["duration_min"] = int(max(normalized.get("duration_min") or 0, 0))
    normalized["commit_messages"] = _compact_strings([
        normalized.get("commit_message"),
        *normalized.get("commit_messages", []),
    ])
    return normalized


def _can_merge_journal_entries(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return (
        left.get("active_project") == right.get("active_project")
        and left.get("probable_task") == right.get("probable_task")
    )


def _merge_journal_pair(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(left)
    merged["entry_id"] = str(left.get("entry_id") or right.get("entry_id") or "")
    merged["ended_at"] = right.get("ended_at") or left.get("ended_at")
    merged["duration_min"] = int(left.get("duration_min") or 0) + int(right.get("duration_min") or 0)
    merged["task_confidence"] = max(
        _float_or_zero(left.get("task_confidence")),
        _float_or_zero(right.get("task_confidence")),
    )
    merged["files_count"] = max(
        int(left.get("files_count") or 0),
        len(_merge_unique_strings(left.get("top_files", []), right.get("top_files", []))),
        int(right.get("files_count") or 0),
    )
    merged["top_files"] = _merge_unique_strings(left.get("top_files", []), right.get("top_files", []))
    merged["commit_messages"] = _merge_unique_strings(
        left.get("commit_messages", []),
        right.get("commit_messages", []),
    )
    merged["commit_message"] = merged["commit_messages"][0] if merged["commit_messages"] else ""
    merged["body"] = "\n".join(_compact_strings([left.get("body"), right.get("body")]))
    return merged


def _journal_entry_title(entry: Dict[str, Any]) -> str:
    task_labels = {
        "coding": "développement",
        "debug": "débogage",
        "writing": "rédaction",
        "exploration": "exploration",
        "browsing": "exploration",
        "general": "travail général",
    }
    task = str(entry.get("probable_task") or "general")
    return task_labels.get(task, task.replace("_", " "))


def _journal_entry_description(entry: Dict[str, Any]) -> str:
    lines: List[str] = []
    commit_messages = _compact_strings(entry.get("commit_messages", []))
    if commit_messages:
        if len(commit_messages) == 1:
            lines.append(f"Commit : {commit_messages[0]}")
        else:
            lines.append("Commits : " + " · ".join(commit_messages))

    body = str(entry.get("body") or "").strip()
    body = _strip_commit_sentence(body, commit_messages)
    if body.startswith("Portée : ") and not commit_messages:
        body = ""
    if body:
        lines.append(body)

    if not lines:
        duration = int(entry.get("duration_min") or 0)
        lines.append(f"Travail observé sur {_journal_entry_title(entry)} pendant {duration} min.")

    return "\n".join(lines)


def _journal_entry_scope(entry: Dict[str, Any]) -> str:
    top_files = _compact_strings(entry.get("top_files", []))
    if top_files:
        return ", ".join(top_files[:4])
    files_count = int(entry.get("files_count") or 0)
    if files_count > 0:
        return f"{files_count} fichier(s) / module(s)"
    return "non déterminée"


def _journal_entry_time_range(entry: Dict[str, Any]) -> str:
    start = _format_journal_time(entry.get("started_at"))
    end = _format_journal_time(entry.get("ended_at"))
    return f"{start} → {end}"


def _format_journal_time(value: Any) -> str:
    if not value:
        return "??:??"
    text = str(value)
    try:
        return datetime.fromisoformat(text).strftime("%H:%M")
    except ValueError:
        if "T" in text:
            return text.split("T", 1)[1][:5]
        if " " in text:
            return text.split(" ", 1)[1][:5]
        return text[:5]


def _is_noise_journal_entry(entry: Dict[str, Any]) -> bool:
    duration = int(entry.get("duration_min") or 0)
    task = str(entry.get("probable_task") or "general")
    commit_messages = _compact_strings(entry.get("commit_messages", []))
    body = str(entry.get("body") or "").strip()
    top_files = _compact_strings(entry.get("top_files", []))

    if duration < 3 and not commit_messages and not _has_useful_journal_body(body):
        return True
    if task == "general" and not commit_messages and not _has_useful_journal_body(body):
        return True
    if task == "general" and not commit_messages and top_files and _all_files_technical(top_files):
        return True
    if duration < 5 and not commit_messages and top_files and _all_files_technical(top_files):
        return True
    return False


def _has_useful_journal_body(body: str) -> bool:
    if not body:
        return False
    normalized = body.strip()
    weak_prefixes = (
        "Session de ",
        "Travail observé sur ",
    )
    return len(normalized) >= 20 and not normalized.startswith(weak_prefixes)


def _all_files_technical(files: List[str]) -> bool:
    if not files:
        return False
    lowered = [name.lower() for name in files]
    return all(any(pattern in name for pattern in _TECHNICAL_FILE_PATTERNS) for name in lowered)


def _strip_commit_sentence(body: str, commit_messages: List[str]) -> str:
    if not body:
        return ""
    cleaned = body
    for message in commit_messages:
        if not message:
            continue
        escaped = re.escape(message)
        cleaned = re.sub(
            rf"^Livraison : « {escaped} »\.\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned.strip()


def _compact_strings(values: List[Any]) -> List[str]:
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _merge_unique_strings(left: List[Any], right: List[Any]) -> List[str]:
    return _compact_strings([*left, *right])[:5]


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ── Projets et habitudes ──────────────────────────────────────────────────────

def _update_projects(base_dir: Path, session: Dict[str, Any], *, consolidation: Dict[str, Any]) -> None:
    project = consolidation["active_project"]
    if not project:
        return

    projects_file = base_dir / "projects.md"
    with _memory_write_lock:
        current  = _parse_project_sections(projects_file)
        today    = datetime.now().strftime("%Y-%m-%d")
        duration = consolidation["duration_min"]
        task     = consolidation["probable_task"]
        latest_episode = _normalize_project_episode(consolidation.get("episode"))

        entry = current.get(project)
        if entry is None:
            current[project] = {
                "first_session": today,
                "last_session": today,
                "last_duration": duration,
                "last_task": task,
                "task": task,
                "recent_episodes": [],
            }
        else:
            entry["last_session"]  = today
            entry["last_duration"] = duration
            entry["last_task"]     = task
            entry["task"]          = task
            entry.setdefault("recent_episodes", [])

        entry = current[project]
        entry["recent_episodes"] = _merge_project_recent_episodes(
            entry.get("recent_episodes", []),
            latest_episode,
        )

        latest_known = entry["recent_episodes"][0] if entry["recent_episodes"] else None
        if latest_known is not None:
            entry["last_session"] = latest_known["date"]
            entry["last_duration"] = latest_known["duration_min"]
            entry["last_task"] = latest_known["probable_task"]

        dominant_task = _dominant_project_task(entry["recent_episodes"]) or entry["task"]
        entry["task"] = dominant_task

        lines = ["# Projets\n"]
        for name in sorted(current):
            item = current[name]
            lines.extend([
                "", f"## {name}", "",
                f"- Première session : {item['first_session']}",
                f"- Dernière session : {item['last_session']} ({item['last_duration']} min, {item.get('last_task', item['task'])})",
                f"- Type de travail détecté : {item['task']}",
            ])
            recent_episodes = item.get("recent_episodes", [])
            if recent_episodes:
                lines.append("- Épisodes récents :")
                for episode in recent_episodes[:5]:
                    lines.append(
                        "  - "
                        f"{episode['date_time']} | {episode['probable_task']} | "
                        f"{episode['activity_level']} | {episode['duration_min']} min | "
                        f"{episode['boundary_reason']} | {episode['episode_id']}"
                    )
        projects_file.write_text("\n".join(lines).strip() + "\n")


def _update_index(base_dir: Path) -> None:
    index_file = base_dir / "MEMORY.md"
    with _memory_write_lock:
        entries = [
            f"- [{f.stem}]({f.name})"
            for f in sorted(base_dir.glob("*.md"))
            if f.name != "MEMORY.md"
        ]
        content = "# Index mémoire Pulse\n\n" + "\n".join(entries)
        if entries:
            content += "\n"
        index_file.write_text(content)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_project_sections(projects_file: Path) -> Dict[str, Dict[str, Any]]:
    if not projects_file.exists():
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    current_name = None
    in_recent_episodes = False

    for raw_line in projects_file.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_name = line[3:]
            result[current_name] = {"recent_episodes": []}
            in_recent_episodes = False
        elif current_name and line.startswith("- Première session : "):
            result[current_name]["first_session"] = line.split(": ", 1)[1]
            in_recent_episodes = False
        elif current_name and line.startswith("- Dernière session : "):
            value = line.split(": ", 1)[1]
            date_part, details = _split_last_session(value)
            result[current_name]["last_session"]  = date_part
            result[current_name]["last_duration"] = details["duration"]
            result[current_name]["last_task"]      = details["task"]
            in_recent_episodes = False
        elif current_name and line.startswith("- Type de travail détecté : "):
            result[current_name]["task"] = line.split(": ", 1)[1]
            in_recent_episodes = False
        elif current_name and line == "- Épisodes récents :":
            in_recent_episodes = True
        elif current_name and in_recent_episodes and raw_line.startswith("  - "):
            episode = _parse_project_episode_line(raw_line.strip()[2:].strip())
            if episode is not None:
                result[current_name]["recent_episodes"].append(episode)
        elif line:
            in_recent_episodes = False

    return result


def _build_consolidation_frame(
    session_data: Dict[str, Any],
    *,
    commit_message: Optional[str] = None,
) -> Dict[str, Any]:
    episode = _latest_closed_episode(session_data.get("closed_episodes"))
    active_project = (
        (episode or {}).get("active_project")
        or session_data.get("active_project")
    )
    probable_task = (
        (episode or {}).get("probable_task")
        or session_data.get("probable_task")
        or "general"
    )
    if commit_message:
        probable_task = _commit_task_correction(commit_message, probable_task)

    duration_min = _episode_duration_min(episode)
    if duration_min is None:
        duration_min = int(session_data.get("duration_min", 0) or 0)

    return {
        "episode": episode,
        "active_project": active_project,
        "probable_task": probable_task,
        "activity_level": (episode or {}).get("activity_level"),
        "task_confidence": (episode or {}).get("task_confidence"),
        "duration_min": duration_min,
    }


def _latest_closed_episode(closed_episodes: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(closed_episodes, list):
        return None

    def _sort_key(item: Dict[str, Any]) -> tuple[str, str]:
        ended_at = str(item.get("ended_at") or "")
        started_at = str(item.get("started_at") or "")
        return (ended_at, started_at)

    candidates = [
        item for item in closed_episodes
        if isinstance(item, dict) and item.get("ended_at")
    ]
    if not candidates:
        return None
    return max(candidates, key=_sort_key)


def _episode_duration_min(episode: Optional[Dict[str, Any]]) -> Optional[int]:
    if episode is None:
        return None
    duration_sec = episode.get("duration_sec")
    if duration_sec is None:
        return None
    try:
        return max(int(round(float(duration_sec) / 60.0)), 0)
    except (TypeError, ValueError):
        return None


def _normalize_project_episode(episode: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(episode, dict):
        return None
    ended_at = episode.get("ended_at")
    started_at = episode.get("started_at")
    timestamp = ended_at or started_at
    if not timestamp:
        return None
    duration_min = _episode_duration_min(episode)
    if duration_min is None:
        return None
    date, date_time = _format_project_episode_timestamp(str(timestamp))
    return {
        "episode_id": str(episode.get("episode_id") or episode.get("id") or ""),
        "date": date,
        "date_time": date_time,
        "probable_task": str(episode.get("probable_task") or "general"),
        "activity_level": str(episode.get("activity_level") or "unknown"),
        "duration_min": duration_min,
        "boundary_reason": str(episode.get("boundary_reason") or "unknown"),
    }


def _merge_project_recent_episodes(existing: List[Dict[str, Any]], latest: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    episodes = [episode for episode in existing if isinstance(episode, dict)]
    if latest is not None:
        episodes = [episode for episode in episodes if episode.get("episode_id") != latest["episode_id"]]
        episodes.append(latest)
    episodes.sort(
        key=lambda item: (
            str(item.get("date_time") or ""),
            str(item.get("episode_id") or ""),
        ),
        reverse=True,
    )
    return episodes[:5]


def _dominant_project_task(episodes: List[Dict[str, Any]]) -> Optional[str]:
    counts: Dict[str, int] = {}
    for episode in episodes:
        task = str(episode.get("probable_task") or "general")
        counts[task] = counts.get(task, 0) + 1
    if not counts:
        return None
    return max(
        counts,
        key=lambda task: (
            counts[task],
            next(
                (
                    index
                    for index, episode in enumerate(episodes)
                    if episode.get("probable_task") == task
                ),
                len(episodes),
            ) * -1,
        ),
    )


def _format_project_episode_timestamp(timestamp: str) -> tuple[str, str]:
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp[:10], timestamp.replace("T", " ")[:16]
    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m-%d %H:%M")


def _parse_project_episode_line(value: str) -> Optional[Dict[str, Any]]:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) != 6:
        return None
    duration_text = parts[3]
    if not duration_text.endswith(" min"):
        return None
    try:
        duration_min = int(duration_text[:-4].strip())
    except ValueError:
        return None
    date_time = parts[0]
    date = date_time[:10]
    return {
        "date": date,
        "date_time": date_time,
        "probable_task": parts[1] or "general",
        "activity_level": parts[2] or "unknown",
        "duration_min": duration_min,
        "boundary_reason": parts[4] or "unknown",
        "episode_id": parts[5],
    }


def _split_last_session(value: str) -> tuple:
    if "(" not in value or ")" not in value:
        return value, {"duration": 0, "task": "general"}
    date_part, rest = value.split("(", 1)
    details = rest.rstrip(")")
    duration, task = 0, "general"
    if "," in details:
        dur_part, task_part = details.split(",", 1)
        tokens = dur_part.strip().split()
        if tokens and tokens[0].isdigit():
            duration = int(tokens[0])
        task = task_part.strip()
    return date_part.strip(), {"duration": duration, "task": task}


def _time_slot(hour: int) -> str:
    if 6 <= hour < 12:   return "matin"
    if 12 <= hour < 18:  return "après-midi"
    return "soir"


def _llm_complete(
    llm: Any,
    prompt: str,
    max_tokens: int = 150,
    think: Optional[bool] = None,
) -> str:
    if hasattr(llm, "complete"):
        kwargs = {"max_tokens": max_tokens}
        if think is not None:
            kwargs["think"] = think
        try:
            return llm.complete(prompt, **kwargs)
        except TypeError:
            kwargs.pop("think", None)
            return llm.complete(prompt, **kwargs)
    raise TypeError("LLM provider incompatible")
