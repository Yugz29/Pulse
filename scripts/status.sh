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

if ! response="$(curl --silent --fail --max-time 2 "$url")"; then
  echo "Pulse V2: daemon inaccessible sur ${url%/status}/."
  echo "Pulse n'a pas été démarré automatiquement."
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

echo ""
echo "Services launchd"
for label in com.pulse.daemon com.pulse.outbox-worker com.pulse.agent-producers; do
  info="$(launchctl print "gui/$(id -u)/$label" 2>/dev/null)"
  if [[ -z "$info" ]]; then
    printf '  %-28s: non installé\n' "$label"
    continue
  fi
  pid="$(printf '%s' "$info" | grep 'pid = ' | grep -o '[0-9]*' || true)"
  state="$(printf '%s' "$info" | grep -m1 'state = ' | sed 's/.*state = //')"
  printf '  %-28s: %s%s\n' "$label" "$state" "${pid:+ (pid $pid)}"
done

echo ""
echo "Outbox"
"$python" -m daemon_v2.producer_outbox status 2>/dev/null | grep -E "^(Pending|Dead-letter):" | sed 's/^/  /'
echo ""
echo "Journaux : ~/.pulse_v2/logs/ (make logs pour les suivre)"
