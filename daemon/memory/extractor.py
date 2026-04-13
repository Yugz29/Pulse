"""
extractor.py — Génération des rapports de session Pulse.

Déclencheurs
────────────
  1. Commit git (signal principal — LLM activé)
  2. screen_lock / user_idle (fallback déterministe uniquement)
  3. Manuel (LLM activé)

Anti-doublon
────────────
  Curseur _last_report_at par projet : un rapport ne se génère pas
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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.memory.facts import FactEngine

# Instance partagée du moteur de faits (initialisée une seule fois)
_fact_engine: Optional[FactEngine] = None


def get_fact_engine() -> FactEngine:
    """Retourne l'instance partagée du FactEngine (lazy init)."""
    global _fact_engine
    if _fact_engine is None:
        _fact_engine = FactEngine()
    return _fact_engine


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

# Curseur anti-doublon : {project_name: datetime du dernier rapport}
# Chargé depuis cooldown.json au premier accès, persisté après chaque écriture.
_last_report_at: Dict[str, datetime] = {}
_cooldown_loaded: bool = False


def _load_cooldown() -> None:
    """Charge le curseur depuis le fichier JSON (une seule fois par processus)."""
    global _last_report_at, _cooldown_loaded
    if _cooldown_loaded:
        return
    _cooldown_loaded = True
    try:
        if _COOLDOWN_FILE.exists():
            raw = json.loads(_COOLDOWN_FILE.read_text())
            cutoff = datetime.now() - timedelta(minutes=REPORT_COOLDOWN_MIN)
            for project, iso in raw.items():
                try:
                    dt = datetime.fromisoformat(iso)
                    if dt > cutoff:  # ignorer les entrées expirées
                        _last_report_at[project] = dt
                except ValueError:
                    pass
    except Exception:
        pass  # cooldown.json corrompu ou absent — on repart de zéro


def _save_cooldown() -> None:
    """Persiste le curseur dans cooldown.json."""
    try:
        _COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {p: dt.isoformat() for p, dt in _last_report_at.items()}
        _COOLDOWN_FILE.write_text(json.dumps(data))
    except Exception:
        pass  # non-bloquant


# ── API publique ───────────────────────────────────────────────────────────────

def update_memories_from_session(
    session_data: Dict[str, Any],
    llm: Optional[Any] = None,
    memory_dir: Optional[Path] = None,
    commit_message: Optional[str] = None,
    trigger: str = "screen_lock",
    diff_summary: Optional[str] = None,
) -> None:
    """
    Met à jour la mémoire de session et génère un rapport si nécessaire.

    Le LLM n'est utilisé que pour les triggers 'commit' et 'manual'.
    Pour 'screen_lock' et 'user_idle', le fallback déterministe est appliqué
    directement — plus honnête et sans risque d'hallucination.

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

    _update_projects(base_dir, session_data)

    # Moteur de faits : observe la session et tente une promotion
    try:
        engine = get_fact_engine()
        new_facts = engine.observe_session(session_data)
        if new_facts:
            print(f"[Facts] {len(new_facts)} nouveau(x) fait(s) consolidé(s)")
    except Exception as exc:
        print(f"[Facts] Erreur observe_session : {exc}")

    project  = session_data.get("active_project") or "inconnu"
    duration = session_data.get("duration_min", 0)

    # Vérifie si un rapport est nécessaire
    should_write = (duration >= 15 or trigger == "commit")
    if not should_write:
        _update_index(base_dir)
        return

    # Curseur anti-doublon — pas deux rapports en moins de REPORT_COOLDOWN_MIN
    # pour le même projet, sauf sur commit (unité de travail explicite).
    if trigger != "commit":
        last = _last_report_at.get(project)
        if last is not None:
            elapsed = (datetime.now() - last).total_seconds() / 60
            if elapsed < REPORT_COOLDOWN_MIN:
                _update_index(base_dir)
                return

    # LLM uniquement sur commit — seul trigger avec assez de signal.
    # screen_lock, user_idle, manual → fallback déterministe toujours.
    effective_llm = llm if trigger == "commit" else None

    _write_session_report(
        base_dir,
        session_data,
        llm=effective_llm,
        commit_message=commit_message,
        trigger=trigger,
        diff_summary=diff_summary,
    )

    # Avance le curseur après écriture réussie et le persiste sur disque
    _last_report_at[project] = datetime.now()
    _save_cooldown()

    _update_index(base_dir)


def load_memory_context(memory_dir: Optional[Path] = None) -> str:
    """Fallback legacy : lit projects.md uniquement (habits.md = bruit pur)."""
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    parts = []
    for filename in ("projects.md", "preferences.md"):
        path = base_dir / filename
        if path.exists():
            parts.append(path.read_text())
    return "\n---\n".join(parts)[:2000]


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


def read_head_sha(git_root: Path) -> Optional[str]:
    """Lit le SHA courant de HEAD. Retourne None si indisponible."""
    try:
        head_file = git_root / ".git" / "HEAD"
        if not head_file.exists():
            gitfile = git_root / ".git"
            if gitfile.is_file():
                content = gitfile.read_text().strip()
                if content.startswith("gitdir:"):
                    gitdir = Path(content[7:].strip())
                    head_file = gitdir / "HEAD"

        if not head_file.exists():
            return None

        ref = head_file.read_text().strip()
        if ref.startswith("ref: "):
            ref_path = git_root / ".git" / ref[5:]
            if not ref_path.exists():
                return None
            return ref_path.read_text().strip()
        return ref if len(ref) == 40 else None
    except Exception:
        return None


def read_commit_message(git_root: Path) -> Optional[str]:
    """Lit le message du dernier commit depuis COMMIT_EDITMSG."""
    commit_msg_file = git_root / ".git" / "COMMIT_EDITMSG"
    try:
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
    llm: Optional[Any],
    commit_message: Optional[str],
    trigger: str,
    diff_summary: Optional[str] = None,
) -> None:
    """
    Journal quotidien : un seul fichier par jour (YYYY-MM-DD.md).
    Chaque session ajoute une section ## HH:MM en bas du fichier.
    Plus de fichiers -2, -3, -4...
    """
    now      = datetime.now()
    today    = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    sessions_dir = base_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    journal_file = sessions_dir / f"{today}.md"

    project     = session.get("active_project") or "inconnu"
    duration    = session.get("duration_min", 0)
    task        = session.get("probable_task", "general")
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
            print(f"[Memory] Erreur résumé LLM: {exc}")
            body = _deterministic_summary(
                duration, task, focus, friction, top_files, files_count, commit_message,
            )
    else:
        body = _deterministic_summary(
            duration, task, focus, friction, top_files, files_count, commit_message,
        )

    # En-tête de section : ## HH:MM — coding, 45 min
    task_labels = {
        "coding":   "développement",
        "debug":    "débogage",
        "writing":  "rédaction",
        "browsing": "navigation",
    }
    section_header = f"## {time_str} — {task_labels.get(task, task)}, {duration} min"

    entry = f"\n{section_header}\n{body.strip()}\n"

    if journal_file.exists():
        # Append au journal existant
        journal_file.open("a", encoding="utf-8").write(entry)
    else:
        # Créer le journal du jour avec en-tête
        header = f"# Journal Pulse — {today}\n"
        journal_file.write_text(header + entry, encoding="utf-8")


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
Dis ce qui a été livré et pourquoi — pas comment ni les détails techniques.
Si le message de commit est explicite, reformule-le naturellement.
N'invente aucun fait absent des données ci-dessus."""

    return _llm_complete(llm, prompt, max_tokens=120)


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
        parts.append(f"Commit : « {commit_message.splitlines()[0]} ».")

    # Fichier principal touché
    if top_files:
        main_file = top_files[0]
        if len(top_files) > 1:
            others = f" (+{len(top_files) - 1})"
        else:
            others = ""
        parts.append(f"Fichier principal : {main_file}{others}.")
    elif files_count:
        parts.append(f"{files_count} fichier(s) modifié(s).")

    # Focus et friction
    if focus_str:
        parts.append(focus_str.capitalize() + ".")
    if friction >= 0.7:
        parts.append("Friction élevée.")

    # Fallback si rien à dire
    if not parts:
        parts.append(f"Session de {duration} min.")

    return " ".join(parts)


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


# ── Projets et habitudes ──────────────────────────────────────────────────────

def _update_projects(base_dir: Path, session: Dict[str, Any]) -> None:
    project = session.get("active_project")
    if not project:
        return

    projects_file = base_dir / "projects.md"
    current  = _parse_project_sections(projects_file)
    today    = datetime.now().strftime("%Y-%m-%d")
    duration = session.get("duration_min", 0)
    task     = session.get("probable_task", "general")

    entry = current.get(project)
    if entry is None:
        current[project] = {"first_session": today, "last_session": today,
                             "last_duration": duration, "task": task}
    else:
        entry["last_session"]  = today
        entry["last_duration"] = duration
        entry["task"]          = task

    lines = ["# Projets\n"]
    for name in sorted(current):
        item = current[name]
        lines.extend([
            "", f"## {name}", "",
            f"- Première session : {item['first_session']}",
            f"- Dernière session : {item['last_session']} ({item['last_duration']} min, {item['task']})",
            f"- Type de travail détecté : {item['task']}",
        ])
    projects_file.write_text("\n".join(lines).strip() + "\n")


def _update_index(base_dir: Path) -> None:
    index_file = base_dir / "MEMORY.md"
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

    for raw_line in projects_file.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_name = line[3:]
            result[current_name] = {}
        elif current_name and line.startswith("- Première session : "):
            result[current_name]["first_session"] = line.split(": ", 1)[1]
        elif current_name and line.startswith("- Dernière session : "):
            value = line.split(": ", 1)[1]
            date_part, details = _split_last_session(value)
            result[current_name]["last_session"]  = date_part
            result[current_name]["last_duration"] = details["duration"]
            result[current_name]["task"]           = details["task"]
        elif current_name and line.startswith("- Type de travail détecté : "):
            result[current_name]["task"] = line.split(": ", 1)[1]

    return result


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


def _llm_complete(llm: Any, prompt: str, max_tokens: int = 150) -> str:
    if hasattr(llm, "complete"):
        return llm.complete(prompt, max_tokens=max_tokens)
    raise TypeError("LLM provider incompatible")
