# C4b — Lazy Runtime Creation Decision

## Statut

Cette décision est documentaire.

Aucun code n'est modifié dans ce patch.

Elle n'autorise pas de refactor massif.

Elle n'autorise aucun changement de routes ou de payloads.

Elle autorise seulement un futur patch de lazy runtime / app creation sous tests.

## Pourquoi cette décision existe

`daemon.main` crée encore le runtime et l'app Flask à l'import.

Cette dette est documentée par C4b.1 dans `docs/audits/C4B_BOOT_IMPORT_AUDIT.md`.

Depuis C4b.2, `main()` existe comme entrypoint explicite.

Depuis C4b.3-prep, `get_runtime()` et `get_app()` existent.

Depuis la migration C4b.3, les consommateurs simples ont été migrés vers ces accessors.

Les usages directs restants de `app` et `runtime` sont limités aux tests de compatibilité legacy.

Il est donc possible d'envisager un lazy réel, mais uniquement avec compatibilité et tests.

## Objectif du futur patch

Le futur patch doit viser à réduire les effets de bord à l'import.

Objectifs :

- faire en sorte que `get_runtime()` crée le runtime à la demande ou retourne l'existant ;
- faire en sorte que `get_app()` crée l'app à la demande ou retourne l'existante ;
- éviter la création de DB, stores ou routes à l'import si possible ;
- préserver le lancement daemon existant ;
- préserver toutes les routes et tous les payloads.

## Décision

Un futur patch C4b.3 réel est autorisé sous conditions strictes.

Conditions :

- garder `create_runtime()` et `create_app(runtime)` comme surfaces explicites ;
- faire de `get_runtime()` le point d'accès principal au runtime ;
- faire de `get_app()` le point d'accès principal à l'app Flask ;
- conserver temporairement les globals `runtime` et `app` si nécessaire pour compatibilité, mais les traiter comme legacy ;
- documenter par tests si les globals deviennent lazy, proxy ou initialisés à `None` ;
- garder les aliases legacy compatibles, ou les migrer / tester avant toute suppression ;
- ne démarrer aucun worker ou serveur à l'import ;
- ne faire disparaître aucune route dans l'app complète.

## Stratégie recommandée

### 1. C4b.3-real phase 1

Rendre les accessors lazy.

Conserver une compatibilité minimale.

Ne pas supprimer les globals si cela casse trop de tests ou le lancement local.

### 2. C4b.3-real phase 2

Adapter les tests qui vérifient les globals.

Vérifier que l'import ne crée plus `.pulse` si cet objectif est atteint.

Documenter explicitement tout comportement conservé par compatibilité.

### 3. C4b.3-real phase 3

Dogfooder après redémarrage daemon.

Documenter les résultats dans `docs/audits/CORE_DOGFOODING_NOTES.md`.

## Tests obligatoires

Avant acceptation du patch lazy, les tests doivent vérifier :

- `import daemon.main` ne lance pas `Flask.run` ;
- `import daemon.main` ne démarre aucun worker ;
- si l'objectif du patch est atteint, `import daemon.main` ne crée plus runtime, app ou fichiers `.pulse` ;
- `get_runtime()` retourne un `RuntimeBundle` valide ;
- `get_app()` retourne une app Flask valide ;
- les appels répétés retournent le même objet pendant le process ;
- `get_app().url_map` contient `/health/core`, `/state`, `/feed` et `/memory/candidates` ;
- `/health/core` OK ;
- `/state` OK ;
- `/feed` OK ;
- `/memory/candidates` OK ;
- route inventory inchangé ;
- tests memory candidates OK ;
- tests MCP OK si les routes MCP sont concernées.

## Dogfooding obligatoire

Après le patch :

- redémarrer daemon ;
- vérifier `/health/core` ;
- vérifier `/state` ;
- vérifier `/feed` ;
- vérifier `/memory/candidates` ;
- vérifier qu'aucune candidate spontanée n'est créée ;
- documenter dans `docs/audits/CORE_DOGFOODING_NOTES.md`.

## Rollback / arrêt

Si le lazy casse le lancement daemon, revenir au comportement précédent.

Si trop de tests dépendent encore des globals, arrêter et migrer davantage avant de retenter.

Ne pas forcer un lazy fragile.

## Ce que cette décision interdit

Cette décision interdit :

- refactor massif de `main.py` ;
- suppression brutale des globals ;
- suppression des aliases legacy sans migration ;
- changement de routes ;
- changement de payload ;
- changement Swift ;
- changement `RuntimeOrchestrator` ;
- changement `MemoryStore`, facts, DayDream, LLM ou vector store ;
- changement `memory_candidates` ;
- changement de port ou de protocole ;
- ajout d'UI ou de générateur.

## Décision finale

C4b autorise un patch lazy runtime / app creation uniquement s'il est progressif, testé et dogfoodé.

Le patch doit réduire les effets de bord d'import sans changer le comportement produit.
