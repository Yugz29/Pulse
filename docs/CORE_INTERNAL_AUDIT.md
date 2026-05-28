

# Core Internal Audit

Ce document suit l’audit interne du Core Pulse après la validation du Core Reset R1-R6.

Il ne remplace pas :

- `docs/ROADMAP_CORE_RESET.md` ;
- `docs/CORE_RESET_VALIDATION_SUMMARY.md` ;
- les contrats Core ;
- `docs/CORE_DOGFOODING_NOTES.md`.

## Objectif

L’objectif est d’auditer les fondations internes du Core fichier par fichier avant toute reprise de R7, apprentissage utilisateur, mémoire intelligente ou systèmes Lab.

Le but n’est pas de rendre Pulse plus intelligent maintenant. Le but est de vérifier que le Core est :

- lisible ;
- testable ;
- honnête dans ses surfaces ;
- robuste en usage réel ;
- clair sur ses frontières Core / Lab ;
- explicite sur ses hardcodings et dettes acceptées.

## Règles de cette phase

- Auditer fichier par fichier.
- Ne pas lancer R7.
- Ne pas ajouter d’apprentissage utilisateur.
- Ne pas réactiver DayDream, facts/profile, vector store, LLM summaries, context probes, work intent ou propositions intelligentes.
- Ne pas faire de refactor massif sans audit dédié.
- Classer chaque dette comme :
  - acceptable maintenant ;
  - à corriger plus tard ;
  - critique / à traiter rapidement.
- Ne coder que des patchs minimaux quand l’audit ou le dogfooding prouve un problème concret.

## Statut global

Core Reset R1-R6 : validé côté Python.

Phase actuelle : dogfooding et hardening Core.

C1 — Core Internal Audit : démarré.

---

# Audit fichier : `daemon/main.py`

## Verdict

`daemon/main.py` est un fichier Core critique, mais il reste trop chargé. Il joue à la fois le rôle de composition root, hub de routes legacy / Lab, point d’entrée exécutable, lifecycle dev et glue globale.

Le fichier tient aujourd’hui parce que les garde-fous R1-R6 existent dans les modules appelés. Mais `main.py` ne matérialise pas encore clairement la frontière Core / Lab.

Point dur : le runtime est créé au chargement du module, avant tout bind Flask. Un lancement direct `python -m daemon.main` peut donc encore créer logs, DB, runtime, `SessionMemory`, `MemoryStore`, router LLM et app Flask avant de découvrir un conflit de port.

## Rôle réel

`daemon/main.py` fait aujourd’hui quatre choses :

1. Compose le runtime global :
   - `EventBus` ;
   - `StateStore` ;
   - `SignalScorer` ;
   - `DecisionEngine` ;
   - `SessionMemory` ;
   - `MemoryStore` ;
   - `RuntimeState` ;
   - `LLMRuntime` ;
   - `LightweightLLMQueue` ;
   - `RuntimeOrchestrator`.
2. Configure Flask et enregistre les routes.
3. Branche le bus sur le store et l’orchestrator.
4. Démarre le daemon en mode exécutable : services runtime, MCP server, watchdog, deferred startup, Flask.

Ce n’est donc pas seulement un entrypoint. C’est aussi le conteneur global de dépendances.

## Responsabilités concentrées

Responsabilités Core :

- création `EventBus` / `StateStore` / `RuntimeState` ;
- création `SessionMemory` ;
- création `SignalScorer` ;
- création `RuntimeOrchestrator` ;
- routes runtime via `register_runtime_routes()` : `/ping`, `/state`, `/debug/state`, `/event`, `/feed`, `/health/core` ;
- heartbeat présence utilisateur ;
- shutdown runtime ;
- watchdog dev.

Responsabilités Lab / legacy encore présentes :

- assistant / cognitive routes ;
- LLM router et settings modèles ;
- `LightweightLLMQueue` ;
- `MemoryStore` ;
- facts routes ;
- memory routes Core / Lab mélangées ;
- MCP routes ;
- DayDream route indirectement dans feed routes ;
- context probes mentionnés dans le filtre logs ;
- surfaces modèles LLM.

## Frontières Core / Lab

La frontière Core / Lab est aujourd’hui principalement portée par les modules appelés, pas par `main.py`.

`main.py` enregistre toujours :

- `register_assistant_routes()` ;
- `register_memory_routes()` ;
- `register_mcp_routes()` ;
- `register_facts_routes()` ;
- `register_runtime_routes()`.

En mode Core, les surfaces Lab existent donc encore comme routes. Leur sécurité dépend des gates internes ajoutés pendant R1-R6.

État acceptable post-reset : oui, parce que les gates existent.

Dette architecturale : oui, parce que `main.py` ne donne pas une lecture claire “Core services only”. Il expose beaucoup, puis chaque route doit se discipliner.

## Hardcoding identifié

Ports :

- Flask principal : `127.0.0.1:8765` ;
- MCP : `127.0.0.1:8766`.

Chemins :

- logs : `~/.pulse/logs/daemon.app.log` ;
- settings : `~/.pulse/settings.json` ;
- `SessionMemory` et `MemoryStore` dépendent aussi de `Path.home()` via leurs constructeurs.

Intervalles :

- `WATCHDOG_TIMEOUT_SEC = 30` ;
- `WATCHDOG_GRACE_SEC = 15` ;
- boucle watchdog toutes les 10 secondes ;
- log rotation : 5 MB, 5 backups.

Routes / filtres :

- filtre access logs avec liste explicite de routes : `/ping`, `/state`, `/feed`, `/daydreams`, `/llm/lightweight/pending`, `/context-probes/requests`, etc. ;
- route registration centralisée mais non déclarative.

Providers / modèles :

- `_build_summary_llm()` lit `model` ou `command_model` ;
- import dynamique de `daemon.llm.router` ;
- fallback `UnavailableLLMRouter`.

## Sources de vérité

Sources runtime :

- `runtime` global créé par `create_runtime()` ;
- alias globaux : `bus`, `store`, `scorer`, `session_memory`, `runtime_state`, `runtime_orchestrator`, etc.

Sources état :

- `RuntimeState` pour `/state`, pause, ping, lock markers ;
- `SessionMemory` pour sessions récentes, today summary, work episodes debug ;
- `EventBus` pour ingestion et feed ;
- `StateStore` encore branché sur le bus, probablement legacy / support runtime.

Sources configuration :

- environnement pour logs : `PULSE_LOG_LEVEL`, `PULSE_DEBUG` ;
- settings JSON pour modèles ;
- `PULSE_MODE` n’est pas lu directement dans `main.py`; les gates sont ailleurs.

## Side effects / risques de boot

Side effects au chargement du module :

- configuration logging globale avec handlers ;
- création de `~/.pulse/logs` ;
- création `runtime = create_runtime()` ;
- instanciation `SessionMemory`, donc DB / session state ;
- instanciation `MemoryStore` ;
- construction du router LLM ou fallback ;
- configuration MCP LLM router global ;
- création Flask app ;
- enregistrement des routes ;
- subscription des handlers bus.

Risques de boot :

- `runtime` créé avant bind port ;
- en `__main__`, `start_runtime_services()` arrive avant `app.run()` ;
- MCP server démarre avant bind Flask ;
- deferred startup et watchdog démarrent avant confirmation que Flask est opérationnel ;
- si `8765` est occupé lors d’un lancement direct, le runtime peut déjà avoir eu des effets de bord ;
- le script dev protège désormais mieux ce cas, mais `python -m daemon.main` reste exposé.

Shutdown / restart :

- `_shutdown_runtime()` stoppe heartbeat, coalescer, puis orchestrator ;
- watchdog dev appelle `_shutdown_runtime()` puis `os._exit(0)` ;
- comportement pragmatique et utile en dev, mais lifecycle encore brutal.

## Legacy restant

Legacy clair :

- `StateStore` global encore abonné au bus ;
- routes assistant / cognitive dans `main.py` ;
- facts routes toujours enregistrées ;
- `MemoryStore` toujours instancié ;
- `LLMRuntime` global toujours instancié ;
- `LightweightLLMQueue` globale toujours instanciée ;
- filtre logs contenant des routes Lab : `/daydreams`, `/llm/lightweight/pending`, `/context-probes/requests`.

Acceptable pour l’instant parce que les gates R1-R6 existent.

Risque : donne une fausse impression que tout ce qui est branché dans `main.py` est Core.

## Tests existants

Couverture utile :

- `tests/test_main_runtime_state.py` : import, globals, `create_runtime()`, `create_app()`, start services, shutdown, watchdog, `/state`, `/insights` ;
- `tests/test_runtime_routes.py` : `/ping`, `/health/core`, `/state`, `/debug/state` ;
- `tests/test_main_memory_routes.py` : routes mémoire via `daemon.main` ;
- `tests/test_main_mcp_routes.py` : routes MCP ;
- `tests/test_main_llm_models.py` : surfaces modèles / LLM ;
- `tests/test_main_logging.py` : logging, filter, log level.

## Tests manquants

Manques importants :

- test prouvant qu’un conflit port `8765` ne démarre pas le runtime quand lancé via entrypoint direct ;
- test explicite “Core mode import does not start background threads” ;
- test sur ordre de boot `start_runtime_services()` avant bind Flask ;
- test sur échec MCP port `8766` ;
- test documentant que `create_app()` enregistre les routes Lab mais que celles-ci restent gatées ;
- test de non-dépendance de `/ping` et `/health/core` à un router LLM réel pendant import complet de `main.py`.

## Dette acceptable maintenant

Acceptable pour le moment :

- garder les routes Lab enregistrées si elles sont gatées ;
- garder `LLMRuntime` et `LightweightLLMQueue` instanciés, tant qu’ils ne bloquent pas Core ;
- garder `MemoryStore` instancié, tant qu’il ne participe pas au flux Core ;
- garder les alias globaux pour compatibilité tests/routes ;
- garder le watchdog dev, couvert et utile en dogfooding ;
- garder le script dev comme première ligne de défense contre ports occupés.

## Dette à corriger plus tard

À corriger après dogfooding Core, pas maintenant :

- séparer entrypoint exécutable et factory importable ;
- éviter `runtime = create_runtime()` au module import ;
- déplacer ports/config dans une config runtime explicite ;
- rendre l’ordre de boot plus sûr : vérifier bind/preflight avant démarrage services ;
- isoler route registration Core vs Lab dans des fonctions lisibles ;
- sortir le filtre logs des routes Lab hardcodées ou le rendre déclaratif ;
- clarifier ownership de `StateStore` legacy ;
- réduire les globals exposés par `main.py`.

## Ce qu’il ne faut pas modifier maintenant

- Ne pas toucher `SessionFSM`.
- Ne pas lancer R7.
- Ne pas ajouter apprentissage, facts/profile, vector store, DayDream ou LLM summaries.
- Ne pas désenregistrer brutalement les routes Lab.
- Ne pas rendre LLM lazy sans plan dédié.
- Ne pas refactorer `main.py` en grand composition root maintenant.
- Ne pas casser les tests qui importent `daemon.main` et utilisent les globals.
- Ne pas mélanger hardening boot avec nouvelles features.