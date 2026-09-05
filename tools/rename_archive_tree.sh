#!/usr/bin/env bash
# Renomme l'arborescence d'archive pour qu'elle corresponde aux
# clés normalisées du manifeste. À lancer sur une COPIE des 215 Mo,
# depuis la racine de l'archive. Parents avant enfants.
set -euo pipefail
root="${1:?usage: rename_archive_tree.sh <racine-archive-copiee>}"
cd "$root"

[ -e "Users-yugz-.claude-projects" ] && mv "Users-yugz-.claude-projects" "Users-Yugz-.claude-projects"
[ -e "Users-yugz-.codex-sessions" ] && mv "Users-yugz-.codex-sessions" "Users-Yugz-.codex-sessions"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Cortex-cortex-immersive" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Cortex-cortex-immersive" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Cortex-cortex-immersive"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Cortex" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Cortex" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Cortex"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-DevNote-DevNote" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-DevNote-DevNote" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-DevNote-DevNote"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-movie-night" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-movie-night" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-movie-night"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-react" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-react" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-react"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-svelte" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-svelte" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-svelte"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-vue" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-vue" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks-vue"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Holberton28-holbertonschool-agentic-ai-front-end-frameworks"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-agentic-ai" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Holberton28-holbertonschool-agentic-ai"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-devops-formation" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Holberton28-holbertonschool-devops-formation" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Holberton28-holbertonschool-devops-formation"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Pulse" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Pulse" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Pulse"
[ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Pulse-Pulse-Core" ] && mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Pulse-Pulse-Core" "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Pulse-core"
if [ -e "Users-Yugz-.claude-projects/-Users-yugz-Projets-Pulse-Pulse" ]; then
  mkdir -p "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Pulse"
  mv "Users-Yugz-.claude-projects/-Users-yugz-Projets-Pulse-Pulse"/* "Users-Yugz-.claude-projects/-Users-Yugz-Projets-Pulse"/ 2>/dev/null || true
  rmdir "Users-Yugz-.claude-projects/-Users-yugz-Projets-Pulse-Pulse"
fi
