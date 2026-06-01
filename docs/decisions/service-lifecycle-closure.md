# Service Lifecycle Closure

Internal phase: C4c

## Statut

Decision documentaire de cloture C4c.

Aucun code dans ce patch.

## Ce que C4c cloture

C4c cloture :

- cartographie des services Core/Lab ;
- workers demarres par `create_runtime()`, `start_runtime_services()`, `RuntimeOrchestrator.start()` et `main()` ;
- nettoyage de la planification `pulse-memory-sync` en Core ;
- audit/test de `pulse-diff` ;
- audit/test de `pulse-prepare-resume-card` ;
- audit/test de `pulse-commit-watch` ;
- audit/documentation de `pulse-startup`.

## Decision

C4c est cloturable.

En Core :

- aucun flux runtime normal ne doit creer `pulse-memory-sync` ;
- les chemins memory sync restent Lab-gated ;
- les workers Core toleres restent acceptes temporairement car ils servent observation, reprise du fil ou lifecycle local.

Workers Core strict :

- `pulse-file-burst`
- `pulse-periodic-sync` apres gates memoire
- `pulse-idle-heartbeat`
- `pulse-watchdog`

Workers Core toleres / Produit :

- `pulse-diff`
- `pulse-commit-watch`
- `pulse-prepare-resume-card`
- `pulse-resume-card`

Worker mixte / Core tolere :

- `pulse-startup`

Lab only :

- `pulse-memory-sync` par flux normal
- `pulse-daydream-scheduler`
- `pulse-daydream`

## Ce qui est accepte temporairement

- `pulse-diff` lance du git diff/subprocess avec cooldown.
- `pulse-commit-watch` lit HEAD/metadata git et message de commit.
- `pulse-prepare-resume-card` garde un payload temporaire en memoire.
- `pulse-startup` garde une maintenance legacy/recovery en Core.
- `recover_missed_commits()` peut ecrire un journal deterministe en Core.

## Ce qui reste interdit

- reactiver memory sync avance en Core ;
- lancer DayDream en Core ;
- lancer facts maintenance en Core ;
- utiliser VectorStore/embeddings/LLM pour la memoire Core ;
- creer des memory candidates automatiquement ;
- transformer les workers Core toleres en surfaces Lab actives ;
- ajouter une nouvelle feature Produit depuis C4c sans decision separee.

## Dette reportee

- cleanup futur de `pulse-startup` ;
- clarification du recovery journal deterministe en Core ;
- budget/cadence plus explicite pour `pulse-diff` ;
- sensibilite des noms de fichiers/fonctions dans diff/commit/resume card ;
- eventuel lazy loading ou gating plus fin des services legacy instancies.

## Prochaine phase recommandee

Ne pas lancer R7/apprentissage.

Ne pas activer Lab.

Revenir a une phase de stabilisation/dogfooding ou a une decision separee si une nouvelle direction Produit est choisie.
