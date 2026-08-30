#!/usr/bin/env bash
# Passage séquentiel des producteurs agents : l'archive AVANT les pointeurs.
#
# Ordre imposé par la décision de rétention du 2026-08-30 : un événement
# agent_session pointe vers son transcript ; l'archive zstd doit exister
# d'abord pour que le pointeur survive à la purge des outils sources.
# Si l'archivage échoue (exit != 0), aucun pointeur n'est émis — le
# prochain passage rattrapera tout, les deux outils sont idempotents.
#
# Surcharges de test : PULSE_AGENT_CLAUDE_DIR / PULSE_AGENT_CODEX_DIR
# remplacent les sources par défaut des deux outils.
#
# Codes de sortie : 0 = passage complet ; 2 = archivage ou émission en
# erreur d'infrastructure (le détail est dans la sortie).

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(dirname "$script_dir")"
python="$repo_root/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  python="$(command -v python3)"
fi

cd "$repo_root" || exit 2

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

echo "[pulse-agent-producers] $(date '+%Y-%m-%dT%H:%M:%S%z') archive"
if ! "$python" -m scripts.archive_transcripts "${archive_args[@]+"${archive_args[@]}"}"; then
  echo "[pulse-agent-producers] archivage en échec — émission annulée" >&2
  exit 2
fi

echo "[pulse-agent-producers] agent sessions"
exec "$python" -m daemon_v2.agent_sessions "${sessions_args[@]+"${sessions_args[@]}"}"
