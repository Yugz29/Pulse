#!/bin/zsh

set -eu

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="$REPO_DIR/.venv/bin/python3"
PING_URL="http://127.0.0.1:8765/ping"
LOG_DIR="$HOME/.pulse/logs"

mkdir -p "$LOG_DIR"

log() {
  echo "$1"
  echo "$1" >> "$LOG_DIR/daemon.error.log"
}

port_in_use() {
  local port="$1"
  local lsof_bin

  lsof_bin="$(command -v lsof || true)"
  if [ -z "$lsof_bin" ]; then
    log "[Pulse] Warning: lsof not found; cannot preflight port $port."
    return 1
  fi

  "$lsof_bin" -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

if /usr/bin/curl -fsS --max-time 2 "$PING_URL" >/dev/null 2>&1; then
  log "[Pulse] Daemon already active on :8765."
  exit 0
fi

if port_in_use 8765; then
  log "[Pulse] Port 8765 is already in use, but /ping did not return a Pulse daemon. Refusing to start to avoid a duplicate daemon and session pollution."
  exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
  log "[Pulse] Missing Python runtime: $PYTHON_BIN"
  exit 1
fi

if port_in_use 8766; then
  log "[Pulse] Warning: port 8766 is already in use; MCP SSE may be unavailable, but Core daemon startup will continue."
fi

cd "$REPO_DIR"
exec "$PYTHON_BIN" -m daemon.main \
  >> "$LOG_DIR/daemon.stdout.log" \
  2>> "$LOG_DIR/daemon.error.log"
