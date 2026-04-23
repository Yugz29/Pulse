#!/bin/zsh

# Pulse terminal watcher (zsh only)
#
# Usage:
#   source /Users/yugz/Projets/Pulse/Pulse/scripts/pulse_terminal_watcher.zsh
#
# The watcher emits lightweight terminal events to the local Pulse daemon.
# Raw commands are sent only to /event for normalization, then stripped by
# the daemon before publication/persistence.

if [[ -n "${PULSE_TERMINAL_WATCHER_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
typeset -g PULSE_TERMINAL_WATCHER_LOADED=1

typeset -g PULSE_TERMINAL_ENDPOINT="${PULSE_TERMINAL_ENDPOINT:-http://127.0.0.1:8765/event}"
typeset -g PULSE_TERMINAL_PROGRAM="${TERM_PROGRAM:-${TERM:-terminal}}"
typeset -g PULSE_TERMINAL_ACTIVE=0
typeset -g PULSE_TERMINAL_COMMAND=""
typeset -g PULSE_TERMINAL_STARTED_MS=0

_pulse_terminal_escape_json() {
  local value="${1:-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

_pulse_terminal_now_ms() {
  local seconds
  seconds="$(python3 -c 'import time; print(int(time.time() * 1000))' 2>/dev/null)"
  if [[ -z "$seconds" ]]; then
    seconds="$(( EPOCHSECONDS * 1000 ))"
  fi
  printf '%s' "$seconds"
}

_pulse_terminal_post() {
  local event_type="$1"
  local command="$2"
  local exit_code="$3"
  local duration_ms="$4"

  local cwd shell_name timestamp payload
  cwd="$PWD"
  shell_name="${ZSH_NAME:-zsh}"
  timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  payload="{\"type\":\"${event_type}\",\"timestamp\":\"${timestamp}\",\"command\":\"$(_pulse_terminal_escape_json "$command")\",\"cwd\":\"$(_pulse_terminal_escape_json "$cwd")\",\"shell\":\"${shell_name}\",\"terminal_program\":\"$(_pulse_terminal_escape_json "$PULSE_TERMINAL_PROGRAM")\""

  if [[ -n "$exit_code" ]]; then
    payload="${payload},\"exit_code\":${exit_code}"
  fi
  if [[ -n "$duration_ms" ]]; then
    payload="${payload},\"duration_ms\":${duration_ms}"
  fi
  payload="${payload}}"

  curl -sS -X POST "$PULSE_TERMINAL_ENDPOINT" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    >/dev/null 2>&1 || true
}

_pulse_terminal_preexec() {
  PULSE_TERMINAL_ACTIVE=1
  PULSE_TERMINAL_COMMAND="$1"
  PULSE_TERMINAL_STARTED_MS="$(_pulse_terminal_now_ms)"
  _pulse_terminal_post "terminal_command_started" "$PULSE_TERMINAL_COMMAND" "" ""
}

_pulse_terminal_precmd() {
  local exit_code duration_ms ended_ms
  exit_code="$?"

  if [[ "$PULSE_TERMINAL_ACTIVE" != "1" ]]; then
    return 0
  fi

  ended_ms="$(_pulse_terminal_now_ms)"
  if [[ -n "$PULSE_TERMINAL_STARTED_MS" ]]; then
    duration_ms="$(( ended_ms - PULSE_TERMINAL_STARTED_MS ))"
    if (( duration_ms < 0 )); then
      duration_ms=0
    fi
  else
    duration_ms=""
  fi

  _pulse_terminal_post "terminal_command_finished" "$PULSE_TERMINAL_COMMAND" "$exit_code" "$duration_ms"

  PULSE_TERMINAL_ACTIVE=0
  PULSE_TERMINAL_COMMAND=""
  PULSE_TERMINAL_STARTED_MS=0
}

autoload -Uz add-zsh-hook
add-zsh-hook preexec _pulse_terminal_preexec
add-zsh-hook precmd _pulse_terminal_precmd
