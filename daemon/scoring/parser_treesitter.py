"""
Parser multi-langages basé sur tree-sitter.

Couvre avec une analyse AST réelle :
  TypeScript .ts .tsx          (tree-sitter-typescript — PyPI stable)
  JavaScript .js .jsx .mjs    (tree-sitter-javascript — PyPI stable)
  Rust       .rs               (tree-sitter-rust — PyPI stable)
  Go         .go               (tree-sitter-go — PyPI stable)
  Java       .java             (tree-sitter-java — PyPI stable)
  C          .c .h             (tree-sitter-c — PyPI stable)
  C++        .cpp .hpp         (tree-sitter-cpp — PyPI stable)
  Ruby       .rb               (tree-sitter-ruby — PyPI stable)
  C#         .cs               (tree-sitter-c-sharp — PyPI stable)
  Swift      .swift            (optionnel — absent sur PyPI, fallback regex)
  Kotlin     .kt               (optionnel — disponibilité variable)

Python (.py) → parser_python.py (ast builtin, plus précis).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from tree_sitter import Language, Parser
    _TREE_SITTER_AVAILABLE = True
except ImportError:
    _TREE_SITTER_AVAILABLE = False
    Language = None  # type: ignore
    Parser   = None  # type: ignore


# ── INTERFACES ────────────────────────────────────────────────────────────────

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


# ── CONFIGURATION PAR LANGAGE ─────────────────────────────────────────────────

@dataclass
class LanguageConfig:
    function_nodes: set[str]
    name_nodes:     set[str]
    param_nodes:    set[str]
    branch_nodes:   set[str]
    nesting_nodes:  set[str]
    break_nodes:    set[str]
    module:      str              # package Python : "tree_sitter_javascript"
    language_fn: str = "language" # nom de la fonction dans le module
                                  # ex: "language_typescript" pour tree_sitter_typescript


_CONFIGS: dict[str, LanguageConfig] = {

    "typescript": LanguageConfig(
        module="tree_sitter_typescript",
        language_fn="language_typescript",   # ← spécifique à ce module
        function_nodes={
            "function_declaration", "function_expression", "arrow_function",
            "method_definition", "generator_function_declaration", "generator_function",
        },
        name_nodes={"identifier", "property_identifier"},
        param_nodes={"formal_parameters", "required_parameter", "optional_parameter"},
        branch_nodes={
            "if_statement", "for_statement", "for_in_statement",
            "while_statement", "do_statement", "switch_case", "catch_clause",
            "conditional_expression", "&&", "||", "??",
        },
        nesting_nodes={
            "if_statement", "for_statement", "for_in_statement",
            "while_statement", "do_statement", "switch_statement", "try_statement",
        },
        break_nodes={"catch_clause", "conditional_expression", "&&", "||", "??"},
    ),

    "tsx": LanguageConfig(
        module="tree_sitter_typescript",
        language_fn="language_tsx",          # ← spécifique à ce module
        function_nodes={
            "function_declaration", "function_expression",
            "arrow_function", "method_definition",
        },
        name_nodes={"identifier", "property_identifier"},
        param_nodes={"formal_parameters"},
        branch_nodes={
            "if_statement", "for_statement", "for_in_statement",
            "while_statement", "do_statement", "switch_case", "catch_clause",
            "conditional_expression", "&&", "||", "??",
        },
        nesting_nodes={
            "if_statement", "for_statement", "for_in_statement",
            "while_statement", "do_statement",
        },
        break_nodes={"catch_clause", "conditional_expression", "&&", "||", "??"},
    ),

    "javascript": LanguageConfig(
        module="tree_sitter_javascript",
        function_nodes={
            "function_declaration", "function_expression", "arrow_function",
            "method_definition", "generator_function_declaration", "generator_function",
        },
        name_nodes={"identifier", "property_identifier"},
        param_nodes={"formal_parameters"},
        branch_nodes={
            "if_statement", "for_statement", "for_in_statement",
            "while_statement", "do_statement", "switch_case", "catch_clause",
            "conditional_expression", "&&", "||", "??",
        },
        nesting_nodes={
            "if_statement", "for_statement", "for_in_statement",
            "while_statement", "do_statement", "switch_statement",
        },
        break_nodes={"catch_clause", "conditional_expression", "&&", "||", "??"},
    ),

    "swift": LanguageConfig(
        module="tree_sitter_swift",
        function_nodes={
            "function_declaration", "initializer_declaration",
            "subscript_declaration", "closure_expression", "accessor_declaration",
        },
        name_nodes={"simple_identifier"},
        param_nodes={"parameter", "function_value_parameters"},
        branch_nodes={
            "if_statement", "guard_statement", "for_statement",
            "while_statement", "repeat_while_statement",
            "switch_entry", "catch_block", "conditional_expression",
            "&&", "||", "nil_coalescing_expression",
        },
        nesting_nodes={
            "if_statement", "guard_statement", "for_statement",
            "while_statement", "repeat_while_statement", "switch_statement",
        },
        break_nodes={
            "catch_block", "conditional_expression",
            "&&", "||", "nil_coalescing_expression",
        },
    ),

    "rust": LanguageConfig(
        module="tree_sitter_rust",
        function_nodes={"function_item", "closure_expression"},
        name_nodes={"identifier"},
        param_nodes={"parameters", "parameter"},
        branch_nodes={
            "if_expression", "for_expression", "while_expression",
            "loop_expression", "match_arm", "if_let_expression",
            "while_let_expression", "&&", "||",
        },
        nesting_nodes={
            "if_expression", "for_expression", "while_expression",
            "loop_expression", "match_expression",
            "if_let_expression", "while_let_expression",
        },
        break_nodes={"match_arm", "&&", "||"},
    ),

    "go": LanguageConfig(
        module="tree_sitter_go",
        function_nodes={"function_declaration", "method_declaration", "func_literal"},
        name_nodes={"identifier"},
        param_nodes={"parameter_declaration", "parameter_list"},
        branch_nodes={
            "if_statement", "for_statement", "range_clause",
            "switch_case", "type_switch_case", "communication_case",
            "&&", "||",
        },
        nesting_nodes={
            "if_statement", "for_statement", "switch_statement",
            "select_statement", "type_switch_statement",
        },
        break_nodes={"&&", "||", "communication_case"},
    ),

    "java": LanguageConfig(
        module="tree_sitter_java",
        function_nodes={
            "method_declaration", "constructor_declaration", "lambda_expression",
        },
        name_nodes={"identifier"},
        param_nodes={"formal_parameter", "formal_parameters"},
        branch_nodes={
            "if_statement", "for_statement", "enhanced_for_statement",
            "while_statement", "do_statement", "switch_label",
            "catch_clause", "conditional_expression", "&&", "||",
        },
        nesting_nodes={
            "if_statement", "for_statement", "enhanced_for_statement",
            "while_statement", "do_statement", "switch_statement", "try_statement",
        },
        break_nodes={"catch_clause", "conditional_expression", "&&", "||"},
    ),

    "kotlin": LanguageConfig(
        module="tree_sitter_kotlin",
        function_nodes={
            "function_declaration", "anonymous_function", "lambda_literal",
        },
        name_nodes={"simple_identifier"},
        param_nodes={"function_value_parameter", "parameter"},
        branch_nodes={
            "if_expression", "for_statement", "while_statement",
            "do_while_statement", "when_entry", "catch_block",
            "&&", "||", "elvis_expression",
        },
        nesting_nodes={
            "if_expression", "for_statement", "while_statement",
            "do_while_statement", "when_expression", "try_expression",
        },
        break_nodes={"catch_block", "&&", "||", "elvis_expression"},
    ),

    "c": LanguageConfig(
        module="tree_sitter_c",
        function_nodes={"function_definition"},
        name_nodes={"identifier"},
        param_nodes={"parameter_declaration", "parameter_list"},
        branch_nodes={
            "if_statement", "for_statement", "while_statement",
            "do_statement", "case_statement", "conditional_expression",
            "&&", "||",
        },
        nesting_nodes={
            "if_statement", "for_statement", "while_statement",
            "do_statement", "switch_statement",
        },
        break_nodes={"case_statement", "conditional_expression", "&&", "||"},
    ),

    "cpp": LanguageConfig(
        module="tree_sitter_cpp",
        function_nodes={
            "function_definition", "lambda_expression",
            "constructor_or_destructor_definition",
        },
        name_nodes={"identifier", "field_identifier"},
        param_nodes={"parameter_declaration", "parameter_list"},
        branch_nodes={
            "if_statement", "for_statement", "range_based_for_statement",
            "while_statement", "do_statement", "case_statement",
            "catch_clause", "conditional_expression", "&&", "||",
        },
        nesting_nodes={
            "if_statement", "for_statement", "range_based_for_statement",
            "while_statement", "do_statement", "switch_statement", "try_statement",
        },
        break_nodes={"catch_clause", "conditional_expression", "&&", "||"},
    ),

    "ruby": LanguageConfig(
        module="tree_sitter_ruby",
        function_nodes={"method", "singleton_method", "block", "lambda"},
        name_nodes={"identifier"},
        param_nodes={"method_parameters", "block_parameters"},
        branch_nodes={
            "if", "unless", "elsif", "for", "while", "until",
            "when", "rescue", "conditional", "&&", "||", "and", "or",
        },
        nesting_nodes={"if", "unless", "for", "while", "until", "case", "begin"},
        break_nodes={"rescue", "conditional", "&&", "||", "and", "or"},
    ),

    "csharp": LanguageConfig(
        module="tree_sitter_c_sharp",
        function_nodes={
            "method_declaration", "constructor_declaration",
            "anonymous_method_expression", "lambda_expression",
            "local_function_statement",
        },
        name_nodes={"identifier"},
        param_nodes={"parameter", "formal_parameter_list"},
        branch_nodes={
            "if_statement", "for_statement", "foreach_statement",
            "while_statement", "do_statement", "switch_label",
            "catch_clause", "conditional_expression", "&&", "||", "??",
        },
        nesting_nodes={
            "if_statement", "for_statement", "foreach_statement",
            "while_statement", "do_statement", "switch_statement", "try_statement",
        },
        break_nodes={"catch_clause", "conditional_expression", "&&", "||", "??"},
    ),
}

_EXT_TO_CONFIG: dict[str, str] = {
    ".ts": "typescript", ".tsx": "tsx",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".swift": "swift",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".rb": "ruby",
    ".cs": "csharp",
}

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".ts": "typescript", ".tsx": "tsx",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".swift": "swift", ".rs": "rust", ".go": "go", ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".rb": "ruby", ".cs": "csharp",
}

# Cache : None = tentative échouée (ne pas retenter)
_lang_cache: dict[str, Optional[object]] = {}


def _get_language(config_key: str) -> Optional[object]:
    """
    Charge le Language tree-sitter pour une config.
    Chaque grammar est isolé — un échec n'affecte pas les autres.
    """
    if config_key in _lang_cache:
        return _lang_cache[config_key]

    cfg = _CONFIGS.get(config_key)
    if cfg is None:
        _lang_cache[config_key] = None
        return None

    try:
        mod = __import__(cfg.module, fromlist=[cfg.language_fn])
        lang_fn = getattr(mod, cfg.language_fn, None)
        if lang_fn is None:
            _lang_cache[config_key] = None
            return None

        lang = Language(lang_fn())
        _lang_cache[config_key] = lang
        return lang

    except Exception:
        _lang_cache[config_key] = None
        return None


# ── ALGORITHME DE TRAVERSAL ───────────────────────────────────────────────────

def _node_name(node: object) -> str:
    name_types = {
        "identifier", "simple_identifier", "property_identifier",
        "field_identifier", "name",
    }
    for child in node.children:  # type: ignore
        if child.type in name_types:
            return child.text.decode("utf-8", errors="replace")
    return "anonymous"


def _count_params(node: object, cfg: LanguageConfig) -> int:
    param_child_types = {
        "required_parameter", "optional_parameter", "parameter",
        "formal_parameter", "parameter_declaration", "function_value_parameter",
        "variadic_parameter",
    }
    skip = {"self", "this", "cls", "_"}

    for child in node.children:  # type: ignore
        if child.type in cfg.param_nodes:
            direct = [c for c in child.children if c.type in param_child_types]
            if direct:
                return len(direct)
            idents = [
                c for c in child.children
                if c.type in {"identifier", "simple_identifier"}
                and c.text.decode("utf-8", errors="replace") not in skip
            ]
            return len(idents)
    return 0


def _compute_metrics(fn_node: object, cfg: LanguageConfig) -> tuple[int, int, int, int]:
    cyclomatic  = 1
    cognitive   = 0
    max_depth   = 0
    param_count = _count_params(fn_node, cfg)

    def traverse(node: object, depth: int, nesting: int, is_root: bool) -> None:
        nonlocal cyclomatic, cognitive, max_depth

        for child in node.children:  # type: ignore
            ctype = child.type
            if not is_root and ctype in cfg.function_nodes:
                continue
            if ctype in cfg.branch_nodes:
                cyclomatic += 1
            if ctype in cfg.nesting_nodes:
                cognitive += 1 + nesting
                max_depth  = max(max_depth, depth + 1)
                traverse(child, depth + 1, nesting + 1, False)
            elif ctype in cfg.break_nodes:
                cognitive += 1
                traverse(child, depth, nesting, False)
            else:
                traverse(child, depth, nesting, False)

    traverse(fn_node, 0, 0, True)
    return cyclomatic, cognitive, max_depth, param_count


def _extract_functions(root: object, cfg: LanguageConfig, source: bytes) -> list[FunctionMetrics]:
    functions: list[FunctionMetrics] = []

    def walk(node: object) -> None:
        if node.type in cfg.function_nodes:  # type: ignore
            start = node.start_point[0]  # type: ignore
            end   = node.end_point[0]    # type: ignore
            cyclomatic, cognitive, max_depth, params = _compute_metrics(node, cfg)
            functions.append(FunctionMetrics(
                name=_node_name(node),
                start_line=start + 1,
                line_count=max(1, end - start + 1),
                cyclomatic_complexity=cyclomatic,
                cognitive_complexity=cognitive,
                parameter_count=params,
                max_depth=max_depth,
            ))
        for child in node.children:  # type: ignore
            walk(child)

    walk(root)
    return functions


# ── API PUBLIQUE ──────────────────────────────────────────────────────────────

def is_available() -> bool:
    return _TREE_SITTER_AVAILABLE


def available_languages() -> dict[str, bool]:
    """Retourne {config_key: disponible} pour diagnostic."""
    if not _TREE_SITTER_AVAILABLE:
        return {k: False for k in _CONFIGS}
    return {k: _get_language(k) is not None for k in _CONFIGS}


def supported_extensions() -> set[str]:
    return set(_EXT_TO_CONFIG.keys())


def analyze_file(file_path: str) -> Optional[FileMetrics]:
    if not _TREE_SITTER_AVAILABLE:
        return None

    ext = Path(file_path).suffix.lower()
    config_key = _EXT_TO_CONFIG.get(ext)
    if config_key is None:
        return None

    lang = _get_language(config_key)
    if lang is None:
        return None

    try:
        source = Path(file_path).read_bytes()
    except OSError:
        return None

    try:
        parser = Parser(lang)
        tree   = parser.parse(source)
    except Exception:
        return None

    cfg = _CONFIGS[config_key]
    functions = _extract_functions(tree.root_node, cfg, source)

    return FileMetrics(
        file_path=file_path,
        total_lines=len(source.split(b"\n")),
        total_functions=len(functions),
        functions=functions,
        language=_EXT_TO_LANGUAGE.get(ext, config_key),
    )
