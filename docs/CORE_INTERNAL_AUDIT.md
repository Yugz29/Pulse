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

C1 — Core Internal Audit : terminé.
C2 — Hardening minimal : en cours.

C2.1, C2.2 et C2.3 sont terminés : santé Core côté Swift, clarification des textes Lab UI, et tests de garde routes / state / UI.

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

---

# Audit fichier : `daemon/runtime_state.py`

## Verdict

`daemon/runtime_state.py` est une brique Core critique et globalement saine. C’est un conteneur thread-safe de l’état live, pas un moteur d’intelligence.

Il fait correctement le pont entre signaux calculés, état runtime, présence utilisateur, pause, lock et payloads `/state`.

Le risque principal n’est pas technique pur : c’est que l’UI ou l’API lise `PresentState` comme une vérité certaine alors que plusieurs champs sont dérivés ou inférés depuis `Signals`.

## Rôle réel

`RuntimeState` est la source de vérité live côté daemon pour :

- état courant exposé dans `/state.present` ;
- pause runtime ;
- lock marker ;
- présence utilisateur ;
- dernier état de signaux / décision ;
- dernière app active observée ;
- timestamps de sync mémoire / diff ;
- état transitoire `work_intent`.

Il ne score pas, ne persiste pas, ne décide pas de session canonique, et ne devrait pas devenir un orchestrateur.

## Responsabilités concentrées

Le fichier concentre :

- `PresentState` : vue live lisible du contexte courant ;
- `RuntimeSnapshot` : snapshot debug / runtime plus large ;
- pause / ping ;
- lock / unlock markers ;
- présence utilisateur ;
- projection des `Signals` vers le présent ;
- cache des derniers `signals` et `decision` ;
- `WorkIntent` ;
- déduplication fichier via `event_meaning` ;
- latest active app / bundle / category.

Cette concentration reste acceptable, mais la frontière Core / debug est fine.

## Données du présent

`PresentState` expose notamment :

- `session_status` ;
- `awake` ;
- `locked` ;
- `active_file` ;
- `active_project` ;
- `probable_task` ;
- `activity_level` ;
- `focus_level` ;
- `friction_score` ;
- `clipboard_context` ;
- `user_presence_state` ;
- `user_idle_seconds` ;
- `user_presence_source` ;
- durées app / window ;
- compteurs de switch ;
- `session_duration_min` ;
- `work_intent`.

Point important : `probable_task`, `active_project`, `activity_level` et `focus_level` viennent des `Signals`. Ce sont des interprétations, pas des observations brutes.

`task_confidence` n’est pas dans `PresentState`, donc la surface live peut paraître plus affirmative que le scorer réel.

## Core stable vs debug / legacy

Core raisonnablement stable :

- pause runtime ;
- ping ;
- `PresentState` ;
- lock markers ;
- présence utilisateur ;
- latest active app ;
- projection des signaux récents ;
- déduplication fichier via policy existante.

Debug / legacy / Lab-ish :

- `_last_signals` ;
- `_last_decision` ;
- `memory_synced_at` ;
- `last_diff_summary` ;
- `WorkIntent` ;
- `clipboard_context` ;
- `get_signal_snapshot()` / `get_context_snapshot()` ;
- `_recent_file_events`, qui semble désormais résiduel puisque la déduplication délègue à `event_meaning`.

## Lock / presence / pause

La séparation est correcte :

- `paused` est une pause runtime, pas un état `SessionFSM` ;
- `locked` est un état d’écran / runtime ;
- `user_presence` est un signal de présence, pas une preuve de travail ;
- `last_screen_locked_at` reste volontairement après unlock jusqu’à `clear_sleep_markers()`.

Point fragile : `mark_screen_unlocked()` ne nettoie pas tout seul le timestamp de lock. C’est probablement intentionnel pour calculer la durée de sommeil, mais dangereux si quelqu’un lit ce champ sans connaître le protocole.

## Projet, fichier, app active

`active_file` et `active_project` viennent des signaux. Ce ne sont pas des vérités observées directement.

`latest_active_app` signifie plutôt “dernière app observée” que “app actuellement certaine”. Il n’y a pas de fraîcheur ou expiration locale dans `RuntimeState`.

Le top-level `/state.active_app` et `present.active_project` / `present.active_file` peuvent donc raconter des temporalités différentes.

## Champs sensibles ou trop bruts

Champs à surveiller :

- `active_file` : chemin local potentiellement sensible ;
- `active_project` : peut révéler nom de workspace / client ;
- `clipboard_context` : ambigu et potentiellement sensible ;
- `work_intent.summary` / `evidence_refs` : Lab-ish, peut sembler produit ;
- `latest_active_app_bundle_id` ;
- `last_diff_summary` ;
- `signals` / `decision` stockés en `Any` puis exposables via payloads debug / legacy.

Ce n’est pas forcément un bug, mais ce n’est pas une surface produit neutre.

## Hardcoding identifié

Hardcoding modéré :

- valeurs par défaut : `idle`, `general`, `normal` ;
- déduplication fichier : cleanup TTL `5s`, fenêtre `1s` ;
- `WorkIntent.evidence_refs` limité à 5 items, 120 caractères chacun ;
- confidence clampée entre `0.0` et `1.0`.

Pas de hardcoding de port, provider LLM ou chemin utilisateur dans ce fichier.

## Sources de vérité

Sources réelles :

- `SignalScorer` produit les `Signals` ;
- `RuntimeState` stocke la projection live ;
- `SessionFSM` reste source de logique session runtime ;
- `SessionMemory` reste source de persistance historique ;
- `EventMeaningPolicy` porte la logique de déduplication / bruit fichier ;
- `RuntimeOrchestrator` décide de l’ordre d’update ;
- ingestion runtime alimente latest active app et présence.

`RuntimeState` est une source de vérité live, pas la source canonique des sessions ou de la mémoire.

## Risques UI / API

Risques principaux :

- `/state.present.probable_task` peut sembler certain sans `task_confidence` ;
- `activity_level` peut être lu comme activité produit alors que c’est un signal récent ;
- `paused`, `locked`, `awake`, `session_status` peuvent être confondus ;
- `active_app`, `active_file`, `active_project` n’ont pas tous la même temporalité ;
- `work_intent` peut être pris pour du Core alors qu’il doit rester Lab / debug ;
- les payload builders ajoutent `signals`, `current_context`, `recent_sessions`, ce qui brouille produit / debug.

## Legacy restant

Legacy clair :

- `get_signal_snapshot()` / `get_context_snapshot()` ;
- `_recent_file_events` inutilisé localement ;
- stockage `Any` de `signals` et `decision` ;
- `WorkIntent` dans le runtime live alors que ce n’est pas Core strict ;
- `last_diff_workspace` / `last_diff_computed_at` stockés mais peu exposés ;
- `memory_synced_at` encore présent dans snapshot Core / debug malgré gating mémoire avancée.

## Tests existants

Couverture utile existante :

- `tests/test_main_runtime_state.py` ;
- `tests/routes/test_runtime_state_payloads.py` ;
- `tests/test_runtime_routes.py` ;
- `tests/test_runtime_orchestrator.py` ;
- `tests/platform/test_idle_probe.py` ;
- `tests/core/test_signal_scorer.py` ;
- tests work intent / decision engine qui utilisent `PresentState`.

La couverture est correcte pour la stabilité actuelle.

## Tests manquants

Manques utiles plus tard :

- invalidité / normalisation de `user_presence` ;
- fraîcheur ou staleness de `latest_active_app` ;
- test explicite que `PresentState` n’expose pas `task_confidence` ;
- comportement voulu de `last_screen_locked_at` après unlock ;
- `WorkIntent.from_dict()` sur payloads invalides ;
- garantie que `work_intent` reste hors Core produit ;
- test de non-exposition des champs diff / memory dans surface produit ;
- stress thread-safety si le daemon devient plus concurrent.

## Dette acceptable

Acceptable maintenant :

- conteneur mutable protégé par lock ;
- `Any` pour compatibilité avec les objets signaux actuels ;
- duplication partielle `/state` / `/debug/state` ;
- présence de `WorkIntent` tant qu’il reste traité comme Lab / debug ;
- lock timestamp conservé après unlock ;
- déduplication déléguée à `event_meaning`.

Ce fichier n’est pas le problème prioritaire du Core.

## Dette à corriger plus tard

À corriger après dogfooding, sans ouvrir R7 :

- séparer plus nettement `CorePresentState` et `DebugRuntimeSnapshot` ;
- rendre explicite confidence / uncertainty dans les surfaces UI / API ;
- sortir ou marquer plus fortement `WorkIntent` comme Lab ;
- supprimer `_recent_file_events` ;
- clarifier `latest_active_app` en `latest_observed_app` ou ajouter une fraîcheur ;
- valider les champs `user_presence` ;
- réduire les payloads bruts exposables côté produit.

## Ce qu’il ne faut pas modifier maintenant

- Ne pas fusionner `SessionFSM` dans `RuntimeState`.
- Ne pas faire scorer `RuntimeState`.
- Ne pas ajouter mémoire intelligente, facts, LLM, DayDream ou apprentissage ici.
- Ne pas supprimer des champs consommés par Swift sans migration API.
- Ne pas changer `mark_screen_unlocked()` pour nettoyer aveuglément `last_screen_locked_at`.
- Ne pas faire de `user_presence` une preuve directe de session.
- Ne pas transformer `WorkIntent` en feature Core.

---

# Audit fichier : `daemon/core/signal_scorer.py`

## Verdict

`daemon/core/signal_scorer.py` est un vrai composant Core. Il transforme les observations récentes en signaux prudents, déterministes et testés.

Il ne fait pas d’apprentissage, pas de LLM, pas de mémoire intelligente, pas de Lab actif.

Le fichier est solide pour le dogfooding Core, mais il reste heuristique et non explicable de façon canonique : les poids existent, mais `SignalScorer.compute()` ne retourne pas la liste des signaux actifs ni leur contribution.

Le risque principal reste l’overclaim côté surfaces consommatrices, pas le calcul brut lui-même.

## Rôle réel

`SignalScorer` lit les derniers événements de l’`EventBus` et produit un objet `Signals`.

Il calcule :

- projet / fichier actif probable ;
- tâche probable ;
- niveau d’activité ;
- niveau de focus ;
- confiance de tâche ;
- friction ;
- mix de fichiers ;
- signaux terminal / MCP / window title / presence ;
- durées app / window ;
- compteurs de switchs.

Il ne possède plus la session : `reset_session()` est explicitement un shim legacy, et la durée vient de `session_started_at` fourni par l’extérieur.

## Signaux produits

`Signals` expose une surface riche :

- `active_project`, `active_file` ;
- `probable_task` ;
- `task_confidence` ;
- `activity_level` ;
- `focus_level` ;
- `friction_score` ;
- `session_duration_min` ;
- `recent_apps` ;
- `clipboard_context` ;
- `edited_file_count_10m` ;
- `file_type_mix_10m` ;
- `rename_delete_ratio_10m` ;
- `dominant_file_mode` ;
- `work_pattern_candidate` ;
- signaux MCP ;
- signaux terminal ;
- window title ;
- app bundle / category ;
- app / window durations ;
- switch counts ;
- user presence.

Cette sortie est une interprétation, pas une preuve observée brute.

## Heuristiques / hardcoding

Hardcoding assumé et centralisé :

- fenêtres temporelles : 5, 10, 30, 60 minutes selon les signaux ;
- `_TASK_MIN_SCORE = 1.0` ;
- `_TASK_WEIGHTS` pour `coding`, `debug`, `writing`, `exploration` ;
- seuils de focus : 6 switches, 3 fichiers, 2 fichiers pour `deep` ;
- friction : max churn divisé par `6`, bonus stacktrace `+0.3` ;
- `task_confidence` plafonnée à `0.92` ;
- pattern workspace dominant pondéré par `0.65 ** index` ;
- `reading_only = 0.8`, donc insuffisant seul ;
- `high_friction = 0.3`, donc jamais décisif seul.

C’est acceptable maintenant, mais ce sont des constantes produit déguisées en code. Elles devront rester stables pendant le dogfooding.

## Sources d’événements

Le scorer consomme notamment :

- `file_created`, `file_modified`, `file_renamed`, `file_deleted`, `file_change` ;
- `app_activated`, `app_switch` ;
- `clipboard_updated`, `clipboard_update` ;
- `mcp_command_received`, `mcp_decision` ;
- `terminal_command_started`, `terminal_command_finished` ;
- `window_title_poll` ;
- `user_presence`, `user_active`, `user_idle` ;
- `screen_locked` ;
- `local_exploration`.

La qualification bruit / scoring est déléguée à `event_meaning._default_policy`, donc le scorer dépend fortement de la qualité R2.

## Calcul `probable_task`

Le calcul est raisonnablement prudent :

1. Collecte des signaux actifs.
2. Pondération via `_TASK_WEIGHTS`.
3. Fallback `general` si aucun score ou score sous seuil.
4. Sinon meilleure tâche + confiance relative au total positif, plafonnée à `0.92`.

Points forts :

- `browsing` n’est plus une tâche ; c’est `exploration` + `activity_level=navigating` ;
- `executing` n’est pas une tâche ; c’est une activité ;
- debug exige une preuve forte ;
- app dev seule sans édition ne force pas `coding` ;
- tool-assisted peut ancrer le projet mais n’inflate pas l’édition utilisateur.

Limite : le scorer ne retourne pas les signaux actifs, donc l’explication doit être reconstruite ailleurs.

## Calcul `activity_level` / `focus_level`

`activity_level` est séparé de `probable_task`, ce qui est sain :

- `idle` ;
- `executing` ;
- `editing` ;
- `navigating` ;
- `reading`.

`focus_level` reste pragmatique :

- `idle` si lock / user idle récent sans activité fichier substantielle ;
- `normal` si workflow IA assisté ou switchs nombreux avec activité fichier ;
- `scattered` si 6+ switches non-IA sans activité fichier suffisante ;
- `deep` si peu de switches et au moins 2 edits fichiers ;
- sinon `normal`.

Ces labels peuvent encore être surinterprétés côté UI.

## Calcul `task_confidence`

`task_confidence` est une confiance relative du meilleur score :

```text
confidence = min(best_score / positive_total, 0.92)
```

S’il n’y a pas de score : `0.4`.

Si le score est sous seuil : `0.4 + best_score * 0.1`.

Limite importante : ce n’est pas une probabilité statistique. C’est une confiance heuristique normalisée. Elle ne mesure ni qualité des observations, ni fraîcheur globale, ni contradiction entre sources.

## Anti-overclaim

Le fichier contient de bons garde-fous :

- fichiers `system` exclus comme ancre projet ;
- fichiers `tool_assisted` exclus des counts utilisateur ;
- bruit technique filtré via `event_meaning` ;
- screenshots / caches / `.pulse` couverts par tests ;
- project hint rejeté sans signal de continuité ;
- window title seul ne confirme pas le projet ;
- stacktrace ancienne ignorée ;
- navigateur ancien n’impose pas exploration ;
- app inconnue seule ne crée pas coding ;
- `user_presence` ne crée pas du travail à lui seul ;
- MCP deny n’est pas usable ;
- diff git est signal de secours, plus faible que FSEvents.

C’est aligné Core Reset.

## Limites connues

Limites à garder visibles :

- pas de trace canonique des poids internes dans `Signals` ;
- pas de raison structurée “pourquoi cette tâche” ;
- `task_confidence` est heuristique, pas probabiliste ;
- `active_file` peut venir d’un titre de fenêtre basename-only ;
- `active_project` peut venir du terminal ou d’un project hint conservé ;
- certains signaux Lab / debug peuvent influencer l’interprétation ;
- `SESSION_TIMEOUT_MIN` est importé mais semble inutilisé ;
- `_is_pulse_internal_path()` paraît inutilisé localement ;
- dépendance à `_default_policy` interne de `event_meaning` ;
- les listes d’apps bootstrap restent un biais fort.

## Données sensibles

Le scorer manipule et expose potentiellement :

- chemins de fichiers complets ;
- noms de projets ;
- commandes terminal ;
- cwd terminal ;
- résumés terminal ;
- bundle IDs ;
- titres de fenêtres ;
- type de clipboard ;
- signaux MCP.

Il ne semble pas exposer le contenu brut du clipboard, ce qui est bon. Mais les titres de fenêtre et commandes terminal peuvent déjà contenir des informations sensibles.

## Dépendances Core / Lab

Core :

- `EventBus` ;
- `event_meaning` ;
- `file_classifier` ;
- `app_classifier` ;
- `workspace_context` ;
- `terminal_event_normalizer` en amont ;
- `RuntimeState` en aval.

Lab / à surveiller :

- MCP signals ;
- app transition `app_ai_assisted` ;
- `local_exploration` ;
- diff summary ;
- downstream resume cards / probes / work intent qui consomment ces champs.

Le scorer ne lance aucun système Lab, mais il accepte des signaux issus de surfaces proches du Lab. C’est acceptable tant que les consommateurs ne les vendent pas comme vérité produit.

## Tests existants

Très bonne couverture :

- `tests/core/test_signal_scorer.py` ;
- `tests/test_interpretation_signal_scorer_golden.py` ;
- `tests/core/test_signal_scorer_session.py` ;
- `tests/core/test_observation_qualification_consistency.py` ;
- tests payloads `/state`, qui vérifient notamment que `task_confidence` reste hors `PresentState`.

## Tests manquants

Manques utiles plus tard :

- test explicite sur l’import inutilisé `SESSION_TIMEOUT_MIN` / absence de dépendance session ;
- test que `_TASK_WEIGHTS` ne contient pas de nouvelle tâche non documentée ;
- test de stabilité des signaux actifs si deux tâches ont score égal ;
- test sur terminal `deny` ou signal terminal invalide ;
- test de non-exposition de contenu clipboard brut ;
- test que `local_exploration` seul ne devient pas projet confirmé hors contexte terminal ;
- test de fraîcheur des `active_app_duration_sec` / `active_window_title_duration_sec` ;
- tests de drift sur bootstrap app lists si elles changent.

## Dette acceptable

Acceptable maintenant :

- heuristiques codées en dur ;
- poids simples ;
- pas de ML ;
- pas d’explication canonique ;
- confiance heuristique ;
- dépendance à `event_meaning` ;
- consommation passive de signaux MCP / terminal ;
- window title comme fallback faible.

C’est exactement le bon niveau pour Core hardening : déterministe, testable, pas magique.

## Dette future

À corriger plus tard, après dogfooding :

- retourner une trace structurée : signaux actifs, poids, score par tâche ;
- documenter les poids comme contrat testable ;
- séparer clairement signaux Core et signaux Lab / debug dans la sortie ;
- supprimer imports / méthodes mortes ;
- rendre les constantes de seuil auditées, pas dispersées ;
- mieux qualifier les sources sensibles ;
- améliorer le tie-break entre tâches ;
- clarifier `task_confidence` comme “heuristic confidence”.

## Ce qu’il ne faut pas modifier maintenant

- Ne pas ajouter LLM, apprentissage ou profil utilisateur dans le scorer.
- Ne pas transformer `task_confidence` en pseudo-certitude.
- Ne pas faire de `user_presence` une preuve de travail.
- Ne pas réintroduire `browsing` ou `executing` comme tâches produit.
- Ne pas compter `tool_assisted` comme édition utilisateur.
- Ne pas rendre `project_hint` autoritaire.
- Ne pas corriger les heuristiques sans golden tests.
- Ne pas brancher facts / vector / DayDream / mémoire intelligente.
- Ne pas faire du scorer un moteur de décision ou de proposition.

---

# Audit groupé : Observation / Events

## Verdict

La couche Observation / Events est une bonne fondation R2 pour le Core : elle reste passive, déterministe, locale, testée, et ne déclenche pas de mémoire intelligente, LLM, DayDream, facts ou propositions avancées.

Le point fort : le filtrage bruit, l’attribution d’acteur, la normalisation terminal et le traitement lock / presence sont déjà pensés pour éviter que des signaux faibles contaminent le Core.

Le point faible : la couche reste permissive pour les événements non-fichier inconnus, repose sur plusieurs listes hardcodées, et mélange encore une surface legacy dict avec des concepts plus récents comme qualification, actor, noise policy et coalescing.

Ce n’est pas cassé, mais ce n’est pas encore une enveloppe d’événement propre.

## Rôle global de la couche Observation / Events

Cette couche transforme des événements locaux bruts en événements publiables et consommables par le runtime.

Pipeline réel :

```text
Swift / producer local
-> POST /event
-> runtime_ingestion
-> EventMeaningPolicy
-> EventActorClassifier pour fichiers
-> terminal normalization si terminal
-> FileEventCoalescer si fichier coalescible
-> EventBus
-> RuntimeOrchestrator.handle_event()
-> SessionMemory / RuntimeState / SignalScorer
```

Elle ne doit pas interpréter profondément. Son rôle est de recevoir, nettoyer, filtrer, qualifier assez pour que les couches R3-R6 puissent travailler sans avaler du bruit.

## Responsabilité par fichier

| Fichier | Rôle réel | Commentaire |
|---|---|---|
| `daemon/core/events.py` | Introuvable | Le fichier demandé n’existe pas dans le repo actuel. Le modèle d’événement réel est dans `event_bus.py`. |
| `daemon/core/event_bus.py` | Bus mémoire thread-safe | Stocke les derniers events dans une `deque`, notifie les subscribers, isole les erreurs d’abonnés. |
| `daemon/core/event_meaning.py` | Politique de publication / bruit / scoring | Décide `publish_to_bus`, `runtime_relevant`, `scoring_relevant`, `file_significance`, `noise_policy`, coalescing et sanitation. |
| `daemon/core/file_classifier.py` | Classification type fichier | Classe `source`, `test`, `config`, `docs`, `assets`, `other`; délègue la significance à `event_meaning`. |
| `daemon/core/event_actor_classifier.py` | Introuvable | Le fichier réel est `daemon/core/event_actor.py`. |
| `daemon/core/event_actor.py` | Attribution acteur fichier | Infère `user`, `system`, `tool_assisted`, `unknown` avec confidence / automation score. |
| `daemon/platform/idle_heartbeat.py` | Heartbeat présence utilisateur | Publie `user_presence` depuis idle probe, sans créer de travail par lui-même. |
| `daemon/routes/runtime_ingestion.py` | Entrée `/event` | Normalise terminal, filtre pause / lock / bruit, attribue acteur fichier, publie via coalescer. |

## Chemin complet d’un événement

1. Swift ou un producteur local poste vers `/event`.
2. `runtime_ingestion.receive_event()` lit JSON, `type`, timestamp et payload.
3. Si runtime en pause : réponse `{"ok": true, "paused": true, "ignored": true}`.
4. Si app event : mise à jour de `RuntimeState.latest_active_app`.
5. Si terminal event : transformation vers payload normalisé.
6. Si écran verrouillé : seuls `screen_locked` / `screen_unlocked` passent.
7. `EventMeaningPolicy.classify()` nettoie et décide publication.
8. Si fichier : `EventActorClassifier` ajoute `_actor`, `_actor_confidence`, `_automation_score`, `_noise_policy`.
9. `FileEventCoalescer` retarde / fusionne certains bursts fichiers.
10. `EventBus.publish()` stocke et notifie.
11. `RuntimeOrchestrator.handle_event()` applique session, state, mémoire minimale.
12. `SignalScorer` relit les events récents depuis l’EventBus pour produire `Signals`.

Ce flux reste passif : il observe et publie, il n’agit pas.

## Événements bruts vs qualifiés vs meaningful

Événement brut :

- JSON reçu par `/event` ;
- peut contenir `command`, `raw`, `content`, chemin complet, titre fenêtre, etc.

Événement nettoyé / normalisé :

- terminal : `terminal_command`, `terminal_command_base`, `terminal_action_category`, `terminal_success`, `test_result` ;
- clipboard : `content` supprimé, `content_kind` conservé ;
- terminal raw `command` / `raw` supprimés par `EventMeaningPolicy` avant bus si non normalisés.

Événement qualifié :

- via `EventMeaningPolicy` : `file_significance`, `noise_policy`, pertinence runtime / scoring ;
- via `EventActorClassifier` : `_actor`, confidence, automation score ;
- via `observation_qualification.py` : contrat passif, non source runtime principale aujourd’hui.

`meaningful` :

- source / test / config / docs / assets de projet ;
- peut influencer runtime / scoring ;
- peut ancrer projet / fichier.

`technical_noise` :

- `.pulse`, `.git` hors `COMMIT_EDITMSG`, caches, venv, site-packages, DB, logs, UUID, private var, system libs ;
- généralement non publié.

`observe_only` :

- screenshots ;
- visible comme observation, pas preuve de travail.

`neutral` :

- lockfiles, Downloads, CSV, plist génériques ;
- souvent non publié au bus, mais classé plus prudemment que bruit technique.

## Filtrage / minimisation

Filtrage au bon endroit : oui, globalement.

- `/event` applique pause / lock avant bus.
- `EventMeaningPolicy` filtre bruit fichier.
- `EventActorClassifier` n’intervient qu’après décision de publication.
- `SignalScorer` refiltre via policy pour ne pas compter le bruit.

Minimisation correcte :

- `clipboard_updated.content` est retiré ;
- terminal `command` / `raw` sont retirés par la policy, puis remplacés par une forme normalisée quand l’ingestion terminal passe ;
- `.pulse` est filtré ;
- caches et `site-packages` sont filtrés ;
- screenshots sont observe-only ;
- lockfiles sont downrank / neutral.

Fragilité : les commandes terminal normalisées restent sensibles. Ce n’est pas du contenu brut complet, mais cela peut inclure secrets si l’utilisateur tape une commande contenant un token.

## Lock / unlock / user_presence / idle

`screen_locked` / `screen_unlocked` :

- passent toujours, même pendant lock ;
- ne sont pas `runtime_relevant` dans `EventMeaningPolicy`, mais sont traités explicitement par `RuntimeOrchestrator` ;
- mettent à jour `SessionFSM` et `RuntimeState` ;
- servent de signal lifecycle, pas d’activité projet.

Pendant lock :

- `/event` bloque tout sauf lock / unlock ;
- `RuntimeOrchestrator` refiltre aussi ;
- `IdlePresenceHeartbeat` ne publie pas si `is_locked()` est vrai ;
- si le callback lock échoue, heartbeat fail-closed et ne publie rien.

`user_presence` :

- publié par heartbeat Python ;
- peut aussi venir d’autres producteurs ;
- influence activity / focus comme signal support ;
- ne doit pas créer de work block seul ;
- tests présents pour garantir que ce n’est pas une preuve de travail.

Il existe un doublon potentiel Swift / Python autour présence / idle : Swift peut envoyer `user_idle` / `user_active`, Python heartbeat publie `user_presence`. Le scorer accepte les deux familles. C’est acceptable, mais cela peut bruiter les surfaces brutes.

## Classification des acteurs

Acteurs :

- `user` ;
- `system` ;
- `tool_assisted` ;
- `unknown`.

L’attribution s’applique aux événements fichier dans `/event`.

Règles principales :

- prior utilisateur de base ;
- chemins système => `system` ;
- répétitions rapides même fichier => `system` ;
- lockfiles / dépendances => tendance `tool_assisted` ;
- bursts rapides multi-fichiers => tendance `tool_assisted` ;
- app outil / IA active => tendance `tool_assisted` ;
- chemins système court-circuitent comme système.

Point important : `tool_assisted` peut encore ancrer projet / fichier, mais `SignalScorer` l’empêche d’inflater `edited_file_count_10m`. C’est la bonne séparation.

## Thread-safety / EventBus

`EventBus` :

- utilise une `deque(maxlen=500)` par défaut ;
- protège queue avec un lock ;
- `recent()` et `recent_of_type()` prennent le lock ;
- les subscribers sont appelés hors lock ;
- erreur subscriber isolée avec `print`.

Limites :

- la liste `_subscribers` n’est pas protégée par lock lors de `subscribe` ;
- les subscribers peuvent voir des événements pendant mutation externe du payload si un producteur réutilise le dict ;
- `Event.payload` est mutable ;
- queue mémoire uniquement, pas durable ;
- pas de backpressure ;
- pas d’ID d’événement.

Pour Core local-first, c’est acceptable.

## Hardcoding identifié

Hardcoding important mais assumé :

- types fichier : `file_created`, `file_modified`, `file_renamed`, `file_deleted`, `file_change` ;
- types terminal ;
- lock passthrough ;
- noms de lockfiles ;
- extensions screenshots ;
- patterns screenshots FR / EN ;
- segments path bruit : `.git`, `node_modules`, `__pycache__`, `site-packages`, `.venv`, `.cache`, `.codex`, Homebrew, `/private/var`, `/System/Library` ;
- coalescing file event : `1.0s` ;
- dedupe policy : `cleanup_ttl=5s`, `dedupe_window=1s` ;
- actor burst : 4 fichiers en 600 ms ;
- repeat : 3 répétitions en 30 s ;
- idle heartbeat : 30 s, idle threshold 300 s.

Ces filtres sont hardcodés mais acceptables maintenant parce qu’ils sont locaux, testés et lisibles. Ne pas les transformer en système dynamique avant retour terrain.

## Sources de vérité

Sources actuelles :

- `EventBus` : vérité mémoire des événements récents publiés.
- `EventMeaningPolicy` : vérité de publish / runtime / scoring / noise pour les fichiers.
- `file_classifier` : vérité de type fichier.
- `EventActorClassifier` : vérité d’attribution acteur fichier.
- `runtime_ingestion` : vérité d’entrée `/event`.
- `IdlePresenceHeartbeat` : source Python de `user_presence`.
- `RuntimeState` : état lock / pause / latest app utilisé pour filtrage et actor attribution.
- `RuntimeOrchestrator` : vérité de l’effet runtime / session après publication.

`observation_qualification.py` est un contrat passif utile, mais son docstring dit explicitement qu’il n’est pas encore câblé comme source de comportement runtime.

## Données sensibles

Données sensibles qui peuvent traverser la couche :

- chemins complets ;
- noms de fichiers ;
- titres de fenêtre ;
- app bundle IDs ;
- terminal command normalisée ;
- cwd ;
- git context ;
- test output summary / output summary ;
- clipboard metadata ;
- MCP command metadata ;
- source idle / présence.

La minimisation est bonne sur clipboard et raw terminal, mais le Core expose encore des données brutes-ish dans `/events/debug`, `/insights`, `/state.signals`, `/feed` partiel et mémoire session.

Ce n’est pas bloquant pour local-first, mais il faut continuer à l’afficher comme diagnostic local, pas produit cloud-safe.

## Frontières Core / Lab

Core :

- `/event` ;
- `EventBus` ;
- `EventMeaningPolicy` ;
- file classifier ;
- actor classifier ;
- terminal normalization ;
- idle heartbeat ;
- lock / unlock filtering.

Lab / debug proche mais non Core produit :

- `context_probe_executed` ;
- `llm_loading` ;
- `llm_ready` ;
- `resume_card` ;
- MCP comme signal d’outil ;
- `local_exploration` ;
- `event_envelope.py`, qui reste passif et non branché globalement.

Observation reste passive. Elle ne déclenche pas d’action autonome. Les risques viennent des consommateurs, pas de cette couche elle-même.

## Legacy restant

Legacy / dette visible :

- `daemon/core/events.py` absent alors que le nom existe encore dans la tête / doc utilisateur ;
- `event_actor_classifier.py` absent, remplacé par `event_actor.py` ;
- payload legacy dict, pas envelope typée ;
- `observation_qualification.py` décrit un contrat mais n’est pas source runtime principale ;
- `EventMeaningPolicy` et `file_classifier` dupliquent certains patterns screenshot / UUID / `.pulse` ;
- `EventMeaningPolicy._default_policy` singleton utilisé directement par plusieurs modules ;
- `EventBus` utilise des payloads mutables ;
- événements inconnus non-fichier passent par défaut ;
- `print` pour erreurs subscriber, pas logger structuré.

## Tests existants

Couverture solide :

- `tests/test_observation_ingestion_golden.py` ;
- `tests/core/test_event_meaning.py` ;
- `tests/core/test_file_classifier.py` ;
- `tests/core/test_event_actor.py` ;
- `tests/core/test_event_bus.py` ;
- `tests/platform/test_idle_probe.py` ;
- `tests/test_bus_filter.py` ;
- `tests/core/test_observation_qualification.py` ;
- `tests/core/test_observation_qualification_consistency.py`.

Les tests R2 sont sérieux : golden ingestion, bruit, actor, terminal, feed readability, lock / presence.

## Tests manquants

Tests utiles plus tard :

- `/event` avec type inconnu non-fichier : vérifier explicitement la permissivité actuelle ;
- payload non-dict ou JSON invalide ;
- mutation payload après `bus.publish` ;
- thread-safety subscribe / publish concurrent ;
- event coalescer avec actor attribution conservée sur priorité gagnante ;
- coalescing screenshots FR / EN avec unicode variants côté coalescer et policy ;
- duplication Swift `user_idle` + Python `user_presence` ;
- terminal command contenant secret : vérifier au moins que `raw` disparaît partout ;
- MCP events dans `/event` vs routes MCP directes ;
- `EventMeaningPolicy` singleton state cleanup ;
- test que `observation_qualification` reste passif et non utilisé comme runtime source.

## Dette acceptable

Acceptable maintenant :

- filtres hardcodés ;
- payload dict legacy ;
- EventBus mémoire ;
- queue size 500 ;
- actor classifier heuristique ;
- singleton `_default_policy` ;
- événements non-fichier généralement publiés ;
- duplication partielle entre `file_classifier` et `event_meaning` ;
- heartbeat présence Python en plus de possibles events Swift.

Cette couche fait son travail Core : observer sans prétendre comprendre.

## Dette à corriger plus tard

À corriger après dogfooding :

- introduire une envelope typée uniquement si le besoin est prouvé ;
- unifier les patterns de classification fichier entre `event_meaning` et `file_classifier` ;
- décider quoi faire des événements inconnus ;
- rendre les erreurs EventBus loggées proprement ;
- rendre payloads immutables ou copier défensivement dans `EventBus` ;
- clarifier source Swift vs Python pour présence ;
- réduire l’exposition brute dans surfaces debug accessibles à l’UI ;
- rendre `observation_qualification` soit réellement source de contrat, soit strictement doc / test-only ;
- supprimer les vieux noms mentaux `events.py` / `event_actor_classifier.py` dans docs si encore présents.

## Ce qu’il ne faut pas modifier maintenant

- Ne pas brancher `event_envelope.py` globalement maintenant.
- Ne pas rendre l’observation intelligente.
- Ne pas ajouter apprentissage, facts, vector store, LLM ou DayDream.
- Ne pas faire de `user_presence` une preuve de travail.
- Ne pas compter `tool_assisted` comme édition utilisateur.
- Ne pas bloquer brutalement tous les événements inconnus sans audit UI / Swift.
- Ne pas supprimer les événements debug / Lab sans vérifier les routes.
- Ne pas déplacer le filtrage bruit dans le scorer uniquement.
- Ne pas rendre le bus persistant.
- Ne pas toucher aux règles de lock / unlock sans tests session complets.
- Ne pas remplacer les heuristiques hardcodées par config dynamique prématurée.

---

# Audit groupé : Routes runtime / surfaces API

## Verdict

Les routes runtime / API sont fonctionnelles pour le Core, mais la frontière produit / debug / Lab reste imparfaite.

Les surfaces essentielles Core existent et sont testées : `/ping`, `/health/core`, `/state`, `/event`, `/feed`. Elles permettent le dogfooding.

Le problème principal : `/state` est encore trop large pour être une surface Core propre. Même sans `include_debug`, il peut exposer `signals`, `decision`, `current_context`, `session_fsm`, `recent_sessions`. C’est utile pour compatibilité Swift et debug, mais ce n’est pas une API produit nette.

Les routes Lab restent enregistrées. Plusieurs sont neutralisées en Core, mais pas toutes au même niveau : certaines sont lecture seule avec metadata Lab, certaines restent actives parce qu’elles sont debug / consent-based, et certaines peuvent encore déclencher des effets de bord si appelées explicitement.

## Rôle global des routes runtime / API

Les routes sont la frontière entre :

- observation locale (`/event`) ;
- état Core live (`/state`, `/health/core`, `/ping`) ;
- feed UI notable (`/feed`) ;
- debug local (`/debug/state`, `/insights`, `/events/debug`, `/work-context`) ;
- mémoire minimale / historique (`/memory/sessions`, `/search`) ;
- surfaces Lab / legacy encore visibles (`/memory`, `/facts`, `/daydreams`, `/context-probes`, `/work-intent`, `/llm/lightweight`, resume cards).

La couche routes ne doit pas devenir une couche d’intelligence. Elle agrège, expose, marque ou bloque.

## Responsabilité par fichier

| Fichier | Rôle réel | Statut |
|---|---|---|
| `daemon/routes/runtime.py` | Agrégateur de routes runtime | Critique, mais enregistre Core + debug + Lab ensemble. |
| `daemon/routes/runtime_ingestion.py` | `/event`, normalisation terminal, filtrage pause / lock / bruit | Core stable. |
| `daemon/routes/runtime_feed_routes.py` | `/feed`, `/observation`, `/today_summary`, `/daydreams` | Mix Core / debug / Lab. |
| `daemon/routes/runtime_status_routes.py` | `/ping`, `/health/core`, `/state`, `/debug/state`, `/insights` | Core + debug brut. |
| `daemon/routes/runtime_state_payloads.py` | Construction payload `/state` et `/debug/state` | Critique, frontière produit / debug encore floue. |
| `daemon/routes/memory.py` | mémoire list / write / remove / session / search | Mix historique Core + Lab mémoire avancée. |
| `daemon/routes/facts.py` | facts / profile / mutations | Lab, mutations gatées en Core. |
| `daemon/routes/mcp.py` | MCP pending / intercept / decision / proposals | Core R6 contrôlé, mais expose commandes sensibles. |
| `daemon/routes/runtime_debug_routes.py` | events debug, timeline preview, work-context | Debug local, plutôt bien marqué. |
| `daemon/routes/debug_memory.py` | work episodes, journal candidates, commit links | Debug mémoire, hors Core strict produit. |
| `daemon/routes/runtime_probe_routes.py` | context probes lifecycle | Lab / debug, encore enregistré. |
| `daemon/routes/work_intent_routes.py` | work intent candidates | Lab / future, peut modifier `RuntimeState.work_intent`. |
| `daemon/routes/lightweight_llm.py` | lightweight LLM queue / result | Lab, correctement neutralisé en Core. |
| `daemon/routes/runtime_resume_card_routes.py` | debug resume card generation | Debug / Lab, peut publier `resume_card`. |
| `daemon/routes/runtime_daemon_routes.py` | pause / resume / shutdown / restart | Core dev / control, avec LLM warmup gated par policy. |

## Surfaces Core stables

Surfaces Core raisonnablement stables :

- `/ping` ;
- `/health/core` ;
- `/state` ;
- `/event` ;
- `/feed` ;
- `/daemon/pause` ;
- `/daemon/resume` ;
- `/search` comme recherche events SQLite minimale ;
- `/memory/sessions` comme lecture historique Markdown, non canonique.

`/event` est bien défensif : pause, lock, filtrage, normalisation terminal, actor attribution, coalescing.

`/health/core` est sobre et ne dépend pas de DayDream, facts, embeddings, vector store ou LLM.

## Surfaces debug

Surfaces debug nettes :

- `/debug/state` ;
- `/events/debug` ;
- `/events/schema` ;
- `/timeline/preview` ;
- `/timeline/schema` ;
- `/work-context` ;
- `/debug/work-episodes` ;
- `/debug/journal-candidates` ;
- `/debug/journal-comparison` ;
- `/debug/commit-episode-links` ;
- `/debug/resume-card` ;
- `/debug/resume-card/llm`.

`/events/debug` est mieux conçu que `/insights` : il expose metadata, privacy, retention et payload keys, sans valeurs raw.

`/insights` est plus risqué : il retourne les payloads récents bruts.

## Surfaces Lab / legacy

Lab / legacy visibles :

- `/memory` ;
- `/memory/write` ;
- `/memory/remove` ;
- `/memory/usage` ;
- `/facts` ;
- `/facts/stats` ;
- `/facts/profile` ;
- `/facts/<id>/reinforce` ;
- `/facts/<id>/contradict` ;
- `/facts/<id>/archive` ;
- `/daydreams` ;
- `/context-probes/*` ;
- `/work-intent/*` ;
- `/llm/lightweight/*` ;
- `/debug/resume-card/llm`.

Gating inégal :

- `memory/write/remove` : bloqués en Core ;
- `facts/profile` : retourne profil vide en Core ;
- facts mutations : bloquées en Core ;
- lightweight LLM pending/result : neutralisé en Core ;
- context probes : pas globalement gated par `PULSE_MODE`, mais consent / lifecycle-based ;
- work intent : pas gated, peut modifier runtime state si candidat existant ;
- `/daydreams` : lecture de fichiers DayDream encore exposée, non bloquante mais Lab visible.

## `/state` : structure et risques

`/state` expose :

- top-level aliases : `active_app`, `active_file`, `active_project`, `session_duration_min`, `last_event_type`, `runtime_paused` ;
- `pulse_mode`, `experimental_enabled` ;
- `present` ;
- et, selon runtime / callbacks : `decision`, `session_fsm`, `current_context`, `signals`, `recent_sessions`.

Risque : même sans `include_debug`, `build_debug_state_payload()` enrichit `product_state` avec des champs legacy / debug. Le test le documente explicitement : `signals` est exposé par défaut.

Risques concrets :

- `present.probable_task` sans `task_confidence` ;
- `signals.task_confidence` ailleurs dans le même payload ;
- `current_context` peut avoir une temporalité différente ;
- `recent_sessions` vient de persistance historique ;
- `session_fsm` est runtime live ;
- top-level aliases dupliquent `present` ;
- `terminal_command`, `terminal_cwd`, `window_title` peuvent apparaître via `signals/current_context`.

Donc `/state` est encore trop large pour une surface Core stable propre. Le réduire brutalement casserait Swift et les tests.

## `/feed` : rôle réel

`/feed` n’est pas un journal complet.

Rôle réel :

- sélection d’événements notables pour UI ;
- principalement terminal commands finies avec succès / échec ;
- quelques événements internes : `llm_loading`, `llm_ready`, `resume_card` ;
- labels raccourcis pour pytest / build / git / setup.

Il ignore volontairement :

- la plupart des fichiers ;
- lock / unlock ;
- user_presence ;
- app activations ;
- bruit technique.

Il doit rester une sélection notable, pas devenir un journal exhaustif. Le journal brut existe déjà via `/insights` ou `/events/debug`.

## `/health/core` : garanties et limites

Garanties réelles :

- daemon répond ;
- runtime state présent ;
- EventBus / feed source présent ;
- scoring marqué disponible ;
- session FSM présent ou `not_checked` ;
- mode runtime exposé ;
- Lab non requis en Core ;
- ne touche pas DayDream / facts / embeddings / vector store.

Limites :

- ne prouve pas que `/event` publie réellement ;
- ne prouve pas que `SignalScorer.compute()` fonctionne ;
- ne prouve pas `SessionMemory` ;
- ne vérifie pas SQLite ;
- ne vérifie pas le dashboard Swift ;
- `scoring: "available"` est déclaratif ;
- `session_fsm: "not_checked"` possible selon injection.

C’est une santé minimale, pas un diagnostic complet.

## `/debug/state` / `/insights` : exposition brute

`/debug/state` est clairement marqué :

- `surface: "debug_state"` ;
- `legacy_in_state` ;
- `runtime` ;
- `signals` ;
- `current_context` ;
- `recent_sessions`.

C’est suffisamment marqué debug.

`/insights` est moins sûr :

- retourne `event.payload` brut ;
- peut contenir terminal commands, cwd, git context, window titles, chemins privés ;
- limite 100 ;
- utile au dashboard / onglet événements, mais brut-ish.

Pour UI produit, `/events/debug` est plus sain que `/insights`.

## Gates Core / Lab

Routes Lab encore enregistrées : oui.

Neutralisation Core :

- bonne pour `memory/write/remove` ;
- bonne pour facts mutations ;
- bonne pour facts profile rendu ;
- bonne pour lightweight LLM claim/result ;
- partielle pour memory list/usage, qui appellent encore `memory_store` mais marquent Lab metadata ;
- inexistante ou non uniforme pour context probes / work intent / debug resume card.

Effets de bord encore possibles en Core si appel explicite :

- `/context-probes/requests` crée une demande ;
- approve / refuse / execute modifient le store probes ;
- execute peut publier `context_probe_executed` ;
- work intent accept peut modifier `RuntimeState.work_intent` ;
- debug resume-card peut publier `resume_card` ;
- `/daemon/resume` peut publier LLM loading / ready si policy heavy LLM l’autorise.

Ce sont des surfaces debug / Lab locales, pas chemin Core automatique. Mais elles restent actives.

## Hardcoding identifié

Hardcoding :

- noms de routes ;
- version `/ping`: `0.1.0` ;
- `/health/core` checks sous forme string ;
- `/insights` limite 25, clamp 100 ;
- `/events/debug` limite 50, clamp 200 ;
- `/feed` lit 200 events ;
- labels feed en français ;
- generic labels filtrés ;
- `/memory/sessions` limite 7, clamp 30 ;
- `/search` limite 20, clamp 100 ;
- facts limit 20, clamp 100 ;
- DayDream lit `~/.pulse/memory/daydreams` ;
- routes debug / probes / work-intent toujours enregistrées par `register_runtime_routes()`.

Acceptable pour hardening, mais pas propre pour API contract long terme.

## Données sensibles exposées

Exposées ou potentiellement exposées :

- chemins complets ;
- terminal command ;
- terminal cwd ;
- git context ;
- window title ;
- app bundle IDs ;
- recent apps ;
- MCP commands ;
- memory entries ;
- facts ;
- session Markdown ;
- hidden payload si `include_hidden=true` ;
- raw event payloads via `/insights` ;
- resume card payload ;
- context probe results.

Les surfaces sont locales, mais ce n’est pas une API “safe by default” partout.

## Compatibilité Swift

Champs probablement difficiles à supprimer brutalement :

- `/ping.status`, `/ping.paused` ;
- `/state.active_app` ;
- `/state.active_file` ;
- `/state.active_project` ;
- `/state.session_duration_min` ;
- `/state.runtime_paused` ;
- `/state.present` ;
- `/state.signals` ;
- `/state.current_context` ;
- `/state.recent_sessions` ;
- `/feed.kind`, `label`, `success`, `command`, `timestamp` ;
- `/insights` raw events pour onglet Événements ;
- `/today_summary` ;
- `/memory/sessions` ;
- `/daydreams` si onglet Lab visible ;
- `/mcp/pending`, `/mcp/proposals`.

Tout nettoyage doit être additif ou documenté, pas destructif.

## Tests existants

Tests utiles :

- `tests/test_runtime_routes.py` ;
- `tests/routes/test_runtime_state_payloads.py` ;
- `tests/test_main_runtime_state.py` ;
- `tests/test_observation_ingestion_golden.py` ;
- `tests/test_main_memory_routes.py` ;
- `tests/test_facts_routes.py` ;
- `tests/test_main_mcp_routes.py` ;
- `tests/mcp/test_handlers_proposals.py` ;
- `tests/test_lightweight_llm_routes.py` ;
- tests context probe / work intent ;
- tests debug events / schema / feed readability.

La couverture est bonne sur Core + beaucoup de boundaries.

## Tests manquants

Manques utiles :

- test inventaire global des routes Core / debug / Lab enregistrées ;
- test que `/state` n’ajoute pas de nouveaux champs sensibles sans accord ;
- test que `/insights` est explicitement debug/raw dans un metadata ou doc contract ;
- test `/daydreams` marqué Lab en Core ;
- test context probes Core mode : statut Lab / debug explicite ;
- test work-intent Core mode : statut Lab / debug explicite ou absence d’effet sans candidat ;
- test `/memory` list / usage metadata Lab et absence de mutation ;
- test facts list / stats en Core : metadata Lab + pas de profile rendering ;
- test `/daemon/resume` n’émet pas LLM events en Core si policy désactivée ;
- test Swift contract minimal sur labels / champs consommés, si côté Swift.

## Dette acceptable

Acceptable maintenant :

- routes Lab enregistrées mais non appelées automatiquement ;
- `/state` large pour compatibilité ;
- `/feed` sélection notable, pas journal complet ;
- `/insights` brut pour dashboard local ;
- `/events/debug` comme meilleure surface debug future ;
- memory sessions Markdown legacy ;
- facts routes lisibles mais marquées Lab ;
- MCP Core R6 conservé comme flux contrôlé.

## Dette à corriger plus tard

À corriger après dogfooding :

- définir `/state/core` ou réduire progressivement `/state` ;
- déplacer les champs legacy vers `/debug/state` ;
- remplacer l’usage UI de `/insights` par `/events/debug` ou une surface events filtrée ;
- marquer `/daydreams`, context probes, work intent et resume-card comme Lab dans payload ;
- auditer toutes les routes enregistrées par `register_runtime_routes()` avec une table Core / debug / Lab ;
- ajouter metadata `surface`, `lab_only`, `debug_only` partout où nécessaire ;
- clarifier `memory.py` entre historique Core et mémoire avancée Lab ;
- éviter `get_fact_engine()` sur routes facts read en Core si coût / side effects réels ;
- documenter les champs Swift consommés.

## Ce qu’il ne faut pas modifier maintenant

- Ne pas supprimer `/state.signals` brutalement.
- Ne pas supprimer `/insights` avant migration Swift.
- Ne pas transformer `/feed` en journal complet.
- Ne pas désenregistrer toutes les routes Lab d’un coup.
- Ne pas casser `/mcp/*`, qui est le flux Core R6 validé.
- Ne pas rendre `/health/core` dépendant de LLM, facts, vector store ou DayDream.
- Ne pas déplacer memory sessions vers MemoryStore.
- Ne pas exposer facts / profile comme Core.
- Ne pas activer context probes / work intent comme produit.
- Ne pas ajouter auth / refactor global maintenant.
- Ne pas démarrer R7 ou apprentissage.

---

# Audit groupé : Swift runtime / Dashboard surfaces

## Verdict

La couche Swift est utilisable pour le dogfooding, mais ce n’est pas une UI Core pure. C’est un cockpit interne qui mélange Core, debug, Lab et legacy.

Les récents libellés “Lab”, “debug”, “Lecture courante”, “Activité récente” réduisent la confusion, mais le couplage réel reste large : le Dashboard consomme encore facts, mémoire, DayDream, LLM, context probes, work intent, debug episodes et `/insights`.

Point le plus important : le backend Core R1-R6 est plus strict que l’UI. Swift ne casse pas le Core, mais il peut encore le présenter comme plus intelligent, plus agentique ou plus dépendant du LLM qu’il ne l’est réellement.

## Rôle global Swift runtime / Dashboard

La couche Swift fait trois choses :

- surveiller le daemon local et piloter start / stop / restart ;
- consommer les surfaces daemon pour alimenter Notch + Dashboard ;
- exposer à l’utilisateur un mélange de lecture live, historique, debug, Lab et contrôle MCP.

Elle n’est pas seulement une UI Core. Elle reste aussi une console de laboratoire.

## Responsabilité par fichier

| Fichier | Rôle | Risque |
|---|---|---|
| `App/App/DaemonBridge.swift` | Client HTTP bas niveau vers `127.0.0.1:8765` | Base URL hardcodée, pas de notion Core / Lab. |
| `App/App/DaemonBridge+CoreAPI.swift` | Bindings API daemon | Mélange Core, debug, Lab, LLM, facts, DayDream, probes. |
| `App/App/DaemonBridgeModels.swift` | Décodage JSON + labels UI | Beaucoup de champs legacy / Lab ; `StateResponse` ne décode pas `pulse_mode` / `experimental_enabled`. |
| `App/App/DashboardViewModel.swift` | Agrégateur Dashboard + polling | Charge beaucoup de surfaces Lab / debug en slow refresh. |
| `App/App/DashboardRootView.swift` | UI Dashboard complète | Libellés mieux clarifiés, mais Lab encore très visible. |
| `App/App/CurrentStateContentView.swift` | Panneau Notch “lecture courante” | Présente des hypothèses live de façon plus prudente qu’avant, mais reste synthétique. |
| `App/App/PulseViewModel+Runtime.swift` | Polling Notch runtime | Polling agressif, dépend encore de LLM / probes / MCP / feed. |
| `App/App/DaemonController.swift` | Cycle start / stop / restart daemon | Patch récent cohérent : ne marque plus stopped si `/ping` répond encore. |

## Flux de données daemon -> Swift

Surfaces Core consommées :

- `/ping` : daemon reachable, pause ;
- `/state` : présent, current context, signals, recent sessions ;
- `/feed` : événements notables pour notifications ;
- `/event` : envoi d’événements Swift vers daemon ;
- `/scoring/status` : statut scoring, Dashboard système.

Surface Core historiquement non consommée au moment de l’audit C1 :

- `/health/core` existait côté backend, mais Swift ne semblait pas l’utiliser. L’UI continuait à dériver la santé via `/ping`, état daemon et disponibilité LLM.

Note C2.1 : ce point a été corrigé. Swift consomme désormais `/health/core` pour distinguer santé Core et disponibilité LLM. Un Core sain ne doit plus apparaître dégradé seulement parce que le LLM est indisponible.

Surfaces debug / raw :

- `/insights` pour l’onglet Événements et le Notch insight ;
- `/debug/work-episodes` ;
- `/debug/commit-episode-links` ;
- `/work-context`.

Surfaces Lab visibles :

- `/daydreams` ;
- facts / profile / stats / archive ;
- `/memory` ;
- context probes ;
- work intent candidates ;
- LLM models / status / lightweight ;
- MCP proposals.

## Notch vs Dashboard

Le Notch est plus sensible que le Dashboard parce qu’il est toujours présent.

Il poll :

- `/ping` toutes les 0,5 s ;
- `/feed` toutes les 0,5 s ;
- `/mcp/pending` toutes les 0,5 s ;
- `/state` environ toutes les 3 s ;
- `/insights` + `/mcp/proposals` si panneau insight / currentState ouvert ;
- LLM models périodiquement.

Problème observé au moment de l’audit C1 : le Notch traitait encore `LLM indisponible` comme état dégradé global. En Core, LLM n’est pas requis. Cette dette UX pouvait faire croire que Pulse Core dépendait du LLM.

Note C2.1 : ce point a été corrigé côté Swift. L’indisponibilité LLM reste visible comme capacité LLM / Lab, mais ne dégrade plus l’état Core global si `/health/core.status == "ok"`.

Le Dashboard est plus explicitement interne. Il est acceptable pour dogfooding, mais pas comme surface produit Core propre.

## Core / debug / Lab dans l’UI

Ce qui est bien :

- `Mémoire (Lab)`, `DayDream (Lab)`, `Contexte (Lab)` sont marqués ;
- `Séquences debug` et “Reconstruction debug…” sont clairs ;
- `Lecture courante`, `Hypothèse live`, `Tâche principale`, `Activité récente`, `Confiance tâche` sont meilleurs que les anciens labels.

Ce qui reste fragile :

- `MCP` n’est pas clairement nommé comme “MCP contrôlé” ou “validation commande” ;
- Work intent peut apparaître dans `Aujourd’hui`, donc une surface Lab fuit dans une surface Core.

Note C2.2 : les textes Mémoire / DayDream / `context_injection` ont été corrigés. Les formulations qui présentaient profil LLM, mémoire figée, injection LLM ou DayDream automatique comme des comportements Core stables ont été remplacées par des libellés Lab / debug, non requis par le Core.

## Temporalités affichées

Temporalités actuellement mélangées mais mieux nommées :

- live : `/state.present`, `session_fsm`, `current_context` ;
- interprétation courante : `/state.current_context` ;
- explication reconstruite : `/work-context` ;
- feed notable : `/feed` ;
- événements raw-ish : `/insights` ;
- journée : `/today_summary` ;
- historique : `/state.recent_sessions`, `/memory/sessions` ;
- debug : work episodes / commit links ;
- Lab : memory, facts, DayDream, probes, work intent, LLM.

Le patch UI récent améliore la lisibilité, mais la séparation reste conventionnelle, pas structurelle. L’UI ne s’appuie pas encore sur `pulse_mode` pour masquer ou annoter automatiquement les surfaces.

## Risques d’overclaim

Risques encore présents :

- `probable_task` est affiché comme titre principal dans plusieurs endroits ;
- `active_project` peut paraître confirmé alors qu’il vient parfois d’un contexte faible ;
- le Notch privilégie `currentContext` avant `present`, ce qui peut donner une impression d’interprétation plus forte ;
- `Confiance tâche` est affichée sans toujours rappeler la source exacte ;
- les blocs du jour et séquences debug peuvent être lus comme des sessions Core alors qu’ils agrègent différemment ;
- `session_duration` est lisible, mais l’utilisateur peut confondre durée live, bloc du jour, session persistée et séquence reconstruite.

Le niveau est acceptable pour usage interne, pas pour une UI publique.

## Données sensibles affichées

Exposition sensible confirmée :

- titres de fenêtres dans Observation ;
- commandes terminal récentes ;
- chemins / fichiers, même si souvent réduits au basename ;
- app names et bundle IDs dans diagnostics AX ;
- textes capturés / redacted via context probes ;
- MCP commands ;
- facts / profile / memory en Lab ;
- journaux de session.

C’est cohérent avec une app locale-first de diagnostic, mais il faut continuer à traiter le Dashboard comme surface locale / debug, pas comme UI produit externe.

## Robustesse polling / parsing / daemon down

Points solides :

- beaucoup d’appels utilisent `try?`, donc l’UI ne tombe pas brutalement si une route manque ;
- `DaemonController.waitForStop()` est maintenant cohérent : timeout + `/ping` encore vivant => reste `.running` avec erreur ;
- le Dashboard tolère plusieurs payloads absents.

Points fragiles :

- Notch poll très fréquent : `/ping`, `/feed`, `/mcp/pending` toutes les 0,5 s ;
- point C1 corrigé en C2.1 : `/health/core` est maintenant utilisé côté Swift pour distinguer Core OK et indisponibilité LLM / Lab ;
- les erreurs réseau sont souvent silencieuses ;
- si le daemon est down, certaines zones gardent potentiellement le dernier état connu sans signal visuel très fort ;
- `DaemonBridge` imprime du JSON brut sur erreur de décodage MCP, potentiellement sensible.

## Couplage Swift ↔ API

Champs backend difficiles à supprimer sans casser Swift :

- `/state.present` ;
- `/state.current_context` ;
- `/state.signals` ;
- `/state.session_fsm` ;
- `/state.recent_sessions` ;
- top-level `active_app`, `active_file`, `active_project`, `session_duration_min`, `runtime_paused` ;
- `/feed` payload `kind`, `label`, `timestamp`, `command`, `resume_card` ;
- `/insights` type / timestamp / payload simple ;
- `/mcp/pending`, `/mcp/proposals` ;
- `/memory/sessions` ;
- `/today_summary`.

Dette claire : `StateResponse` ne décode pas `pulse_mode` / `experimental_enabled`. Les labels Lab sont donc hardcodés côté UI, pas pilotés par le runtime mode.

## Hardcoding identifié

- Base daemon : `http://127.0.0.1:8765` ;
- poll Notch : 0,5 s ;
- refresh `/state` Notch : environ 3 s ;
- Dashboard refresh : 10 s, slow refresh environ 60 s ;
- LaunchAgent label : `cafe.pulse.daemon` ;
- chemins dev script : `~/Projets/Pulse/Pulse/scripts/start_pulse_daemon.sh`, etc. ;
- labels FR hardcodés ;
- catégories de tâches, activités, focus et confidence hardcodées côté Swift ;
- filtrage événementiel `/insights` dupliqué côté Swift pour fichiers techniques ;
- onglets Lab / debug hardcodés, non dérivés de `PULSE_MODE`.

## Tests existants

Tests Swift pertinents :

- `AppTests/DaemonControllerTests.swift` ;
- `AppTests/PulseViewModelInteractionsTests.swift` ;
- `AppTests/DaemonBridgeLLMTests.swift` ;
- `AppTests/AccessibilityContextProbeServiceTests.swift`.

Couverture utile déjà présente :

- `DaemonController` stop / restart timeout ;
- décodage `StateResponse` ;
- labels events `screen_locked`, `screen_unlocked`, `user_presence` ;
- labels sections Dashboard, dont `Séquences debug` et `Contexte (Lab)` ;
- modèles work context, signals, proposals, work intent ;
- context probes.

## Tests manquants

Manques principaux :

- fait en C2.1 : test que l’état Core ne devient pas “dégradé” seulement parce que LLM est indisponible ;
- fait / renforcé en C2.3 : test que les surfaces Lab restent clairement marquées dans les labels principaux ;
- fait en C2.2 : test que DayDream / Mémoire / `context_injection` ne présentent plus le Lab comme automatique ou stable Core ;
- test que work intent ne fuit pas comme Core dans `Aujourd’hui` ;
- test que `/insights` user_presence reste masqué par défaut dans l’UI ;
- test de fallback UI quand `/state` manque `current_context`, `signals` ou `present`.

## Dette acceptable

Acceptable maintenant :

- Dashboard comme outil interne de dogfooding ;
- onglets Lab visibles mais marqués ;
- `/insights` encore utilisé pour l’onglet Événements ;
- labels encore imparfaits si le Core reste en validation terrain ;
- polling local un peu bavard tant que l’impact batterie / logs est observé.

## Dette à corriger plus tard

À corriger avant une UI Core propre :

- décoder et afficher `pulse_mode` / `experimental_enabled` ;
- fait en C2.1 : utiliser `/health/core` pour santé Core au lieu de faire dépendre la santé UI du LLM ;
- réduire ou cadencer mieux le polling Notch ;
- séparer structurellement Core / debug / Lab dans le Dashboard ;
- fait en C2.2 : corriger les textes DayDream et Mémoire qui vendaient encore des comportements Lab comme naturels ;
- éviter que work intent / context probes apparaissent dans les surfaces Core ;
- remplacer progressivement `/insights` par une surface événementielle mieux bornée pour l’UI ;
- réduire l’exposition brute de commandes, titres, diagnostics AX et mémoire dans les vues non-debug.

## Ce qu’il ne faut pas modifier maintenant

- Ne pas toucher scoring.
- Ne pas toucher daemon Core.
- Ne pas toucher `SessionFSM`.
- Ne pas toucher `RuntimeState`.
- Ne pas toucher EventBus.
- Ne pas toucher routes backend.
- Ne pas toucher gates Core / Lab.
- Ne pas modifier DayDream / facts / vector / LLM pour les “améliorer”.
- Ne pas rendre work intent / context probes plus intelligents.
- Ne pas faire de gros refactor Dashboard.

Le bon angle reste Core hardening : clarifier, tester, réduire l’ambiguïté, sans relancer une phase Lab.e l’ambiguïté, documenter, migrer les surfaces brutes vers des surfaces plus sûres, et observer en usage réel avant toute reprise de R7 ou d’apprentissage.

---

# Synthèse C1 — Core Internal Audit

## Verdict global

Pulse Core est réellement stabilisé pour du dogfooding local : runtime, observation, interprétation prudente, sessions, mémoire minimale et MCP contrôlé ont des garde-fous et des tests.

Mais le Core reste entouré d’un Lab très branché : routes enregistrées, modèles Swift, mémoire avancée, DayDream, facts, LLM, probes, work intent, resume cards.

Le vrai état : Pulse est un runtime local de diagnostic de contexte de travail, pas encore un agent intelligent. Il est prêt pour usage terrain contrôlé, pas pour R7, apprentissage ou mémoire intelligente.

## Ce qui est solide

- Observation passive : `/event`, EventBus, filtrage bruit, actor classification, terminal normalization.
- `SignalScorer` : déterministe, sans LLM, anti-overclaim correct, tests golden.
- `RuntimeState` : source live saine, thread-safe, pas moteur d’intelligence.
- `SessionFSM` + `SessionMemory` : sessions testées, lock / unlock, restart repair, close reasons.
- Gates R1-R6 : DayDream / facts / sync mémoire avancée / LLM auto sont neutralisés en Core.
- MCP approval : seul flux Core de proposition contrôlée, avec validation humaine.

## Ce qui est fragile mais acceptable

- `main.py` crée le runtime au module import et avant bind Flask.
- `RuntimeOrchestrator` concentre trop de responsabilités Core + Lab.
- `/state` est trop large pour une API produit propre.
- Swift Dashboard reste une console interne Core / debug / Lab.
- `/insights` expose du raw-ish et reste consommé par l’UI.
- Les routes Lab restent enregistrées, mais globalement gatées ou marquées.
- Le Notch traite encore LLM indisponible comme dégradation globale, alors que Core n’en dépend pas.

## Risques principaux

Le risque numéro un est de recommencer à ajouter des features intelligentes sur une base encore trop mélangée.

Chaque ajout dans `RuntimeOrchestrator`, `/state` ou le Dashboard risque de brouiller Core / Lab et de vendre des hypothèses comme des vérités.

Le second risque est UX / API : Pulse peut être techniquement prudent mais apparaître trop affirmatif, notamment avec `probable_task`, `active_project`, `Confiance`, `session_duration`, work blocks et debug sequences.

## Top 5 dettes Core

1. `RuntimeOrchestrator` est un hub trop large : sessions, scoring, memory, DayDream, proposals, resume, commits.
2. `main.py` a des side effects au chargement et un ordre de boot encore fragile.
3. `/state` mélange surface produit, debug, legacy et données sensibles.
4. Swift consomme et expose trop de surfaces Lab / debug pour une UI Core.
5. Les routes Lab sont enregistrées partout ; les gates tiennent, mais la frontière reste implicite.

## Corrections prioritaires

### Patch minimal maintenant

- Faire consommer `/health/core` côté Swift pour distinguer “Core OK” de “LLM indisponible”.
- Corriger les textes UI DayDream / Mémoire qui vendent encore du Lab comme comportement normal.
- Ajouter un test Swift : Core ne doit pas apparaître dégradé si seul le LLM est indisponible.
- Ajouter un test route inventory Core / debug / Lab pour éviter les dérives silencieuses.
- Ajouter un test `/state` anti-expansion : pas de nouveau champ sensible sans décision explicite.

### Patch plus tard

- Démarrer moins de workers inutiles en Core, notamment periodic sync no-op.
- Remplacer progressivement `/insights` côté UI par `/events/debug` ou une surface filtrée.
- Décoder `pulse_mode` / `experimental_enabled` côté Swift.
- Marquer uniformément les routes Lab avec `surface`, `lab_only`, `disabled_in_core`.
- Séparer restart repair et commit recovery.

### Documentation seulement

- Documenter `/state` comme surface compat / debug large, pas API produit propre.
- Documenter que le Dashboard est un cockpit interne de dogfooding.
- Documenter que `task_confidence` est heuristique, pas probabiliste.
- Documenter que `/feed` est une sélection notable, pas un journal complet.

### À ne pas toucher

- `SessionFSM`.
- Heuristiques `SignalScorer` sans nouveaux golden tests.
- Gates Core / Lab existants.
- Routes Swift-consumed comme `/state.signals` ou `/insights` sans migration.
- Grand refactor `main.py`, `RuntimeOrchestrator` ou Dashboard maintenant.

## Tests de garde prioritaires

- Swift : Core health OK même si LLM absent.
- Routes : inventaire Core / debug / Lab enregistré.
- `/state` : pas d’ajout de champs sensibles non documentés.
- `/insights` : explicitement raw / debug ou remplacé côté UI.
- Runtime : periodic sync Core ne déclenche aucune sync avancée observable.
- Orchestrator : close_reason complet `RuntimeOrchestrator -> SessionMemory -> /state.recent_sessions`.
- UI : DayDream / Mémoire / Contexte restent marqués Lab partout.
- MCP : aucun `allowed=true` sans `accepted`.

## Roadmap courte proposée

### C2 — Hardening minimal

- Santé Core côté Swift.
- Nettoyage textes Lab UI.
- Tests de garde routes / state / UI.
- Observation dogfooding : logs, batterie, polling, sessions courtes, port conflicts.

### C3 — Contrats mémoire / apprentissage contrôlé

- Uniquement contrat et critères, pas implémentation.
- Définir promotion evidence, contradiction, decay, validation humaine.
- Décider ce qui serait Core-safe plus tard.

### R7 — Plus tard

R7 ne doit reprendre qu’après C2 validé en usage réel et C3 écrit.

Pas avant que Core / Lab soit lisible dans API et UI.

## Sujets interdits temporairement

- apprentissage utilisateur / projet ;
- facts / profile comme produit ;
- mémoire intelligente ;
- vector store / embeddings ;
- DayDream ;
- LLM summaries ;
- context probes automatiques ;
- work intent intelligent ;
- smart proposals ;
- autonomie agentique ;
- refonte Dashboard ;
- gros refactor `RuntimeOrchestrator`.

## Conclusion

Pulse n’est pas prêt pour apprentissage ou mémoire intelligente.

Il est prêt pour dogfooding Core et hardening ciblé.

La bonne prochaine étape n’est pas de rendre Pulse plus intelligent. C’est de réduire les ambiguïtés restantes : santé Core UI, surfaces Lab, `/state`, `/insights`, textes qui sur-vendent, tests de garde.

Le Core est enfin assez solide pour être observé en usage réel ; il n’est pas encore assez séparé pour supporter R7 sans recréer le désordre initial.