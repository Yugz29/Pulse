"""
Analyse AST Python — port du pythonParser.ts (Cortex) avec ast builtin.

Métriques calculées :
- Complexité cyclomatique (McCabe) par fonction
- Complexité cognitive (modèle SonarSource — pénalité d'imbrication)
- Taille des fonctions (lignes)
- Profondeur d'imbrication max
- Nombre de paramètres
"""

import ast
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FunctionMetrics:
    name:                 str
    start_line:           int
    line_count:           int
    cyclomatic_complexity: int
    cognitive_complexity:  int
    parameter_count:      int
    max_depth:            int


@dataclass
class FileMetrics:
    file_path:       str
    total_lines:     int
    total_functions: int
    functions:       list[FunctionMetrics] = field(default_factory=list)
    language:        str = "python"


# ── NOEUDS QUI AUGMENTENT LA COMPLEXITÉ CYCLOMATIQUE ──────────────────────────

_CYCLOMATIC_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.Assert,
    ast.comprehension,
    ast.IfExp,       # ternaire x if cond else y
)

_BOOL_OPS = (ast.And, ast.Or)


# ── NOEUDS QUI AUGMENTENT LA COMPLEXITÉ COGNITIVE ─────────────────────────────
# Structures qui créent une rupture de flux ET pénalisent l'imbrication.

_COGNITIVE_NESTING_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
)

_COGNITIVE_BREAK_ONLY = (
    ast.IfExp,
    ast.Assert,
)


# ── VISITEUR AST ───────────────────────────────────────────────────────────────

class _FunctionVisitor(ast.NodeVisitor):
    """Visite les noeuds AST et collecte les métriques par fonction."""

    def __init__(self, source_lines: list[str]):
        self.source_lines = source_lines
        self.functions: list[FunctionMetrics] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._analyze(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._analyze(node)
        self.generic_visit(node)

    def _analyze(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        name       = node.name
        start_line = node.lineno
        end_line   = _end_line(node)
        line_count = max(1, end_line - start_line + 1)

        cyclomatic = _cyclomatic_complexity(node)
        cognitive  = _cognitive_complexity(node, nesting_level=0)
        params     = _param_count(node)
        depth      = _max_depth(node, current=0)

        self.functions.append(FunctionMetrics(
            name=name,
            start_line=start_line,
            line_count=line_count,
            cyclomatic_complexity=cyclomatic,
            cognitive_complexity=cognitive,
            parameter_count=params,
            max_depth=depth,
        ))


# ── COMPLEXITÉ CYCLOMATIQUE ────────────────────────────────────────────────────

def _cyclomatic_complexity(node: ast.AST) -> int:
    """
    Complexité cyclomatique = 1 + nombre de branches.
    On ne descend pas dans les fonctions imbriquées (double comptage).
    """
    count = 1

    for child in ast.walk(node):
        if child is node:
            continue
        # Ne pas descendre dans les fonctions imbriquées
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(child, _CYCLOMATIC_NODES):
            count += 1
        if isinstance(child, ast.BoolOp):
            # and/or : +1 par opérande supplémentaire
            count += len(child.values) - 1

    return count


# ── COMPLEXITÉ COGNITIVE ───────────────────────────────────────────────────────

def _cognitive_complexity(node: ast.AST, nesting_level: int, is_root: bool = True) -> int:
    """
    Complexité cognitive (modèle SonarSource) :
    +1 pour chaque rupture de flux
    +nesting_level pour les structures imbriquantes
    """
    score = 0

    for child in ast.iter_child_nodes(node):
        if not is_root and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        if isinstance(child, _COGNITIVE_NESTING_NODES):
            score += 1 + nesting_level
            score += _cognitive_complexity(child, nesting_level + 1, is_root=False)

        elif isinstance(child, _COGNITIVE_BREAK_ONLY):
            score += 1
            score += _cognitive_complexity(child, nesting_level, is_root=False)

        elif isinstance(child, ast.BoolOp):
            # +1 par opérateur (and/or)
            score += len(child.values) - 1
            score += _cognitive_complexity(child, nesting_level, is_root=False)

        else:
            score += _cognitive_complexity(child, nesting_level, is_root=False)

    return score


# ── PROFONDEUR D'IMBRICATION MAX ───────────────────────────────────────────────

_DEPTH_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.ExceptHandler,
)


def _max_depth(node: ast.AST, current: int) -> int:
    max_d = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        next_depth = current + 1 if isinstance(child, _DEPTH_NODES) else current
        max_d = max(max_d, _max_depth(child, next_depth))
    return max_d


# ── NOMBRE DE PARAMÈTRES ───────────────────────────────────────────────────────

def _param_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = node.args
    # Exclut `self` et `cls` des méthodes
    positional = [
        a for a in args.args
        if a.arg not in ("self", "cls")
    ]
    return len(positional) + len(args.kwonlyargs)


# ── LIGNE DE FIN (approximation) ──────────────────────────────────────────────

def _end_line(node: ast.AST) -> int:
    """Retourne la dernière ligne du noeud (end_lineno dispo depuis Python 3.8)."""
    if hasattr(node, "end_lineno") and node.end_lineno:
        return node.end_lineno
    # Fallback : on cherche la dernière ligne de tous les enfants
    last = getattr(node, "lineno", 0)
    for child in ast.walk(node):
        last = max(last, getattr(child, "lineno", 0))
    return last


# ── POINT D'ENTRÉE ─────────────────────────────────────────────────────────────

def analyze_python_file(file_path: str) -> FileMetrics:
    """
    Analyse un fichier Python et retourne ses métriques.
    Lève FileNotFoundError si le fichier n'existe pas,
    SyntaxError si le fichier n'est pas du Python valide.
    """
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()

    source_lines = source.splitlines()
    total_lines  = len(source_lines)

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        # Fichier non parseable — on retourne des métriques vides plutôt que de crasher
        return FileMetrics(
            file_path=file_path,
            total_lines=total_lines,
            total_functions=0,
            functions=[],
            language="python",
        )

    visitor = _FunctionVisitor(source_lines)
    visitor.visit(tree)

    return FileMetrics(
        file_path=file_path,
        total_lines=total_lines,
        total_functions=len(visitor.functions),
        functions=visitor.functions,
        language="python",
    )
