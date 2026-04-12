#!/bin/zsh
# install_scoring.sh — Installe les dépendances tree-sitter pour le scoring Pulse

set -eu

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="$REPO_DIR/.venv/bin/python3"
PIP_BIN="$REPO_DIR/.venv/bin/pip"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "[Pulse] Venv introuvable : $PYTHON_BIN"
  echo "        Crée le venv d'abord : python3 -m venv .venv"
  exit 1
fi

echo "[Pulse] Installation des dépendances scoring..."
"$PIP_BIN" install -r "$REPO_DIR/daemon/requirements.txt"

echo ""
echo "[Pulse] Vérification tree-sitter..."
"$PYTHON_BIN" -c "
import sys
try:
    from tree_sitter import Language, Parser
    print('  ✓ tree-sitter core')
except ImportError:
    print('  ✗ tree-sitter non disponible')
    sys.exit(1)

grammars = [
    ('tree_sitter_typescript', 'typescript'),
    ('tree_sitter_javascript', 'javascript'),
    ('tree_sitter_swift',      'swift'),
    ('tree_sitter_rust',       'rust'),
    ('tree_sitter_go',         'go'),
    ('tree_sitter_java',       'java'),
    ('tree_sitter_kotlin',     'kotlin'),
    ('tree_sitter_c',          'c'),
    ('tree_sitter_cpp',        'cpp'),
    ('tree_sitter_ruby',       'ruby'),
    ('tree_sitter_c_sharp',    'c_sharp'),
]
for mod, name in grammars:
    try:
        m = __import__(mod, fromlist=['language'])
        fn = getattr(m, 'language', None) or getattr(m, name, None)
        if fn:
            Language(fn())
            print(f'  ✓ {name}')
        else:
            print(f'  ⚠ {name} (language() introuvable)')
    except Exception as e:
        print(f'  ✗ {name} : {e}')
"

echo ""
echo "[Pulse] Scoring prêt."
