#!/usr/bin/env bash
# Remet ~/.pulse_intelligence en privé : dossiers 0700, fichiers 0600 — même
# politique que Core (core/scripts/fix_permissions.sh). Idempotent : liste
# ce qu'il change, ne dit rien sinon, ne touche à rien hors de cette racine.
#
# Surcharge de test : PULSE_INTELLIGENCE_HOME.

set -u

root="${PULSE_INTELLIGENCE_HOME:-$HOME/.pulse_intelligence}"
changed=0

[[ -d "$root" ]] || exit 0

while IFS= read -r -d '' directory; do
  chmod 700 "$directory"
  echo "[fix-permissions] 0700 $directory"
  changed=$((changed + 1))
done < <(find "$root" -type d ! -perm 700 -print0)

while IFS= read -r -d '' file; do
  chmod 600 "$file"
  echo "[fix-permissions] 0600 $file"
  changed=$((changed + 1))
done < <(find "$root" -type f ! -perm 600 -print0)

if [[ "$changed" -eq 0 ]]; then
  exit 0
fi
echo "[fix-permissions] $changed entrée(s) corrigée(s)"
