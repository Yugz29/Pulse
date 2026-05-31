# C4b.3 — Runtime Creation Timing

## Statut

Cette décision est documentaire.

Aucun code n'est modifié dans ce patch.

Ce document ne déplace pas encore `runtime = create_runtime()`.

Il définit la stratégie avant toute modification du timing de création runtime.

## Problème

`daemon.main` crée encore le runtime et l'app Flask à l'import.

Ce comportement crée des fichiers sous `.pulse`, rend les imports coûteux et impurs, et mélange encore composition root, factory importable et app globale legacy.

La dette est confirmée par `docs/audits/C4B_BOOT_IMPORT_AUDIT.md`.

Elle ne peut pas être corrigée brutalement, car plusieurs tests et surfaces full-app dépendent encore des globals importables de `daemon.main`.

## Dépendances actuelles

### `daemon.main.app`

Consommateurs trouvés :

- `tests/test_main_runtime_state.py` — utilise `daemon_main.app.test_client()` pour les routes runtime / state / feed et inventorie `app.url_map`.
- `tests/test_main_memory_routes.py` — utilise `daemon_main.app.test_client()` pour les routes mémoire historiques et Lab.
- `tests/test_main_mcp_routes.py` — utilise `daemon_main.app.test_client()` pour les routes MCP / proposals.
- `tests/test_main_llm_models.py` — utilise `daemon_main.app.test_client()` pour `/llm/model`, `/llm/models`, `/ask` et les daemon controls.

Ces tests documentent l'app complète enregistrée par `daemon.main`, pas seulement une route isolée.

### `daemon.main.runtime`

Consommateurs trouvés :

- `tests/test_main_runtime_state.py` — vérifie que les alias globaux legacy pointent vers `daemon_main.runtime`.

Aliases couverts :

- `bus`
- `store`
- `scorer`
- `decision_engine`
- `summary_llm`
- `session_memory`
- `memory_store`
- `memory_candidate_store`
- `runtime_state`
- `llm_runtime`
- `runtime_orchestrator`

D'autres tests utilisent ces aliases directement, notamment `runtime_state`, `runtime_orchestrator`, `bus`, `memory_store`, `session_memory` et `summary_llm`.

### `create_runtime()`

Consommateurs trouvés :

- `daemon/main.py` — crée le `RuntimeBundle` global au chargement du module.
- `tests/test_main_runtime_state.py` — crée un runtime isolé et vérifie qu'il ne démarre pas `RuntimeOrchestrator`, le file flush worker ou le periodic sync worker.

`create_runtime()` est déjà une surface utile pour préparer un boot plus testable. Elle doit rester disponible.

### `create_app(runtime)`

Consommateurs trouvés :

- `daemon/main.py` — crée l'app Flask globale à partir du runtime global.
- `tests/test_main_runtime_state.py` — crée une app à partir d'un runtime isolé et vérifie que les routes sont enregistrées sans démarrer le runtime.

`create_app(runtime)` doit rester la surface factory principale pour tester l'enregistrement des routes sans lancer le serveur.

### Imports sans app globale directe

Consommateur trouvé :

- `tests/test_main_logging.py` — importe `daemon.main` pour tester les helpers de logging et filtres d'access logs.

Même sans utiliser `app`, cet import déclenche aujourd'hui la création runtime globale. Une future correction devra éviter de casser ces tests tout en réduisant les effets de bord.

### Swift et tooling local

Aucun import Python direct de `daemon.main.app` ou `daemon.main.runtime` n'a été trouvé côté `App/` ou `AppTests/`.

Le risque Swift reste indirect : le dashboard local dépend des routes HTTP et du lancement daemon existants.

## Risques

Déplacer `runtime = create_runtime()` peut :

- casser les tests qui importent `daemon.main.app` ;
- casser les tests qui vérifient les aliases globaux legacy ;
- casser le lancement daemon si `main()` ne retrouve plus une app prête ;
- laisser des routes non enregistrées ;
- retarder ou modifier l'initialisation des stores ;
- changer le moment où les fichiers `.pulse` sont créés ;
- perturber le dogfooding ou le redémarrage local ;
- casser du tooling local qui suppose une app globale importable ;
- masquer des effets de bord au lieu de les supprimer réellement.

## Décision

C4b.3 doit rester progressif.

La création runtime globale ne doit pas être déplacée brutalement.

Avant tout déplacement, il faut conserver une stratégie de compatibilité pour les consommateurs actuels.

Si un déplacement futur est tenté, il doit :

- préserver temporairement une compatibilité `app` importable ou migrer les tests avant ;
- préserver les aliases legacy tant qu'ils sont testés ;
- garder `create_runtime()` disponible ;
- garder `create_app(runtime)` comme surface testable ;
- préserver toutes les routes et payloads ;
- vérifier `/health/core`, `/state`, `/feed` et `/memory/candidates` ;
- confirmer que l'import ne lance toujours pas serveur ou workers ;
- être dogfoodé après redémarrage daemon.

## Options futures

### 1. Garder les globals temporairement

C'est l'état actuel.

Cette option conserve `runtime`, `app` et les aliases au niveau module, mais maintient les effets de bord d'import documentés.

Elle est acceptable seulement comme dette temporaire.

### 2. Lazy globals via `get_runtime()` / `get_app()`

Cette option introduirait des accesseurs explicites qui créent le runtime et l'app au premier usage.

Elle peut réduire les effets de bord pour les imports qui ne demandent pas l'app, tout en conservant une compatibilité progressive.

C'est probablement la prochaine étape sûre.

### 3. Suppression des globals après migration

Cette option supprimerait les globals importables après migration des tests, du lancement daemon et du tooling local.

Elle est reportée.

Elle ne doit pas être faite dans C4b.3 sans décision séparée et sans migration explicite des consommateurs.

## Tests requis avant tout changement

Avant toute modification du timing runtime, les tests doivent couvrir :

- `import daemon.main` ne lance pas serveur ou workers ;
- route inventory inchangé ;
- app créée par factory contient les routes attendues ;
- `/health/core` OK ;
- `/state` OK ;
- `/feed` OK ;
- `/memory/candidates` OK ;
- aucun changement payload ;
- `main()` lance toujours le daemon comme avant ;
- les aliases legacy restent compatibles tant qu'ils existent ;
- dogfooding post-redémarrage.

## Décision finale

C4b.3 doit être progressif.

Aucun déplacement runtime n'est autorisé tant que la compatibilité des consommateurs n'est pas inventoriée et testée.

La prochaine étape recommandée est un patch préparatoire autour de lazy accessors ou d'une compatibilité équivalente, sans suppression brutale des globals.
