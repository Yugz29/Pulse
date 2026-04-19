"""Module de détection de motifs destructeurs dans les commandes.
Ce module définit des expressions régulières pour identifier les 
commandes potentiellement dangereuses"""

import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class DestructiveMatch:
    """Représente un motif destructeur détecté dans une commande."""
    warning: str
    risk_level: str

DESTRUCTIVE_PATTERNS: list[tuple[re.Pattern, DestructiveMatch]] = [

    # --- Exécution de code distant (risque critique) ---

    # curl ... | bash/sh/zsh/fish : télécharge et exécute du code distant
    # Couvre : curl URL | bash, curl -s URL | sh, curl -fsSL URL | sudo bash
    (re.compile(r'\bcurl\b.*?\|\s*(?:sudo\s+)?(?:bash|sh|zsh|fish)\b'),
     DestructiveMatch("Exécute du code téléchargé depuis internet", "critical")),

    # wget ... | bash/sh/zsh : variante wget
    # Couvre : wget -qO- URL | bash, wget -O - URL | sh
    (re.compile(r'\bwget\b.*?\|\s*(?:sudo\s+)?(?:bash|sh|zsh|fish)\b'),
     DestructiveMatch("Exécute du code téléchargé depuis internet", "critical")),


    # --- Git — risque de perte de données ---

    # git reset --hard : efface tous les changements non commités
    (re.compile(r'\bgit\s+reset\s+--hard\b'),
     DestructiveMatch("Annule tous les changements non commités", "high")),

    # git push --force ou -f : peut écraser l'historique distant
    (re.compile(r'\bgit\s+push\b.*?(?:--force|-f)\b'),
     DestructiveMatch("Peut écraser l'historique distant", "high")),

    # git clean -f : supprime les fichiers non trackés définitivement
    (re.compile(r'\bgit\s+clean\b.*?-[a-zA-Z]*f'),
     DestructiveMatch("Supprime définitivement les fichiers non trackés", "high")),

    # git stash drop/clear : supprime des changements mis de côté
    (re.compile(r'\bgit\s+stash\s+(?:drop|clear)\b'),
     DestructiveMatch("Supprime des changements mis de côté", "medium")),

    # git commit --amend : réécrit le dernier commit
    (re.compile(r'\bgit\s+commit\b.*?--amend\b'),
     DestructiveMatch("Réécrit le dernier commit", "medium")),

    # --no-verify : contourne les hooks git (tests, linting...)
    (re.compile(r'\bgit\s+(?:commit|push|merge)\b.*?--no-verify\b'),
     DestructiveMatch("Contourne les hooks de sécurité", "medium")),


    # --- Suppression de fichiers ---

    # rm -rf : suppression récursive et forcée — le plus dangereux
    # [rR] = r ou R (certains écrivent -Rf), f après r
    (re.compile(r'(?:^|[;&|]\s*)rm\s+-[a-zA-Z]*[rR][a-zA-Z]*f'),
     DestructiveMatch("Suppression récursive et forcée de fichiers", "critical")),

    # rm -r : suppression récursive sans -f
    (re.compile(r'(?:^|[;&|]\s*)rm\s+-[a-zA-Z]*[rR]'),
     DestructiveMatch("Suppression récursive de fichiers", "high")),

    # rm -f : suppression forcée (sans confirmation)
    (re.compile(r'(?:^|[;&|]\s*)rm\s+-[a-zA-Z]*f'),
     DestructiveMatch("Suppression forcée de fichiers", "medium")),


    # --- Base de données ---

    # DROP TABLE / TRUNCATE : supprime ou vide une table entière
    # re.IGNORECASE : matche DROP, drop, Drop...
    (re.compile(r'\b(?:DROP|TRUNCATE)\s+(?:TABLE|DATABASE|SCHEMA)\b', re.IGNORECASE),
     DestructiveMatch("Supprime ou vide une table/base de données", "critical")),

    # DELETE FROM sans WHERE : supprime toutes les lignes
    (re.compile(r'\bDELETE\s+FROM\s+\w+\s*(?:;|$)', re.IGNORECASE),
     DestructiveMatch("Supprime toutes les lignes d'une table", "high")),


    # --- Infrastructure ---

    # kubectl delete : supprime des ressources Kubernetes
    (re.compile(r'\bkubectl\s+delete\b'),
     DestructiveMatch("Supprime des ressources Kubernetes", "high")),

    # terraform destroy : détruit toute l'infrastructure
    (re.compile(r'\bterraform\s+destroy\b'),
     DestructiveMatch("Détruit l'infrastructure Terraform", "critical")),
]


def get_destructive_warning(command: str) -> Optional[DestructiveMatch]:
    """Analyse une commande pour détecter des motifs destructeurs connus."""
    for pattern, match in DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            return match
    return None
