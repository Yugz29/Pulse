#!/usr/bin/env bash
# Remet les données locales de Pulse en privé : dossiers 0700, fichiers 0600
# (politique du 2026-09-03). Idempotent : liste ce qu'il change, ne dit rien
# sinon. Ne touche à rien hors des racines Pulse :
#   ~/.pulse_v2   (trace, journaux, archives de transcripts, manifestes)
#   ~/.pulse_core (outbox durable des producteurs)
# Les binaires de ~/.pulse_v2/bin restent exécutables (0700).
#
# Surcharges de test : PULSE_V2_HOME, PULSE_CORE_HOME.

set -u

roots=("${PULSE_V2_HOME:-$HOME/.pulse_v2}" "${PULSE_CORE_HOME:-$HOME/.pulse_core}")
changed=0

for root in "${roots[@]}"; do
  [[ -d "$root" ]] || continue

  while IFS= read -r -d '' directory; do
    chmod 700 "$directory"
    echo "[fix-permissions] 0700 $directory"
    changed=$((changed + 1))
  done < <(find "$root" -type d ! -perm 700 -print0)

  while IFS= read -r -d '' binary; do
    chmod 700 "$binary"
    echo "[fix-permissions] 0700 $binary"
    changed=$((changed + 1))
  done < <(find "$root/bin" -type f ! -perm 700 -print0 2>/dev/null)

  while IFS= read -r -d '' file; do
    chmod 600 "$file"
    echo "[fix-permissions] 0600 $file"
    changed=$((changed + 1))
  done < <(find "$root" -type f ! -path "$root/bin/*" ! -perm 600 -print0)
done

if [[ "$changed" -eq 0 ]]; then
  exit 0
fi
echo "[fix-permissions] $changed entrée(s) corrigée(s)"
