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

---

# Audit fichier : `daemon/runtime_orchestrator.py`

## Verdict

`daemon/runtime_orchestrator.py` est le vrai cœur opérationnel de Pulse. Il relie observation, scoring, sessions, state, mémoire minimale, restart repair, propositions contextuelles et surfaces Lab.

Le fichier est beaucoup trop chargé, mais les gates Core / Lab posées en R1-R6 tiennent globalement.

Le risque principal n’est pas une feature isolée : c’est la concentration. Ce fichier est à la fois orchestrateur Core, scheduler, glue mémoire, runner DayDream, gestionnaire commit, producteur resume cards, passerelle lightweight LLM et émetteur de propositions contextuelles.

Pour le dogfooding Core, cette dette reste acceptable tant qu’on ne rend pas ce fichier plus intelligent.

## Rôle réel

`RuntimeOrchestrator` est le coordinateur runtime après ingestion dans l’`EventBus`.

Il :

- reçoit les events via `handle_event()` ;
- filtre certains events fichiers ;
- met à jour `SessionFSM` ;
- met à jour `RuntimeState` ;
- appelle `SignalScorer` ;
- appelle `DecisionEngine` ;
- persiste events et snapshots dans `SessionMemory` ;
- prépare, ferme et reprend des sessions ;
- déclenche ou bloque les sync mémoire avancées ;
- gère restart repair ;
- gère DayDream en Lab ;
- gère resume cards ;
- gère context injection proposals ;
- gère commit detection et commit memory sync.

## Responsabilités concentrées

Responsabilités Core légitimes :

- lifecycle workers `start()` / `shutdown_runtime()` ;
- file burst debounce ;
- lock / unlock ;
- idle / user presence ;
- scoring pipeline ;
- session boundaries ;
- `RuntimeState.update_present()` ;
- `SessionMemory.record_event()` ;
- `SessionMemory.update_present_snapshot()` ;
- snapshot Core minimal dans `freeze_memory()` quand Lab est désactivé.

Responsabilités Lab / legacy concentrées :

- facts engine ;
- DayDream scheduler ;
- advanced memory sync ;
- `MemoryStore` ;
- LLM warmup ;
- lightweight LLM queue ;
- resume card generation / update ;
- commit journal enrichment ;
- context injection proposal ;
- work intent lifecycle ;
- commit episode / work block linking helpers.

## Flux événementiel Core

Flux réel :

1. `/event` publie dans `EventBus`.
2. `main.py` abonne `runtime_orchestrator.handle_event`.
3. `handle_event()` filtre pause / lock / noise.
4. `SessionMemory.record_event(event)` persiste l’event.
5. Events fichiers : debounce puis `_process_file_burst()`.
6. Events non fichiers : `_process_signals(event)`.
7. `_process_signals()` lit `scorer.bus.recent()`.
8. `SessionFSM.observe_recent_events()` calcule lifecycle.
9. `SignalScorer.compute()` produit les signaux.
10. `RuntimeState.update_present()` expose l’état live.
11. `DecisionEngine.evaluate()` produit une décision.
12. `SessionMemory.update_present_snapshot()` persiste le snapshot session.
13. `RuntimeState.set_analysis()` expose signals / decision.

Le flux est cohérent, mais contient encore des embranchements Lab.

## Gestion sessions

`start()` :

- démarre deux workers : file burst et periodic sync.

Fermeture :

- `shutdown_runtime()` draine les fichiers ;
- exporte payload ;
- sauvegarde restart state ;
- ferme `SessionMemory` avec `close_reason="session_end"`.

Lock / unlock :

- `screen_locked` appelle `SessionFSM.on_screen_locked()` et `RuntimeState.mark_screen_locked()` ;
- `screen_unlocked` appelle `SessionFSM.on_screen_unlocked()` ;
- lock long peut créer une nouvelle session avec `close_reason="screen_lock"`.

Idle :

- `user_idle` force `SessionFSM.on_user_idle()` ;
- boundary idle passe ensuite par `new_session(... close_reason="idle_timeout")`.

Restart repair :

- `deferred_startup()` charge restart state et applique `RestartManager` ;
- `recover_missed_commits()` est appelé dans le même bloc ;
- utile en dogfooding dev, mais hors Core session strict.

`close_reason` :

- maintenant transmis depuis l’orchestrator vers `SessionMemory` ;
- mapping actuel : `screen_lock`, `idle_timeout`, `session_end` ;
- ces raisons sont désormais persistées et projetées dans `recent_sessions`.

## Mémoire Core vs Lab

Core :

- `SessionMemory.record_event()` ;
- `SessionMemory.update_present_snapshot()` ;
- `export_memory_payload()` comme compatibilité / historique minimal ;
- `freeze_memory()` produit un `Pulse Core Snapshot` en Core.

Lab :

- `update_memories_from_session()` ;
- `render_project_memory()` ;
- `load_memory_context()` ;
- `MemoryStore.render()` ;
- `fact_engine.render_for_context()` ;
- lightweight summaries ;
- DayDream ;
- resume cards intelligentes.

Bon point : `_sync_memory_background()` retourne immédiatement en Core si `not is_lab_enabled()`.

Point fragile : le periodic sync worker démarre quand même en Core, puis finit par appeler `_schedule_memory_sync()` selon conditions. La sync est ensuite no-op. Ce n’est pas dangereux aujourd’hui, mais c’est du bruit architectural.

## Propositions Core vs Lab

MCP Core contrôlé n’est pas principalement géré ici.

Le point sensible dans ce fichier est `context_injection` :

- `_attach_context_proposal_if_needed()` crée une proposition via `proposal_store` ;
- en Core, elle reste `pending` ;
- en Lab / dev, elle est auto-résolue `executed`.

C’est conforme à R6d / R6e, mais dangereux à garder dans le même orchestrateur Core : une régression de gate pourrait remettre de l’auto-execution dans le chemin runtime.

## Frontières Core / Lab

Gates présentes :

- DayDream derrière `is_lab_enabled()` ;
- facts maintenance derrière `is_lab_enabled()` ;
- advanced memory sync derrière `is_lab_enabled()` ;
- lightweight commit / resume summaries derrière `is_lab_enabled()` ;
- context proposal auto-execution derrière `is_lab_enabled()` ;
- LLM warmup derrière lifecycle policy.

Frontière imparfaite :

- `get_fact_engine()` est instancié dans `__init__` même en Core ;
- `MemoryStore` est injecté et utilisé pour purge expired au startup ;
- resume card deterministic paths existent dans Core ;
- work intent lifecycle tourne dans `_process_signals()` ;
- periodic sync worker tourne en Core ;
- commit recovery est mélangé au restart repair.

## Hardcoding identifié

Seuils / timeouts :

- `sleep_session_threshold_min = 30` ;
- `file_debounce_sec = 0.25` ;
- `commit_poll_sec = 0.4` ;
- `commit_confirm_timeout_sec = 15` ;
- `_diff_cooldown_sec = 120` ;
- `_prepared_resume_card_ttl_sec = 8h` ;
- `_resume_card_wait_timeout_sec = 90` ;
- `_resume_card_wait_poll_sec = 0.5` ;
- `_periodic_sync_interval_sec = 30min` ;
- `_critical_worker_join_timeout_sec = 1`.

Types events :

- `screen_locked`, `screen_unlocked` ;
- `user_presence`, `user_idle`, `user_active` ;
- `file_modified`, `file_created` ;
- `COMMIT_EDITMSG` ;
- `resume_card`.

Boundary reasons :

- `screen_lock` ;
- `idle_timeout` ;
- `session_end` ;
- `user_idle`.

Provider / flags :

- `is_lab_enabled()` ;
- `is_heavy_llm_autowarm_enabled()` ;
- `is_legacy_journal_repair_enabled()`.

## Sources de vérité

- `EventBus` : source des observations récentes.
- `SessionFSM` : vérité runtime des transitions session.
- `RuntimeState` : vérité live exposée par `/state`.
- `SessionMemory` : vérité persistée sessions / events.
- `SignalScorer` : vérité heuristique des signaux.
- `DecisionEngine` : décision runtime.
- `StateStore` : encore injecté, mais les tests interdisent son usage direct dans l’orchestrator.

## Side effects / risques runtime

Side effects à l’instanciation :

- instancie `FactEngine` ;
- instancie `SessionFSM` ;
- instancie `RestartManager` ;
- ne démarre pas de threads tant que `start()` n’est pas appelé.

Side effects à `start()` :

- démarre file burst worker ;
- démarre periodic sync worker.

Risques :

- beaucoup de workers critiques en daemon threads ;
- shutdown join timeout très court ;
- periodic sync Core inutile mais actif ;
- commit watch lance subprocess `git` ;
- restart repair et commit recovery mélangés ;
- resume card peut publier des events depuis lock / unlock ;
- context proposal global `proposal_store` mutable ;
- erreurs aval souvent loggées puis absorbées, ce qui protège le runtime mais peut masquer des régressions.

## Legacy restant

Legacy clair :

- `SessionContext` fallback ;
- `work_window` alias ;
- legacy journal repair ;
- commit summary repair Ollama ;
- `MemoryStore` ;
- facts engine instancié ;
- DayDream methods dans l’orchestrator ;
- resume card pipeline ;
- `StateStore` injecté ;
- `load_memory_context()` fallback Lab ;
- `proposal_store` global.

Tout cela est hors Core strict, mais encore dans le fichier Core le plus critique.

## Tests existants

Très bonne couverture dans :

- `tests/test_runtime_orchestrator.py` ;
- `tests/test_runtime_lifecycle.py` ;
- `tests/core/test_restart_manager.py` ;
- `tests/core/test_session_fsm.py` ;
- `tests/routes/test_runtime_state_payloads.py`.

Les tests couvrent :

- workers start / shutdown ;
- lock / unlock ;
- DayDream gated ;
- facts gated ;
- memory sync Core no-op ;
- lightweight queue Core no-op ;
- context proposal Core pending / Lab executed ;
- session boundary ;
- restart repair ;
- state projection.

## Tests manquants

Manques utiles :

- test end-to-end `EventBus -> RuntimeOrchestrator -> /state -> SessionMemory` sur scénario lock long réel ;
- test periodic sync en Core prouvant qu’il ne crée pas de worker advanced observable ;
- test restart repair sans commit recovery ;
- test `close_reason` depuis `RuntimeOrchestrator` jusqu’à `get_recent_sessions()` ;
- test d’absence de resume card produit en Core si on décide que resume cards restent Lab ;
- test sur ordre shutdown avec workers réels, pas seulement mocks ;
- test de non-utilisation `MemoryStore` en Core hors purge ;
- test de non-instanciation facts en Core si ce point devient objectif.

## Dette acceptable

Acceptable maintenant :

- garder `RuntimeOrchestrator` large mais sous tests ;
- garder gates internes plutôt que refactor global ;
- garder periodic sync worker no-op en Core ;
- garder facts engine instancié si aucun effet Core visible ;
- garder resume card deterministic si les tests R6 maintiennent la frontière produit ;
- garder commit watch, car dogfooding dev en bénéficie ;
- garder `proposal_store` global tant que R6 tests restent stricts.

## Dette à corriger plus tard

À corriger après dogfooding :

- extraire `CoreRuntimePipeline` ou au moins séparer mémoire / LLM / DayDream / proposals ;
- sortir DayDream du fichier orchestrator ;
- sortir lightweight LLM handlers ;
- séparer restart repair de commit recovery ;
- rendre periodic sync non démarré en Core ;
- rendre facts engine lazy ou Lab-only ;
- clarifier resume cards comme Lab ou Core debug, puis aligner le code ;
- supprimer alias legacy `work_window` quand plus nécessaire ;
- centraliser les event type constants.

## Ce qu’il ne faut pas modifier maintenant

- Ne pas toucher `SessionFSM`.
- Ne pas rendre le scorer plus intelligent.
- Ne pas réactiver advanced memory en Core.
- Ne pas lancer R7.
- Ne pas ajouter facts/profile, DayDream, vector store, LLM summaries ou apprentissage.
- Ne pas supprimer brutalement resume cards / proposals sans audit UI/API.
- Ne pas refactorer ce fichier en grand maintenant : trop de risques.
- Ne pas déplacer les gates Core / Lab sans tests équivalents.
- Ne pas confondre hardening Core avec nouvelle autonomie.