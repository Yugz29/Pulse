"""
Parseur regex pour TypeScript, JavaScript et Swift.

Couvre les métriques clés sans dépendance externe :
- Détection des fonctions (déclarées, arrow, méthodes, closures Swift)
- Complexité cyclomatique (branches logiques)
- Complexité cognitive (pénalité d'imbrication, modèle SonarSource)
- Taille des fonctions (lignes entre accolades)
- Profondeur d'imbrication max
- Nombre de paramètres

Précision : ~80-85% vs ts-morph pour des projets standards.
Limite connue : les arrow functions imbriquées sont parfois fusionnées avec
leur parent si les accolades sont sur la même ligne. Acceptable pour le scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


# ── INTERFACES (réutilise celles de parser_python) ──────────────────────────

@dataclass
class FunctionMetrics:
    name:                  str
    start_line:            int
    line_count:            int
    cyclomatic_complexity: int
    cognitive_complexity:  int
    parameter_count:       int
    max_depth:             int


@dataclass
class FileMetrics:
    file_path:       str
    total_lines:     int
    total_functions: int
    functions:       list[FunctionMetrics] = field(default_factory=list)
    language:        str = "unknown"


# ── PATTERNS PAR LANGAGE ─────────────────────────────────────────────────────

# TypeScript / JavaScript
_TS_FUNC_PATTERNS = [
    # function foo(...)
    re.compile(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)'),
    # const foo = (...) => ou const foo = function(...)
    re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=>\s]+)\s*=>'),
    re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function\s*\(([^)]*)\)'),
    # méthode de classe : foo(...) { ou async foo(...) {
    re.compile(r'^\s*(?:public|private|protected|static|override|async|\s)*(\w+)\s*\(([^)]*)\)\s*(?::\s*\S+\s*)?\{'),
    # arrow function anonyme : () => { ou (x, y) => {
    re.compile(r'^\s*(?:const|let|var)\s+(\w+)\s*[=:]\s*(?:async\s+)?\([^)]*\)\s*(?::\s*\S+\s*)?=>'),
]

# Swift
_SWIFT_FUNC_PATTERNS = [
    # func foo(...) -> Type {
    re.compile(r'^\s*(?:@\w+\s+)*(?:public|private|internal|fileprivate|open|static|class|override|mutating|final|\s)*func\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)'),
    # init(...) {
    re.compile(r'^\s*(?:(?:public|private|internal|fileprivate|convenience|required)\s+)*init\s*\(([^)]*)\)'),
    # closure : { (params) -> Type in
    re.compile(r'^\s*\{?\s*\(([^)]*)\)\s*(?:->\s*\S+\s+)?in\s*$'),
    # computed property get/set
    re.compile(r'^\s*(get|set|willSet|didSet)\s*\{'),
]

# Branches qui augmentent la complexité cyclomatique (TS/JS et Swift)
_CYCLOMATIC_PATTERNS = re.compile(
    r'\b(?:if|else\s+if|elif|for|foreach|while|do|case|catch|catch\s+let|guard|switch'
    r'|&&|\|\||throw|throws|try|ternary|\?(?!\?))\b'
    r'|(?<!\?)\?(?!\?)'    # ternaire ? (pas ??)
    r'|\?\?'               # null-coalescing Swift/TS
)

# Nœuds qui augmentent la complexité cognitive avec pénalité d'imbrication
_COGNITIVE_NESTING = re.compile(
    r'^\s*(?:if|else\s+if|for|foreach|ForEach|while|do|switch|guard|with|try)\b'
)
_COGNITIVE_BREAK = re.compile(
    r'\b(?:if|else|for|foreach|ForEach|while|do|catch|switch|guard|throw|throws)\b'
    r'|&&|\|\||\?\?'
)

# Accolades ouvrantes/fermantes pour le suivi de profondeur
_OPEN_BRACE  = re.compile(r'\{')
_CLOSE_BRACE = re.compile(r'\}')

# Ligne de commentaire ou vide
_COMMENT_LINE = re.compile(r'^\s*(?://|/\*|\*|#)')


# ── EXTRACTION DES PARAMÈTRES ─────────────────────────────────────────────────

def _count_params(params_str: str) -> int:
    """Compte les paramètres dans une signature de fonction."""
    s = params_str.strip()
    if not s or s in ("void", "_"):
        return 0
    # Supprime les types génériques imbriqués genre Map<String, Int>
    s = re.sub(r'<[^>]*>', '', s)
    parts = [p.strip() for p in s.split(',') if p.strip()]
    # Exclut self/cls/this
    parts = [p for p in parts if not re.match(r'^(?:self|cls|this|_)\s*[:$]?$', p)]
    return len(parts)


# ── TRACKING DES BLOCS (accolades) ───────────────────────────────────────────

def _build_block_map(lines: list[str]) -> list[int]:
    """
    Pour chaque ligne, retourne la profondeur d'imbrication d'accolades.
    Utile pour délimiter les corps de fonctions.
    """
    depths = []
    depth = 0
    for line in lines:
        # Ignore les commentaires pour le comptage
        clean = re.sub(r'//.*$', '', line)
        clean = re.sub(r'"[^"]*"', '""', clean)  # retire les strings basiques
        opens  = len(_OPEN_BRACE.findall(clean))
        closes = len(_CLOSE_BRACE.findall(clean))
        depths.append(depth)
        depth += opens - closes
        depth = max(0, depth)
    return depths


# ── ANALYSE D'UN BLOC DE FONCTION ─────────────────────────────────────────────

def _analyze_block(
    lines: list[str],
    start: int,
    end: int,
    name: str,
    param_count: int,
) -> FunctionMetrics:
    """Analyse les métriques d'un bloc de fonction délimité."""
    block = lines[start:end]
    line_count = len(block)

    # Complexité cyclomatique
    cyclomatic = 1
    for line in block:
        if _COMMENT_LINE.match(line):
            continue
        matches = _CYCLOMATIC_PATTERNS.findall(line)
        cyclomatic += len(matches)

    # Complexité cognitive (approx — pénalité via indentation)
    cognitive = 0
    for line in block:
        if _COMMENT_LINE.match(line):
            continue
        # Profondeur estimée via indentation (4 espaces ou 1 tab = 1 niveau)
        indent_str = re.match(r'^(\s*)', line)
        indent = 0
        if indent_str:
            raw = indent_str.group(1)
            indent = raw.count('\t') + len(raw.replace('\t', '    ')) // 4
        nesting_level = max(0, indent - 1)

        if _COGNITIVE_NESTING.match(line):
            cognitive += 1 + nesting_level
        elif _COGNITIVE_BREAK.search(line):
            cognitive += 1

    # Profondeur max
    max_depth = 0
    depth = 0
    for line in block:
        clean = re.sub(r'//.*$', '', line)
        depth += len(_OPEN_BRACE.findall(clean)) - len(_CLOSE_BRACE.findall(clean))
        depth = max(0, depth)
        max_depth = max(max_depth, depth)

    return FunctionMetrics(
        name=name,
        start_line=start + 1,
        line_count=line_count,
        cyclomatic_complexity=min(cyclomatic, 200),   # plafond de sécurité
        cognitive_complexity=min(cognitive, 200),
        parameter_count=param_count,
        max_depth=max_depth,
    )


# ── EXTRACTION DES FONCTIONS ──────────────────────────────────────────────────

def _find_functions_ts(lines: list[str], depths: list[int]) -> list[FunctionMetrics]:
    """Détecte les fonctions TS/JS et calcule leurs métriques."""
    functions: list[FunctionMetrics] = []
    seen_lines: set[int] = set()

    for i, line in enumerate(lines):
        if i in seen_lines:
            continue
        if _COMMENT_LINE.match(line):
            continue

        name = "anonymous"
        param_count = 0
        matched = False

        for pattern in _TS_FUNC_PATTERNS:
            m = pattern.match(line)
            if m:
                groups = m.groups()
                name = groups[0] if groups else "anonymous"
                params_str = groups[1] if len(groups) > 1 else ""
                param_count = _count_params(params_str)
                matched = True
                break

        if not matched:
            continue

        # Trouve la fin du bloc via les accolades
        base_depth = depths[i]
        end = i + 1
        # Cherche l'accolade ouvrante si pas sur la même ligne
        open_found = '{' in re.sub(r'//.*$', '', line)
        j = i
        if not open_found:
            for j in range(i, min(i + 5, len(lines))):
                if '{' in re.sub(r'//.*$', '', lines[j]):
                    open_found = True
                    break

        if not open_found:
            # Arrow function sans accolades : const f = x => x + 1
            functions.append(FunctionMetrics(
                name=name, start_line=i + 1, line_count=1,
                cyclomatic_complexity=1, cognitive_complexity=0,
                parameter_count=param_count, max_depth=0,
            ))
            seen_lines.add(i)
            continue

        # Cherche la fermeture au même niveau d'imbrication
        open_depth = depths[j] + 1  # profondeur après l'accolade ouvrante
        end = j + 1
        for k in range(j + 1, len(lines)):
            if depths[k] <= base_depth and k > j:
                end = k
                break
        else:
            end = len(lines)

        metrics = _analyze_block(lines, i, end, name, param_count)
        functions.append(metrics)
        seen_lines.update(range(i, min(i + 3, len(lines))))

    return functions


def _find_functions_swift(lines: list[str], depths: list[int]) -> list[FunctionMetrics]:
    """Détecte les fonctions Swift et calcule leurs métriques."""
    functions: list[FunctionMetrics] = []
    seen_lines: set[int] = set()

    for i, line in enumerate(lines):
        if i in seen_lines:
            continue
        if _COMMENT_LINE.match(line):
            continue

        name = "anonymous"
        param_count = 0
        matched = False

        for pattern in _SWIFT_FUNC_PATTERNS:
            m = pattern.match(line)
            if m:
                groups = m.groups()
                if groups:
                    # Essaie de trouver le nom de fonction
                    name_match = re.search(r'\bfunc\s+(\w+)', line)
                    if name_match:
                        name = name_match.group(1)
                    elif re.search(r'\binit\b', line):
                        name = "init"
                    elif m.group(1) in ("get", "set", "willSet", "didSet"):
                        name = m.group(1)
                    param_count = _count_params(groups[-1] if groups else "")
                matched = True
                break

        if not matched:
            continue

        base_depth = depths[i]
        end = len(lines)
        for k in range(i + 1, len(lines)):
            if depths[k] <= base_depth and k > i + 1:
                end = k
                break

        metrics = _analyze_block(lines, i, end, name, param_count)
        functions.append(metrics)
        seen_lines.update(range(i, min(i + 2, len(lines))))

    return functions


# ── POINT D'ENTRÉE ─────────────────────────────────────────────────────────────

_EXTENSION_LANGUAGE = {
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript",
    ".swift": "swift",
}


def analyze_file_regex(file_path: str) -> FileMetrics:
    """
    Analyse un fichier TS/JS/Swift par regex et retourne ses métriques.
    Fallback si le fichier ne peut pas être lu → FileMetrics vide.
    """
    ext      = Path(file_path).suffix.lower()
    language = _EXTENSION_LANGUAGE.get(ext, "unknown")

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except OSError:
        return FileMetrics(file_path=file_path, total_lines=0,
                           total_functions=0, language=language)

    lines  = source.splitlines()
    depths = _build_block_map(lines)

    if language in ("typescript", "javascript"):
        functions = _find_functions_ts(lines, depths)
    elif language == "swift":
        functions = _find_functions_swift(lines, depths)
    else:
        functions = []

    return FileMetrics(
        file_path=file_path,
        total_lines=len(lines),
        total_functions=len(functions),
        functions=functions,
        language=language,
    )
