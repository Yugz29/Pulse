# Boot Safety Closure

Internal phase: C4b

## Statut

Cette décision est documentation-only.

Aucun code n'est modifié dans ce patch.

C4b est clôturable.

C4b n'a pas changé les routes.

C4b n'a pas changé les payloads.

C4b n'a pas changé Swift.

C4b n'a pas supprimé les globals legacy.

## Ce que C4b a amélioré

C4b a amélioré le boot de `daemon/main.py` sans changer le comportement produit.

Améliorations réalisées :

- `main()` existe maintenant comme entrypoint exécutable explicite ;
- l'import de `daemon.main` ne lance pas le serveur Flask ;
- l'import de `daemon.main` ne démarre pas les workers permanents ;
- `get_runtime()` et `get_app()` existent comme accessors explicites ;
- la création runtime / app est devenue lazy ;
- l'import ne crée plus runtime, app, routes ou fichiers `.pulse` ;
- les consommateurs de test simples ont été migrés vers `get_runtime()` et `get_app()` ;
- la compatibilité legacy reste conservée pour `app`, `runtime` et les aliases historiques ;
- `main()` préflight maintenant `127.0.0.1:8765` avant `get_app()`, services runtime, MCP, threads et `Flask.run` ;
- le dogfooding post-redémarrage a validé `/health/core`, `/state`, `/feed` et `/memory/candidates`.

## Ce qui est verrouillé par tests

Les tests verrouillent :

- `import daemon.main` ne lance pas `Flask.run` ;
- `import daemon.main` ne démarre pas les workers permanents ;
- `get_runtime()` retourne un runtime valide ;
- `get_app()` retourne une app Flask valide ;
- les appels répétés à `get_runtime()` et `get_app()` restent stables dans le process ;
- les routes principales sont présentes ;
- `/health/core`, `/state`, `/feed` et `/memory/candidates` restent accessibles ;
- un port 8765 indisponible stoppe `main()` avant `get_app()` ;
- les services runtime ne sont pas démarrés si 8765 est indisponible ;
- le serveur MCP SSE secondaire n'est pas démarré si 8765 est indisponible ;
- les threads watchdog / deferred startup ne sont pas lancés si 8765 est indisponible ;
- `Flask.run` n'est pas appelé si 8765 est indisponible ;
- route inventory et tests Core restent verts.

## Ce qui reste volontairement legacy

Restent volontairement legacy :

- `daemon.main.runtime` ;
- `daemon.main.app` ;
- aliases legacy comme `bus`, `store`, `runtime_state`, `runtime_orchestrator`, `memory_store`, `session_memory`, `summary_llm` ;
- compatibilité via `__getattr__` module-level ;
- `main.py` comme composition root large ;
- port 8766 / serveur MCP SSE secondaire traité par script / warning, pas par préflight bloquant dans `main()`.

Ces éléments restent acceptés pour compatibilité et dogfooding local.

## Décision

C4b est considéré clôturable.

Décision :

- conserver les globals legacy pour compatibilité ;
- ne pas supprimer les globals legacy sans décision séparée ;
- ne pas supprimer les aliases legacy sans migration dédiée ;
- ne pas traiter 8766 / MCP dans C4b ;
- ne pas refactorer davantage `main.py` dans cette phase ;
- passer à C4c.

## Ce que cette décision interdit

Cette décision interdit :

- suppression brutale des globals legacy ;
- suppression brutale des aliases legacy ;
- changement du port 8765 ;
- changement du port 8766 ;
- changement du lancement Swift / LaunchAgent ;
- refactor massif de `main.py` ;
- extraction de `RuntimeOrchestrator` ;
- changement des routes ;
- changement des payloads ;
- modification de `memory_candidates` ;
- ajout d'UI ;
- ajout de générateur.

## Dettes reportées

Dettes reportées :

- décider plus tard si les globals legacy doivent être retirés ou conservés comme façade de compatibilité ;
- clarifier séparément le comportement port 8766 / MCP SSE secondaire ;
- poursuivre la réduction du rôle composition root de `main.py` dans une phase ultérieure si nécessaire ;
- garder le dogfooding attentif aux sessions réparées avec `stale_repair` après redémarrage.

## Suite historique à la clôture C4b

La phase recommandée après C4b était C4c — Core/Lab service lifecycle cleanup.

Objectif C4c :

- clarifier les services Lab encore instanciés ou tolérés en Core ;
- rendre certains services lazy / no-op si pertinent ;
- vérifier `FactEngine`, `MemoryStore`, periodic sync worker, LLM / lightweight queue, context probes et work intent ;
- ne pas supprimer brutalement Lab ;
- ne pas changer les routes.

## Décision finale

C4b est clôturé.

La suite historique était C4c.

Aucun nouveau comportement produit n'est autorisé par cette clôture.
