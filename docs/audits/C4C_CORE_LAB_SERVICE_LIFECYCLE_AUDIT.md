# C4c — Core/Lab Service Lifecycle Audit

## Statut

- Audit documentaire C4c.1.
- Aucun comportement produit corrigé dans cette note.
- Aucun service Lab supprimé.
- Aucune route, payload, UI ou surface Swift modifiée.
- Le but est de documenter ce qui est instancié, lazy, no-op, gated ou toléré en Core.

## Pourquoi cet audit existe

C4a a clarifié les surfaces de routes. C4b a réduit les effets de bord du boot : `import daemon.main` ne matérialise plus runtime, app, routes ou fichiers `.pulse`, et le lancement direct vérifie maintenant le port HTTP principal avant création runtime/app.

C4c commence par vérifier les services encore présents en Core avant toute réduction de couplage. Cette phase ne doit pas activer d'apprentissage, de mémoire avancée, de générateur, de DayDream, de facts produit, de vector store ou d'injection LLM.

## Source de test

Tests de garde principaux :

- `tests/test_main_runtime_state.py`
- `tests/test_runtime_routes.py`
- `tests/test_main_memory_routes.py`
- `tests/test_memory_candidate_routes.py`
- `tests/routes/test_runtime_state_payloads.py`

Le test C4c.1 ajouté documente que `create_runtime()` instancie le bundle complet sans démarrer les workers permanents.

## Services créés par `create_runtime()`

`create_runtime()` crée aujourd'hui :

- `EventBus`
- `StateStore`
- `SignalScorer`
- `DecisionEngine`
- `summary_llm`
- `SessionMemory`
- `MemoryStore`
- `MemoryCandidateStore`
- `RuntimeState`
- `LightweightLLMQueue`
- `LLMRuntime`
- `RuntimeOrchestrator`

`RuntimeOrchestrator.__init__()` crée aussi :

- `FactEngine`
- `CurrentContextBuilder`
- `SessionFSM`
- `RestartManager`

Ces créations ont lieu seulement quand `get_runtime()` est appelé. Elles n'ont plus lieu à l'import de `daemon.main`.

## Core strict

Services considérés comme Core strict ou nécessaires au flux runtime validé :

- `EventBus`
- `StateStore`, encore legacy mais branché au flux local existant
- `SignalScorer`
- `DecisionEngine`
- `RuntimeState`
- `SessionMemory`
- `SessionFSM`
- `RuntimeOrchestrator`, comme orchestrateur Core actuel
- file coalescer HTTP enregistré par `create_app(runtime)`

Ces services supportent `/event`, `/state`, `/feed`, `/health/core`, les sessions et le cycle runtime local.

## Surfaces dédiées séparées

`MemoryCandidateStore` est instancié par `create_runtime()` mais reste une surface dédiée :

- séparée de `SessionMemory` ;
- séparée de `MemoryStore` ;
- séparée de facts ;
- séparée de DayDream ;
- séparée de LLM ;
- non branchée dans `RuntimeOrchestrator`.

Les tests `memory_candidates` vérifient que les routes candidates n'appellent pas `MemoryStore`, facts, DayDream ou LLM, et que `/state`, `/debug/state` et `/insights` ne créent pas de candidates.

## Lab / legacy toléré en Core

Services ou surfaces Lab/legacy encore instanciés ou enregistrés pour compatibilité :

- `MemoryStore`, créé par `create_runtime()`.
- `FactEngine`, créé par `RuntimeOrchestrator.__init__()`.
- `summary_llm`, construit par `_build_summary_llm()` avec fallback `UnavailableLLMRouter`.
- `LLMRuntime`, créé par `create_runtime()`.
- `LightweightLLMQueue`, créé par `create_runtime()`.
- Routes assistant / LLM legacy.
- Routes facts/profile.
- Routes context probes.
- Routes work intent.
- Route `/daydreams`.

Ces éléments restent tolérés temporairement parce que les tests de C4a/C4b verrouillent leurs frontières : ils ne doivent pas devenir Core minimal, ne doivent pas alimenter memory candidates et ne doivent pas devenir dépendances de `/health/core`.

## Services créés lors de `create_app(runtime)`

`create_app(runtime)` enregistre les routes et crée aussi des stores locaux de routes runtime :

- `ContextProbeRequestStore`
- `WorkIntentCandidateStore`
- `CurrentContextBuilder`

Ces créations arrivent à la matérialisation de l'app, pas à l'import de `daemon.main`. Elles restent des surfaces non-Core enregistrées temporairement pour compatibilité locale / dogfooding.

## Workers et side effects observés

`create_runtime()` :

- ne démarre pas `RuntimeOrchestrator` ;
- ne démarre pas `pulse-file-burst` ;
- ne démarre pas `pulse-periodic-sync` ;
- ne crée pas de critical workers ;
- ne démarre pas de serveur Flask ;
- ne démarre pas le heartbeat idle.

`start_runtime_services()` démarre ensuite :

- `RuntimeOrchestrator.start()` ;
- le heartbeat idle.

`RuntimeOrchestrator.start()` démarre aujourd'hui deux workers permanents :

- `pulse-file-burst` ;
- `pulse-periodic-sync`.

Le worker `pulse-periodic-sync` reste une dette C4c : il existe en Core, mais ses conditions internes doivent rester strictes et ne doivent pas transformer le Core en apprentissage automatique.

Les workers DayDream et warmup LLM restent conditionnels :

- DayDream est gated par `is_lab_enabled()`.
- Le warmup LLM dépend de la policy heavy LLM autowarm.
- Les memory sync background workers sont déclenchés par des chemins runtime précis, pas par `create_runtime()` seul.

## Dépendances des surfaces Core

`/health/core` :

- ne dépend pas de `MemoryStore` ;
- ne dépend pas de facts ;
- ne dépend pas de DayDream ;
- ne dépend pas de LLM ;
- ne dépend pas de vector store / embeddings ;
- ne dépend pas de context probes ou work intent.

`/state` :

- reste basé sur `RuntimeState`, `StateStore`, `SessionFSM`, `CurrentContextBuilder` et `SessionMemory` ;
- ne doit pas matérialiser de mémoire Lab ;
- ne doit pas exposer `memory_candidates`.

`/feed` :

- reste basé sur `EventBus.recent()` ;
- ne doit pas être une source de création de memory candidates ;
- ne doit pas déclencher DayDream, facts, MemoryStore ou LLM.

`/memory/candidates` :

- dépend de `MemoryCandidateStore` ;
- ne dépend pas de `MemoryStore` ;
- ne dépend pas de facts ;
- ne dépend pas de DayDream ;
- ne dépend pas de LLM ;
- ne dépend pas de `RuntimeOrchestrator`.

## Mutations Lab en Core

Les tests existants documentent que :

- `/memory/write` est enregistrée mais bloquée en Core ;
- `/memory/remove` est enregistrée mais bloquée en Core ;
- les mutations facts `reinforce`, `contradict` et `archive` sont bloquées en Core ;
- `/facts/profile` est neutralisée en Core ;
- `/llm/lightweight/result` est bloquée en Core.

Ces routes restent enregistrées pour compatibilité, mais elles ne doivent pas devenir des capacités Core actives.

## Contradictions / dettes confirmées

Dettes acceptées pour C4c.1 :

- `MemoryStore` est encore instancié par `create_runtime()` en Core.
- `FactEngine` est encore instancié par `RuntimeOrchestrator.__init__()` en Core.
- `summary_llm` et `LLMRuntime` sont encore créés dans le bundle runtime.
- `LightweightLLMQueue` est encore créée et ses routes sont enregistrées, même si les mutations restent gated.
- `ContextProbeRequestStore` et `WorkIntentCandidateStore` sont créés à l'enregistrement de l'app complète.
- `pulse-periodic-sync` démarre avec `RuntimeOrchestrator.start()` même en Core.

Ces dettes ne sont pas corrigées dans C4c.1. Elles doivent être traitées par petits patchs test-first.

## Décision provisoire

C4c.1 confirme que le Core ne dépend pas directement des surfaces Lab pour `/health/core`, `/state`, `/feed` et `memory_candidates`, mais que plusieurs services Lab/legacy restent instanciés pour compatibilité.

Le comportement est toléré temporairement. Il ne doit pas être interprété comme une validation produit de facts, DayDream, LLM, context probes, work intent ou MemoryStore en Core.

## Prochaine étape recommandée

C4c.2 devrait cibler une dette précise, sans refactor massif. Les candidats les plus sûrs sont :

- rendre `FactEngine` lazy ou explicitement no-op en Core ;
- rendre `MemoryStore` lazy si les routes Lab peuvent conserver leur compatibilité ;
- documenter ou tester plus strictement le no-op du worker `pulse-periodic-sync` en Core ;
- éviter la création des stores context probes / work intent tant qu'une route non-Core n'est pas appelée.

Toute correction C4c.2 doit préserver les routes, payloads, gates Lab, memory candidates et le lancement daemon validé par C4b.
