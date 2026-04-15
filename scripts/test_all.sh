#!/bin/zsh

set -eu

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="$REPO_DIR/.venv/bin/python3"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Missing Python runtime: $PYTHON_BIN"
  echo "Create it with:"
  echo "  cd $REPO_DIR"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/pip install -r daemon/requirements.txt"
  exit 1
fi

cd "$REPO_DIR"

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"

echo "==> Python: $PYTHON_BIN ($PY_VERSION)"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Pulse daemon tests require Python 3.11+."
  exit 1
fi

echo "==> Running unit tests"
if [ "$#" -gt 0 ]; then
  "$PYTHON_BIN" -m unittest "$@"
else
  "$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py'
fi

echo
echo "==> Skipping interactive E2E by default"
echo "Run manually if needed:"
echo "  $PYTHON_BIN tests/test_e2e.py"
