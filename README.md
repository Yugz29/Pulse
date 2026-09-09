# Pulse

[![core](https://github.com/Yugz29/Pulse/actions/workflows/core.yml/badge.svg)](https://github.com/Yugz29/Pulse/actions/workflows/core.yml) [![intelligence](https://github.com/Yugz29/Pulse/actions/workflows/intelligence.yml/badge.svg)](https://github.com/Yugz29/Pulse/actions/workflows/intelligence.yml)

Pulse est une IA personnelle locale : elle observe l'activité de développement
sur le Mac, en garde une trace fidèle, reconstruit le contexte courant et
génère des résumés de session en dogfooding. À terme, elle intervient seulement
quand cela en vaut la peine. L'usage local garde les données sur la machine ;
un provider distant optionnel existe pour les comparaisons.

## Structure du repo

- `core/` — Pulse Core, la couche observation (daemon Python, watchers,
  SQLite, observateur macOS, Context API `GET /context`). Collecte sans
  dépendre d'un modèle ; ses contrats consommés évoluent par décision datée
  et version (voir `AGENTS.md`). Historique git conservé.
- `intelligence/` — couche Intelligence (résumés de session, mémoire). CLI
  complète, trois providers (faux, endpoint OpenAI, MLX local) ; résumés
  générés en dogfooding, service résident encore à construire.
- `docs/VISION.md` — document canonique : principe, architecture, roadmap,
  décisions.
- `docs/decisions/` — notes de décision datées.
- `docs/specs/` — spécifications des chantiers, une par pas de roadmap.
- `docs/sources/` — documents de cadrage d'origine, conservés tels quels.

L'ancien Pulse Lab (SwiftUI, Ollama, MCP) est archivé hors du repo dans
`~/Projets/ARCHIVE/Pulse_Lab`, tag `archive/lab-2026-09`.

## Lancer Core

Installation, services launchd, tests et commandes : voir
[`core/README.md`](core/README.md). En résumé, depuis `core/` :
`make status`, `make test`, `make dev`.

## Direction

Lire [`docs/VISION.md`](docs/VISION.md) avant toute contribution ; les
consignes de travail sont dans [`AGENTS.md`](AGENTS.md).
