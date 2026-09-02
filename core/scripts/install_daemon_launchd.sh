#!/usr/bin/env bash
# Install the launchd services for the Pulse daemon and its outbox worker.
#
# Usage: scripts/install_daemon_launchd.sh [--uninstall]
#
# Generates two user LaunchAgents (one per long-running service, KeepAlive):
#   com.pulse.daemon         -> python -m daemon_v2.main
#   com.pulse.outbox-worker  -> python -m daemon_v2.outbox_worker
# then (re)loads them via launchctl. Refuses to overwrite plists it did not
# install itself. Idempotent. Same managed-marker pattern as
# install_agent_producers_launchd.sh.
#
# Coexistence with scripts/dev.sh: the worker holds a flock and a second
# instance exits silently; the daemon would conflict on the port — stop the
# services first (--uninstall or launchctl bootout) before running dev.sh.

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
marker="pulse-daemon-services: managed"
labels=("com.pulse.daemon" "com.pulse.outbox-worker")
modules=("daemon_v2.main" "daemon_v2.outbox_worker")
logs=("daemon.log" "outbox_worker.log")

if [[ "${1:-}" == "--uninstall" ]]; then
  for label in "${labels[@]}"; do
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
    rm -f -- "$plist_dir/$label.plist"
    echo "LaunchAgent désinstallé: $label"
  done
  exit 0
fi

mkdir -p -- "$plist_dir" "$log_dir"

for i in 0 1; do
  label="${labels[$i]}"
  module="${modules[$i]}"
  log_file="${logs[$i]}"
  plist_path="$plist_dir/$label.plist"

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
  <!-- $marker (généré par install_daemon_launchd.sh) -->
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$python</string>
    <string>-m</string>
    <string>$module</string>
  </array>
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
done

echo "Journaux: $log_dir/daemon.log, $log_dir/outbox_worker.log"
