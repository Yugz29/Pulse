#!/bin/zsh

set -eu

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="$REPO_DIR/.venv/bin/python3"
PING_URL="http://127.0.0.1:8765/ping"
LOG_DIR="$HOME/.pulse/logs"

mkdir -p "$LOG_DIR"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "[Pulse] Missing Python runtime: $PYTHON_BIN" >> "$LOG_DIR/daemon.error.log"
  exit 1
fi

if /usr/bin/curl -fsS --max-time 2 "$PING_URL" >/dev/null 2>&1; then
  exit 0
fi

cd "$REPO_DIR"
exec "$PYTHON_BIN" -m daemon.main \
  >> "$LOG_DIR/daemon.stdout.log" \
  2>> "$LOG_DIR/daemon.error.log"
