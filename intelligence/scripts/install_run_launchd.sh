#!/usr/bin/env bash
# Install the daily launchd agent running `pulse-intel run --once`.
#
# Usage: scripts/install_run_launchd.sh [--uninstall]
#        PULSE_INTEL_RUN_HOUR=6 PULSE_INTEL_RUN_MINUTE=30 scripts/install_run_launchd.sh
#
# Generates ~/Library/LaunchAgents/com.pulse.intelligence-run.plist pointing
# at scripts/pulse_intel_run.sh by absolute path (future edits to the script
# apply without reinstalling), then (re)loads it via launchctl. Calendar job:
# if the Mac is asleep at that time, launchd runs it at wake-up. Refuses to
# overwrite a plist it did not install itself. Idempotent. Same pattern as
# core/scripts/install_agent_producers_launchd.sh.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
wrapper="$script_dir/pulse_intel_run.sh"
label="com.pulse.intelligence-run"
plist_dir="$HOME/Library/LaunchAgents"
plist_path="$plist_dir/$label.plist"
log_dir="$HOME/.pulse_intelligence/logs"
marker="pulse-intelligence-run: managed"
hour="${PULSE_INTEL_RUN_HOUR:-6}"
minute="${PULSE_INTEL_RUN_MINUTE:-30}"

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
chmod 700 -- "$log_dir"

cat > "$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <!-- $marker (généré par install_run_launchd.sh) -->
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$wrapper</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$hour</integer>
    <key>Minute</key>
    <integer>$minute</integer>
  </dict>
  <key>RunAtLoad</key>
  <false/>
  <key>StandardOutPath</key>
  <string>$log_dir/run.log</string>
  <key>StandardErrorPath</key>
  <string>$log_dir/run.log</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
PLIST

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

printf 'LaunchAgent installé: %s (chaque jour à %02d:%02d, rattrapé au réveil)\n' "$label" "$hour" "$minute"
echo "Journal: $log_dir/run.log"
