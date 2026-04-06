import re

# Variables d'environnement sûres à retirer avant d'analyser une commande.
# Ces variables ne peuvent pas exécuter du code ni modifier le comportement système.
SAFE_ENV_VARS = {
    # Go
    "GOEXPERIMENT", "GOOS", "GOARCH", "CGO_ENABLED", "GO111MODULE",
    # Rust
    "RUST_BACKTRACE", "RUST_LOG",
    # Node (pas NODE_OPTIONS — peut exécuter du code)
    "NODE_ENV",
    # Python (pas PYTHONPATH — modifie les modules chargés)
    "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
    # Locale et encodage
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_TIME", "CHARSET",
    # Terminal et affichage
    "TERM", "COLORTERM", "NO_COLOR", "FORCE_COLOR", "TZ",
    # Couleurs des outils
    "LS_COLORS", "LSCOLORS", "GREP_COLORS",
    # Anthropic
    "ANTHROPIC_API_KEY",
}

# Ces variables ne doivent JAMAIS être retirées, elles peuvent modifier l'exécution.
NEVER_SAFE = {
    "PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
    "PYTHONPATH", "NODE_PATH", "CLASSPATH", "RUBYLIB",
    "GOFLAGS", "RUSTFLAGS", "NODE_OPTIONS",
    "HOME", "TMPDIR", "SHELL", "BASH_ENV",
}

# Pattern : VAR=valeur suivi d'un espace horizontal (pas un saut de ligne)
_ENV_VAR_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)=\S*[ \t]+')


def strip_safe_env_vars(command: str) -> str:
    """
    Retire les variables d'environnement sûres du début d'une commande.
    """
    stripped = command

    while True:
        match = _ENV_VAR_RE.match(stripped)
        if not match:
            break

        var_name = match.group(1)

        # Stop si la variable est explicitement dangereuse ou inconnue
        if var_name in NEVER_SAFE or var_name not in SAFE_ENV_VARS:
            break

        stripped = stripped[match.end():]

    return stripped.strip()
