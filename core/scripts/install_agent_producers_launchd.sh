#!/usr/bin/env bash
# Install the hourly launchd agent running the Pulse agent producers.
#
# Usage: scripts/install_agent_producers_launchd.sh [--uninstall]
#
# Generates ~/Library/LaunchAgents/com.pulse.agent-producers.plist pointing
# at scripts/pulse_agent_producers.sh by absolute path (future edits to the
# script apply without reinstalling), then (re)loads it via launchctl.
# Refuses to overwrite a plist it did not install itself. Idempotent.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
wrapper="$script_dir/pulse_agent_producers.sh"
label="com.pulse.agent-producers"
plist_dir="$HOME/Library/LaunchAgents"
plist_path="$plist_dir/$label.plist"
log_dir="$HOME/.pulse_v2/logs"
marker="pulse-agent-producers: managed"

if [[ ! -x "$wrapper" ]]; then
  echo "Wrapper introuvable ou non exécutable: $wrapper" >&2
  exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
  rm -f -- "$plist_path"
  echo "LaunchAgent désinstallé: $label"
  exit 0
fi

if [[ -e "$plist_path" ]] && ! grep -qF "$marker" "$plist_path" 2>/dev/null; then
  echo "Un plist existe déjà et n'est pas géré par Pulse: $plist_path" >&2
  exit 1
fi

mkdir -p -- "$plist_dir" "$log_dir"
"$script_dir/fix_permissions.sh"

cat > "$plist_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <!-- $marker (généré par install_agent_producers_launchd.sh) -->
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$wrapper</string>
  </array>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$log_dir/agent_producers.log</string>
  <key>StandardErrorPath</key>
  <string>$log_dir/agent_producers.log</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
EOF

if ! plutil -lint -s "$plist_path"; then
  echo "Plist généré invalide: $plist_path" >&2
  exit 1
fi

# Recharge idempotente : bootout silencieux si déjà chargé, puis bootstrap.
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
if ! launchctl bootstrap "gui/$(id -u)" "$plist_path"; then
  echo "launchctl bootstrap en échec pour $plist_path" >&2
  exit 1
fi

echo "LaunchAgent installé: $label (toutes les heures + au chargement)"
echo "Journal: $log_dir/agent_producers.log"
