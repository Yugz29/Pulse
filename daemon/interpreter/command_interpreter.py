import shlex
from dataclasses import dataclass, field
from typing import Optional

from .safe_env_vars import strip_safe_env_vars
from .destructive_patterns import get_destructive_warning
from .command_semantics import get_command_description


# Score et label associés à chaque niveau de risque
RISK_LEVELS = {
    "safe":     {"score": 0,   "label": "Sûr"},
    "low":      {"score": 25,  "label": "Faible"},
    "medium":   {"score": 50,  "label": "Modéré"},
    "high":     {"score": 75,  "label": "Élevé"},
    "critical": {"score": 100, "label": "Critique"},
}

# Commandes qui ne modifient jamais rien — toujours sûres
READ_ONLY_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "rg", "find", "echo",
    "pwd", "whoami", "date", "wc", "diff", "ps", "top", "df",
    "du", "uname", "which", "type", "file", "stat", "tree",
}

# Sous-commandes git en lecture seule
READ_ONLY_GIT = {
    "log", "status", "diff", "show", "branch",
    "remote", "describe", "fetch",
}


@dataclass
class CommandInterpretation:
    original: str              # Commande brute reçue
    translated: str            # Explication en français
    risk_level: str            # "safe", "low", "medium", "high", "critical"
    risk_score: int            # 0–100
    is_read_only: bool         # True si la commande ne modifie rien
    affects: list[str]         # Catégories impactées : fichiers, git, réseau...
    warning: Optional[str]     # Avertissement si commande destructive
    needs_llm: bool            # True si la commande est inconnue → LLM requis


class CommandInterpreter:

    def interpret(self, command: str) -> CommandInterpretation:
        """Point d'entrée principal — analyse une commande complète."""

        # 1. Retire les variables d'environnement sûres
        clean = strip_safe_env_vars(command.strip())

        # 2. Extrait la commande de base (premier mot)
        base_cmd = self._extract_base(clean)

        # 3. Vérifie si la commande est en lecture seule
        is_read_only = self._is_read_only(clean, base_cmd)

        if is_read_only:
            semantic = get_command_description(clean, base_cmd)
            translated = semantic or self._translate_read_only(clean, base_cmd)
            return CommandInterpretation(
                original=command,
                translated=translated,
                risk_level="safe",
                risk_score=0,
                is_read_only=True,
                affects=["lecture seule"],
                warning=None,
                needs_llm=False,
            )

        # 4. Cherche un pattern destructif connu
        destructive = get_destructive_warning(clean)

        # 5. Cherche une description sémantique
        semantic = get_command_description(clean, base_cmd)

        # 6. Calcule le niveau de risque
        risk_level, risk_score = self._compute_risk(clean, base_cmd, destructive)

        # 7. Choisit la traduction
        # Priorité : warning destructif > description sémantique > fallback
        translated = destructive.warning if destructive else semantic
        needs_llm = translated is None

        if needs_llm:
            translated = f"Exécute : `{clean}`"

        return CommandInterpretation(
            original=command,
            translated=translated,
            risk_level=risk_level,
            risk_score=risk_score,
            is_read_only=False,
            affects=self._detect_affects(clean),
            warning=destructive.warning if destructive else None,
            needs_llm=needs_llm,
        )

    def _extract_base(self, command: str) -> str:
        """Extrait le premier mot de la commande."""
        try:
            tokens = shlex.split(command)
            return tokens[0] if tokens else command.split()[0]
        except ValueError:
            return command.split()[0] if command.split() else ""

    def _is_read_only(self, command: str, base_cmd: str) -> bool:
        """Retourne True si la commande ne peut pas modifier le système."""
        if base_cmd in READ_ONLY_COMMANDS:
            return True
        # git log, git status, git diff... sont en lecture seule
        if base_cmd == "git":
            tokens = command.split()
            if len(tokens) >= 2 and tokens[1] in READ_ONLY_GIT:
                return True
        return False

    def _compute_risk(self, command: str, base_cmd: str, destructive) -> tuple[str, int]:
        """Calcule le niveau et le score de risque."""
        # Un pattern destructif connu → on utilise son niveau directement
        if destructive:
            level = destructive.risk_level
            return level, RISK_LEVELS[level]["score"]

        # Heuristiques pour les autres commandes
        HIGH_RISK = {"sudo", "chmod", "chown", "dd", "mkfs"}
        MED_RISK  = {"mv", "cp", "npm", "pip", "brew", "curl", "wget"}

        if base_cmd in HIGH_RISK:
            return "high", 75

        # Redirection vers un fichier (>) = écriture potentielle
        if ">" in command:
            return "medium", 50

        if base_cmd in MED_RISK:
            return "medium", 40

        return "low", 15

    def _detect_affects(self, command: str) -> list[str]:
        """Détecte les catégories impactées par la commande."""
        affects = []
        if any(c in command for c in [">", ">>", "rm", "mv", "cp"]):
            affects.append("fichiers")
        if "git" in command:
            affects.append("git")
        if any(c in command for c in ["curl", "wget", "ssh", "scp"]):
            affects.append("réseau")
        if any(c in command for c in ["npm", "pip", "brew"]):
            affects.append("dépendances")
        if any(c in command for c in ["docker", "kubectl"]):
            affects.append("infrastructure")
        return affects if affects else ["système"]

    def _translate_read_only(self, command: str, base_cmd: str) -> str:
        """Traduction simple pour les commandes en lecture seule."""
        translations = {
            "ls":   "Liste les fichiers du dossier",
            "cat":  "Affiche le contenu d'un fichier",
            "grep": "Recherche du texte dans des fichiers",
            "rg":   "Recherche rapide dans des fichiers",
            "find": "Cherche des fichiers selon des critères",
            "git":  "Commande git en lecture",
            "ps":   "Liste les processus actifs",
            "df":   "Affiche l'espace disque disponible",
            "du":   "Affiche la taille des dossiers",
        }
        return translations.get(base_cmd, f"Lit les données : `{base_cmd}`")
