# Tests Pulse

Ce guide remplace les anciennes notes de test FR/EN. Il est aligné sur le Core Reset R1-R6 validé côté Python.

Pulse Core est un runtime local de diagnostic du contexte de travail. Les tests Core prouvent le runtime, l'observation, l'interprétation prudente, les sessions, la mémoire minimale et les propositions MCP contrôlées. Ils ne prouvent pas que les surfaces Lab sont des fonctionnalités produit stables.

## Runtime Python

Utiliser le Python du venv du repo :

```bash
.venv/bin/python3
```

Ne pas lancer la suite avec le Python système macOS si sa version ou ses dépendances divergent du venv.

Le script canonique vérifie lui-même le runtime attendu :

```bash
./scripts/test_all.sh
```

Ce script utilise `./.venv/bin/python3`, exige Python 3.11+ et lance la suite Python non interactive.

Dernière validation Core Reset documentée : `1216 tests OK`.

## Suite complète

Depuis la racine du repo :

```bash
./scripts/test_all.sh
```

Lancer cette suite après tout changement qui touche une surface Core critique :

- boot daemon ;
- routes `/ping`, `/state`, `/debug/state`, `/feed`, `/health/core`, `/event` ;
- `RuntimeState` / `PresentState` ;
- `RuntimeOrchestrator` ;
- observation / filtrage ;
- `SignalScorer` ;
- `SessionFSM` ;
- `SessionMemory` ;
- routes mémoire Core ;
- MCP approval.

## Tests ciblés Core

Pour un patch local, lancer d'abord les tests ciblés de la couche touchée, puis la suite complète si la surface est critique ou partagée.

Commande type :

```bash
.venv/bin/python3 -m pytest <fichiers>
```

### Runtime

Tests utiles :

```bash
.venv/bin/python3 -m pytest \
  tests/test_runtime_orchestrator.py \
  tests/routes/test_runtime_state_payloads.py \
  tests/test_main_runtime_state.py \
  tests/test_runtime_routes.py
```

Ces tests couvrent le mode Core, les payloads d'état, la santé runtime, les routes essentielles et les gates Core/Lab déjà validés.

### Observation

Tests utiles :

```bash
.venv/bin/python3 -m pytest \
  tests/test_observation_ingestion_golden.py \
  tests/core/test_event_meaning.py \
  tests/core/test_event_actor.py \
  tests/core/test_file_classifier.py \
  tests/core/test_app_classifier.py \
  tests/core/test_terminal_event_normalizer.py \
  tests/core/test_event_bus.py \
  tests/core/test_observation_qualification.py \
  tests/core/test_observation_qualification_consistency.py
```

Ces tests couvrent les fixtures golden, l'ingestion `/event`, le filtrage du bruit, l'attribution d'acteur, les événements terminal et la lisibilité du feed.

### Interprétation

Tests utiles :

```bash
.venv/bin/python3 -m pytest \
  tests/test_interpretation_scoring_fixtures.py \
  tests/test_interpretation_signal_scorer_golden.py \
  tests/core/test_signal_scorer.py \
  tests/core/test_work_context_card.py \
  tests/core/test_work_evidence_resolver.py \
  tests/core/test_decision_engine.py \
  tests/routes/test_runtime_state_payloads.py \
  tests/test_main_runtime_state.py \
  tests/test_runtime_routes.py
```

Ces tests verrouillent les scénarios golden `SignalScorer`, les preuves/incertitudes, les boundaries produit/debug et les anti-overclaim.

### Sessions

Tests utiles :

```bash
.venv/bin/python3 -m pytest \
  tests/core/test_session_fsm.py \
  tests/test_runtime_orchestrator.py \
  tests/memory/test_session.py \
  tests/core/test_restart_manager.py \
  tests/routes/test_runtime_state_payloads.py \
  tests/test_main_runtime_state.py \
  tests/test_runtime_routes.py
```

Ces tests couvrent la FSM de session, l'intégration runtime, la persistance minimale, le restart repair et les boundaries `/state` / `/debug/state`.

### Mémoire minimale

Tests utiles :

```bash
.venv/bin/python3 -m pytest \
  tests/memory/test_session.py \
  tests/memory/test_extractor.py \
  tests/memory/test_pipeline.py \
  tests/test_runtime_orchestrator.py \
  tests/test_main_memory_routes.py
```

Ces tests couvrent `SessionMemory`, les snapshots, le journal minimal avec `truth_layers`, les guards Core/Lab et les routes mémoire.

### Propositions contrôlées

Tests utiles :

```bash
.venv/bin/python3 -m pytest \
  tests/core/test_proposals.py \
  tests/mcp/test_handlers_proposals.py \
  tests/test_main_mcp_routes.py \
  tests/test_runtime_orchestrator.py \
  tests/core/test_decision_engine.py \
  tests/core/test_context_probe_request.py \
  tests/core/test_context_probe_executor.py \
  tests/core/test_context_probe_store.py \
  tests/core/test_context_probe_runner.py \
  tests/core/test_context_probe_policy.py \
  tests/core/test_context_probe_redaction.py \
  tests/core/test_context_probe_debug.py \
  tests/core/test_work_intent_candidate.py \
  tests/core/test_work_intent_lifecycle.py
```

Ces tests prouvent le lifecycle `ProposalStore`, le flux MCP approval, l'absence d'auto-exécution Core pour `context_injection`, et la séparation des surfaces Lab/debug.

## Core tests vs Lab regression tests

Les tests Core valident le chemin produit minimal :

- runtime ;
- observation ;
- interprétation prudente ;
- sessions ;
- mémoire minimale ;
- MCP approval contrôlé.

Les tests Lab peuvent rester utiles pour éviter des régressions, mais ils ne rendent pas ces surfaces stables :

- DayDream ;
- facts / profile ;
- vector store ;
- embeddings ;
- résumés LLM ;
- lightweight LLM queue ;
- context probes ;
- work intent ;
- resume cards ;
- smart proposals ;
- dashboard avancé ;
- adaptation.

Règle : un test Lab qui passe ne transforme pas une surface Lab en capacité Core.

## Règles de validation

- Pour une modification locale et isolée : lancer les tests ciblés de la couche touchée.
- Pour une modification Core critique : lancer les tests ciblés puis `./scripts/test_all.sh`.
- Pour une modification de contrat public ou payload exact : considérer tout échec comme breaking change jusqu'à preuve contraire.
- Pour une modification Lab : vérifier qu'elle ne réactive pas le Lab dans le chemin Core.
- Ne pas utiliser un LLM, DayDream, facts/profile, vector store ou résumé LLM pour masquer une faiblesse du Core.

## E2E interactif

Le script complet ignore les tests interactifs par défaut. Si un daemon vivant est nécessaire, le script indique la commande manuelle :

```bash
.venv/bin/python3 tests/test_e2e.py
```

Ces tests ne remplacent pas la suite complète et ne prouvent pas la stabilité terrain.

## Validation terrain Core

Après R1-R6, la prochaine validation utile est terrain, pas une nouvelle feature :

- lancer Pulse en `PULSE_MODE=core` ;
- observer les logs daemon ;
- vérifier `/health/core`, `/state`, `/debug/state` et `/feed` ;
- comparer l'état affiché avec l'activité réelle ;
- vérifier que le dashboard reste diagnostic ;
- relancer `./scripts/test_all.sh` après observation.
