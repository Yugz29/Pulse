#!/usr/bin/env bash
# Install the launchd agent that runs `pulse-intel run --once` once a day.
#
# Usage: scripts/install_run_launchd.sh [--uninstall]
#        PULSE_INTEL_CYCLE_START=07:00 PULSE_INTEL_RUN_INTERVAL=900 scripts/install_run_launchd.sh
#
# Generates ~/Library/LaunchAgents/com.pulse.intelligence-run.plist pointing
# at scripts/pulse_intel_run.sh by absolute path (future edits to the script
# apply without reinstalling), then (re)loads it via launchctl. The agent
# runs every PULSE_INTEL_RUN_INTERVAL seconds (default 900); the wrapper's
# gate turns each run into a no-op once the day's pass is done, and defers
# it in a DarkWake, while the lid is closed or the battery is under the floor — a calendar
# job fired at wake-up inside a two-second DarkWake, lid closed, and the
# pass only progressed by DarkWake slices until the Mac was really awake.
# The day starts at PULSE_INTEL_CYCLE_START (local time, default 06:30).
# Refuses to overwrite a plist it did not install itself. Idempotent. Same
# pattern as core/scripts/install_agent_producers_launchd.sh.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
wrapper="$script_dir/pulse_intel_run.sh"
label="com.pulse.intelligence-run"
plist_dir="$HOME/Library/LaunchAgents"
plist_path="$plist_dir/$label.plist"
log_dir="$HOME/.pulse_intelligence/logs"
marker="pulse-intelligence-run: managed"
cycle_start="${PULSE_INTEL_CYCLE_START:-06:30}"
interval="${PULSE_INTEL_RUN_INTERVAL:-900}"

if [[ ! -x "$wrapper" ]]; then
  echo "Wrapper introuvable ou non exécutable: $wrapper" >&2
  exit 1
fi

if [[ ! "$cycle_start" =~ ^[0-9]{2}:[0-9]{2}$ ]]; then
  echo "PULSE_INTEL_CYCLE_START attendu au format HH:MM: $cycle_start" >&2
  exit 1
fi
if [[ ! "$interval" =~ ^[0-9]+$ ]] || (( interval < 60 )); then
  echo "PULSE_INTEL_RUN_INTERVAL attendu en secondes (60 au moins): $interval" >&2
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
chmod 700 "$log_dir"

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
  <key>EnvironmentVariables</key>
  <dict>
    <key>PULSE_INTEL_CYCLE_START</key>
    <string>$cycle_start</string>
  </dict>
  <key>StartInterval</key>
  <integer>$interval</integer>
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

printf 'LaunchAgent installé: %s (toutes les %s s ; lot du jour à partir de %s, en réveil complet, capot ouvert, batterie au-dessus du plancher)\n' "$label" "$interval" "$cycle_start"
