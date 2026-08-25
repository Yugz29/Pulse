#!/usr/bin/env bash
# Post-commit hook: records every commit as a dedicated git_commit event,
# regardless of which client created it (terminal, VS Code, another GUI...).
#
# This script is not meant to be copied into a repository's .git/hooks
# directly. Install it with scripts/install_git_hook.sh, which writes a
# tiny post-commit wrapper that calls this script by its absolute path, so
# updates here apply to every repo without reinstalling.
#
# Best-effort by design: a missing venv, a stopped daemon, or any failure
# here must never block or fail the commit itself.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
pulse_repo_root="$(cd "$script_dir/.." && pwd -P)"
python="$pulse_repo_root/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  python="$(command -v python3 || true)"
fi
[[ -n "$python" ]] || exit 0

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[[ -n "$repo_root" ]] || exit 0

commit_hash="$(git rev-parse HEAD 2>/dev/null)" || exit 0
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
[[ -n "$branch" ]] || branch="HEAD"
message="$(git log -1 --pretty=%B HEAD 2>/dev/null)"
occurred_at="$(git log -1 --pretty=%cI HEAD 2>/dev/null)"
repository="$(basename "$repo_root")"

shortstat="$(git show --shortstat --pretty=format: HEAD 2>/dev/null | tail -n1)"

PYTHONPATH="$pulse_repo_root" "$python" -c '
import json
import re
import sys

shortstat = sys.argv[7]

def _extract(pattern, text):
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None

payload = {
    "commit_hash": sys.argv[1],
    "repository": sys.argv[2],
    "git_root": sys.argv[3],
    "branch": sys.argv[4],
    "message": sys.argv[5],
    "occurred_at": sys.argv[6],
}
files_changed = _extract(r"(\d+) files? changed", shortstat)
insertions = _extract(r"(\d+) insertions?\(\+\)", shortstat)
deletions = _extract(r"(\d+) deletions?\(-\)", shortstat)
if files_changed is not None:
    payload["files_changed"] = files_changed
if insertions is not None:
    payload["insertions"] = insertions
if deletions is not None:
    payload["deletions"] = deletions

print(json.dumps(payload))
' "$commit_hash" "$repository" "$repo_root" "$branch" "$message" "$occurred_at" "$shortstat" 2>/dev/null |
  PYTHONPATH="$pulse_repo_root" "$python" -m daemon_v2.producer_outbox \
    enqueue-git-commit >/dev/null 2>&1

exit 0