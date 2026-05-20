# Roadmap de Recadrage — Pulse Core Reset

> Statut : **document maître prioritaire**  
> Périmètre : recadrage de Pulse autour du Core  
> Priorité : ce document passe devant les anciennes roadmaps, notes d’architecture, documents mémoire, agent, apprentissage, DayDream, facts, propositions et extensions dashboard tant que le Core Reset n’est pas terminé et vérifié.

## 0. Objectif du document

Pulse ne repart pas de zéro.

Pulse possède déjà une vraie base technique : daemon, état runtime, ingestion d’événements, scoring de signaux, sessions, dashboard, mémoire expérimentale, intégrations LLM et surfaces de propositions.

Le problème n’est pas le manque de code.

Le problème est que les fonctionnalités stables, les expérimentations avancées, les outils de debug et les idées produit futures sont aujourd’hui trop mélangés.

Ce document sert à remettre Pulse dans un cadre d’ingénierie contrôlé.

L’objectif du Core Reset est :

> Construire un runtime local-first fiable, capable d’observer l’activité de travail, filtrer le bruit, produire des signaux explicables, suivre des sessions de travail et écrire un historique minimal vérifiable.

Tant que ce document n’est pas accompli, Pulse ne doit pas être présenté ni traité comme :

- un agent autonome ;
- un assistant adaptatif ;
- une mémoire intelligente ;
- un système d’apprentissage utilisateur ;
- une intelligence proactive.

## 1. Définition produit pendant le Core Reset

Pendant le Core Reset, Pulse est défini comme :

> Un runtime local de diagnostic du contexte de travail.

Pulse Core doit répondre à des questions simples et vérifiables :

- Le daemon est-il vivant ?
- Que voit Pulse actuellement ?
- Quels événements récents sont réellement utiles ?
- Quelle activité Pulse infère-t-il ?
- Quelles preuves soutiennent cette inférence ?
- Qu’est-ce qui reste incertain ?
- Une session de travail est-elle active, en pause, reprise ou fermée ?
- Quel journal historique minimal peut être produit à partir de faits observés ?

Pulse Core ne doit pas prétendre :

- comprendre profondément l’utilisateur ;
- avoir appris des habitudes stables ;
- connaître des préférences long terme ;
- adapter son comportement de manière fiable ;
- proposer ou exécuter des actions de façon autonome ;
- transformer des récits ou résumés narratifs en vérité canonique.

## 2. Principe directeur

Pulse ne doit pas apprendre tant qu’il n’observe pas correctement.

Pulse ne doit pas proposer tant qu’il n’interprète pas prudemment.

Pulse ne doit pas agir tant qu’il ne peut pas expliquer pourquoi.

Toute affirmation visible côté produit doit être soutenue par :

1. des preuves observées ;
2. des signaux dérivés ;
3. un niveau de confiance ou une incertitude ;
4. une trace de debug consultable.

Si cette chaîne manque, la fonctionnalité appartient à Pulse Lab, pas à Pulse Core.

## 3. Frontière Core / Lab

### 3.1 Pulse Core

Pulse Core est le chemin stable.

Core contient :

- démarrage et arrêt du daemon ;
- `/ping` ;
- `/state` ;
- ingestion via `/event` ;
- `/feed` ;
- statut runtime ;
- pause / reprise du daemon ;
- `RuntimeState` / `PresentState` ;
- bus d’événements ;
- filtrage des événements ;
- classification des applications ;
- classification des fichiers ;
- qualification du sens des événements ;
- classification de l’acteur ;
- normalisation des événements terminal ;
- scoring des signaux ;
- construction du contexte courant ;
- `SessionFSM` ;
- réparation après redémarrage ;
- snapshots de session minimaux ;
- journal de session minimal ;
- debug state ;
- statut du scoring ;
- dashboard diagnostic.

### 3.2 Pulse Lab

Pulse Lab contient les systèmes avancés ou prématurés qui peuvent rester dans le dépôt, mais qui ne doivent pas faire partie du chemin produit par défaut.

Lab contient :

- DayDream ;
- moteur de facts / profil ;
- apprentissage du profil utilisateur ;
- apprentissage du profil projet ;
- vector store ;
- recherche sémantique mémoire ;
- résumés LLM ;
- queue LLM légère ;
- candidats d’intention de travail ;
- context probes ;
- génération avancée de propositions ;
- exécution automatique de propositions ;
- liaison commits / épisodes ;
- hooks d’adaptation ;
- niveaux d’autonomie ;
- surfaces avancées d’écriture / suppression mémoire ;
- surfaces dashboard qui présentent des fonctionnalités expérimentales comme si elles étaient prêtes.

Les fonctionnalités Lab peuvent être :

- importables ;
- testées ;
- documentées comme expérimentales ;
- activées manuellement en mode lab ou dev.

Les fonctionnalités Lab ne doivent pas être :

- démarrées par défaut ;
- nécessaires au boot du daemon ;
- nécessaires à `/state` ;
- présentées comme stables dans le dashboard ;
- utilisées pour produire une mémoire canonique ;
- utilisées pour justifier un comportement autonome.

## 4. Modes runtime

Pulse doit avoir un mode runtime explicite.

Modes cibles :

```txt
core
lab
dev
```

### 4.1 `core`

Mode par défaut.

Seuls les services stables du Core sont démarrés.

Les services expérimentaux sont désactivés.

Payload attendu dans `/state` ou `/debug/state` :

```json
{
  "pulse_mode": "core",
  "experimental_enabled": false
}
```

### 4.2 `lab`

Mode manuel pour les expérimentations avancées.

Le mode lab peut activer des services expérimentaux, mais ils doivent être clairement marqués comme expérimentaux dans les payloads API et dans le dashboard.

### 4.3 `dev`

Mode développeur.

Le mode dev peut activer les routes debug verbeuses, les traces et les fonctionnalités Lab.

Le mode dev n’est pas un mode produit.

## 5. Règles non négociables

Tant que le Core Reset n’est pas terminé :

1. Ne pas ajouter de nouveau comportement DayDream.
2. Ne pas ajouter de nouveau comportement facts / profil.
3. Ne pas ajouter de comportement d’adaptation utilisateur.
4. Ne pas ajouter de nouvelles actions autonomes.
5. Ne pas ajouter de nouveaux types de propositions, sauf pour la baseline stricte de validation MCP.
6. Ne pas améliorer la mémoire vectorielle.
7. Ne pas optimiser Ollama ou les LLM pour le flux produit.
8. Ne pas ajouter de nouveaux onglets produit au dashboard.
9. Ne pas promouvoir de données expérimentales en mémoire canonique.
10. Ne pas confondre tests unitaires qui passent et fiabilité produit.
11. Ne pas laisser Pulse affirmer quelque chose sans preuve et sans incertitude.
12. Ne pas patcher au hasard des modules avancés avant que le chemin Core soit vérifié.

Travail autorisé :

- documentation qui clarifie Core vs Lab ;
- tests qui verrouillent le comportement Core existant ;
- refactors qui réduisent le couplage au démarrage ;
- feature gates ;
- health checks ;
- fixtures d’observation ;
- explication des signaux ;
- fiabilité des sessions ;
- correction du journal minimal ;
- simplification du dashboard diagnostic.

## 6. Pipeline cible du Core

Le pipeline Core est :

```txt
Événement brut
  -> ingestion / filtrage
  -> EventBus
  -> RuntimeOrchestrator
  -> SessionFSM
  -> SignalScorer
  -> RuntimeState.update_present()
  -> CurrentContextBuilder / payloads d’état
  -> SessionMemory snapshot minimal
  -> feed / dashboard diagnostic
```

Chaque étape doit être inspectable indépendamment.

## 7. Phases de remise sur rails

### R0 — Gel du périmètre et autorité

Objectif : stopper l’expansion du scope et définir le nouveau contrat du projet.

Livrables :

- ce document existe et est commit ;
- les anciennes docs deviennent secondaires si elles contredisent cette roadmap ;
- Core et Lab sont explicitement définis ;
- le README commence à distinguer Core stable et Lab expérimental ;
- aucune nouvelle fonctionnalité intelligente n’est démarrée.

Validation :

- un contributeur peut lire ce document et comprendre ce qu’il ne faut pas toucher ;
- chaque tâche active peut être reliée à une phase du Core Reset.

À ne pas faire :

- polish de feature ;
- travail sur DayDream ;
- travail sur facts / profil ;
- travail sur le comportement LLM ;
- extension du dashboard.

### R1 — Baseline Runtime

Objectif : Pulse démarre dans un mode minimal et fiable.

Travail cible :

- introduire un mode runtime explicite ;
- mettre `core` comme mode par défaut ;
- empêcher les services expérimentaux de démarrer en mode Core ;
- exposer le mode dans `/state` ou `/debug/state` ;
- ajouter `/health/core` ou une surface équivalente ;
- vérifier que `/ping`, `/state`, `/feed` et le boot Core ne dépendent pas de la disponibilité d’un provider LLM, d’un warmup LLM, d’une requête LLM, de DayDream, des facts, du vector store, du work intent ou d’une sync mémoire avancée ;
- clarifier `freeze_memory()` : en mode Core, cette fonction peut rester disponible pour produire une snapshot minimale observée / dérivée, mais elle ne doit pas rendre les facts, le profil, le vector store ou la mémoire narrative ;
- couper les points d’entrée Lab actuellement branchés dans le boot, le démarrage différé, la boucle événementielle et les rendus mémoire.

Validation :

- le daemon démarre en mode Core ;
- `/ping` fonctionne ;
- `/state` fonctionne ;
- `/feed` fonctionne ;
- `/health/core` indique que les services Core requis sont OK ;
- les services expérimentaux sont indiqués comme désactivés ;
- les tests prouvent que le mode Core ne dépend pas des services Lab ;
- `freeze_memory()` reste disponible en mode Core, mais ne produit que des données minimales observées / dérivées ;
- DayDream n’est pas planifié, démarré ou déclenché par les événements en mode Core ;
- facts / profil ne participent pas au boot Core ;
- aucun chemin Core ne doit instancier `VectorStore` ni déclencher des embeddings pour produire une sortie Core ;
- les surfaces LLM légères ne doivent pas être actives en produit Core ou doivent être explicitement marquées Lab / debug.

À ne pas faire :

- mémoire intelligente ;
- propositions intelligentes ;
- refonte dashboard au-delà de l’affichage du mode runtime et de la santé Core.

### R2 — Baseline Observation

Objectif : Pulse observe proprement avant d’interpréter profondément.

Travail cible :

- définir des fixtures golden d’événements ;
- vérifier les événements app, fichier, terminal, idle, lock / unlock ;
- vérifier le filtrage du bruit technique ;
- supprimer autant que possible les hypothèses locales hardcodées ;
- séparer les données observées des données inférées.

Validation :

- les événements utilisateur significatifs influencent l’état ;
- le bruit technique / système est ignoré ou déclassé ;
- la classification de l’acteur est explicable ;
- le feed d’événements est lisible et utile ;
- les tests couvrent des scénarios réalistes.

À ne pas faire :

- inférer des habitudes long terme ;
- créer des facts ;
- inférer l’identité d’un projet au-delà d’un contexte courant prudent.

### R3 — Baseline Interprétation

Objectif : Pulse produit des signaux prudents et explicables.

Travail cible :

- rendre les sorties de `SignalScorer` explicables ;
- attacher des preuves à l’activité probable, au focus et au type de tâche ;
- exposer les incertitudes ;
- définir des scénarios golden de scoring ;
- éviter d’ajouter de nouvelles catégories de tâches sans justification forte.

Validation :

- chaque tâche probable a des preuves ;
- l’incertitude est visible ;
- la confiance n’est pas traitée comme une vérité ;
- les scénarios golden passent ;
- le dashboard peut montrer pourquoi Pulse pense quelque chose.

À ne pas faire :

- utiliser un LLM pour réparer un scoring faible ;
- promouvoir des interprétations faibles en mémoire ;
- ajouter des règles d’adaptation.

### R4 — Baseline Sessions

Objectif : Pulse suit les sessions de travail de manière fiable.

Travail cible :

- vérifier les états session started, active, idle, paused, resumed, closed ;
- vérifier le comportement lock / unlock ;
- vérifier les pauses courtes et longues ;
- vérifier la réparation après redémarrage du daemon ;
- rendre l’état de session visible dans `/state` et dans le dashboard.

Validation :

- les sessions sont compréhensibles depuis les payloads API ;
- un redémarrage ne crée pas de session active trompeuse ;
- les frontières d’inactivité sont cohérentes ;
- la durée de session vient de la `SessionFSM`, pas d’approximations legacy.

À ne pas faire :

- liaison commits / épisodes ;
- resume cards intelligentes ;
- résumés narratifs.

### R5 — Baseline Mémoire minimale

Objectif : écrire des journaux de session historiques vérifiables, sans apprentissage.

Travail cible :

- réduire la mémoire Core à un historique observé / dérivé des sessions ;
- préserver la provenance ;
- marquer clairement le contenu inféré ;
- éviter toute promotion vers facts / profil ;
- rendre les journaux lisibles dans le dashboard sans bruit Markdown brut lorsque possible.

Validation :

- un journal de session peut être relié aux events, signaux et états de session ;
- aucune habitude utilisateur n’est promue en vérité canonique ;
- la sortie journal est utile à relire ;
- la mémoire peut être désactivée sans casser le runtime.

À ne pas faire :

- recherche vectorielle ;
- extraction de facts ;
- mise à jour du profil utilisateur ;
- mise à jour du profil projet ;
- mémoire narrative DayDream.

### R6 — Baseline Propositions contrôlées

Objectif : conserver uniquement un flux de proposition strictement contrôlé par validation humaine.

Travail cible :

- préserver le flux minimal d’approbation MCP si nécessaire ;
- rendre le cycle de vie des propositions explicite ;
- empêcher les propositions auto-exécutées de ressembler à des validations humaines ;
- séparer les propositions debug des propositions produit.

Cycle attendu :

```txt
candidate -> pending -> approved | denied | expired -> executed uniquement après approval
```

Validation :

- aucune proposition n’est exécutée sans validation explicite dans le flux produit ;
- les chemins timeout / deny sont testés ;
- le dashboard et l’API montrent clairement l’état des propositions ;
- l’auto-résolution debug est marquée debug only ou désactivée en mode Core.

À ne pas faire :

- suggestions agentiques proactives ;
- automatisation des context probes ;
- corrections autonomes ;
- propositions pilotées par apprentissage.

### R7 — Apprentissage plus tard

Objectif : phase reportée.

L’apprentissage, l’adaptation, les facts, les profils, la mémoire sémantique et l’intelligence proactive ne peuvent pas revenir dans le flux produit avant que R0 à R6 soient terminées et vérifiées en usage réel.

R7 ne peut commencer que lorsque :

- le mode Core est stable ;
- l’observation est fiable ;
- le scoring est explicable ;
- les sessions sont robustes ;
- la mémoire minimale est vérifiable ;
- le contrôle des propositions est honnête.

## 8. Definition of Done du Core Reset

Le Core Reset est terminé uniquement quand :

- Pulse démarre en mode Core par défaut ;
- le mode Core ne démarre pas les services Lab ;
- `/ping`, `/state`, `/feed` et les health checks fonctionnent sans services Lab ;
- le mode runtime est visible depuis l’API et le dashboard ;
- des fixtures d’observation existent ;
- des scénarios de scoring existent ;
- les sessions sont testées sur idle, lock et redémarrage ;
- les journaux minimaux sont produits sans claims d’apprentissage ;
- `freeze_memory()` fonctionne en mode Core sans facts, profil, vector store ni mémoire narrative ;
- la vue dashboard par défaut est diagnostic, pas agentique ;
- le README distingue Core stable et Lab expérimental ;
- les fonctionnalités avancées sont documentées comme Lab-only ;
- les tests valident la frontière Core / Lab.

## 9. Stratégie de commits

Le travail doit être commit en petits commits relisibles.

Séquence suggérée :

```txt
docs(core): définir la roadmap de recadrage Pulse Core
docs(core): documenter la frontière Core stable / Lab expérimental
feat(config): introduire le mode runtime Pulse
refactor(runtime): placer les services expérimentaux derrière un gate
feat(health): exposer la santé du Core
test(runtime): vérifier que le mode Core démarre sans services Lab
test(observation): ajouter les fixtures golden d’événements
test(scoring): ajouter les scénarios de signaux explicables
test(session): verrouiller le comportement session idle / lock / restart
docs(readme): distinguer capacités Core et expérimentations Lab
```

Aucun commit ne doit mélanger des changements Core et Lab sans raison claire.

## 10. Priorité actuelle

La priorité immédiate est R0, puis R1.

Prochaines actions :

1. finaliser et commit ce document ;
2. aligner le README avec le statut Core Reset ;
3. introduire le mode runtime minimal ;
4. exposer `pulse_mode` et `experimental_enabled` ;
5. gater DayDream dans un patch séparé ;
6. gater facts / rendu mémoire avancé dans un patch séparé ;
7. ajouter la santé Core ;
8. tester le boot Core sans dépendances expérimentales.

Rien d’autre ne doit passer avant, sauf si cela corrige un problème de boot Core, d’observation, de scoring, de session ou de journal minimal.

## 11. Checklist R0 — Gel et autorité

Objectif : transformer ce document en contrat réel du projet.

- [x] `docs/ROADMAP_CORE_RESET.md` existe.
- [x] Le document est relu et compris comme document maître.
- [x] Le document est commit sur la branche de recadrage.
- [x] Le README indique clairement que Pulse est en Core Reset.
- [x] Le README distingue Core stable et Lab expérimental.
- [x] Le README indique que les anciennes roadmaps sont secondaires pendant le Core Reset.
- [ ] Les anciennes roadmaps principales reçoivent un avertissement ou un renvoi vers ce document si nécessaire.
- [x] Les anciennes docs ne sont pas supprimées, mais deviennent secondaires si elles contredisent ce document.
- [x] Aucune tâche DayDream, facts, LLM, adaptation ou dashboard avancé n’est prioritaire pendant R0/R1.
- [x] La prochaine tâche technique officielle est l’introduction du mode runtime.
- [x] `git status` ne montre plus `docs/ROADMAP_CORE_RESET.md` comme fichier non suivi.

Sortie attendue de R0 :

> Le projet a une autorité claire, un périmètre clair, et une interdiction explicite de repartir dans les features avancées avant que le Core soit stable.

## 12. Checklist R1 — Baseline Runtime

Objectif : obtenir un Pulse qui démarre proprement en mode Core, sans faire un gros refactor risqué.

R1 est découpé en sous-étapes obligatoires. Chaque sous-étape doit pouvoir être testée et commit séparément.

### R1a — Mode runtime minimal

Objectif : introduire le mode Core sans encore couper brutalement les services.

- [x] Ajouter une configuration `PULSE_MODE`.
- [x] Créer un module central dédié au mode runtime, par exemple `daemon/runtime_mode.py`, plutôt que placer cette logique dans une policy LLM.
- [x] Ajouter une fonction centralisée `get_pulse_mode()`.
- [x] Ajouter une fonction centralisée `is_lab_enabled()` pour activer Lab uniquement en mode `lab` ou `dev`.
- [x] Définir `core` comme valeur par défaut.
- [x] Exposer `pulse_mode` dans `/state`.
- [x] Exposer `experimental_enabled: false` en mode Core.
- [x] Exposer les détails plus verbeux uniquement dans `/debug/state` si nécessaire.
- [x] Ajouter des tests unitaires de parsing du mode runtime.
- [x] Ajouter des tests sur les payloads `/state` ou builders d’état.

Sortie attendue de R1a :

> Pulse expose clairement son mode runtime sans changement de comportement risqué.

Validation R1a :

- module central ajouté : `daemon/runtime_mode.py` ;
- mode par défaut : `core` ;
- modes acceptés : `core`, `lab`, `dev` ;
- fallback invalide : `core` ;
- champs exposés : `pulse_mode`, `experimental_enabled` ;
- aucun gate DayDream / facts / LLM / mémoire avancée ajouté à cette étape ;
- tests ciblés passés : `tests/test_runtime_mode.py`, `tests/routes/test_runtime_state_payloads.py`, `tests/test_main_runtime_state.py`.

### R1b — Gate DayDream

Objectif : sortir DayDream du chemin Core sans supprimer le module.

- [x] Empêcher `_mark_missed_daydream_pending()` de tourner en mode Core.
- [x] Empêcher le thread `_daydream_scheduler` de démarrer en mode Core.
- [x] Empêcher `_run_daydream_if_pending()` d’être appelé depuis `handle_event()` en mode Core.
- [x] Ajouter des tests prouvant que DayDream n’est ni planifié, ni démarré, ni déclenché par événement en mode Core.
- [x] Vérifier que DayDream reste disponible en mode `lab` ou `dev` si nécessaire.

Sortie attendue de R1b :

> DayDream n’est plus câblé dans le boot ou la boucle événementielle du Core.

Validation R1b :

- DayDream est maintenant derrière `is_lab_enabled()` ;
- en mode Core, `deferred_startup()` ne planifie plus DayDream ;
- en mode Core, le thread scheduler DayDream ne démarre plus ;
- en mode Core, `handle_event()` ne déclenche plus DayDream sur `screen_locked` / `screen_unlocked` ;
- en mode Lab, les chemins DayDream existants restent activables ;
- aucun changement facts / profil / `freeze_memory()` / vector store / routes Lab / dashboard Swift / boot global ;
- tests ciblés passés : `tests/test_runtime_orchestrator.py`.

### R1c — Gate facts et mémoire avancée

Objectif : empêcher facts / profil / mémoire avancée de contaminer le Core.

- [x] Empêcher `archive_legacy_facts()` de tourner en mode Core.
- [x] Empêcher `decay_all()` de tourner en mode Core.
- [x] Vérifier si `get_fact_engine()` est encore instancié au boot Core ; si oui, ne pas le rendre lazy dans le premier patch sauf si c’est trivial. Gater d’abord ses effets de bord et son rendu.
- [x] Empêcher le rendu facts / profil dans `freeze_memory()` en mode Core.
- [x] Éviter `load_memory_context()` en mode Core si ce legacy context peut contenir des mémoires Lab non qualifiées.
- [x] Garder `freeze_memory()` disponible en Core uniquement pour une snapshot minimale observée / dérivée.
- [x] Ajouter des tests prouvant que `freeze_memory()` exclut facts / profil / mémoire narrative en mode Core.

Sortie attendue de R1c :

> `freeze_memory()` reste utile en Core, mais ne rend plus de mémoire intelligente ou expérimentale.

Validation R1c :

- en mode Core, `deferred_startup()` ne lance plus `archive_legacy_facts()` ;
- en mode Core, `deferred_startup()` ne lance plus `decay_all()` ;
- en mode Core, `freeze_memory()` n’appelle plus `render_project_memory()` ;
- en mode Core, `freeze_memory()` n’appelle plus `memory_store.render()` ;
- en mode Core, `freeze_memory()` n’appelle plus `load_memory_context()` ;
- en mode Core, `freeze_memory()` n’appelle plus `fact_engine.render_for_context()` ;
- en mode Core, `freeze_memory()` reste disponible et produit une snapshot minimale depuis `PresentState` ;
- en mode Lab, les chemins facts et mémoire avancée existants restent actifs ;
- `get_fact_engine()` reste volontairement instancié dans `RuntimeOrchestrator.__init__`, mais ses effets de bord et son rendu sont gatés en Core ;
- aucun changement DayDream / vector store / routes Lab / dashboard Swift / boot global ;
- tests ciblés passés : `tests/test_runtime_orchestrator.py`.

### R1d — LLM léger, vector store et sync mémoire

Objectif : clarifier les dépendances avancées sans casser les surfaces existantes.

- [x] Ne pas chercher à supprimer l’objet LLM au premier patch.
- [x] Vérifier que `/ping`, `/state` et `/feed` ne dépendent pas d’un provider LLM disponible.
- [x] Vérifier que le warmup LLM reste désactivé par défaut ou déjà gate par policy existante.
- [x] Empêcher les enqueues lightweight LLM d’être actifs en mode Core, ou les marquer explicitement Lab / debug.
- [x] Ne pas supprimer `LightweightLLMQueue` au premier patch.
- [x] Prouver qu’aucun chemin Core n’instancie `VectorStore` ni ne déclenche d’embeddings.
- [x] Vérifier `_sync_memory_background()` et `update_memories_from_session()` pour éviter facts, journal intelligent, summaries LLM ou vectorisation dans le flux Core.

Sortie attendue de R1d :

> Le Core ne dépend pas des LLM, embeddings ou sync mémoire avancée pour fonctionner.

Validation R1d :

- l’objet LLM global reste volontairement créé ;
- `LightweightLLMQueue` reste présent ;
- `VectorStore` reste présent ;
- les routes `/llm/lightweight/*` restent exposées pour traitement ultérieur en R1e ;
- en mode Core, les sync mémoire avancées automatiques ne lancent plus `update_memories_from_session()` ;
- en mode Core, les chemins pré-reset après longue veille, shutdown runtime et `_sync_memory_background()` ne déclenchent plus de sync mémoire avancée ;
- en mode Core, les enqueues LLM légères automatiques sont bloquées pour les résumés de commit journal et resume card ;
- en mode Lab, les chemins existants restent activables ;
- `/feed` a été vérifié comme route read-only sur l’event bus, sans provider LLM ;
- aucun changement DayDream / gates facts existants / routes / dashboard Swift / boot global ;
- tests ciblés passés : `tests/test_runtime_orchestrator.py`, `tests/llm/test_lifecycle_policy.py`, `tests/llm/test_lightweight_queue.py`, `tests/memory/test_embedding_policy.py`, `tests/test_main_runtime_state.py`.

### R1e — Routes et surfaces Lab

Objectif : éviter une casse large de l’API et du dashboard.

- [x] Ne pas désenregistrer en bloc les routes Lab au premier patch.
- [x] Identifier les routes Lab enregistrées dans `main.create_app()`.
- [x] Identifier les routes Lab enregistrées dans `register_runtime_routes()`.
- [x] Marquer ou gater progressivement les effets de bord des routes Lab.
- [x] Garder `/state` sobre et produit.
- [x] Réserver les détails expérimentaux à `/debug/state` ou à des routes explicitement Lab / debug.
- [x] Vérifier que l’app Swift ne dépend pas d’une route brutalement supprimée.

Sortie attendue de R1e :

> Les routes expérimentales ne sont pas traitées comme produit Core, sans casser brutalement l’existant.

Validation R1e :

- aucune route Lab n’a été désenregistrée brutalement ;
- les routes Core confirmées restent : `/ping`, `/state`, `/debug/state`, `/event`, `/feed`, `/scoring/status`, `/daemon/pause`, `/daemon/resume` ;
- les surfaces Lab identifiées incluent facts / profile, mémoire avancée, LLM léger, debug mémoire, probes, work intent, resume card debug, DayDream read surface et MCP proposals / intercept ;
- `/llm/lightweight/status` expose maintenant `pulse_mode`, `experimental`, `lab_only`, `disabled_in_core` ;
- `/llm/lightweight/pending` ne claim plus de requête en mode Core ;
- `/llm/lightweight/result` retourne `403 lab_surface_disabled` en mode Core ;
- `/memory/write` et `/memory/remove` retournent `403 lab_surface_disabled` en mode Core ;
- `/facts/profile` ne rend plus le profil en mode Core ;
- les mutations facts `reinforce`, `contradict`, `archive` retournent `403 lab_surface_disabled` en mode Core ;
- `/facts`, `/facts/stats`, `/memory`, `/memory/usage` sont marquées Lab via métadonnées sans bloquer la lecture ;
- `/context-probes/*`, `/work-intent/*`, `/debug/resume-card*` et `/mcp/*` restent volontairement non modifiés dans ce patch pour éviter une casse large ;
- aucun changement DayDream / Swift / `create_app()` global / `register_runtime_routes()` global ;
- tests ciblés passés : `tests/test_lightweight_llm_routes.py`, `tests/test_facts_routes.py`, `tests/test_main_memory_routes.py`, `tests/test_main_runtime_state.py`, `tests/test_runtime_routes.py`, `tests/test_main_mcp_routes.py` ;
- fragilité existante notée : certains runs combinés exposent un problème d’ordre d’import autour de `HOME` / `daemon.main`, non corrigé ici car hors scope R1e.

### R1f — Santé Core et tests

Objectif : prouver que le Core fonctionne réellement.

- [ ] Ajouter `/health/core` ou une surface équivalente.
- [ ] Vérifier que `/ping` fonctionne en mode Core.
- [ ] Vérifier que `/state` fonctionne en mode Core.
- [ ] Vérifier que `/feed` fonctionne en mode Core.
- [ ] Ajouter des tests prouvant que le mode Core démarre sans services Lab actifs.
- [ ] Ajouter des tests prouvant que les effets de bord Lab sont absents en mode Core.
- [ ] Ajouter au moins un test prouvant que le mode `lab` ou `dev` peut réactiver les chemins Lab ciblés.

Sortie attendue de R1f :

> Pulse peut démarrer dans un mode minimal, explicite, testable, sans dépendre de ses fonctionnalités expérimentales.

## 13. Notes de vérification R1

Le code actuel confirme que R1 est prioritaire.

Points d’entrée Lab à traiter en premier :

- `RuntimeOrchestrator.__init__` : vérifier l’instanciation systématique du moteur de facts ;
- `deferred_startup()` : gater les opérations facts, memory freeze avancée et DayDream ;
- `handle_event()` : gater le déclenchement DayDream sur événements lock / unlock ;
- `freeze_memory()` : séparer snapshot Core minimale et rendu Lab avancé ;
- `/state` ou `/debug/state` : exposer `pulse_mode` et `experimental_enabled` ;
- `main.create_app()` : inventorier les routes Lab enregistrées directement ;
- `register_runtime_routes()` : inventorier debug memory, probes, work intent, resume cards et lightweight LLM ;
- `_sync_memory_background()` : vérifier les chemins de sync mémoire avancée ;
- `update_memories_from_session()` : vérifier facts, journal intelligent, summaries LLM et vectorisation optionnelle ;
- tests runtime : prouver que le mode Core démarre et fonctionne sans services Lab.

Décision importante : `freeze_memory()` n’est pas entièrement Lab.

En mode Core, elle peut rester utile si elle produit uniquement une représentation minimale, observée et dérivée du contexte courant.

En mode Lab ou Dev, elle peut inclure les rendus avancés : facts, profil, vector store, mémoire narrative ou sémantique.

Cette séparation évite une coupe brutale de la mémoire tout en empêchant les systèmes expérimentaux de devenir des vérités produit.

Décision importante : R1 ne doit pas être un seul gros patch.

Le premier patch technique doit seulement introduire le mode runtime, l’exposer dans les payloads d’état et ajouter les tests associés.

Les gates DayDream, facts, mémoire avancée, LLM léger, routes Lab et santé Core doivent être faits dans des patchs séparés.

Note R1e : toutes les surfaces Lab n’ont pas vocation à être bloquées immédiatement. Les routes à risque faible peuvent être marquées comme Lab via métadonnées. Les routes avec effets de bord critiques doivent être bloquées en Core. Les surfaces complexes comme MCP, probes, work intent et debug resume card doivent être traitées dans des patchs séparés si leur blocage risque de casser des workflows existants.