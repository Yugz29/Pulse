#!/usr/bin/env bash
# Hook SessionEnd Claude Code : émission agent_session immédiate et ciblée.
#
# Décision (a) du 2026-08-31 : la session qui vient de finir est émise tout
# de suite (fenêtre de silence contournée pour SON transcript seulement) au
# lieu d'attendre le passage horaire launchd + 60 min. Une reprise rapide
# après émission donne un résumé figé (grown_after_emit) — assumé ; l'item
# « segments de reprise » du backlog porte le déclencheur de réexamen.
#
# Garde-fou 1 : ne JAMAIS bloquer ni faire échouer la fermeture de session —
# toute sortie va au log, le code de sortie est TOUJOURS 0.
# Garde-fou 2 : l'archive zstd d'abord, le pointeur ensuite (même invariant
# que pulse_agent_producers.sh) — archivage en échec = émission annulée,
# le passage horaire launchd rattrape.
#
# Course bénigne avec le passage horaire : les deux peuvent traiter le même
# transcript ; l'event_id déterministe fait de la double émission un
# duplicate inoffensif à l'ingestion.
#
# Entrée : le JSON SessionEnd de Claude Code sur stdin (transcript_path,
# session_id, reason). Surcharges de test : PULSE_AGENT_CLAUDE_DIR /
# PULSE_AGENT_CODEX_DIR (sources), PULSE_SESSION_END_LOG (journal).

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(dirname "$script_dir")"
python="$repo_root/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  python="$(command -v python3)"
fi

log_file="${PULSE_SESSION_END_LOG:-$HOME/.pulse_v2/logs/session_end_hook.log}"
mkdir -p "$(dirname "$log_file")" 2>/dev/null || exit 0
exec >>"$log_file" 2>&1

# Extraction du payload SessionEnd (une valeur par ligne : un chemin peut
# contenir des espaces) — stdin illisible = no-op silencieux.
{
  read -r transcript_path
  read -r session_id
  read -r reason
} < <("$python" -c "
import json, sys
try:
    payload = json.load(sys.stdin)
except Exception:
    payload = {}
for field in ('transcript_path', 'session_id', 'reason'):
    print(payload.get(field) or '-')
") || exit 0

echo "[session-end-hook] $(date '+%Y-%m-%dT%H:%M:%S%z') session=$session_id reason=$reason"
if [[ "$transcript_path" == "-" ]]; then
  echo "[session-end-hook] payload sans transcript_path — ignoré"
  exit 0
fi

cd "$repo_root" || exit 0

archive_args=()
sessions_args=()
if [[ -n "${PULSE_AGENT_CLAUDE_DIR:-}" ]]; then
  archive_args+=(--source "$PULSE_AGENT_CLAUDE_DIR")
  sessions_args+=(--claude-dir "$PULSE_AGENT_CLAUDE_DIR")
fi
if [[ -n "${PULSE_AGENT_CODEX_DIR:-}" ]]; then
  archive_args+=(--source "$PULSE_AGENT_CODEX_DIR")
  sessions_args+=(--codex-dir "$PULSE_AGENT_CODEX_DIR")
fi

if ! "$python" -m scripts.archive_transcripts "${archive_args[@]+"${archive_args[@]}"}"; then
  echo "[session-end-hook] archivage en échec — émission annulée (launchd rattrapera)"
  exit 0
fi

if ! "$python" -m daemon_v2.agent_sessions \
    "${sessions_args[@]+"${sessions_args[@]}"}" \
    --transcript "$transcript_path"; then
  echo "[session-end-hook] émission ciblée en échec (launchd rattrapera)"
fi
exit 0
