#!/usr/bin/env bash
# Un passage `pulse-intel run --once` sur la config du poste, pour launchd.
#
# Le venv d'Intelligence est pris par chemin absolu depuis ce script ; aucune
# variable PULSE_LLM_* n'est nécessaire au provider local (mlx). Sortie et
# erreurs vont dans le journal choisi par le plist.
#
# L'agent launchd appelle ce script toutes les quinze minutes. Avant de
# lancer le passage, `pulse-intel gate` répond dans l'ordre : lot du jour
# déjà fait (code 10, rien dans le journal), pas en réveil complet (DarkWake),
# capot fermé ou batterie sous le plancher (code 11, une ligne « lot
# reporté » par cycle au plus), sinon 0.
# Décision 2026-09-19 : un lot qui part dans un DarkWake capot fermé n'avance
# que par tranches de quelques secondes.
#
# Le niveau de batterie est journalisé au début et à la fin du passage, pour
# ajuster le plancher sur des mesures. `caffeinate -i` retient la veille
# d'inactivité pendant le passage, capot ouvert.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
intel_dir="$(cd "$script_dir/.." && pwd -P)"
cli="$intel_dir/.venv/bin/pulse-intel"
cycle_start="${PULSE_INTEL_CYCLE_START:-06:30}"

stamp() { date '+%Y-%m-%d %H:%M:%S'; }
# « 68 % secteur » ou « 50 % batterie » ; vide si pmset ne dit rien.
power() {
  /usr/bin/pmset -g batt 2>/dev/null | awk '
    NR == 1 { source = ($0 ~ /AC Power/) ? "secteur" : "batterie" }
    match($0, /[0-9]+%/) { level = substr($0, RSTART, RLENGTH - 1) }
    END { if (level != "") printf "%s %% %s", level, source }'
}

if [[ ! -x "$cli" ]]; then
  echo "[$(stamp)] pulse-intel introuvable: $cli" >&2
  exit 1
fi

cd "$intel_dir" || exit 1
"$cli" gate --cycle-start "$cycle_start"
gate=$?
case "$gate" in
  0) ;;
  10|11) exit 0 ;;
  *) echo "[$(stamp)] garde en échec (code $gate), passage lancé quand même" >&2 ;;
esac

echo "[$(stamp)] run --once (launchd) — $(power)"
/usr/bin/caffeinate -i "$cli" run --once
code=$?
echo "[$(stamp)] fin du passage, code $code — $(power)"
exit "$code"
