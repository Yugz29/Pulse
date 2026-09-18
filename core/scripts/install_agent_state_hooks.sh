#!/usr/bin/env bash
# Pose (ou retire) les hooks Claude Code de l'état d'agent dans
# ~/.claude/settings.json, et lie le plugin SwiftBar si SwiftBar est là.
#
#   scripts/install_agent_state_hooks.sh              # pose les six hooks
#   scripts/install_agent_state_hooks.sh --uninstall  # les retire
#
# Idempotent : nos entrées se reconnaissent à la commande
# (`pulse_agent_state_hook.sh`) ; les autres hooks du fichier — dont le
# hook SessionEnd existant — ne sont pas touchés. Une sauvegarde
# `settings.json.bak-agent-state` est écrite avant toute modification.
# Claude Code relit ses hooks à chaud (docs hooks-guide) : pas de relance.
#
# SwiftBar n'est jamais installé par ce script : s'il manque, il le dit et
# donne la commande, c'est tout. Refuse de tourner depuis un worktree git.
# Surcharges de test : PULSE_CLAUDE_SETTINGS (fichier de réglages),
# PULSE_SWIFTBAR_PLUGIN_DIR (dossier de plugins), PULSE_ALLOW_WORKTREE=1
# (lève le refus, pour la suite de tests qui tourne parfois en worktree).

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
hook="$script_dir/pulse_agent_state_hook.sh"
plugin="$script_dir/swiftbar/pulse-agents.5s.sh"
settings="${PULSE_CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
mode="install"
[[ "${1:-}" == "--uninstall" ]] && mode="uninstall"

# Jamais depuis un worktree : les hooks pointent sur ce checkout par chemin
# absolu, et un worktree se retire (`git worktree remove`), ce qui laisserait
# six hooks sur des scripts disparus. Le checkout principal a le même
# `--git-dir` et `--git-common-dir` ; un worktree lié, non.
git_dir="$(git -C "$script_dir" rev-parse --git-dir 2>/dev/null || true)"
common_dir="$(git -C "$script_dir" rev-parse --git-common-dir 2>/dev/null || true)"
if [[ -n "$git_dir" && -n "$common_dir" && "${PULSE_ALLOW_WORKTREE:-}" != "1" ]]; then
  git_dir="$(cd "$script_dir" && cd "$git_dir" && pwd -P)"
  common_dir="$(cd "$script_dir" && cd "$common_dir" && pwd -P)"
  if [[ "$git_dir" != "$common_dir" ]]; then
    echo "refus : ce checkout est un worktree ($(cd "$script_dir/../.." && pwd -P))." >&2
    echo "Les hooks pointeraient sur des scripts qui disparaissent avec lui. Lance l'installateur depuis le checkout principal : $(dirname "$common_dir")/core/scripts/install_agent_state_hooks.sh" >&2
    exit 2
  fi
fi

python="$(command -v python3 || true)"
if [[ -z "$python" ]]; then
  echo "python3 introuvable" >&2
  exit 2
fi

"$python" - "$settings" "$hook" "$mode" <<'PY' || exit 2
import json, os, shutil, sys
from pathlib import Path

settings, hook, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
MARK = "pulse_agent_state_hook.sh"
WANTED = {
    "SessionStart": (None, hook),
    "UserPromptSubmit": (None, hook),
    "PostToolUse": (None, hook),
    "Notification": ("permission_prompt", f"{hook} permission_prompt"),
    "Stop": (None, hook),
    "SessionEnd": (None, hook),
}

data = {}
if settings.exists():
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"{settings} illisible : {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print(f"{settings} : objet JSON attendu", file=sys.stderr)
        sys.exit(1)

hooks = data.get("hooks")
if not isinstance(hooks, dict):
    hooks = {}

def ours(entry):
    return isinstance(entry, dict) and any(
        isinstance(h, dict) and MARK in str(h.get("command", "")) for h in entry.get("hooks", [])
    )

changed = False
for event in set(list(hooks) + list(WANTED)):
    entries = hooks.get(event)
    if not isinstance(entries, list):
        entries = []
    kept = [e for e in entries if not ours(e)]
    if mode == "install" and event in WANTED:
        matcher, command = WANTED[event]
        entry = {"hooks": [{"type": "command", "command": command, "timeout": 3}]}
        if matcher:
            entry["matcher"] = matcher
        kept.append(entry)
    if kept != entries:
        changed = True
    if kept:
        hooks[event] = kept
    elif event in hooks:
        del hooks[event]
        changed = True

if hooks:
    data["hooks"] = hooks
elif "hooks" in data:
    del data["hooks"]

if not changed:
    print(f"réglages déjà à jour : {settings}")
    sys.exit(0)
settings.parent.mkdir(parents=True, exist_ok=True)
if settings.exists():
    shutil.copy2(settings, settings.with_name(settings.name + ".bak-agent-state"))
tmp = settings.with_name(settings.name + ".tmp-agent-state")
tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
os.replace(tmp, settings)
count = sum(1 for entries in hooks.values() for e in entries if ours(e))
print(f"{'posés' if mode == 'install' else 'retirés'} : {count} hooks d'état d'agent dans {settings}")
PY

# --- Plugin SwiftBar ---------------------------------------------------------
plugin_dir="${PULSE_SWIFTBAR_PLUGIN_DIR:-$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)}"
app_present=0
[[ -d /Applications/SwiftBar.app || -d "$HOME/Applications/SwiftBar.app" || -n "${PULSE_SWIFTBAR_PLUGIN_DIR:-}" ]] && app_present=1

if [[ "$mode" == "uninstall" ]]; then
  if [[ -n "$plugin_dir" && -L "$plugin_dir/pulse-agents.5s.sh" ]]; then
    rm -f "$plugin_dir/pulse-agents.5s.sh"
    echo "plugin retiré de $plugin_dir"
  fi
  exit 0
fi

if [[ "$app_present" == 1 && -n "$plugin_dir" && -d "$plugin_dir" ]]; then
  ln -sfn "$plugin" "$plugin_dir/pulse-agents.5s.sh"
  echo "plugin lié : $plugin_dir/pulse-agents.5s.sh -> $plugin"
elif [[ "$app_present" == 1 ]]; then
  echo "SwiftBar est installé mais n'a pas encore de dossier de plugins : lance-le une fois, choisis le dossier, puis relance ce script."
else
  echo "SwiftBar absent : hooks posés, plugin non lié. Installation, avec ton accord : brew install --cask swiftbar ; puis relancer ce script."
fi
exit 0
