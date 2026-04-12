"""
Port de referenceBaselines.ts (Cortex) — baselines de référence par type de fichier
et multiplicateurs par langage.
"""

from dataclasses import dataclass
from typing import Literal


# ── TYPES ──────────────────────────────────────────────────────────────────────

@dataclass
class Percentiles:
    p25: float
    p90: float


@dataclass
class ProjectBaselines:
    complexity:           Percentiles
    complexity_mean:      Percentiles
    cognitive_complexity: Percentiles
    function_size:        Percentiles
    function_size_mean:   Percentiles
    depth:                Percentiles
    params:               Percentiles
    churn:                Percentiles
    fan_in:               Percentiles


@dataclass
class LanguageMultipliers:
    complexity:           float = 1.0
    cognitive_complexity: float = 1.0
    function_size:        float = 1.0
    depth:                float = 1.0
    churn:                float = 1.0
    params:               float = 1.0
    fan_in:               float = 1.0


FileType = Literal[
    "entrypoint", "component", "service",
    "parser", "utility", "config", "generic"
]


# ── BASELINES DE RÉFÉRENCE GÉNÉRIQUES ──────────────────────────────────────────
# Construites à partir de distributions observées sur projets Python/TS de taille moyenne.

REFERENCE_BASELINES = ProjectBaselines(
    complexity           = Percentiles(p25=3,   p90=12),
    complexity_mean      = Percentiles(p25=1.5, p90=5),
    cognitive_complexity = Percentiles(p25=4,   p90=30),
    function_size        = Percentiles(p25=15,  p90=60),
    function_size_mean   = Percentiles(p25=8,   p90=30),
    depth                = Percentiles(p25=1,   p90=4),
    params               = Percentiles(p25=2,   p90=5),
    churn                = Percentiles(p25=1,   p90=10),
    fan_in               = Percentiles(p25=1,   p90=10),
)


# ── SURCHARGES PAR TYPE DE FICHIER ─────────────────────────────────────────────

_OVERRIDES: dict[FileType, dict] = {
    "entrypoint": {
        "complexity":           Percentiles(p25=8,  p90=40),
        "cognitive_complexity": Percentiles(p25=10, p90=80),
        "function_size":        Percentiles(p25=30, p90=200),
        "function_size_mean":   Percentiles(p25=15, p90=80),
    },
    "service": {
        "complexity":           Percentiles(p25=4,  p90=18),
        "cognitive_complexity": Percentiles(p25=6,  p90=40),
        "function_size":        Percentiles(p25=20, p90=80),
        "function_size_mean":   Percentiles(p25=12, p90=40),
        "churn":                Percentiles(p25=2,  p90=15),
    },
    "parser": {
        "complexity":           Percentiles(p25=6,  p90=25),
        "cognitive_complexity": Percentiles(p25=8,  p90=50),
        "function_size":        Percentiles(p25=25, p90=100),
        "function_size_mean":   Percentiles(p25=15, p90=50),
        "depth":                Percentiles(p25=2,  p90=6),
    },
    "utility": {
        "complexity":           Percentiles(p25=1,  p90=6),
        "cognitive_complexity": Percentiles(p25=1,  p90=12),
        "function_size":        Percentiles(p25=8,  p90=30),
        "function_size_mean":   Percentiles(p25=5,  p90=20),
    },
    "config": {
        "complexity":           Percentiles(p25=1,  p90=6),
        "cognitive_complexity": Percentiles(p25=1,  p90=10),
        "function_size":        Percentiles(p25=5,  p90=40),
        "function_size_mean":   Percentiles(p25=3,  p90=20),
    },
    "component": {},
    "generic":   {},
}


# ── MULTIPLICATEURS PAR LANGAGE ─────────────────────────────────────────────────

_LANGUAGE_MULTIPLIERS: dict[str, LanguageMultipliers] = {
    "py":  LanguageMultipliers(),   # Python — neutre, AST précis
    "ts":  LanguageMultipliers(),   # TypeScript pur — neutre
    "js":  LanguageMultipliers(),   # JavaScript pur — neutre
    "mjs": LanguageMultipliers(),
    # TSX/JSX : ternaires de style inline gonflent cx artificiellement
    "tsx": LanguageMultipliers(complexity=0.80, cognitive_complexity=0.75),
    "jsx": LanguageMultipliers(complexity=0.85, cognitive_complexity=0.80),
}

_NEUTRAL = LanguageMultipliers()


# ── DÉTECTION DU TYPE DE FICHIER ───────────────────────────────────────────────

_EXACT_NAMES: dict[str, FileType] = {
    "app.py": "entrypoint", "main.py": "entrypoint",
    "app.ts": "entrypoint", "main.ts": "entrypoint",
    "index.ts": "entrypoint", "index.js": "entrypoint",
    "types.ts": "config", "types.py": "config",
    "constants.py": "config", "settings.py": "config",
    "config.py": "config",
}

_NAME_FRAGMENTS: list[tuple[str, FileType]] = [
    # config
    ("baseline",   "config"),
    ("reference",  "config"),
    ("constants",  "config"),
    ("fixtures",   "config"),
    ("defaults",   "config"),
    ("thresholds", "config"),
    # parser
    ("parser",     "parser"),
    ("lexer",      "parser"),
    ("analyzer",   "parser"),
    # service
    ("service",    "service"),
    ("store",      "service"),
    ("engine",     "service"),
    ("manager",    "service"),
    ("handler",    "service"),
    ("controller", "service"),
    ("scanner",    "service"),
    ("watcher",    "service"),
    ("router",     "service"),
    ("churn",      "service"),
    # utility
    ("util",       "utility"),
    ("helper",     "utility"),
    ("common",     "utility"),
    ("format",     "utility"),
    ("transform",  "utility"),
]


def detect_file_type(file_path: str) -> FileType:
    """Détecte le type de fichier à partir de son chemin."""
    name  = file_path.split("/")[-1].lower()
    ext   = name.split(".")[-1] if "." in name else ""
    parts = file_path.lower().split("/")

    # 1. Nom exact connu
    if name in _EXACT_NAMES:
        return _EXACT_NAMES[name]

    # 2. Préfixe config
    if name.startswith("config") or name.endswith((".config.ts", ".config.js", ".config.py")):
        return "config"

    # 3. Fragments dans le nom
    for fragment, ftype in _NAME_FRAGMENTS:
        if fragment in name:
            return ftype

    # 4. Dossier partagé → utility
    if any(p in parts for p in ("shared", "lib", "utils", "helpers")):
        return "utility"

    return "generic"


def get_reference_baselines(file_path: str) -> ProjectBaselines:
    """Retourne les baselines de référence ajustées pour ce type de fichier."""
    file_type = detect_file_type(file_path)
    overrides = _OVERRIDES.get(file_type, {})

    import copy
    result = copy.deepcopy(REFERENCE_BASELINES)
    for field_name, value in overrides.items():
        setattr(result, field_name, value)

    return result


def get_language_multipliers(file_path: str) -> LanguageMultipliers:
    """Retourne les multiplicateurs de score pour l'extension de ce fichier."""
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return _LANGUAGE_MULTIPLIERS.get(ext, _NEUTRAL)


def compute_project_baselines(all_metrics: list[dict]) -> ProjectBaselines:
    """
    Calcule les baselines p25/p90 à partir des métriques brutes d'un projet entier.
    `all_metrics` est une liste de dicts avec les clés de RawMetrics.
    """
    def percentile(values: list[float], p: int) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = max(0, int(len(sorted_vals) * p / 100) - 1)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

    fields = [
        "complexity", "complexity_mean", "cognitive_complexity",
        "function_size", "function_size_mean",
        "depth", "params", "churn", "fan_in",
    ]

    kwargs = {}
    for f in fields:
        values = [float(m.get(f, 0)) for m in all_metrics]
        kwargs[f] = Percentiles(p25=percentile(values, 25), p90=percentile(values, 90))

    return ProjectBaselines(**kwargs)
