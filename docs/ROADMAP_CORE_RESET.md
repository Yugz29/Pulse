# Pulse Core Reset Roadmap

## Statut actuel

- Core Reset R1-R6 termine.
- C4a Route surfaces : cloture.
- C4b Boot safety : cloture.
- C4c Service lifecycle cleanup : cloture.
- Boucle produit minimale "Aujourd'hui" validee en dogfooding initial.
- Phase actuelle : observation / stabilisation Core-Produit.

## Objectif du Core Reset

Le Core Reset remet Pulse sur un socle local, observable et prudent.

Objectifs principaux :

- stabiliser l'observation runtime ;
- separer clairement Core et Lab ;
- empecher les actions, memoires avancees et apprentissages non valides ;
- garder le controle humain sur les surfaces sensibles ;
- creer une premiere boucle de valeur : aider a reprendre le fil du travail.

## Ce qui est Core aujourd'hui

- Observation runtime locale.
- `EventBus`, `RuntimeState`, `SessionFSM`.
- `SignalScorer` et interpretation legere.
- `SessionMemory` minimale.
- Routes `/health/core`, `/state`, `/feed`, `/today_summary`.
- Resume cards deterministes.
- Workers Core toleres documentes.

## Ce qui reste Lab / gele

- DayDream.
- `FactEngine` / profile.
- `VectorStore` / embeddings.
- LLM summaries.
- Memory candidates automatiques.
- Apprentissage utilisateur / R7.
- WorkIntent intelligent avance.

## Decisions de cloture

- `decisions/C4A_ROUTE_SURFACES_CLOSURE.md`
- `decisions/C4B_BOOT_SAFETY_CLOSURE.md`
- `decisions/C4C_SERVICE_LIFECYCLE_CLOSURE.md`

## Documentation publique utile

- `CORE_RESET_VALIDATION_SUMMARY.md`
- `contract/`
- `decisions/`
- `TESTING.md`

## Phase actuelle : observation / stabilisation

Ne pas lancer R7.

Ne pas activer Lab.

Ne pas ajouter de nouvelle feature majeure.

Dogfooder plusieurs sessions reelles.

Corriger uniquement les anomalies terrain claires.

## Dette reportee

- `RuntimeOrchestrator` reste gros.
- `pulse-startup` reste mixte / Core tolere.
- `extractor.py` reste mixte Core/Lab.
- Dashboard Produit a stabiliser.
- Encoche a aligner plus tard seulement si decision dediee.
