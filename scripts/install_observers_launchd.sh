#!/usr/bin/env bash
# Install the resident observers as launchd services (mode service complet).
#
# Usage: scripts/install_observers_launchd.sh [--uninstall]
#
# Deux LaunchAgents KeepAlive (chantier « couverture d'observation en mode
# service » — sans eux, le journal est aveugle aux fichiers et aux apps dès
# que make dev ne tourne pas) :
#   com.pulse.file-watcher  -> python -m daemon_v2.file_watcher --config
#                              ~/.pulse_v2/watched_workspaces
#   com.pulse.app-observer  -> ~/.pulse_v2/bin/PulseApplicationObserver
#                              (binaire release copié hors de .build)
#
# La liste des workspaces observés vit dans ~/.pulse_v2/watched_workspaces
# (un chemin par ligne, # commentaires) — créée avec ce dépôt comme seule
# entrée si absente. Après édition : launchctl kickstart -k
# gui/$UID/com.pulse.file-watcher (la liste est lue au démarrage).
#
# Les deux services écrivent dans l'outbox durable : daemon éteint, rien
# n'est perdu. Coexistence dev.sh : pulse_mode.sh dev décharge ces agents
# (sinon événements en double) et les recharge en sortie.
#
# Même patron managé que install_daemon_launchd.sh : marqueur, refus
# d'écraser un plist étranger, plutil -lint, --uninstall, idempotent.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(dirname "$script_dir")"
python="$repo_root/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  echo "Python du venv introuvable: $python" >&2
  exit 1
fi

plist_dir="$HOME/Library/LaunchAgents"
log_dir="$HOME/.pulse_v2/logs"
bin_dir="$HOME/.pulse_v2/bin"
workspaces_file="$HOME/.pulse_v2/watched_workspaces"
marker="pulse-observer-services: managed"
watcher_label="com.pulse.file-watcher"
observer_label="com.pulse.app-observer"

if [[ "${1:-}" == "--uninstall" ]]; then
  for label in "$watcher_label" "$observer_label"; do
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
    rm -f -- "$plist_dir/$label.plist"
    echo "LaunchAgent désinstallé: $label"
  done
  exit 0
fi

mkdir -p -- "$plist_dir" "$log_dir" "$bin_dir"

if [[ ! -f "$workspaces_file" ]]; then
  cat > "$workspaces_file" <<EOF
# Workspaces observés par le watcher fichiers résident (com.pulse.file-watcher).
# Un chemin absolu par ligne (~ accepté). Après édition :
#   launchctl kickstart -k gui/\$(id -u)/com.pulse.file-watcher
$repo_root
EOF
  echo "Liste de workspaces créée: $workspaces_file (à éditer)"
fi

echo "Construction de l'observateur d'applications (release)"
if ! swift build -c release \
    --package-path "$repo_root/macos_observer" \
    --product PulseApplicationObserver; then
  echo "Échec du build Swift" >&2
  exit 1
fi
swift_bin_path="$(swift build -c release \
  --package-path "$repo_root/macos_observer" \
  --show-bin-path)" || exit 1
install -m 0755 "$swift_bin_path/PulseApplicationObserver" \
  "$bin_dir/PulseApplicationObserver"

write_and_load() {
  local label="$1"
  local log_file="$2"
  local plist_body="$3"
  local plist_path="$plist_dir/$label.plist"

  if [[ -e "$plist_path" ]] && ! grep -qF "$marker" "$plist_path" 2>/dev/null; then
    echo "Un plist existe déjà et n'est pas géré par Pulse: $plist_path" >&2
    exit 1
  fi

  cat > "$plist_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <!-- $marker (généré par install_observers_launchd.sh) -->
  <key>Label</key>
  <string>$label</string>
$plist_body
  <key>WorkingDirectory</key>
  <string>$repo_root</string>
  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$log_dir/$log_file</string>
  <key>StandardErrorPath</key>
  <string>$log_dir/$log_file</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
EOF

  if ! plutil -lint -s "$plist_path"; then
    echo "Plist généré invalide: $plist_path" >&2
    exit 1
  fi

  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
  if ! launchctl bootstrap "gui/$(id -u)" "$plist_path"; then
    echo "launchctl bootstrap en échec pour $plist_path" >&2
    exit 1
  fi
  echo "LaunchAgent installé: $label (KeepAlive)"
}

write_and_load "$watcher_label" "file_watcher.log" "  <key>ProgramArguments</key>
  <array>
    <string>$python</string>
    <string>-m</string>
    <string>daemon_v2.file_watcher</string>
    <string>--config</string>
    <string>$workspaces_file</string>
  </array>"

write_and_load "$observer_label" "app_observer.log" "  <key>ProgramArguments</key>
  <array>
    <string>$bin_dir/PulseApplicationObserver</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PULSE_CORE_REPO_ROOT</key>
    <string>$repo_root</string>
  </dict>"

echo "Journaux: $log_dir/file_watcher.log, $log_dir/app_observer.log"
echo "Workspaces observés: $workspaces_file"
