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

R2 n’est pas une phase de scoring, de mémoire, de LLM, de propositions ou d’apprentissage.

Travail cible :

- définir un contrat d’observation ;
- créer des fixtures golden d’événements ;
- tester le pipeline `/event` -> `EventBus` ;
- vérifier le filtrage du bruit ;
- vérifier l’actor classification ;
- stabiliser les événements terminal ;
- vérifier la lisibilité de `/feed`.

Validation :

- les événements utilisateur significatifs influencent l’état ;
- le bruit technique / système est ignoré ou déclassé ;
- la classification de l’acteur est explicable ;
- le feed d’événements est lisible et utile ;
- les tests couvrent des scénarios réalistes ;
- les fixtures golden n’utilisent pas de chemins locaux `/Users/yugz`.

À ne pas faire :

- inférer des habitudes long terme ;
- créer des facts ;
- utiliser un LLM ;
- améliorer le scoring ;
- modifier DayDream ;
- modifier la mémoire avancée ;
- refactorer le Swift observer ;
- brancher globalement `event_envelope.py` dans le runtime.

Découpage recommandé :

- [x] R2a — Contrat d’inventaire observation (`docs/OBSERVATION_CONTRACT.md`) ;
- [x] R2b — Fixtures golden ;
- [x] R2c — Tests pipeline ingestion ;
- [x] R2d — Bruit et actor baseline ;
- [x] R2e — Terminal baseline ;
- [x] R2f — Feed readability baseline.


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

Découpage recommandé :

- [x] R3a — Contrat d’interprétation actuel (`docs/INTERPRETATION_CONTRACT.md`) ;
- [x] R3b — Fixtures golden scoring ;
- [x] R3c — Golden `SignalScorer` ;
- R3d — Evidence / uncertainty baseline ;
- R3e — Payload boundaries ;
- R3f — Anti-overclaim tests.

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
- R1 valide une santé Core sobre via `/health/core` ;
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

La priorité immédiate est désormais R3 — Baseline Interprétation.

R1 — Baseline Runtime est validée côté Python.

R2 — Baseline Observation est validée côté Python.

Prochaines actions :

1. formaliser le contrat d’interprétation actuel ;
2. créer des scénarios golden de scoring ;
3. verrouiller le comportement actuel de `SignalScorer` sans modifier ses heuristiques ;
4. vérifier les preuves et incertitudes exposées par `/work-context` ou les builders associés ;
5. clarifier les frontières `/state` vs `/debug/state` ;
6. ajouter des tests anti-overclaim.

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

- [x] Ajouter `/health/core` ou une surface équivalente.
- [x] Vérifier que `/ping` fonctionne en mode Core.
- [x] Vérifier que `/state` fonctionne en mode Core.
- [x] Vérifier que `/feed` fonctionne en mode Core.
- [x] Ajouter des tests prouvant que le mode Core démarre sans services Lab actifs.
- [x] Ajouter des tests prouvant que les effets de bord Lab sont absents en mode Core.
- [x] Ajouter au moins un test prouvant que le mode `lab` ou `dev` peut réactiver les chemins Lab ciblés.

Sortie attendue de R1f :

> Pulse peut démarrer dans un mode minimal, explicite, testable, sans dépendre de ses fonctionnalités expérimentales.

Validation R1f :

- `/health/core` a été ajouté dans les routes de statut runtime ;
- payload Core sobre : `status`, `pulse_mode`, `experimental_enabled`, `checks`, `failed` ;
- `/health/core` ne dépend pas d’un provider LLM, DayDream, facts, vector store, embeddings, mémoire avancée ou routes Lab ;
- en mode Core, `checks.lab_services` vaut `not_required` ;
- en mode Lab / Dev, `experimental_enabled` passe à `true` et `checks.lab_services` vaut `enabled` ;
- `/ping`, `/state` et `/feed` ont été vérifiés en mode Core ;
- tests ciblés passés : `tests/test_runtime_routes.py`, `tests/test_main_runtime_state.py`, `tests/test_main_mcp_routes.py`, `tests/test_lightweight_llm_routes.py`.

Validation globale R1 :

- suite ciblée R1 passée : 286 tests OK ;
- suite complète `./scripts/test_all.sh` passée : 1162 tests OK ;
- fragilité test identifiée et corrigée séparément : `tests/test_main_memory_routes.py` isolait mal `HOME` en suite complète ;
- correction test sans changement produit : `HOME` est maintenant patché dans `setUp()` et nettoyé via `addCleanup` ;
- R1 — Baseline Runtime est considéré comme validé côté Python.

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

Validation finale R1 : le reset runtime est validé lorsque les tests ciblés R1 passent et que la suite complète Python passe sans erreur. Une correction de test isolée peut être acceptée si elle stabilise l’environnement de test sans modifier le comportement produit. État actuel : R1 validé côté Python avec 286 tests ciblés OK et `./scripts/test_all.sh` OK sur 1162 tests.

## 14. Checklist R2 — Baseline Observation

Objectif : prouver que Pulse observe proprement avant de continuer vers l’interprétation, les sessions et la mémoire minimale.

R2 doit verrouiller ce que Pulse reçoit, garde, ignore, normalise et publie.

R2 ne doit pas chercher à prouver ce que Pulse comprend.

### R2a — Contrat d’inventaire observation

Objectif : figer la liste des événements acceptés et leurs familles.

- [x] Lister les types d’événements acceptés.
- [x] Classer les événements par famille : app, file, terminal, idle, lock, system.
- [x] Définir pour chaque type : source, bucket, relevance, publishable ou non.
- [x] Identifier ce qui est observé, normalisé, dérivé ou inféré.
- [x] Relier ce contrat au code réel : `runtime_ingestion.py`, `event_meaning.py`, `observation_qualification.py`.

Sortie attendue de R2a :

> Pulse possède un inventaire clair des événements qu’il accepte et de ce qu’ils signifient au niveau observation.

Validation R2a :

- contrat ajouté : `docs/OBSERVATION_CONTRACT.md` ;
- le contrat décrit le comportement observation actuel, sans prescrire un futur idéal ;
- familles d’événements inventoriées : app, file, terminal, idle / presence, lock, clipboard, MCP, internal system / debug, unknown ;
- distinction explicite entre champs observés, normalisés, dérivés et inférés ;
- le contrat référence les fixtures golden R2b / R2c existantes ;
- le contrat couvre l’entrée `/event`, `EventMeaningPolicy`, l’attribution `_actor`, la normalisation terminal, le comportement lock / pause, les limites actuelles de `/feed`, et le statut passif de `observation_qualification.py` / `event_envelope.py` ;
- ambiguïtés documentées : `observation_qualification.py` n’est pas encore source de vérité runtime, `event_envelope.py` reste non branché, les events inconnus restent publishable aujourd’hui hors pause / lock, et `scoring_relevant` ne prouve pas encore l’impact réel sur `SignalScorer` ;
- tests ciblés passés : `tests/test_observation_ingestion_golden.py`, `tests/core/test_observation_qualification.py`, `tests/core/test_observation_qualification_consistency.py`, `tests/core/test_event_meaning.py`, `tests/core/test_event_actor.py`, `tests/core/test_file_classifier.py`, `tests/core/test_app_classifier.py`, `tests/core/test_terminal_event_normalizer.py` ;
- suite complète et tests Swift non lancés à cette étape ;
- aucun changement produit.

### R2b — Fixtures golden

Objectif : créer des scénarios d’observation réalistes et portables.

- [x] Créer `tests/fixtures/observation/core_events.json`.
- [x] Ajouter un événement `app_activated`.
- [x] Ajouter un événement fichier source meaningful.
- [x] Ajouter un événement fichier bruité / cache.
- [x] Ajouter un événement `terminal_command_finished`.
- [x] Ajouter un événement `screen_locked`.
- [x] Ajouter un événement `screen_unlocked`.
- [x] Éviter les chemins locaux `/Users/yugz`.
- [x] Utiliser des chemins portables comme `/Users/tester/...` ou `/tmp/workspaces/...`.

Sortie attendue de R2b :

> Les premiers événements golden existent et ne dépendent pas de la machine de développement.

Validation R2b :

- fixture ajoutée : `tests/fixtures/observation/core_events.json` ;
- la fixture couvre `app_activated`, fichier source meaningful, fichier bruité / cache, `terminal_command_finished`, `screen_locked` et `screen_unlocked` ;
- la fixture est portable et n’utilise pas de chemin local `/Users/yugz` ;
- aucun changement produit.

### R2c — Tests pipeline ingestion

Objectif : tester un flux minimal `/event` -> `EventBus` en mode Core.

- [x] Ajouter un test golden `/event` -> `EventBus`.
- [x] Vérifier `app_activated`.
- [x] Vérifier qu’un fichier source meaningful passe dans le bus.
- [x] Vérifier qu’un fichier bruité est filtré ou déclassé selon le comportement réel.
- [x] Vérifier `terminal_command_finished` après normalisation.
- [x] Vérifier `screen_locked` / `screen_unlocked`.
- [x] Vérifier le payload final publié, pas seulement le status HTTP.
- [x] Documenter les comportements ambigus dans les noms ou commentaires de tests.

Sortie attendue de R2c :

> Un premier flux réaliste d’observation est verrouillé par test golden, sans toucher au scoring.

Validation R2c :

- test ajouté : `tests/test_observation_ingestion_golden.py` ;
- le test verrouille un flux minimal `/event` -> `EventBus` -> `/feed` en mode Core ;
- `app_activated` est accepté, publié et met à jour l’application active ;
- un `file_modified` meaningful passe dans l’EventBus avec attribution `_actor` ;
- un fichier cache `.cache/models_cache.json` est filtré selon la policy actuelle ;
- `terminal_command_finished` est normalisé : commande, base command, catégorie, projet, exit code, succès, résumé et `test_result` ;
- `screen_locked` et `screen_unlocked` restent publiables ;
- `/feed` reste lisible après les événements golden et expose un item terminal utile ;
- ambiguïté documentée : le cache est actuellement filtré, pas simplement déclassé ;
- ambiguïté documentée : le fichier source est coalescé, le test ferme donc le coalescer pour forcer l’émission sans `sleep` ;
- tests ciblés passés : `tests/test_observation_ingestion_golden.py`, `tests/core/test_event_meaning.py`, `tests/core/test_event_actor.py`, `tests/core/test_terminal_event_normalizer.py` ;
- suite complète et tests Swift non lancés à cette étape ;
- aucun changement produit.

### R2d — Bruit et actor baseline

Objectif : prouver que le bruit est ignoré / déclassé et que l’acteur est explicable.

- [x] Couvrir les chemins `.pulse`.
- [x] Couvrir les caches.
- [x] Couvrir `site-packages`.
- [x] Couvrir les screenshots.
- [x] Couvrir les dependency locks.
- [x] Couvrir les bursts rapides.
- [x] Couvrir les événements tool-assisted.
- [x] Vérifier que `_actor` est explicable.

Sortie attendue de R2d :

> Pulse sait distinguer les événements utilisateur significatifs, le bruit technique et les événements probablement assistés par outil.

Validation R2d :

- tests ciblés ajoutés dans `tests/core/test_event_actor.py`, `tests/core/test_event_meaning.py`, `tests/core/test_file_classifier.py` et `tests/test_observation_ingestion_golden.py` ;
- `.pulse` reste classé `technical_noise` ;
- caches et `site-packages` sont filtrés ;
- screenshots restent `observe_only` ;
- dependency locks sont `neutral`, `downrank`, filtrés du bus mais encore `scoring_relevant` dans la policy actuelle ;
- répétition rapide d’un même fichier attribuée `system` ;
- burst rapide de fichiers distincts attribué `tool_assisted` ;
- app tool-assisted via `/event` produit un payload final avec `_actor`, `_actor_confidence`, `_automation_score` et `_noise_policy` ;
- ambiguïté documentée : les dependency locks sont déclassés et filtrés du bus par `EventMeaningPolicy`, mais l’actor classifier les considère `tool_assisted` / `downrank` lorsqu’il est appelé directement ;
- ambiguïté documentée : plusieurs anciens tests utilisent encore `/Users/yugz`, mais les nouveaux cas R2d ajoutés utilisent des chemins portables lorsque possible ;
- tests ciblés passés : `tests/core/test_event_actor.py`, `tests/core/test_event_meaning.py`, `tests/core/test_file_classifier.py`, `tests/test_observation_ingestion_golden.py`, `tests/core/test_app_classifier.py`, `tests/core/test_terminal_event_normalizer.py`, `tests/core/test_observation_qualification.py`, `tests/core/test_observation_qualification_consistency.py` ;
- suite complète et tests Swift non lancés à cette étape ;
- aucun changement produit.

### R2e — Terminal baseline

Objectif : stabiliser la normalisation terminal sans LLM.

- [x] Couvrir `pytest`.
- [x] Couvrir `git`.
- [x] Couvrir build.
- [x] Couvrir setup / install.
- [x] Couvrir read-only inspection.
- [x] Couvrir timestamp invalide.
- [x] Couvrir extraction de projet depuis `cwd`.
- [x] Vérifier qu’aucun LLM n’est appelé.

Sortie attendue de R2e :

> Les événements terminal sont normalisés de manière stable, lisible et sans dépendance LLM.

Validation R2e :

- fixtures terminal golden ajoutées dans `tests/fixtures/observation/core_events.json` pour `git status`, `make build`, `npm install` et `rg runtime_mode` ;
- tests de normalisation terminal ajoutés via l’ingestion réelle `/event` dans `tests/test_observation_ingestion_golden.py` ;
- tests unitaires ajoutés dans `tests/core/test_terminal_event_normalizer.py` pour timestamp invalide, read-only inspection, summaries connues et fallback déterministe sans LLM ;
- `pytest` produit `testing` et `test_result` ;
- `git status` produit `vcs`, read-only, succès et projet dérivé depuis `cwd` ;
- `make build` produit `build` ;
- `npm install` produit `setup` ;
- `rg runtime_mode` produit `inspection` et read-only ;
- `terminal_workspace_root` est exposé quand `find_workspace_root()` retourne une racine ;
- timestamp invalide retourne `None` ;
- une commande inconnue marquée `needs_llm=True` utilise un résumé déterministe de catégorie, sans appel LLM ;
- ambiguïté documentée : `make build` expose actuellement `terminal_affects: ["système"]` via `CommandInterpreter`, comportement conservé ;
- ambiguïté documentée : le test sans LLM passe par un faux `interpret()` avec `needs_llm=True` pour verrouiller le fallback déterministe sans introduire de dépendance LLM ;
- tests ciblés passés : `tests/core/test_terminal_event_normalizer.py`, `tests/test_observation_ingestion_golden.py`, `tests/test_runtime_routes.py` ;
- suite complète et tests Swift non lancés à cette étape ;
- aucun changement produit.

### R2f — Feed readability baseline

Objectif : vérifier que `/feed` reste lisible sur un bus réaliste.

- [x] Tester `/feed` sur un bus réaliste.
- [x] Vérifier que les labels ne sont pas génériques.
- [x] Vérifier que le bruit est absent ou déclassé.
- [x] Vérifier que les événements terminal restent lisibles.
- [x] Vérifier que les événements Lab ne dominent pas le feed Core.


Sortie attendue de R2f :

> Le feed expose une observation lisible et utile sans vendre une compréhension avancée.

Validation R2f :

- test `/feed` ajouté dans `tests/test_observation_ingestion_golden.py` sur un bus réaliste avec app, fichier meaningful, bruit filtré, plusieurs commandes terminal et événements internes / Lab ;
- `/feed` retourne des labels terminaux non génériques : `pytest test_app`, `git status`, `Build make`, etc. ;
- le bruit cache filtré n’apparaît pas dans le feed ;
- les fichiers meaningful ne sont pas vendus comme item feed interprété ;
- les événements terminal restent lisibles via `kind`, `success`, `label`, `command`, `timestamp` ;
- des événements internes comme `llm_loading` et `resume_card` peuvent apparaître avec le comportement actuel, mais ne dominent pas un bus Core réaliste riche en événements terminal ;
- le payload feed reste observationnel : pas de tâche probable, projet inféré, résumé mémoire ou prétention de compréhension avancée ;
- ambiguïté documentée : `/feed` expose encore explicitement `llm_loading` et `resume_card` si ces événements sont dans le bus ;
- ambiguïté documentée : `/feed` ne montre pas les fichiers meaningful, comportement actuel conservé ;
- tests ciblés passés : `tests/test_observation_ingestion_golden.py`, `tests/test_runtime_routes.py`, `tests/core/test_event_meaning.py`, `tests/core/test_event_bus.py` ;
- suite complète et tests Swift non lancés à cette étape ;
- aucun changement produit.

Notes R2 :

- `observation_qualification.py` et `event_envelope.py` sont utiles comme contrats passifs, mais ne doivent pas être branchés globalement dans le runtime pendant R2 sans fixtures golden préalables.
- R2 doit rester centré sur l’observation : événements, filtrage, normalisation, acteur, feed.
- R3 seulement pourra renforcer l’interprétation et les signaux.

### Validation globale R2

Statut : terminé côté Python.

- R2a à R2f sont documentés et testés sans changement produit hors tests / documentation.
- Contrat d’observation : `docs/OBSERVATION_CONTRACT.md`.
- Fixtures golden portables : `tests/fixtures/observation/core_events.json`, sans chemin local `/Users/yugz`.
- Pipeline golden : `tests/test_observation_ingestion_golden.py` couvre `/event` -> `EventBus` -> `/feed` en mode Core.
- Tests ciblés R2 validés : `tests/test_observation_ingestion_golden.py`, `tests/core/test_event_meaning.py`, `tests/core/test_event_actor.py`, `tests/core/test_file_classifier.py`, `tests/core/test_app_classifier.py`, `tests/core/test_terminal_event_normalizer.py`, `tests/core/test_event_bus.py`, `tests/core/test_observation_qualification.py`, `tests/core/test_observation_qualification_consistency.py` : 155 tests OK.
- Suite complète Python validée : `./scripts/test_all.sh` : 1176 tests OK.
- Aucun passage à R3 dans cette validation.
- Aucun ajout de scoring, mémoire, LLM, facts, DayDream, propositions, dashboard Swift ou branchement global de `event_envelope.py`.


Fragilités acceptées en sortie de R2 :

- `observation_qualification.py` et `event_envelope.py` restent des contrats passifs, pas la source de vérité runtime.
- `/feed` peut encore exposer des événements internes comme `llm_loading` ou `resume_card` si ces événements sont présents dans le bus ; R2 vérifie seulement qu’ils ne dominent pas un bus Core réaliste.
- Les fichiers meaningful ne sont pas encore projetés comme items feed dédiés ; comportement actuel conservé.
- Certaines fixtures / anciens tests hors golden utilisent encore des chemins développeur historiques ; les fixtures R2 nouvelles restent portables.


## 15. Checklist R3 — Baseline Interprétation

Objectif : prouver que Pulse interprète prudemment les observations, sans sur-vendre une compréhension avancée.

R3 doit verrouiller ce que Pulse dérive depuis les observations fiables de R2.

R3 ne doit pas chercher à rendre Pulse plus intelligent. Il doit prouver ce que le scorer fait déjà, rendre ses sorties auditables, et empêcher les affirmations trop fortes.

### R3a — Contrat d’interprétation actuel

Objectif : documenter les surfaces d’interprétation existantes.

- [x] Documenter les champs `Signals`.
- [x] Documenter les champs `PresentState`.
- [x] Documenter les champs `CurrentContext`.
- [x] Documenter les champs `WorkContextCard`.
- [x] Distinguer observed / normalized / derived / inferred.
- [x] Documenter où apparaissent `probable_task`, `task_confidence`, `activity_level`, `focus_level`.
- [x] Documenter que `task_confidence` existe dans `Signals`, mais n’est pas exposé dans `PresentState`.
- [x] Documenter que `WorkContextCard` reconstruit une explication après coup et n’est pas encore la preuve canonique du scorer.

Sortie attendue de R3a :

> Pulse possède un contrat clair de ce qu’il interprète, où cela apparaît, et avec quel niveau de prudence.

Validation R3a :

- contrat ajouté : `docs/INTERPRETATION_CONTRACT.md` ;
- le contrat décrit le comportement actuel, pas une architecture cible ;
- surfaces couvertes : `Signals`, `PresentState`, `CurrentContext`, `WorkContextCard`, `WorkEvidenceResolver`, `/state`, `/debug/state`, `/work-context` ;
- distinction documentée entre champs observés, normalisés, dérivés et inférés ;
- limites explicites documentées : `SignalScorer` ne retourne pas encore de trace détaillée des poids / preuves internes, `task_confidence` existe dans `Signals` mais pas dans `PresentState`, `/state.present` peut paraître plus affirmatif que la confiance réelle, et `WorkContextCard` reconstruit une explication après coup ;
- tests non lancés : documentation only ;
- aucun changement produit.

### R3b — Fixtures golden scoring

Objectif : créer des scénarios portables d’interprétation.

- [x] Créer `tests/fixtures/interpretation/scoring_scenarios.json`.
- [x] Ajouter un scénario code editing.
- [x] Ajouter un scénario terminal tests failed.
- [x] Ajouter un scénario browser / read-only exploration.
- [x] Ajouter un scénario idle.
- [x] Ajouter un scénario noisy / tool-assisted files.
- [x] Éviter les chemins locaux `/Users/yugz`.
- [x] Réutiliser les principes de `docs/OBSERVATION_CONTRACT.md`.

Sortie attendue de R3b :

> Les premiers scénarios golden d’interprétation existent et restent portables.

Validation R3b :

- fixture ajoutée : `tests/fixtures/interpretation/scoring_scenarios.json` ;
- scénarios couverts : code editing, terminal tests failed, browser / read-only exploration, idle, noisy / tool-assisted files ;
- chaque scénario contient un nom lisible, une intention de test, des événements compatibles avec `SignalScorer`, des `compute_args`, des attentes minimales futures et des notes ;
- les chemins sont portables et n’utilisent pas `/Users/yugz` ;
- test de structure ajouté : `tests/test_interpretation_scoring_fixtures.py` ;
- test ciblé passé : `tests/test_interpretation_scoring_fixtures.py` ;
- aucun appel à `SignalScorer.compute()` dans R3b ;
- aucun changement produit.

### R3c — Golden `SignalScorer`

Objectif : verrouiller le comportement actuel du scorer sans modifier les heuristiques.

- [x] Charger les fixtures R3b.
- [x] Appeler directement `SignalScorer.compute()`.
- [x] Vérifier `probable_task`.
- [x] Vérifier `task_confidence`.
- [x] Vérifier `activity_level`.
- [x] Vérifier `focus_level`.
- [x] Vérifier projet actif / fichier actif si disponible.
- [x] Documenter les comportements ambigus dans les noms ou commentaires de tests.
- [x] Ne pas modifier `SignalScorer` sauf incohérence évidente.

Sortie attendue de R3c :

> Le comportement actuel du scorer est verrouillé par scénarios golden lisibles.

Validation R3c :

- test golden ajouté : `tests/test_interpretation_signal_scorer_golden.py` ;
- les scénarios R3b appellent maintenant directement `SignalScorer.compute()` ;
- champs verrouillés : `probable_task`, `task_confidence`, `activity_level`, `focus_level`, projet actif / fichier actif quand applicable, signaux terminal et compteur d’éditions quand applicable ;
- scénarios verrouillés : code editing, terminal tests failed, browser / read-only exploration, idle, noisy / tool-assisted files ;
- ambiguïtés documentées dans la fixture : le fichier actif suit le dernier fichier du workspace dominant, un test terminal échoué seul produit `debug` avec confiance seulement modérée, et `probable_task` peut rester `coding` pendant que `activity_level` / `focus_level` sont `idle` ;
- tests ciblés passés : `tests/test_interpretation_signal_scorer_golden.py`, `tests/test_interpretation_scoring_fixtures.py`, `tests/core/test_signal_scorer.py` ;
- aucun changement produit et aucune modification de `SignalScorer`.

### R3d — Evidence / uncertainty baseline

Objectif : vérifier que l’interprétation exposée reste explicable ou incertaine.

- [ ] Tester `/work-context` ou les builders associés.
- [ ] Vérifier que les preuves sont visibles quand une tâche / un projet est proposé.
- [ ] Vérifier que l’incertitude est visible quand les preuves sont faibles.
- [ ] Vérifier que `project_hint` faible ne devient pas projet confirmé.
- [ ] Vérifier que `general` ou contexte faible ne produit pas une affirmation forte.
- [ ] Vérifier les statuts `observed`, `probable`, `inferred`, `weak` si exposés.

Sortie attendue de R3d :

> Pulse sait montrer pourquoi il pense quelque chose, ou dire que la preuve est faible.

### R3e — Payload boundaries

Objectif : clarifier les frontières entre surface produit et surface debug.

- [ ] Vérifier `/state`.
- [ ] Vérifier `/debug/state`.
- [ ] Vérifier où `signals` legacy est exposé.
- [ ] Vérifier que `/state.present` ne paraît pas plus affirmatif que les signaux réels.
- [ ] Vérifier que les détails expérimentaux / debug restent hors surface produit si possible.
- [ ] Documenter les limites si aucun refactor n’est fait.

Sortie attendue de R3e :

> Les payloads d’état ne vendent pas une interprétation plus sûre que ce que les signaux prouvent.

### R3f — Anti-overclaim tests

Objectif : ajouter des tests négatifs contre les interprétations trop fortes.

- [ ] Pas de projet confirmé depuis un titre de fenêtre seul.
- [ ] Pas de `coding` fort depuis une app inconnue seule.
- [ ] Pas de debug fort depuis une stacktrace ancienne isolée.
- [ ] Pas de browsing fort depuis un navigateur ancien ou isolé.
- [ ] Pas d’action ou proposition déclenchée par un signal faible.
- [ ] Vérifier que `DecisionEngine` ne transforme pas un signal faible en action produit.

Sortie attendue de R3f :

> Pulse évite les interprétations trop confiantes quand les preuves sont faibles.

Notes R3 :

- R3 est une phase d’interprétation prudente, pas d’intelligence.
- `SignalScorer` est le cœur R3, mais il ne doit pas être rendu plus intelligent avant d’être couvert par scénarios golden.
- `WorkContextCard` et `WorkEvidenceResolver` sont les meilleures surfaces d’explicabilité actuelles, mais elles ne remplacent pas encore une preuve canonique issue du scorer.
- `DecisionEngine`, `context_formatter.py`, propositions, LLM et mémoire restent hors R3 strict.
