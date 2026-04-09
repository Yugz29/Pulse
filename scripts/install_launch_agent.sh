#!/bin/zsh

set -eu

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PLIST_SOURCE="$REPO_DIR/launchd/cafe.pulse.daemon.plist"
PLIST_TARGET="$HOME/Library/LaunchAgents/cafe.pulse.daemon.plist"
HOME_ESCAPED="${HOME//\//\\/}"
REPO_ESCAPED="${REPO_DIR//\//\\/}"

mkdir -p "$HOME/Library/LaunchAgents"
/usr/bin/sed \
  -e "s/__HOME_DIR__/$HOME_ESCAPED/g" \
  -e "s/__REPO_DIR__/$REPO_ESCAPED/g" \
  "$PLIST_SOURCE" > "$PLIST_TARGET"
/bin/launchctl unload "$PLIST_TARGET" >/dev/null 2>&1 || true
/bin/launchctl load "$PLIST_TARGET"
echo "Installed LaunchAgent: $PLIST_TARGET"
