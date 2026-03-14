/**
 * shellHook.ts
 * Génère les scripts de hook shell pour zsh, bash et fish.
 *
 * Stratégie :
 * - Capture commande + exit code + cwd + stderr (via fichier tmp)
 * - Envoi non-bloquant à Pulse via curl (POST localhost:{port}/command-error)
 * - Compatible : zsh, bash, fish — VSCode terminal, iTerm2, Terminal.app, Xcode
 *
 * Le stderr est capturé via un fichier temporaire /tmp/pulse_stderr_$$.
 * Le hook preexec redirige stderr, precmd lit le fichier et l'envoie.
 */

export interface ShellHookOptions {
    port: number;
}

// ── ZSH ──────────────────────────────────────────────────────────────────────

export function generateZshHook({ port }: ShellHookOptions): string {
    return `
# ── Pulse shell hook (zsh) ──────────────────────────────────────────────────
# Généré automatiquement par Pulse. Coller dans ~/.zshrc

_pulse_port=${port}
_pulse_last_cmd=""
_pulse_stderr_file="/tmp/pulse_stderr_$$"

_pulse_preexec() {
  _pulse_last_cmd="$1"
  # Redirige stderr vers fichier tmp pour capture
  exec 3>&2 2>"$_pulse_stderr_file"
}

_pulse_send() {
  local cmd="$1" exit_code="$2" stderr_content="$3"
  local cmd_escaped=$(echo "$cmd" | sed 's/\\/\\\\/g; s/"/\\"/g; s/$/\\n/g' | tr -d '\\n' | sed 's/\\\\n$//')
  local stderr_escaped=$(echo "$stderr_content" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\\\n", $0}' | sed 's/\\\\n$//')
  local cwd_escaped=$(echo "$PWD" | sed 's/\\/\\\\/g; s/"/\\"/g')
  curl -s -m 1 -X POST "http://127.0.0.1:$_pulse_port/command-error" \\
    -H "Content-Type: application/json" \\
    -d "{\\"command\\":\\"$cmd_escaped\\",\\"exit_code\\":$exit_code,\\"cwd\\":\\"$cwd_escaped\\",\\"stderr\\":\\"$stderr_escaped\\",\\"timestamp\\":$(date +%s000)}" \\
    > /dev/null 2>&1 &
}

# Vérifie si fd 3 est ouvert (stderr a été redirigé)
_pulse_fd3_open() { { true >&3; } 2>/dev/null; }

# Restaure stderr proprement — sans erreur si fd 3 absent
_pulse_restore_stderr() {
  if _pulse_fd3_open; then
    exec 2>&3 3>&-
  fi
}

# Capture Ctrl+C (SIGINT → exit code 130)
TRAPINT() {
  # Seulement si une commande est en cours d'exécution
  if [ -n "$_pulse_last_cmd" ]; then
    local cmd="$_pulse_last_cmd"
    _pulse_restore_stderr
    local stderr_content=""
    if [ -f "$_pulse_stderr_file" ]; then
      stderr_content=$(head -c 4000 "$_pulse_stderr_file" 2>/dev/null || echo "")
      rm -f "$_pulse_stderr_file"
    fi
    _pulse_send "$cmd" 130 "$stderr_content"
    _pulse_last_cmd=""
  fi
  # Propage SIGINT normalement (copier-coller, etc.)
  return 130
}

_pulse_precmd() {
  local exit_code=$?
  _pulse_restore_stderr

  if [ $exit_code -ne 0 ] && [ -n "$_pulse_last_cmd" ]; then
    local stderr_content=""
    if [ -f "$_pulse_stderr_file" ]; then
      stderr_content=$(head -c 4000 "$_pulse_stderr_file" 2>/dev/null || echo "")
      rm -f "$_pulse_stderr_file"
    fi
    _pulse_send "$_pulse_last_cmd" $exit_code "$stderr_content"
  else
    rm -f "$_pulse_stderr_file"
  fi
  _pulse_last_cmd=""
}

# Enregistrement des hooks
if (( \${+functions[add-zsh-hook]} )); then
  add-zsh-hook preexec _pulse_preexec
  add-zsh-hook precmd  _pulse_precmd
else
  autoload -Uz add-zsh-hook
  add-zsh-hook preexec _pulse_preexec
  add-zsh-hook precmd  _pulse_precmd
fi
# ────────────────────────────────────────────────────────────────────────────
`.trim();
}

// ── BASH ─────────────────────────────────────────────────────────────────────

export function generateBashHook({ port }: ShellHookOptions): string {
    return `
# ── Pulse shell hook (bash) ─────────────────────────────────────────────────
# Généré automatiquement par Pulse. Coller dans ~/.bashrc ou ~/.bash_profile

_pulse_port=${port}
_pulse_last_cmd=""
_pulse_stderr_file="/tmp/pulse_stderr_$$"
_pulse_running=0

_pulse_preexec() {
  if [ "$_pulse_running" = "0" ]; then
    _pulse_last_cmd="$BASH_COMMAND"
    exec 3>&2 2>"$_pulse_stderr_file"
    _pulse_running=1
  fi
}

_pulse_precmd() {
  local exit_code=$?
  if [ "$_pulse_running" = "1" ]; then
    exec 2>&3 3>&-
    _pulse_running=0

    if [ $exit_code -ne 0 ] && [ -n "$_pulse_last_cmd" ]; then
      local stderr_content=""
      if [ -f "$_pulse_stderr_file" ]; then
        stderr_content=$(head -c 4000 "$_pulse_stderr_file" 2>/dev/null || echo "")
        rm -f "$_pulse_stderr_file"
      fi

      local cmd_escaped=$(echo "$_pulse_last_cmd" | sed 's/\\/\\\\/g; s/"/\\"/g')
      local stderr_escaped=$(echo "$stderr_content" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\\\n", $0}' | sed 's/\\\\n$//')
      local cwd_escaped=$(echo "$PWD" | sed 's/\\/\\\\/g; s/"/\\"/g')

      curl -s -m 1 -X POST "http://127.0.0.1:$_pulse_port/command-error" \\
        -H "Content-Type: application/json" \\
        -d "{
          \\"command\\": \\"$cmd_escaped\\",
          \\"exit_code\\": $exit_code,
          \\"cwd\\": \\"$cwd_escaped\\",
          \\"stderr\\": \\"$stderr_escaped\\",
          \\"timestamp\\": $(date +%s000)
        }" > /dev/null 2>&1 &
    else
      rm -f "$_pulse_stderr_file"
    fi
    _pulse_last_cmd=""
  fi
}

trap '_pulse_preexec' DEBUG
PROMPT_COMMAND="_pulse_precmd\${PROMPT_COMMAND:+; \$PROMPT_COMMAND}"
# ────────────────────────────────────────────────────────────────────────────
`.trim();
}

// ── FISH ──────────────────────────────────────────────────────────────────────

export function generateFishHook({ port }: ShellHookOptions): string {
    return `
# ── Pulse shell hook (fish) ──────────────────────────────────────────────────
# Généré automatiquement par Pulse.
# Coller dans ~/.config/fish/conf.d/pulse.fish (créer le fichier si nécessaire)

set -g _pulse_port ${port}
set -g _pulse_stderr_file /tmp/pulse_stderr_{$fish_pid}

function _pulse_preexec --on-event fish_preexec
    set -g _pulse_last_cmd $argv[1]
    # fish ne supporte pas la redirection exec — on capture via script
end

function _pulse_postcmd --on-event fish_postexec
    set exit_code $status
    if test $exit_code -ne 0; and test -n "$_pulse_last_cmd"
        set stderr_content ""
        if test -f "$_pulse_stderr_file"
            set stderr_content (head -c 4000 "$_pulse_stderr_file" 2>/dev/null)
            rm -f "$_pulse_stderr_file"
        end

        set cmd_escaped (string replace -a '\\\\' '\\\\\\\\' -- "$_pulse_last_cmd" | string replace -a '"' '\\\\"')
        set cwd_escaped (string replace -a '"' '\\\\"' -- "$PWD")

        curl -s -m 1 -X POST "http://127.0.0.1:$_pulse_port/command-error" \\
            -H "Content-Type: application/json" \\
            -d "{
              \\"command\\": \\"$cmd_escaped\\",
              \\"exit_code\\": $exit_code,
              \\"cwd\\": \\"$cwd_escaped\\",
              \\"stderr\\": \\"$stderr_escaped\\",
              \\"timestamp\\": (date +%s000)
            }" > /dev/null 2>&1 &
    end
    set -e _pulse_last_cmd
end
# ────────────────────────────────────────────────────────────────────────────
`.trim();
}

// ── DÉTECTION DU SHELL ACTIF ─────────────────────────────────────────────────

export type ShellType = 'zsh' | 'bash' | 'fish' | 'unknown';

export function detectShell(): ShellType {
    const shell = process.env['SHELL'] ?? '';
    if (shell.includes('zsh'))  return 'zsh';
    if (shell.includes('bash')) return 'bash';
    if (shell.includes('fish')) return 'fish';
    return 'unknown';
}

export function generateHookForShell(shell: ShellType, options: ShellHookOptions): string {
    switch (shell) {
        case 'zsh':  return generateZshHook(options);
        case 'bash': return generateBashHook(options);
        case 'fish': return generateFishHook(options);
        default:     return generateZshHook(options); // fallback zsh
    }
}

export function getHookInstallPath(shell: ShellType): string {
    switch (shell) {
        case 'zsh':  return '~/.zshrc';
        case 'bash': return '~/.bashrc';
        case 'fish': return '~/.config/fish/conf.d/pulse.fish';
        default:     return '~/.zshrc';
    }
}
