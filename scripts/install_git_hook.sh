#!/usr/bin/env bash
# Install the Pulse git_commit post-commit hook into a target repository.
#
# Usage: scripts/install_git_hook.sh <path-to-target-repo>
#
# Writes a small wrapper at <target-repo>/.git/hooks/post-commit that calls
# scripts/pulse_git_hook.sh by its absolute path, so future edits to that
# script apply without reinstalling. Refuses to overwrite a pre-existing
# hook it did not install itself.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
pulse_hook="$script_dir/pulse_git_hook.sh"
marker="# pulse-git-hook: managed"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <path-to-target-repo>" >&2
  exit 1
fi

target_repo="$(cd "$1" 2>/dev/null && pwd -P)"
if [[ -z "$target_repo" ]]; then
  echo "Dépôt introuvable: $1" >&2
  exit 1
fi

git_dir="$(git -C "$target_repo" rev-parse --git-dir 2>/dev/null)"
if [[ -z "$git_dir" ]]; then
  echo "Pas un dépôt Git: $target_repo" >&2
  exit 1
fi
case "$git_dir" in
  /*) : ;;
  *) git_dir="$target_repo/$git_dir" ;;
esac

hooks_dir="$git_dir/hooks"
mkdir -p -- "$hooks_dir"
hook_path="$hooks_dir/post-commit"

if [[ -e "$hook_path" ]] && ! grep -qF "$marker" "$hook_path" 2>/dev/null; then
  echo "Un hook post-commit existe déjà et n'est pas géré par Pulse: $hook_path" >&2
  echo "Fusionnez-le manuellement pour appeler aussi: $pulse_hook" >&2
  exit 1
fi

cat > "$hook_path" <<EOF
#!/usr/bin/env bash
$marker (généré par install_git_hook.sh, ne pas éditer à la main)
exec "$pulse_hook" "\$@"
EOF
chmod +x "$hook_path"

echo "Hook Pulse installé: $hook_path"
echo "Il appelle: $pulse_hook"