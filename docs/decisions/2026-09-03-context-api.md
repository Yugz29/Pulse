# Context API livrée — Core 0.3.0

**Date :** 2026-09-03
**Statut :** livrée (PR #27, pas 2 de la roadmap)
**Spec :** [`../specs/2026-09-02-context-api.md`](../specs/2026-09-02-context-api.md)

- `GET /context` est livré dans Core 0.3.0, contrat `schema_version: 1` ; Core est de nouveau gelé.
- `current_session` vaut `null` quand rien n'est en cours (gap de 30 min) : la dernière session fermée n'est jamais substituée.
- `last_agent_session` est le dernier `agent_session` sans limite de fenêtre, borné par l'instant de référence.
- `workspace.git` suit la résolution du workspace : session courante entière si `session`, fenêtre si `last_observed`.
- Les huit décisions d'implémentation et les limites connues (minuit local) sont dans le spec, §9 et §10.
