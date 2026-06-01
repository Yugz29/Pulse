# C4c — Core/Lab Service Lifecycle Audit

## Statut

- Audit et suivi C4c.1 a C4c.12.
- C4c.1 a cartographie les services Core/Lab instancies, lazy, gated ou toleres.
- C4c.2 a C4c.12 ont cible les workers runtime, surtout `pulse-memory-sync`, `pulse-diff`, `pulse-prepare-resume-card` et `pulse-commit-watch`.
- Aucune modification Swift, UI dashboard, `/today_summary`, `/feed` ou memory candidates n'a ete faite dans C4c.2-C4c.12.
- Le comportement Lab doit rester conserve.

## Pourquoi cet audit existe

C4a a clarifie les surfaces de routes. C4b a reduit les effets de bord du boot : `import daemon.main` ne materialise plus runtime, app, routes ou fichiers `.pulse`, et le lancement direct verifie le port HTTP principal avant creation runtime/app.

C4c verifie ensuite les services et workers encore presents en Core avant toute reduction de couplage. Cette phase ne doit pas activer d'apprentissage, de memoire avancee, de generateur, de DayDream, de facts produit, de vector store ou d'injection LLM en Core.

## Sources de test

Tests de garde principaux :

- `tests/test_main_runtime_state.py`
- `tests/test_runtime_orchestrator.py`
- `tests/test_runtime_lifecycle.py`
- `tests/test_runtime_routes.py`
- `tests/test_main_memory_routes.py`
- `tests/test_memory_candidate_routes.py`
- `tests/routes/test_runtime_state_payloads.py`

Tests documentaires ajoutes pendant C4c :

- `test_init_ne_demarre_pas_les_workers_permanents`
- `test_start_demarre_les_deux_workers_permanents`
- tests C4c.3/C4c.5 sur le gating de `pulse-memory-sync` en Core et la conservation Lab
- `test_file_burst_core_planifie_pulse_diff_et_respecte_cooldown_workspace`
- `test_resume_card_preparee_core_est_deterministe_et_consommee_sans_lab`
- `test_commit_editmsg_core_planifie_commit_watch_deduplique_et_ne_sync_pas_memory`

## Services crees par `create_runtime()`

`create_runtime()` cree aujourd'hui :

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

`RuntimeOrchestrator.__init__()` cree aussi :

- `FactEngine`
- `CurrentContextBuilder`
- `SessionFSM`
- `RestartManager`

Ces creations ont lieu seulement quand `get_runtime()` est appele. Elles n'ont plus lieu a l'import de `daemon.main`.

## Workers et lifecycle apres C4c.12

`create_runtime()` :

- ne demarre pas `RuntimeOrchestrator` ;
- ne demarre pas `pulse-file-burst` ;
- ne demarre pas `pulse-periodic-sync` ;
- ne cree pas de critical workers ;
- ne demarre pas de serveur Flask ;
- ne demarre pas le heartbeat idle.

`start_runtime_services()` demarre ensuite :

- `RuntimeOrchestrator.start()` ;
- le heartbeat idle.

`RuntimeOrchestrator.start()` demarre deux workers permanents :

- `pulse-file-burst` ;
- `pulse-periodic-sync`.

`daemon.main` demarre aussi, au lancement direct du daemon :

- `pulse-watchdog` ;
- `pulse-startup`.

Le heartbeat idle cree :

- `pulse-idle-heartbeat`.

## Classification workers apres C4c.12

### Core strict

- `pulse-file-burst` : coalesce les evenements fichiers et alimente le runtime local.
- `pulse-periodic-sync` : worker permanent conserve en Core, mais ses chemins memoire sont gates apres C4c.3/C4c.5.
- `pulse-idle-heartbeat` : presence/idle locale.
- `pulse-watchdog` : surveillance daemon.

### Core toleres

- `pulse-diff` : declenche par file burst apres detection workspace ; lit git en arriere-plan et alimente le contexte.
- `pulse-commit-watch` : declenche sur `COMMIT_EDITMSG` ; lit HEAD/metadata git et confirme les commits en Core sans memory sync.
- `pulse-prepare-resume-card` : prepare une resume card deterministe au `screen_locked`.
- `pulse-resume-card` : worker d'emission differee possible, conserve mais non utilise par le chemin normal actuel quand `should_wait_for_llm=False`.
- `pulse-startup` : startup differee mixte ; ses parties DayDream/facts/LLM restent conditionnelles ou gated.
- warmup heavy LLM eventuel : seulement si l'environnement/policy l'active explicitement.

### Lab only par flux normal

- `pulse-memory-sync` : ne doit plus etre cree par les flux runtime normaux en Core apres C4c.5.
- `pulse-daydream-scheduler` : planifie seulement en Lab.
- `pulse-daydream` : execute seulement via chemins Lab.

## Progression C4c.2 a C4c.12

### C4c.2 — Periodic sync audit

`pulse-periodic-sync` demarrait en Core avec `RuntimeOrchestrator.start()`. Il pouvait planifier `pulse-memory-sync` si un diff et une duree de session suffisante etaient presents.

Le worker memoire etait deja no-op en Core via `is_lab_enabled()` dans `_sync_memory_background()`. La dette confirmee etait donc la creation inutile possible d'un worker `pulse-memory-sync`, sans mutation Lab.

### C4c.3 — Gate periodic memory sync

Un gate `is_lab_enabled()` a ete ajoute avant la planification de `pulse-memory-sync` dans le chemin periodic sync.

Etat obtenu :

- en Core, `pulse-periodic-sync` ne cree plus `pulse-memory-sync` ;
- en Lab, le comportement periodic sync est conserve.

### C4c.4 — Inventaire `_schedule_memory_sync`

Les appels a `_schedule_memory_sync(...)` identifies etaient :

- periodic sync ;
- commit confirme ;
- boundary flush ;
- sync classique dans `_process_signals`.

Apres C4c.3, seuls commit confirme, boundary flush et sync classique pouvaient encore creer `pulse-memory-sync` en Core.

### C4c.5 — Gate all memory sync call sites

Des gates `is_lab_enabled()` ont ete ajoutes avant les call sites runtime restants accessibles en Core.

Etat obtenu :

- en Core, aucun chemin runtime normal ne cree plus `pulse-memory-sync` ;
- `_schedule_memory_sync()` n'a pas ete modifie globalement ;
- en Lab, le comportement existant est conserve.

### C4c.6 — Workers inventory

Inventaire des workers non memoire apres le gating complet de `pulse-memory-sync`.

Conclusion principale :

- les workers Core strict restent limites au lifecycle local necessaire ;
- `pulse-diff`, `pulse-commit-watch`, `pulse-prepare-resume-card`, `pulse-resume-card` et `pulse-startup` restent Core toleres ;
- DayDream et memory sync restent Lab only par flux normal.

### C4c.7 — `pulse-diff` audit

`pulse-diff` demarre en Core apres file burst quand un workspace est detecte et que le cooldown par workspace le permet.

Il lance `read_diff_summary(workspace)`, qui lit un resume git compact a partir de `git diff HEAD` ou fallback `git diff --cached`. Le resultat est stocke dans `RuntimeState` via `set_diff_summary(workspace, summary)`.

Surfaces alimentees indirectement :

- scoring / signaux runtime ;
- resume cards ;
- contexte runtime ;
- surfaces qui lisent le snapshot runtime.

Classification : Core tolere, pas Core strict.

Risques :

- cout subprocess git ;
- bruit local ;
- noms de fichiers/fonctions ;
- contexte de workspace local.

### C4c.8 — `pulse-diff` test

Test documentaire ajoute :

- un file burst en Core peut planifier `pulse-diff` ;
- `read_diff_summary` est mocke, donc pas de vrai subprocess git ;
- le resume est stocke dans `RuntimeState` ;
- le cooldown par workspace empeche un second worker immediat.

### C4c.9 — `pulse-prepare-resume-card` audit

`pulse-prepare-resume-card` demarre en Core sur `screen_locked`.

Il prepare une resume card deterministe :

- ne passe pas par `freeze_memory()` ;
- n'appelle pas LLM ;
- ne touche pas `MemoryStore`, `FactEngine` ou `VectorStore` ;
- lit le snapshot runtime, le payload session et le diff summary courant ;
- stocke un payload temporaire en memoire avec TTL.

Classification : Core Produit tolere.

### C4c.10 — prepared resume card test

Test documentaire ajoute :

- `screen_locked` prepare une carte deterministe en Core ;
- le payload est stocke ;
- aucun LLM n'est appele ;
- `freeze_memory()` n'est pas appele ;
- aucun chemin Lab memoire n'est appele ;
- le payload est consomme au unlock/reprise si les conditions sont reunies ;
- un evenement `resume_card` est publie ;
- le payload prepare est vide apres emission.

### C4c.11 — `pulse-commit-watch` audit

`pulse-commit-watch` demarre en Core sur un evenement `COMMIT_EDITMSG`.

Declencheur :

- event type `file_modified` ou `file_created` ;
- path contenant `/COMMIT_EDITMSG` ;
- orchestrateur non paused ;
- ecran non locked ;
- evenement non filtre par `_should_ignore_event()`.

`COMMIT_EDITMSG` reste `runtime_relevant=True` malgre sa classification fichier `technical_noise`. Cela permet au runtime de detecter une livraison de commit sans scorer le fichier `.git` comme activite de code normale.

Le worker est deduplique par git root via `_pending_commit_watch`.

Donnees lues :

- path `COMMIT_EDITMSG` ;
- git root ;
- `.git/HEAD` et refs ;
- commit message ;
- timestamp HEAD ;
- diff HEAD compact ;
- fichiers du commit en fallback ;
- runtime snapshot ;
- session payload ;
- fenetre d'activite fichier.

Commandes git/subprocess :

- `git show -s --format=%ct HEAD` ;
- `git show HEAD --format=format: -U2` ;
- `git show --name-only --format=format: --diff-filter=ACDMRTUXB HEAD`.

En Core :

- met a jour `_last_head_sha` ;
- construit un snapshot commit enrichi ;
- peut rafraichir les signaux runtime ;
- ne planifie plus `pulse-memory-sync` apres C4c.5 ;
- ne touche pas `MemoryStore`, `FactEngine`, `VectorStore`, LLM ou memory candidates.

En Lab :

- peut declencher le pipeline memoire avance via memory sync.

Classification : Core tolere / Produit, pas Core strict, pas Lab, pas Debug.

Risques :

- subprocess git ;
- chemins, fichiers et message de commit potentiellement sensibles ;
- cout IO ;
- bruit si `COMMIT_EDITMSG` est touche sans commit reel, mitige par la confirmation HEAD.

### C4c.12 — `pulse-commit-watch` test

Test documentaire ajoute :

- `test_commit_editmsg_core_planifie_commit_watch_deduplique_et_ne_sync_pas_memory`.

Le test verifie en Core :

- `handle_event(file_modified COMMIT_EDITMSG)` planifie `pulse-commit-watch` ;
- le worker est nomme correctement ;
- le second evenement immediat du meme repo est deduplique ;
- le commit peut etre confirme avec HEAD mocke ;
- aucun `pulse-memory-sync` n'est cree ;
- aucun chemin `MemoryStore`, `FactEngine`, `VectorStore` ou LLM n'est appele.

Le test mocke les acces git et ne lance pas de vrai subprocess.

## Etat actuel apres C4c.12

La frontiere memory-sync Core/Lab est plus propre :

- `pulse-memory-sync` reste disponible pour les flux Lab ;
- les flux runtime normaux Core ne creent plus `pulse-memory-sync` ;
- `_sync_memory_background()` reste no-op en Core, mais le guard est maintenant place avant la creation des workers sur les call sites normaux ;
- le comportement Lab est conserve.

Les workers Core toleres encore presents servent principalement la reprise du fil :

- `pulse-diff` fournit un resume local compact du diff ;
- `pulse-commit-watch` observe les livraisons de commit et construit un snapshot commit enrichi ;
- `pulse-prepare-resume-card` prepare une carte deterministe ;
- `pulse-resume-card` reste un chemin d'emission differee possible.

Les workers Core toleres principaux sont maintenant audites/testes :

- `pulse-diff` ;
- `pulse-prepare-resume-card` ;
- `pulse-commit-watch`.

Les risques restants sont surtout le cout et la sensibilite des donnees locales, pas une contamination Lab.

Les patchs C4c.2-C4c.12 n'ont pas modifie Swift, UI, dashboard, `/today_summary`, `/feed`, memory candidates ou les contrats Lab.

## Surfaces dediees separees

`MemoryCandidateStore` est instancie par `create_runtime()` mais reste une surface dediee :

- separee de `SessionMemory` ;
- separee de `MemoryStore` ;
- separee de facts ;
- separee de DayDream ;
- separee de LLM ;
- non branchee dans `RuntimeOrchestrator`.

Les tests `memory_candidates` verifient que les routes candidates n'appellent pas `MemoryStore`, facts, DayDream ou LLM, et que `/state`, `/debug/state` et `/insights` ne creent pas de candidates.

## Dependances des surfaces Core

`/health/core` :

- ne depend pas de `MemoryStore` ;
- ne depend pas de facts ;
- ne depend pas de DayDream ;
- ne depend pas de LLM ;
- ne depend pas de vector store / embeddings ;
- ne depend pas de context probes ou work intent.

`/state` :

- reste base sur `RuntimeState`, `StateStore`, `SessionFSM`, `CurrentContextBuilder` et `SessionMemory` ;
- ne doit pas materialiser de memoire Lab ;
- ne doit pas exposer `memory_candidates`.

`/feed` :

- reste base sur `EventBus.recent()` ;
- ne doit pas etre une source de creation de memory candidates ;
- ne doit pas declencher DayDream, facts, MemoryStore ou LLM.

`/memory/candidates` :

- depend de `MemoryCandidateStore` ;
- ne depend pas de `MemoryStore` ;
- ne depend pas de facts ;
- ne depend pas de DayDream ;
- ne depend pas de LLM ;
- ne depend pas de `RuntimeOrchestrator`.

## Mutations Lab en Core

Les tests existants documentent que :

- `/memory/write` est enregistree mais bloquee en Core ;
- `/memory/remove` est enregistree mais bloquee en Core ;
- les mutations facts `reinforce`, `contradict` et `archive` sont bloquees en Core ;
- `/facts/profile` est neutralisee en Core ;
- `/llm/lightweight/result` est bloquee en Core.

Ces routes restent enregistrees pour compatibilite, mais elles ne doivent pas devenir des capacites Core actives.

## Risques restants

- `pulse-startup` reste mixte, meme si ses parties Lab sont gated.
- Le warmup heavy LLM eventuel reste a surveiller si l'environnement/policy l'active explicitement.
- `pulse-diff` et `pulse-commit-watch` restent des chemins subprocess/IO Core toleres.
- `pulse-prepare-resume-card` garde un payload en memoire jusqu'a expiration ou consommation.
- Les workers Core toleres doivent rester testes et surveilles pour eviter une derive vers des effets de bord Lab.
- Il faut maintenant decider si C4c peut etre cloture ou s'il reste un audit cible a faire.

## Decision provisoire

C4c confirme que le Core ne depend pas directement des surfaces Lab pour `/health/core`, `/state`, `/feed` et `memory_candidates`.

Apres C4c.12, la dette principale n'est plus la creation de `pulse-memory-sync` en Core par les flux normaux. Elle se deplace vers les workers Core toleres, surtout ceux qui lisent le workspace ou gardent du contexte temporaire.

## Prochaine etape recommandee

Deux options restent ouvertes :

- cloturer C4c si la cartographie actuelle suffit pour Core reset ;
- ou faire un audit cible `pulse-startup` avant cloture.

Si une derniere passe est retenue, C4c.14 devrait etre audit-only sur `pulse-startup` : declencheur, operations au boot differe, gates Lab, heavy LLM warmup eventuel, cout et tests existants.
