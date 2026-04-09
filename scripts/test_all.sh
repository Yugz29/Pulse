#!/bin/zsh

set -eu

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="$REPO_DIR/.venv/bin/python3"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Missing Python runtime: $PYTHON_BIN"
  exit 1
fi

cd "$REPO_DIR"

echo "==> Running unit tests"
"$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py'

echo
echo "==> Skipping interactive E2E by default"
echo "Run manually if needed:"
echo "  $PYTHON_BIN tests/test_e2e.py"
