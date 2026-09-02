# Pulse

Pulse est une IA personnelle locale : elle observe l'activité de développement
sur le Mac, en garde une trace fidèle, reconstruit le contexte courant et, plus
tard, résume et intervient seulement quand cela en vaut la peine. Tout reste
sur la machine.

## Structure du repo

- `core/` — Pulse Core, la couche observation (daemon Python, watchers,
  SQLite, observateur macOS). Gelée en 0.2.0. Historique git conservé.
- `intelligence/` — couche Intelligence (Context API, résumés). À construire.
- `docs/VISION.md` — document canonique : principe, architecture, roadmap,
  décisions.
- `docs/decisions/` — notes de décision datées.
- `docs/sources/` — documents de cadrage d'origine, conservés tels quels.

L'ancien Pulse Lab (SwiftUI, Ollama, MCP) est archivé hors du repo dans
`~/Projets/ARCHIVE/Pulse_Lab`, tag `archive/lab-2026-09`.

## Lancer Core

Installation, services launchd, tests et commandes : voir
[`core/README.md`](core/README.md). En résumé, depuis `core/` :
`make status`, `make test`, `make dev`.

## Direction

Lire [`docs/VISION.md`](docs/VISION.md) avant toute contribution.
