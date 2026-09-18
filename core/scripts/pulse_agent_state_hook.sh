#!/usr/bin/env bash
# Hook Claude Code → fichier d'état de la session d'agent (v0, hors trace.db).
#
# Une seule commande pour SessionStart, UserPromptSubmit, PostToolUse,
# Notification, Stop et SessionEnd : le payload JSON sur stdin porte
# `hook_event_name` et `session_id`. La logique est dans
# `scripts/pulse_agent_state.py` ; ce wrapper ne fait que deux choses :
#
#   - un chemin rapide sans Python pour PostToolUse, qui tire à chaque appel
#     d'outil : si le fichier de la session dit déjà `working` et a moins de
#     60 s, rien à écrire ;
#   - passer son propre `$$` à Python, qui remonte l'arbre des processus
#     jusqu'au processus `claude` (le hook tourne sous un shell
#     intermédiaire : `$PPID` n'est pas l'agent).
#
# Ne bloque jamais l'agent : `exit 0` sur tout, journal dans
# ~/.pulse_v2/logs/agent_state_hook.log. Surcharges : PULSE_AGENT_STATE_DIR
# (dossier des états), PULSE_AGENT_STATE_LOG (journal). Argument optionnel :
# le matcher du hook Notification (`permission_prompt`, `idle_prompt`), que l'installateur
# passe pour ne pas dépendre du nom du champ dans le payload.

set -u
kind="${1:-}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
state_dir="${PULSE_AGENT_STATE_DIR:-$HOME/.pulse_v2/run/agents}"
log_file="${PULSE_AGENT_STATE_LOG:-$HOME/.pulse_v2/logs/agent_state_hook.log}"
mkdir -p "$(dirname "$log_file")" 2>/dev/null || exit 0
exec >>"$log_file" 2>&1

payload="$(cat 2>/dev/null || true)"
[[ -n "$payload" ]] || exit 0

# Chemin rapide PostToolUse : session déjà `working` depuis moins de 60 s.
if [[ "$payload" == *'"hook_event_name"'*'"PostToolUse"'* ]]; then
  session_id="$(printf '%s' "$payload" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
  if [[ -n "$session_id" ]]; then
    safe_id="$(printf '%s' "$session_id" | tr -c 'A-Za-z0-9_-' '_')"
    state_file="$state_dir/claude-code-$safe_id.json"
    if [[ -f "$state_file" ]] && grep -q '"state": *"working"' "$state_file" 2>/dev/null; then
      now_s="$(date +%s)"
      mtime_s="$(stat -f %m "$state_file" 2>/dev/null || echo 0)"
      if (( now_s - mtime_s < 60 )); then
        exit 0
      fi
    fi
  fi
fi

python="$(command -v python3 || true)"
[[ -n "$python" ]] || exit 0
printf '%s' "$payload" | "$python" "$script_dir/pulse_agent_state.py" "$$" "$kind" || true
exit 0
