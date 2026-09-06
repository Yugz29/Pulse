"""Pulse Intelligence — résumé de session (pas 3 de la roadmap V3, spec v2)."""

__version__ = "0.1.0"

PRODUCER_NAME = "pulse-intelligence"

# La version de reconstruction des sessions de Core (`RECONSTRUCTION_VERSION`,
# `core/daemon_v2/analysis/timeline.py`, 3 depuis le 2026-09-06) sur laquelle ce
# code, ses prompts et ses attentes ont été validés. Un daemon qui sert une
# autre version (code plus ancien encore en mémoire, ou plus récent que cette
# constante) rend des vues — et des identifiants de session — qui ne sont pas
# ceux validés : on l'annonce, on ne le corrige pas en silence.
KNOWN_RECONSTRUCTION_VERSION = 3
