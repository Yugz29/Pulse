#!/usr/bin/env bash

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd "$script_dir/.." && pwd -P)"
python="$repo_root/.venv/bin/python"

if [[ ! -x "$python" ]]; then
  python="$(command -v python3 || true)"
fi

if [[ -z "$python" ]]; then
  echo "Pulse V2 status: Python 3 introuvable." >&2
  exit 1
fi

cd "$repo_root"
url="$("$python" -c \
  'from daemon_v2.runtime_config import status_url; print(status_url())')"

# /status reconstruit la journée courante : mesuré à ~2,1 s, soit juste
# au-dessus des 2 s d'origine, qui faisaient annoncer « daemon inaccessible »
# pendant que les cinq services tournaient et que la route répondait 200.
# Le coût suit le volume du jour, pas la taille de l'historique.
timeout_s=10

response="$(curl --silent --fail --max-time "$timeout_s" "$url")" \
  && curl_status=0 || curl_status=$?

if [[ $curl_status -ne 0 ]]; then
  # 28 = délai dépassé : le daemon est là mais trop lent. Le confondre avec
  # une absence de daemon envoie chercher la panne au mauvais endroit.
  if [[ $curl_status -eq 28 ]]; then
    echo "Pulse V2: le daemon n'a pas répondu en ${timeout_s} s sur ${url%/status}/."
    echo "Le service tourne peut-être : vérifier avec 'launchctl list | grep pulse'."
  else
    echo "Pulse V2: daemon inaccessible sur ${url%/status}/."
    echo "Pulse n'a pas été démarré automatiquement."
  fi
  exit 1
fi

printf '%s' "$response" | "$python" -c '
import json
import sys

status = json.load(sys.stdin)
last_event = status["last_event"]
last_text = (
    "{} · {} · {}".format(
        last_event["occurred_at"], last_event["type"], last_event["summary"]
    )
    if last_event
    else "aucun"
)
workspace = status["primary_workspace"] or "non détecté"
db_state = "oui" if status["database_exists"] else "non"

print("Pulse V2")
print("  Daemon             : {}".format(status["daemon"]))
# Absente : le daemon qui répond est antérieur à la 0.8.9.0.
print("  Version servie     : {} · code {}".format(
    status.get("version") or "non servie",
    status.get("code_fingerprint") or "non servi",
))
print("  URL                : {}".format(status["url"]))
print("  Base SQLite        : {}".format(status["database_path"]))
print(f"  Base existante     : {db_state}")
print("  Date               : {}".format(status["date"]))
print("  Événements du jour : {}".format(status["event_count"]))
print("  Sessions affichées : {}".format(status["displayed_session_count"]))
print(f"  Dernier événement  : {last_text}")
print(f"  Workspace principal: {workspace}")
print("  Watcher terminal   : {}".format(status["terminal_watcher"]))
'

# Preuve d'usage minimale du Context API : le status consomme le contrat.
context_url="${url%/status}/context"
if context="$(curl --silent --fail --max-time "$timeout_s" "$context_url")"; then
  printf '%s' "$context" | "$python" -c '
import json
import sys

snapshot = json.load(sys.stdin)
session = snapshot["current_session"]
if session is None:
    print("  Contexte           : aucune session en cours")
else:
    minutes = session["duration_minutes"]
    hours, remaining = divmod(minutes, 60)
    since = f"{hours} h {remaining:02d}" if hours else f"{minutes} min"
    projects = ", ".join(session["projects"]) or "projet non résolu"
    print(f"  Contexte           : session en cours depuis {since} · {projects}")
'
else
  echo "  Contexte           : indisponible (${context_url})"
fi

echo ""
echo "Services launchd"
# Un service launchd ne recharge jamais son code : après un merge, il exécute
# l'ancien tant qu'il n'est pas redémarré. Le daemon a servi le schéma 2 du
# 2026-09-06 au 11 sans que rien ne le montre. Trois états : à jour, STALE,
# INCONNU. L'empreinte du code décide (daemon_v2/code_fingerprint.py : arbre
# syntaxique sans docstrings, plus VERSION et requirements.txt) : un docstring
# ne marque rien, un changement sans bump est vu. La version se lit à côté.
# L'observateur Swift est jugé sur les sources notées à son installation.
served="$(printf '%s' "$response" | "$python" -c '
import json, sys
status = json.load(sys.stdin)
print(status.get("version") or "")
print(status.get("code_fingerprint") or "")' 2>/dev/null || true)"
served_version="$(printf '%s\n' "$served" | sed -n 1p)"
served_fingerprint="$(printf '%s\n' "$served" | sed -n 2p)"
printf '  %-28s: version %s · code %s\n' "checkout" \
  "$(cat "$repo_root/VERSION" 2>/dev/null || echo illisible)" \
  "$("$python" -c 'from daemon_v2.code_fingerprint import python_fingerprint; print(python_fingerprint() or "illisible")' 2>/dev/null || echo illisible)"
# L'état vient en tête de ligne, dans une colonne fixe, avant le « running » de
# launchd : « running » dit que le processus vit, pas qu'il exécute le bon
# code. INCONNU et STALE sont en capitales, « à jour » non. Couleur seulement
# sur un terminal, jamais dans un fichier ni sous NO_COLOR.
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  c_ok=$'\033[32m'; c_stale=$'\033[31m'; c_unknown=$'\033[33m'; c_off=$'\033[0m'
else
  c_ok=""; c_stale=""; c_unknown=""; c_off=""
fi
n_ok=0; n_stale=0; n_unknown=0
for label in com.pulse.daemon com.pulse.outbox-worker com.pulse.agent-producers \
             com.pulse.file-watcher com.pulse.app-observer; do
  info="$(launchctl print "gui/$(id -u)/$label" 2>/dev/null)"
  if [[ -z "$info" ]]; then
    printf '  %-28s: %-9s non installé\n' "$label" ""
    continue
  fi
  pid="$(printf '%s' "$info" | grep 'pid = ' | grep -o '[0-9]*' || true)"
  state="$(printf '%s' "$info" | grep -m1 'state = ' | sed 's/.*state = //')"
  verdict=""; detail=""
  if [[ -n "$pid" ]]; then
    columns="$("$python" -m daemon_v2.service_staleness "$label" "$pid" "$served_version" "$served_fingerprint" 2>/dev/null || true)"
    verdict="${columns%%$'\t'*}"
    [[ "$columns" == *$'\t'* ]] && detail="${columns#*$'\t'}"
  fi
  case "$verdict" in
    "à jour") color="$c_ok"; n_ok=$((n_ok + 1)) ;;
    STALE)    color="$c_stale"; n_stale=$((n_stale + 1)) ;;
    INCONNU)  color="$c_unknown"; n_unknown=$((n_unknown + 1)) ;;
    *)        color="" ;;
  esac
  # Largeur à la main : printf compte des octets, « à jour » a un accent.
  tag=""; pad="         "
  if [[ -n "$verdict" ]]; then
    tag="[$verdict]"; pad="$(printf '%*s' $((9 - ${#tag})) "")"
  fi
  printf '  %-28s: %s%s%s%s %s%s%s\n' "$label" "$color" "$tag" "$c_off" "$pad" \
    "$state" "${pid:+ (pid $pid)}" "${detail:+ · $detail}"
done
printf '  %-28s: %s à jour · %s STALE · %s INCONNU\n' "bilan du code" "$n_ok" "$n_stale" "$n_unknown"
if (( n_stale > 0 || n_unknown > 0 )); then
  echo "  → INCONNU n'est pas « à jour » : tant qu'un service n'annonce pas son code, rien ne dit ce qu'il exécute."
fi

echo ""
echo "Outbox"
"$python" -m daemon_v2.producer_outbox status 2>/dev/null | grep -E "^(Pending|Dead-letter):" | sed 's/^/  /'
echo ""
echo "Journaux : ~/.pulse_v2/logs/ (make logs pour les suivre)"
