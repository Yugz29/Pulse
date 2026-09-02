#!/usr/bin/env bash
# Bascule propre entre les deux modes de fonctionnement de Pulse.
#
# Usage: scripts/pulse_mode.sh {dev|service|status}
#
#   dev      Décharge les services launchd (daemon + worker, plists conservés)
#            puis lance le hot reload au premier plan. À la sortie (Ctrl-C
#            compris), les services sont AUTOMATIQUEMENT rechargés : l'oubli
#            de réinstallation est structurellement impossible.
#   service  (Re)charge les services launchd — les installe s'il le faut.
#   status   Affiche le mode courant et l'état des services.
#
# Le LaunchAgent horaire des producteurs (com.pulse.agent-producers) n'est
# jamais touché : il écrit dans l'outbox durable, valable dans les deux modes.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(dirname "$script_dir")"
services=("com.pulse.daemon" "com.pulse.outbox-worker")
# Observateurs résidents (install_observers_launchd.sh), optionnels :
# déchargés en mode dev — dev.sh lance ses propres watcher + observateur,
# sinon événements en double — puis rechargés s'ils sont installés.
observer_services=("com.pulse.file-watcher" "com.pulse.app-observer")
plist_dir="$HOME/Library/LaunchAgents"

services_loaded() {
  launchctl print "gui/$(id -u)/com.pulse.daemon" >/dev/null 2>&1
}

load_observer_services() {
  for label in "${observer_services[@]}"; do
    if [[ -f "$plist_dir/$label.plist" ]]; then
      launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
      launchctl bootstrap "gui/$(id -u)" "$plist_dir/$label.plist" || return 1
      echo "[pulse-mode] observateur rechargé : $label"
    fi
  done
}

load_services() {
  local missing=0
  for label in "${services[@]}"; do
    [[ -f "$plist_dir/$label.plist" ]] || missing=1
  done
  if [[ $missing -eq 1 ]]; then
    "$script_dir/install_daemon_launchd.sh" || return 1
    load_observer_services
    return $?
  fi
  for label in "${services[@]}"; do
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
    launchctl bootstrap "gui/$(id -u)" "$plist_dir/$label.plist" || return 1
  done
  load_observer_services || return 1
  echo "[pulse-mode] mode service : daemon + worker + observateurs rechargés (KeepAlive)"
}

unload_services() {
  for label in "${services[@]}" "${observer_services[@]}"; do
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
  done
}

wait_port_free() {
  local port
  port="$("$repo_root/.venv/bin/python" -c \
    'from daemon_v2.runtime_config import core_port; print(core_port())' \
    2>/dev/null || echo 8765)"
  for _ in $(seq 1 20); do
    if ! lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "[pulse-mode] le port $port est toujours occupé" >&2
  return 1
}

case "${1:-}" in
  dev)
    echo "[pulse-mode] mode dev : services launchd déchargés, hot reload au premier plan"
    unload_services
    # Quoi qu'il arrive au hot reload (Ctrl-C, crash, exit), on revient en
    # mode service : c'est la garantie centrale de ce script.
    trap 'echo "[pulse-mode] retour au mode service…"; load_services' EXIT
    wait_port_free || exit 1
    cd "$repo_root" && make dev-reload
    ;;
  service)
    load_services
    ;;
  status)
    if services_loaded; then
      echo "Mode : service (launchd, KeepAlive)"
    else
      echo "Mode : dev ou arrêté (services launchd déchargés)"
    fi
    cd "$repo_root" && ./scripts/status.sh
    ;;
  *)
    echo "Usage: $0 {dev|service|status}" >&2
    exit 1
    ;;
esac
