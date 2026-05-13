"""Deterministic, bounded facts about the latest commit.

The digest is meant to enrich lightweight local summaries without exposing raw
diff lines to an LLM. It reads only the latest commit and emits short factual
bullets derived from filenames and added/removed diff metadata.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


MAX_BULLETS = 6
MAX_BULLET_CHARS = 120
MAX_FILES = 8
MAX_SYMBOLS = 4
MAX_DIFF_LINES = 300
TIMEOUT_SEC = 2


def read_commit_change_digest(project_root: str | Path) -> str:
    root = Path(project_root)
    if not root.exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "show", "HEAD", "--format=format:", "-U2"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    raw = "\n".join(result.stdout.splitlines()[:MAX_DIFF_LINES])
    return build_change_digest_from_diff(raw)


def build_change_digest_from_diff(raw_diff: str) -> str:
    if not raw_diff.strip():
        return ""

    state = _DiffState()
    current_file = None
    current_created = False
    for line in raw_diff.splitlines()[:MAX_DIFF_LINES]:
        if line.startswith("diff --git "):
            current_file = _file_from_diff_header(line)
            current_created = False
            if current_file:
                state.touch_file(current_file)
            continue
        if current_file is None:
            continue
        if line.startswith("new file mode") or line.startswith("--- /dev/null"):
            current_created = True
            state.created_files.add(current_file)
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue

        added = line[1:].strip()
        if not added:
            continue
        state.observe_added_line(current_file, added, created=current_created)

    return "\n".join(_bounded_bullets(state.bullets()))


class _DiffState:
    def __init__(self) -> None:
        self.files: list[str] = []
        self.created_files: set[str] = set()
        self.routes: list[tuple[str, str]] = []
        self.tests_touched = False
        self.dashboard_touched = False
        self.bridge_touched = False
        self.models: list[str] = []
        self.services: list[str] = []
        self.symbols: list[str] = []
        self.status_privacy_checks = False
        self.provider_decoupled = False
        self.log_noise_bounded = False
        self.log_retention_cleanup = False
        self.heavy_warmup_gated = False
        self.embeddings_disabled = False

    def touch_file(self, file_path: str) -> None:
        if file_path not in self.files and len(self.files) < MAX_FILES:
            self.files.append(file_path)
        name = Path(file_path).name
        lower = file_path.lower()
        if "test" in lower or "/tests/" in lower or name.endswith("Tests.swift"):
            self.tests_touched = True
        if name.startswith("Dashboard") or "Dashboard" in file_path:
            self.dashboard_touched = True
        if name.startswith("DaemonBridge"):
            self.bridge_touched = True
        if name.endswith("Service.swift") or name.endswith("Worker.swift"):
            _append_unique(self.services, Path(name).stem, limit=3)
        if "log_retention" in lower or "retention" in lower:
            self.log_retention_cleanup = True
        if "lifecycle_policy" in lower or "runtime_orchestrator" in lower or "runtime_daemon_routes" in lower:
            self.heavy_warmup_gated = True
        if "embedding_policy" in lower or "vector_store" in lower:
            self.embeddings_disabled = True

    def observe_added_line(self, file_path: str, added: str, *, created: bool) -> None:
        lower_added = added.lower()
        route = _extract_route(added)
        if route and route not in self.routes:
            self.routes.append(route)

        model_name = _extract_model_name(added)
        if model_name:
            _append_unique(self.models, model_name, limit=4)

        symbol = _extract_symbol_name(added)
        if symbol:
            _append_unique(self.symbols, symbol, limit=MAX_SYMBOLS)

        if "AppleFoundationProvider" in added and ("import" in added or "self.apple" in added):
            self.provider_decoupled = True
        if 'assertNotIn("prompt"' in added or 'assertNotIn("text"' in added:
            self.status_privacy_checks = True
        if (
            "routine" in lower_added
            or "access" in lower_added
            or "maxbytes" in lower_added
            or "backupcount" in lower_added
            or "bounded" in lower_added
        ) and ("log" in lower_added or "logging" in lower_added or "werkzeug" in lower_added):
            self.log_noise_bounded = True
        if "retention" in lower_added and ("log" in lower_added or "cleanup" in lower_added or "delete" in lower_added):
            self.log_retention_cleanup = True
        if "pulse_heavy_llm_autowarm" in lower_added or "autowarm" in lower_added or "warmup" in lower_added:
            self.heavy_warmup_gated = True
        if "pulse_embeddings_enabled" in lower_added or "embeddings_enabled" in lower_added:
            self.embeddings_disabled = True

    def bullets(self) -> list[str]:
        bullets: list[str] = []
        high_level = False
        if self.log_noise_bounded:
            bullets.append("borne les journaux du daemon et réduit le bruit des accès routiniers")
            high_level = True
        if self.log_retention_cleanup:
            bullets.append("ajoute un nettoyage sûr de rétention des logs")
            high_level = True
        if self.heavy_warmup_gated:
            bullets.append("évite le warmup du modèle lourd sur les flux lightweight")
            high_level = True
        if self.embeddings_disabled:
            bullets.append("désactive les embeddings par défaut pour éviter un chargement implicite")
            high_level = True
        if not high_level:
            for method, path in self.routes[:2]:
                bullets.append(f"ajoute une route {method} {path}")
            if self.services:
                bullets.append("ajoute un service ou worker local " + ", ".join(self.services[:2]))
        if self.dashboard_touched:
            bullets.append("affiche l'état Apple Foundation dans le Dashboard Système")
        if self.bridge_touched:
            bullets.append("étend le bridge Swift/daemon pour les requêtes lightweight")
        if self.tests_touched:
            bullets.append("ajoute des tests de régression ou de garde-fous")
        if self.status_privacy_checks:
            bullets.append("vérifie que le statut n'expose ni prompt ni texte généré")
        if self.provider_decoupled:
            bullets.append("décâble le provider Apple Foundation expérimental du router")
        created = [Path(path).name for path in self.files if path in self.created_files and not _is_test_file(path)]
        if created and not high_level:
            bullets.append("ajoute " + ", ".join(created[:3]))
        return bullets


def _bounded_bullets(candidates: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = _sanitize_bullet(candidate)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(f"- {clean[:MAX_BULLET_CHARS].rstrip()}")
        if len(result) >= MAX_BULLETS:
            break
    return result


def _sanitize_bullet(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip())
    text = text.replace("`", "")
    text = re.sub(r"[{}();=]", "", text)
    return text.strip(" -")


def _file_from_diff_header(line: str) -> str | None:
    parts = line.split(" b/", 1)
    if len(parts) != 2:
        return None
    return parts[1].strip()


def _extract_route(line: str) -> tuple[str, str] | None:
    path_match = re.search(r'["\'](/[^"\']+)["\']', line)
    if not path_match:
        return None
    path = path_match.group(1)
    if not path.startswith(("/llm/", "/ask", "/mcp/", "/context", "/daemon", "/debug", "/scoring")):
        return None
    method = "GET"
    method_match = re.search(r"methods\s*=\s*\[[^\]]*['\"]([A-Z]+)['\"]", line)
    if method_match:
        method = method_match.group(1)
    elif ".post" in line.lower() or "method=\"POST\"" in line or "httpMethod = \"POST\"" in line:
        method = "POST"
    return method, path


def _extract_model_name(line: str) -> str | None:
    match = re.search(r"\b(?:struct|class|dataclass)\s+([A-Z][A-Za-z0-9_]+)", line)
    if match:
        return match.group(1)
    return None


def _is_test_file(path: str) -> bool:
    lower = str(path or "").lower()
    return "/tests/" in lower or lower.startswith("tests/") or "test_" in lower or lower.endswith("tests.swift")


def _extract_symbol_name(line: str) -> str | None:
    patterns = [
        r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"\bfunc\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"\bfinal\s+class\s+([A-Z][A-Za-z0-9_]*)",
        r"\bclass\s+([A-Z][A-Za-z0-9_]*)",
        r"\bstruct\s+([A-Z][A-Za-z0-9_]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            return match.group(1)
    return None


def _append_unique(values: list[str], value: str, *, limit: int) -> None:
    if value and value not in values and len(values) < limit:
        values.append(value)
