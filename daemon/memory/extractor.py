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
  pour le même projet. Inspiré du pattern lastMemoryMessageUuid de
  extractMemories.ts (Leak Claude).

Qualité LLM
────────────
  Prompt inspiré de awaySummary.ts (Leak Claude) :
  1-3 phrases, tâche de haut niveau (pas les détails d'implémentation),
  prochaine étape concrète. Le LLM est désactivé pour les triggers
  screen_lock / user_idle — le fallback déterministe est plus honnête.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


MEMORY_DIR = Path.home() / ".pulse" / "memory"

# Cooldown minimum entre deux rapports pour un même projet (en minutes).
# Inspiré du cursor pattern de extractMemories.ts — évite les 46 rapports/jour.
REPORT_COOLDOWN_MIN = 30

# Suffixes et patterns à exclure des top_files
_NOISE_SUFFIXES = {
    ".tmp", ".swp", ".swo", ".orig", ".bak",
    ".xcuserstate", ".DS_Store", "~",
}
_NOISE_PATTERNS = {
    "COMMIT_EDITMSG", "MERGE_MSG", "FETCH_HEAD", "ORIG_HEAD",
    "packed-refs", "index",
}
_NOISE_SUBSTRINGS = {".sb-", "__pycache__", "DerivedData", "xcuserdata"}

# Curseur anti-doublon : {project_name: datetime du dernier rapport}
_last_report_at: Dict[str, datetime] = {}


# ── API publique ───────────────────────────────────────────────────────────────

def update_memories_from_session(
    session_data: Dict[str, Any],
    llm: Optional[Any] = None,
    memory_dir: Optional[Path] = None,
    commit_message: Optional[str] = None,
    trigger: str = "screen_lock",
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

    _update_projects(base_dir, session_data)
    _update_habits(base_dir, session_data)

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

    # LLM uniquement sur commit et manual — désactivé pour idle/screen_lock
    effective_llm = llm if trigger in ("commit", "manual") else None

    _write_session_report(
        base_dir,
        session_data,
        llm=effective_llm,
        commit_message=commit_message,
        trigger=trigger,
    )

    # Avance le curseur après écriture réussie
    _last_report_at[project] = datetime.now()

    _update_index(base_dir)


def load_memory_context(memory_dir: Optional[Path] = None) -> str:
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    index_file = base_dir / "MEMORY.md"
    if not index_file.exists():
        return ""

    parts = [index_file.read_text()]
    for filename in ("habits.md", "projects.md", "preferences.md"):
        path = base_dir / filename
        if path.exists():
            parts.append("\n---\n" + path.read_text())

    return "\n".join(parts)[:4000]


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
) -> None:
    now      = datetime.now()
    today    = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    sessions_dir = base_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Nom de fichier unique
    summary_file = sessions_dir / f"{today}.md"
    if summary_file.exists():
        idx = 2
        while True:
            candidate = sessions_dir / f"{today}-{idx}.md"
            if not candidate.exists():
                summary_file = candidate
                break
            idx += 1

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
                apps, top_files, files_count, commit_message, trigger,
            )
        except Exception as exc:
            print(f"[Memory] Erreur résumé LLM: {exc}")
            body = _deterministic_summary(
                project, duration, task, focus, friction,
                top_files, files_count, commit_message,
            )
    else:
        body = _deterministic_summary(
            project, duration, task, focus, friction,
            top_files, files_count, commit_message,
        )

    trigger_label = {
        "commit":      "commit git",
        "screen_lock": "fin de session",
        "user_idle":   "pause détectée",
        "manual":      "manuel",
    }.get(trigger, trigger)

    content = "\n".join([
        "---",
        f"date: {today}",
        f"time: {time_str}",
        f"project: {project}",
        f"duration_min: {duration}",
        f"task: {task}",
        f"focus: {focus}",
        f"trigger: {trigger_label}",
        *([ f"commit: {commit_message.splitlines()[0]}" ] if commit_message else []),
        "---",
        "",
        body.strip(),
        "",
    ])
    summary_file.write_text(content, encoding="utf-8")


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
    trigger: str,
) -> str:
    """
    Prompt inspiré de awaySummary.ts (Leak Claude) :
    - 1-3 phrases maximum
    - Tâche de haut niveau (ce qu'on construit/débogue), pas les détails d'implémentation
    - Prochaine étape concrète si disponible
    - Pas de récapitulatif de statut, pas de résumé de commits

    Le modèle reçoit uniquement des faits vérifiables — aucune zone blanche
    à remplir, ce qui évite les hallucinations sur les petits modèles.
    """
    facts: List[str] = [
        f"Projet : {project}",
        f"Durée : {duration} minutes",
    ]

    if commit_message:
        facts.append(f"Commit livré : \"{commit_message.splitlines()[0]}\"")

    if top_files:
        facts.append(f"Fichiers modifiés : {', '.join(top_files[:5])}")
    elif files_count:
        facts.append(f"Fichiers modifiés : {files_count}")

    if apps:
        facts.append(f"Outils : {', '.join(apps[:4])}")

    if friction >= 0.7:
        facts.append("Friction : élevée (allers-retours fréquents sur les mêmes fichiers)")

    facts_block = "\n".join(f"- {f}" for f in facts)

    prompt = f"""\
Voici les données factuelles de la session de travail :

{facts_block}

Écris exactement 1 à 3 phrases courtes en français.
Commence par la tâche de haut niveau — ce qui était en cours de construction ou de débogage, pas les détails d'implémentation.
Si c'est évident depuis le commit, mentionne ce qui a été livré.
Ne résume pas le statut, ne liste pas les fichiers, n'invente rien qui ne soit pas dans les données ci-dessus."""

    return _llm_complete(llm, prompt, max_tokens=150)


def _deterministic_summary(
    project: str,
    duration: int,
    task: str,
    focus: str,
    friction: float,
    top_files: List[str],
    files_count: int,
    commit_message: Optional[str],
) -> str:
    """Résumé honnête sans LLM — utilisé pour idle et screen_lock."""
    task_labels = {
        "coding":   "développement",
        "debug":    "débogage",
        "writing":  "rédaction",
        "browsing": "navigation",
    }
    task_str  = task_labels.get(task, task)
    focus_str = {
        "deep":      "focus profond",
        "scattered": "travail dispersé",
        "idle":      "session légère",
    }.get(focus, "focus normal")

    parts = [f"Session de {duration} min sur {project} — {task_str}, {focus_str}."]

    if commit_message:
        parts.append(f"Commit : « {commit_message.splitlines()[0]} ».")

    if top_files:
        parts.append(f"Fichiers : {', '.join(top_files[:4])}.")
    elif files_count:
        parts.append(f"{files_count} fichier(s) modifié(s).")

    if friction >= 0.7:
        parts.append("Forte friction détectée.")

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


def _update_habits(base_dir: Path, session: Dict[str, Any]) -> None:
    habits_file = base_dir / "habits.md"
    if not habits_file.exists():
        habits_file.write_text("# Habitudes\n\n")

    apps = [a for a in session.get("recent_apps", []) if a][:3]
    task = session.get("probable_task", "general")
    slot = _time_slot(datetime.now().hour)
    line = f"- Session {slot} : {task}"
    if apps:
        line += f" avec {', '.join(apps)}"

    existing = [l.strip() for l in habits_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    if existing and existing[-1] == line:
        return
    with habits_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


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
