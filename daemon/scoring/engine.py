"""
Moteur de scoring de risque de fichiers — port de riskScore.ts (Cortex).

Chaîne de parsers (du plus précis au moins précis) :
  1. ast builtin Python   → .py  (exact)
  2. tree-sitter          → .ts .tsx .js .jsx .swift .rs .go .java .kt .c .cpp .rb .cs ...
  3. regex                → fallback si tree-sitter non installé

Usage :
    from daemon.scoring import score_file
    result = score_file("/path/to/file.py")
    print(result.global_score, result.label)   # ex: 42.3, "medium"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .baselines import (
    ProjectBaselines,
    LanguageMultipliers,
    get_reference_baselines,
    get_language_multipliers,
)
from .churn import get_churn, get_git_root
from .parser_python import analyze_python_file
from .parser_python import FileMetrics  # type partagé
from . import parser_treesitter
from . import parser_regex


# ── INTERFACES ─────────────────────────────────────────────────────────────────

@dataclass
class RawMetrics:
    complexity:           float
    complexity_mean:      float
    cognitive_complexity: float
    function_size:        float
    function_size_mean:   float
    depth:                float
    params:               float
    churn:                float
    fan_in:               float


@dataclass
class ScoreDetails:
    complexity_score:           float
    cognitive_complexity_score: float
    function_size_score:        float
    churn_score:                float
    depth_score:                float
    param_score:                float
    fan_in_score:               float


@dataclass
class RiskScoreResult:
    file_path:     str
    language:      str
    global_score:  float       # 0–100
    hotspot_score: float       # complexity × churn, max ~150
    raw:           RawMetrics
    details:       ScoreDetails
    label:         str         # safe | low | medium | high | critical
    parser:        str         # ast | treesitter | regex | churn_only


# ── EXTENSIONS SUPPORTÉES ──────────────────────────────────────────────────────

_PYTHON_EXTS   = {".py"}
_REGEX_EXTS    = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".swift"}


# ── SEUILS ABSOLUS (port Cortex) ───────────────────────────────────────────────

_ABS_SAFE: dict[str, float] = {
    "complexity": 3, "complexity_mean": 2,
    "cognitive_complexity": 8,
    "function_size": 20, "function_size_mean": 15,
    "depth": 2, "params": 3, "churn": 3, "fan_in": 3,
}
_ABS_DANGER: dict[str, float] = {
    "complexity": 15, "complexity_mean": 8,
    "cognitive_complexity": 60,
    "function_size": 80, "function_size_mean": 40,
    "depth": 6, "params": 8, "churn": 20, "fan_in": 15,
}
_WEIGHTS: dict[str, float] = {
    "complexity": 0.28, "cognitive_complexity": 0.19,
    "function_size": 0.14, "depth": 0.14,
    "churn": 0.12, "params": 0.08, "fan_in": 0.05,
}


# ── SCORING ────────────────────────────────────────────────────────────────────

def clamped_score(value: float, safe: float, danger: float) -> float:
    if safe >= danger:
        return 100.0 if value > safe else 0.0
    if value <= safe:   return 0.0
    if value >= danger: return 100.0
    return (value - safe) / (danger - safe) * 100.0


def _adaptive_score(
    value: float, metric: str,
    baselines: Optional[ProjectBaselines],
    ref_baselines: Optional[ProjectBaselines],
) -> float:
    safe   = _ABS_SAFE[metric]
    danger = _ABS_DANGER[metric]
    if ref_baselines:
        ref    = getattr(ref_baselines, metric)
        safe   = max(safe,   ref.p25)
        danger = max(danger, ref.p90)
        if safe >= danger: danger = safe + 1
    if baselines:
        proj = getattr(baselines, metric)
        safe = max(safe, proj.p25)
        if safe >= danger: danger = safe + 1
    return clamped_score(value, safe, danger)


def _blended(
    max_m: str, mean_m: str, raw: RawMetrics,
    baselines, ref_baselines,
) -> float:
    return (
        _adaptive_score(getattr(raw, max_m),  max_m,  baselines, ref_baselines) * 0.65 +
        _adaptive_score(getattr(raw, mean_m), mean_m, baselines, ref_baselines) * 0.35
    )


def _label(score: float) -> str:
    if score < 20: return "safe"
    if score < 40: return "low"
    if score < 60: return "medium"
    if score < 80: return "high"
    return "critical"


# ── SÉLECTION DU PARSER ────────────────────────────────────────────────────────

def _parse(file_path: str) -> tuple[Optional[FileMetrics], str]:
    """
    Retourne (FileMetrics | None, parser_name).
    Ordre de priorité : ast > treesitter > regex.
    """
    ext = Path(file_path).suffix.lower()

    # 1. Python — ast builtin, le plus précis
    if ext in _PYTHON_EXTS:
        try:
            return analyze_python_file(file_path), "ast"
        except Exception:
            return None, "ast"

    # 2. tree-sitter — AST réel pour tous les langages supportés
    if parser_treesitter.is_available() and ext in parser_treesitter.supported_extensions():
        result = parser_treesitter.analyze_file(file_path)
        if result is not None:
            return result, "treesitter"

    # 3. Regex — fallback pour TS/JS/Swift si tree-sitter absent
    if ext in _REGEX_EXTS:
        try:
            return parser_regex.analyze_file_regex(file_path), "regex"
        except Exception:
            return None, "regex"

    return None, "none"


# ── MÉTRIQUES BRUTES ───────────────────────────────────────────────────────────

def _extract_raw(metrics: FileMetrics, churn: float, fan_in: float) -> RawMetrics:
    fns = metrics.functions
    if not fns:
        return RawMetrics(0, 0, 0, 0, 0, 0, 0, churn, fan_in)

    cx   = [f.cyclomatic_complexity for f in fns]
    cog  = [f.cognitive_complexity   for f in fns]
    sz   = [f.line_count             for f in fns]
    dep  = [f.max_depth              for f in fns]
    par  = [f.parameter_count        for f in fns]

    return RawMetrics(
        complexity           = float(max(cx)),
        complexity_mean      = float(sum(cx) / len(cx)),
        cognitive_complexity = float(max(cog)),
        function_size        = float(max(sz)),
        function_size_mean   = float(sum(sz) / len(sz)),
        depth                = float(max(dep)),
        params               = float(max(par)),
        churn                = churn,
        fan_in               = fan_in,
    )


# ── FAN-IN ─────────────────────────────────────────────────────────────────────

def _compute_fan_in(file_path: str, project_path: str | None) -> int:
    if not project_path or not os.path.isdir(project_path):
        return 0

    module_name = Path(file_path).stem
    count = 0
    extensions = {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs",
        ".swift", ".rs", ".go", ".java", ".kt", ".rb", ".cs",
    }
    patterns = [
        f"import {module_name}", f"from {module_name}",
        f'from "./{module_name}', f'from "../{module_name}',
        f'require("{module_name}', f'require(\'{module_name}',
    ]

    try:
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in {
                ".git", "node_modules", "__pycache__",
                ".venv", "venv", "dist", "build", "out",
                "DerivedData", ".build",
            }]
            for fname in files:
                if Path(fname).suffix not in extensions:
                    continue
                fpath = os.path.join(root, fname)
                if fpath == file_path:
                    continue
                try:
                    content = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                    if any(p in content for p in patterns):
                        count += 1
                except OSError:
                    pass
    except OSError:
        pass

    return count


# ── POINT D'ENTRÉE ─────────────────────────────────────────────────────────────

def score_file(
    file_path: str,
    project_path: str | None = None,
    baselines: Optional[ProjectBaselines] = None,
) -> RiskScoreResult:
    """
    Score un fichier.

    Args:
        file_path:    Chemin absolu du fichier.
        project_path: Racine du projet (git churn + fan-in). Auto-détecté si None.
        baselines:    Baselines projet pré-calculées (optionnel).

    Returns:
        RiskScoreResult — global_score ∈ [0, 100], label ∈ safe/low/medium/high/critical.
    """
    if not Path(file_path).is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    if project_path is None:
        project_path = get_git_root(file_path)

    ext = Path(file_path).suffix.lower()

    # Analyse statique
    metrics, parser_used = _parse(file_path)

    # Churn git
    churn  = float(get_churn(file_path, project_path) if project_path else 0)

    # Fan-in
    fan_in = float(_compute_fan_in(file_path, project_path))

    # Extension non supportée → score churn-only
    if metrics is None:
        language = ext.lstrip(".") or "unknown"
        raw = RawMetrics(0, 0, 0, 0, 0, 0, 0, churn, fan_in)
        ref = get_reference_baselines(file_path)
        churn_s = _adaptive_score(churn, "churn", baselines, ref)
        fi_s    = _adaptive_score(fan_in, "fan_in", baselines, ref)
        score   = churn_s * 0.70 + fi_s * 0.30
        return RiskScoreResult(
            file_path=file_path, language=language,
            global_score=round(score, 1), hotspot_score=0.0,
            raw=raw,
            details=ScoreDetails(0, 0, 0, round(churn_s, 1), 0, 0, round(fi_s, 1)),
            label=_label(score), parser="churn_only",
        )

    raw = _extract_raw(metrics, churn, fan_in)
    ref_baselines = get_reference_baselines(file_path)
    lang_mult: LanguageMultipliers = get_language_multipliers(file_path)

    cx_score  = _blended("complexity", "complexity_mean", raw, baselines, ref_baselines)
    cog_score = _adaptive_score(raw.cognitive_complexity, "cognitive_complexity", baselines, ref_baselines)
    sz_score  = _blended("function_size", "function_size_mean", raw, baselines, ref_baselines)
    dep_score = _adaptive_score(raw.depth,  "depth",  baselines, ref_baselines)
    ch_score  = _adaptive_score(raw.churn,  "churn",  baselines, ref_baselines)
    par_score = _adaptive_score(raw.params, "params", baselines, ref_baselines)
    fi_score  = _adaptive_score(raw.fan_in, "fan_in", baselines, ref_baselines)

    global_score = (
        cx_score  * _WEIGHTS["complexity"]           * lang_mult.complexity           +
        cog_score * _WEIGHTS["cognitive_complexity"] * lang_mult.cognitive_complexity +
        sz_score  * _WEIGHTS["function_size"]        * lang_mult.function_size        +
        dep_score * _WEIGHTS["depth"]                * lang_mult.depth                +
        ch_score  * _WEIGHTS["churn"]                * lang_mult.churn                +
        par_score * _WEIGHTS["params"]               * lang_mult.params               +
        fi_score  * _WEIGHTS["fan_in"]               * lang_mult.fan_in
    )

    hotspot_score = min(raw.complexity * raw.churn, 150.0)

    return RiskScoreResult(
        file_path     = file_path,
        language      = metrics.language,
        global_score  = round(global_score, 1),
        hotspot_score = round(hotspot_score, 1),
        raw           = raw,
        details       = ScoreDetails(
            complexity_score           = round(cx_score,  1),
            cognitive_complexity_score = round(cog_score, 1),
            function_size_score        = round(sz_score,  1),
            churn_score                = round(ch_score,  1),
            depth_score                = round(dep_score, 1),
            param_score                = round(par_score, 1),
            fan_in_score               = round(fi_score,  1),
        ),
        label  = _label(global_score),
        parser = parser_used,
    )


def _empty(file_path: str, language: str) -> RiskScoreResult:
    raw = RawMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0)
    det = ScoreDetails(0, 0, 0, 0, 0, 0, 0)
    return RiskScoreResult(
        file_path=file_path, language=language,
        global_score=0.0, hotspot_score=0.0,
        raw=raw, details=det, label="safe", parser="none",
    )
