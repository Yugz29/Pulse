from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


MEMORY_DIR = Path.home() / ".pulse" / "memory"


def update_memories_from_session(
    session_data: Dict[str, Any],
    llm: Optional[Any] = None,
    memory_dir: Optional[Path] = None,
) -> None:
    base_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    _update_projects(base_dir, session_data)
    _update_habits(base_dir, session_data)

    if llm and session_data.get("duration_min", 0) > 20:
        _write_session_summary(base_dir, session_data, llm)

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


def _update_projects(base_dir: Path, session: Dict[str, Any]) -> None:
    project = session.get("active_project")
    if not project:
        return

    projects_file = base_dir / "projects.md"
    current = _parse_project_sections(projects_file)
    today = datetime.now().strftime("%Y-%m-%d")
    duration = session.get("duration_min", 0)
    task = session.get("probable_task", "general")

    entry = current.get(project)
    if entry is None:
        current[project] = {
            "first_session": today,
            "last_session": today,
            "last_duration": duration,
            "task": task,
        }
    else:
        entry["last_session"] = today
        entry["last_duration"] = duration
        entry["task"] = task

    lines = ["# Projets\n"]
    for name in sorted(current):
        item = current[name]
        lines.extend(
            [
                "",
                "## {0}".format(name),
                "",
                "- Première session : {0}".format(item["first_session"]),
                "- Dernière session : {0} ({1} min, {2})".format(
                    item["last_session"], item["last_duration"], item["task"]
                ),
                "- Type de travail détecté : {0}".format(item["task"]),
            ]
        )

    projects_file.write_text("\n".join(lines).strip() + "\n")


def _update_habits(base_dir: Path, session: Dict[str, Any]) -> None:
    habits_file = base_dir / "habits.md"
    if not habits_file.exists():
        habits_file.write_text("# Habitudes\n\n")

    apps = [app for app in session.get("recent_apps", []) if app][:3]
    task = session.get("probable_task", "general")
    slot = _time_slot(datetime.now().hour)
    line = "- Session {0} : {1}".format(slot, task)
    if apps:
        line += " avec {0}".format(", ".join(apps))

    existing_lines = [
        existing.strip()
        for existing in habits_file.read_text(encoding="utf-8").splitlines()
        if existing.strip()
    ]
    if existing_lines and existing_lines[-1] == line:
        return

    with habits_file.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _write_session_summary(base_dir: Path, session: Dict[str, Any], llm: Any) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    summary_file = base_dir / "sessions" / "{0}.md".format(today)
    summary_file.parent.mkdir(parents=True, exist_ok=True)

    if summary_file.exists():
        return

    prompt = (
        "Résume cette session de travail en 2-3 phrases concises.\n\n"
        "Projet : {0}\n"
        "Durée : {1} minutes\n"
        "Tâche principale : {2}\n"
        "Fichiers modifiés : {3}\n"
        "Friction détectée : {4:.1f}/1.0\n\n"
        "Sois factuel et direct. Pas de préambule."
    ).format(
        session.get("active_project", "inconnu"),
        session.get("duration_min", 0),
        session.get("probable_task", "inconnue"),
        session.get("files_changed", 0),
        float(session.get("max_friction", 0.0)),
    )

    try:
        summary = _llm_complete(llm, prompt)
    except Exception as exc:
        print("[Memory] Erreur résumé LLM: {0}".format(exc))
        return

    content = "\n".join(
        [
            "---",
            "date: {0}".format(today),
            "project: {0}".format(session.get("active_project", "")),
            "duration_min: {0}".format(session.get("duration_min", 0)),
            "---",
            "",
            summary.strip(),
            "",
        ]
    )
    summary_file.write_text(content)


def _update_index(base_dir: Path) -> None:
    index_file = base_dir / "MEMORY.md"
    entries = []

    for md_file in sorted(base_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        entries.append("- [{0}]({1})".format(md_file.stem, md_file.name))

    content = "# Index mémoire Pulse\n\n"
    content += "\n".join(entries)
    if entries:
        content += "\n"
    index_file.write_text(content)


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
            result[current_name]["last_session"] = date_part
            result[current_name]["last_duration"] = details["duration"]
            result[current_name]["task"] = details["task"]
        elif current_name and line.startswith("- Type de travail détecté : "):
            result[current_name]["task"] = line.split(": ", 1)[1]

    return result


def _split_last_session(value: str) -> tuple:
    if "(" not in value or ")" not in value:
        return value, {"duration": 0, "task": "general"}

    date_part, rest = value.split("(", 1)
    details = rest.rstrip(")")
    duration = 0
    task = "general"

    if "," in details:
        duration_part, task_part = details.split(",", 1)
        duration_tokens = duration_part.strip().split()
        if duration_tokens and duration_tokens[0].isdigit():
            duration = int(duration_tokens[0])
        task = task_part.strip()

    return date_part.strip(), {"duration": duration, "task": task}


def _time_slot(hour: int) -> str:
    if 6 <= hour < 12:
        return "matin"
    if 12 <= hour < 18:
        return "après-midi"
    return "soir"


def _llm_complete(llm: Any, prompt: str) -> str:
    if hasattr(llm, "complete"):
        return llm.complete(prompt, max_tokens=200)
    raise TypeError("LLM provider incompatible")
