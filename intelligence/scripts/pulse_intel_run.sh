#!/usr/bin/env bash
# Un passage `pulse-intel run --once` sur la config du poste, pour launchd.
#
# Le venv d'Intelligence est pris par chemin absolu depuis ce script ; aucune
# variable PULSE_LLM_* n'est nécessaire au provider local (mlx). Sortie et
# erreurs vont dans le journal choisi par le plist.
#
# `caffeinate -i` empêche la veille d'inactivité pendant le passage, capot
# ouvert. Capot fermé sur batterie, il ne retient rien : le Mac dort, le lot
# avance par DarkWake et se termine à l'ouverture.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
intel_dir="$(cd "$script_dir/.." && pwd -P)"
cli="$intel_dir/.venv/bin/pulse-intel"

if [[ ! -x "$cli" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] pulse-intel introuvable: $cli" >&2
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] run --once (launchd)"
cd "$intel_dir" && exec /usr/bin/caffeinate -i "$cli" run --once
