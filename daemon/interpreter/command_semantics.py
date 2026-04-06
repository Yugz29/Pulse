import re
import shlex
from typing import Optional


def get_command_description(command: str, base_cmd: str) -> Optional[str]:
    """
    Retourne une description en français pour les commandes connues.
    Retourne None si la commande est inconnue → le LLM prendra le relais.
    """
    handlers = {
        "grep":   _describe_grep,
        "rg":     _describe_rg,
        "find":   _describe_find,
        "npm":    _describe_npm,
        "pip":    _describe_pip,
        "git":    _describe_git,
        "curl":   _describe_curl,
        "mv":     _describe_mv,
        "cp":     _describe_cp,
        "mkdir":  _describe_mkdir,
        "chmod":  _describe_chmod,
        "docker": _describe_docker,
        # Commandes simples
        "awk": lambda cmd: "Traite et transforme du texte ligne par ligne",
        "sed": lambda cmd: "Modifie du texte selon des règles (stream editor)",
        "tar": lambda cmd: "Crée ou extrait une archive",
        "ssh": lambda cmd: "Connexion à un serveur distant",
    }

    handler = handlers.get(base_cmd)
    if handler:
        try:
            return handler(command)
        except Exception:
            return None

    return None


# --- Helpers ---

def _safe_split(command: str) -> list[str]:
    """Découpe la commande en tokens en gérant les guillemets."""
    try:
        return shlex.split(command)
    except ValueError:
        # Si shlex échoue (guillemets non fermés...), fallback basique
        return command.split()


def _extract_quoted_arg(command: str) -> Optional[str]:
    """Extrait le premier argument entre guillemets dans la commande."""
    match = re.search(r'"([^"]+)"', command)
    if match:
        return match.group(1)
    match = re.search(r"'([^']+)'", command)
    if match:
        return match.group(1)
    return None


# --- Descripteurs par commande ---

def _describe_grep(command: str) -> str:
    tokens = _safe_split(command)
    has_r = any(t in ("-R", "-r", "--recursive") for t in tokens)
    pattern = _extract_quoted_arg(command)
    if has_r and pattern:
        return f'Recherche "{pattern}" dans tous les fichiers de façon récursive'
    if pattern:
        return f'Recherche "{pattern}" dans les fichiers'
    return "Recherche un pattern dans des fichiers"


def _describe_rg(command: str) -> str:
    pattern = _extract_quoted_arg(command)
    if pattern:
        return f'Recherche rapide de "{pattern}" dans les fichiers'
    return "Recherche rapide dans les fichiers (ripgrep)"


def _describe_find(command: str) -> str:
    tokens = _safe_split(command)
    if "-name" in tokens:
        idx = tokens.index("-name")
        if idx + 1 < len(tokens):
            return f'Cherche les fichiers nommés "{tokens[idx + 1]}"'
    return "Cherche des fichiers selon des critères"


def _describe_npm(command: str) -> str:
    tokens = _safe_split(command)
    if len(tokens) < 2:
        return "Commande npm"
    sub = tokens[1]
    descriptions = {
        "install":   "Installe les dépendances du projet",
        "run":       f"Lance le script : {tokens[2] if len(tokens) > 2 else ''}",
        "test":      "Lance les tests",
        "build":     "Compile le projet",
        "start":     "Démarre l'application",
        "update":    "Met à jour les dépendances",
        "uninstall": "Désinstalle un paquet",
        "audit":     "Vérifie les vulnérabilités de sécurité",
    }
    return descriptions.get(sub, f"npm {sub}")


def _describe_pip(command: str) -> str:
    tokens = _safe_split(command)
    if "install" in tokens:
        pkgs = [t for t in tokens[2:] if not t.startswith("-")]
        return f"Installe : {', '.join(pkgs)}" if pkgs else "Installe des paquets Python"
    if "uninstall" in tokens:
        return "Désinstalle des paquets Python"
    return "Gestion des paquets Python"


def _describe_git(command: str) -> str:
    tokens = _safe_split(command)
    if len(tokens) < 2:
        return "Commande git"
    sub = tokens[1]
    descriptions = {
        "commit":   "Enregistre les changements dans l'historique git",
        "push":     "Envoie les commits vers le dépôt distant",
        "pull":     "Récupère et fusionne les changements distants",
        "merge":    "Fusionne une branche dans la branche actuelle",
        "rebase":   "Réapplique les commits sur une autre base",
        "clone":    "Copie un dépôt distant en local",
        "checkout": "Change de branche ou restaure des fichiers",
        "switch":   "Change de branche",
        "stash":    "Met de côté les changements en cours",
        "fetch":    "Récupère les changements distants sans fusionner",
        "status":   "Affiche l'état du dépôt (fichiers modifiés, staged...)",
    }
    return descriptions.get(sub, f"git {sub}")


def _describe_curl(command: str) -> str:
    # Cherche une URL dans la commande
    url = next((t for t in _safe_split(command) if t.startswith("http")), None)
    if url:
        domain = url.split("/")[2] if "/" in url else url
        return f"Télécharge des données depuis {domain}"
    return "Effectue une requête HTTP"


def _describe_mv(command: str) -> str:
    tokens = _safe_split(command)
    if len(tokens) >= 3:
        return f"Déplace ou renomme : {tokens[-2]} → {tokens[-1]}"
    return "Déplace ou renomme un fichier"


def _describe_cp(command: str) -> str:
    tokens = _safe_split(command)
    if len(tokens) >= 3:
        return f"Copie : {tokens[-2]} → {tokens[-1]}"
    return "Copie un fichier"


def _describe_mkdir(command: str) -> str:
    tokens = _safe_split(command)
    dirs = [t for t in tokens[1:] if not t.startswith("-")]
    if dirs:
        return f"Crée le dossier : {dirs[0]}"
    return "Crée un dossier"


def _describe_chmod(command: str) -> str:
    tokens = _safe_split(command)
    if len(tokens) >= 3:
        return f"Change les permissions de {tokens[-1]} en {tokens[1]}"
    return "Modifie les permissions d'un fichier"


def _describe_docker(command: str) -> str:
    tokens = _safe_split(command)
    if len(tokens) < 2:
        return "Commande Docker"
    sub = tokens[1]
    descriptions = {
        "run":     "Lance un conteneur Docker",
        "build":   "Construit une image Docker",
        "push":    "Envoie une image vers un registry",
        "pull":    "Télécharge une image Docker",
        "stop":    "Arrête un conteneur",
        "rm":      "Supprime un conteneur",
        "rmi":     "Supprime une image",
        "compose": "Orchestre plusieurs conteneurs",
    }
    return descriptions.get(sub, f"docker {sub}")
