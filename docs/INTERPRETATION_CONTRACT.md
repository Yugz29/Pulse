# Contrat d'interpretation Pulse

Etat courant au moment de R3a Core Reset. Ce document decrit le comportement qui existe aujourd'hui. Ce n'est pas une architecture cible et il n'introduit aucun nouveau comportement.

## Perimetre

L'interpretation commence apres l'observation R2 :

```text
EventBus -> SignalScorer -> Signals -> RuntimeState/PresentState -> CurrentContext -> WorkContextCard
```

R3 ne couvre pas les LLM, la memoire, les facts, DayDream, les propositions, l'apprentissage ou l'adaptation. Il doit seulement rendre auditables les signaux deja calcules depuis les observations.

## Surfaces principales

| Surface | Role actuel | Produit / debug | Prudence actuelle |
|---|---|---|---|
| `Signals` | Sortie detaillee de `SignalScorer.compute()` | interne, puis legacy `/state.signals` et debug | contient la confiance de tache mais pas de trace detaillee des poids |
| `PresentState` | Projection runtime canonique minimale | `/state.present` et champs top-level de `/state` | plus compacte, peut paraitre plus affirmative car elle n'expose pas `task_confidence` |
| `CurrentContext` | Transformation structuree de `PresentState + Signals` | `/debug/state.current_context`, `/state.current_context` si fourni | restaure `task_confidence` depuis `Signals`, ajoute contexte terminal/app |
| `WorkContextCard` | Carte explicable passive | `/work-context` | reconstruit une explication apres coup ; pas la preuve canonique du scorer |
| `WorkEvidenceResolver` | Resolution prudente du projet et de ses preuves | via `WorkContextCard` | distingue projet observe/probable/faible et warnings |

## `Signals`

`Signals` est defini dans `daemon/core/signal_scorer.py`. C'est la sortie la plus riche du scorer.

Champs principaux :

- `active_project`, `active_file` : projet/fichier actif deduits de fichiers recents, workspace, terminal ou project hint conserve.
- `probable_task` : tache probable calculee par poids heuristiques.
- `task_confidence` : confiance normalisee de la tache, entre `0.0` et `1.0`.
- `activity_level` : activite bas niveau (`editing`, `reading`, `executing`, `navigating`, `idle`).
- `focus_level` : etat de focus (`deep`, `normal`, `scattered`, `idle`).
- `friction_score` : signal de churn/frottement local.
- `edited_file_count_10m`, `file_type_mix_10m`, `rename_delete_ratio_10m`, `dominant_file_mode`, `work_pattern_candidate` : signaux derives des fichiers.
- `recent_apps`, `recent_app_bundle_ids`, `recent_app_system_categories`, compteurs de switchs : signaux derives des apps.
- champs terminal, MCP, presence utilisateur et window title : derniere information utile extraite des events recents.

Comportement actuel du scorer :

- `SignalScorer` lit les derniers evenements de l'`EventBus`.
- Les fichiers `technical_noise` ne sont pas des ancres de scoring.
- Les fichiers attribues `system` ne servent pas d'ancre projet active.
- Les fichiers `tool_assisted` peuvent ancrer un projet mais ne comptent pas comme editions utilisateur.
- `probable_task` est issu de signaux internes comme `dev_app_with_edit`, `source_files_2plus`, `terminal_testing`, `clipboard_stacktrace`, etc.
- Ces signaux internes sont ponderes dans `_TASK_WEIGHTS`.
- Si aucun score ne passe le seuil, la tache retombe sur `general` avec confiance faible.
- `SignalScorer` ne retourne pas aujourd'hui la liste des signaux actifs, les poids, ni une explication structuree.

## `PresentState`

`PresentState` est defini dans `daemon/runtime_state.py`. Il est construit par `RuntimeState.update_present()` depuis `Signals`.

Il expose notamment :

- `active_file`
- `active_project`
- `probable_task`
- `activity_level`
- `focus_level`
- `friction_score`
- `clipboard_context`
- presence utilisateur
- durees app/window
- compteurs de switchs
- `session_duration_min`
- `work_intent`

Limite importante : `task_confidence` existe dans `Signals`, mais n'est pas un champ de `PresentState` aujourd'hui. Donc `/state.present` peut afficher `probable_task: "coding"` sans afficher la confiance associee.

`PresentState` est une projection runtime minimale, pas une preuve. Quand il contient `probable_task`, il faut le lire comme une interpretation heuristique courante, pas comme une verite observee.

## `CurrentContext`

`CurrentContext` est defini dans `daemon/core/contracts.py` et construit par `CurrentContextBuilder`.

Il combine :

- champs canoniques de `PresentState` ;
- `task_confidence` recupere depuis `Signals` ;
- metadata app, terminal, MCP et presence ;
- `project_root` resolu depuis le fichier actif ou le `terminal_cwd` ;
- `SignalSummary`, qui regroupe les metriques detaillees de fichiers/apps.

`CurrentContextBuilder` reste transformateur : pas de persistance, pas de decision, pas de LLM, pas de preuve canonique. Il permet surtout d'eviter un dump plat de `Signals` dans certaines surfaces.

## `WorkContextCard`

`WorkContextCard` est construit par `build_work_context_card()` et expose par `/work-context`.

Il produit :

- `project`, `project_confidence`, `project_status`, `project_source`
- `project_hint`, `project_hint_confidence`, `project_hint_source`
- `activity_level`
- `probable_task`
- `confidence` pour la tache
- `task_status`
- `project_evidence`, `project_warnings`
- `support_apps`
- `evidence`
- `missing_context`
- `safe_next_probes`

Statuts actuels :

- projet : `observed`, `probable`, `weak`, `unknown`
- tache : `probable`, `inferred`, `weak`, `unknown`

Limite importante : `WorkContextCard` reconstruit une explication apres coup depuis `CurrentContext`, `PresentState`, `Signals` et la decision runtime. Cette carte est utile pour debug/transparence, mais elle n'est pas encore la preuve canonique produite par `SignalScorer`.

## `WorkEvidenceResolver`

`WorkEvidenceResolver` resout surtout le projet de travail. Il est plus prudent que le scorer brut.

Sources fortes actuelles :

- `active_project`
- `commit_repo_root`
- `repo_root`
- `terminal_cwd`
- fichiers recents sous une meme racine

Signaux faibles ou insuffisants :

- fichier basename-only
- titre de fenetre seul
- app IA seule
- `project_hint` non corrobore
- `work_intent` non corrobore

Le resolver expose `project_confidence`, `project_source`, `evidence`, `warnings` et `support_apps`. C'est la meilleure surface actuelle pour rendre visible la prudence sur le projet.

## Ou apparaissent les champs R3

| Champ | Source primaire | `/state.present` | `/state.signals` | `/debug/state` | `/work-context` |
|---|---|---|---|---|---|
| `probable_task` | `Signals` -> `PresentState` | oui | oui si `signals` existe | oui | oui |
| `task_confidence` | `Signals` | non | oui si `signals` existe | oui via `signals` / `current_context` | oui sous `confidence` |
| `activity_level` | `Signals` -> `PresentState` | oui | oui | oui | oui |
| `focus_level` | `Signals` -> `PresentState` | oui | oui | oui | non direct, sauf evidence indirecte |
| `active_project` | `Signals` -> `PresentState` | oui | oui | oui | oui |
| preuves detaillees de tache | reconstruites dans `WorkContextCard` | non | non canonique | partiel | oui, mais non canonique |

## Couches de champs

### Observed

Ces donnees viennent directement ou quasi directement d'evenements observes :

- app active et metadata app ;
- chemin de fichier observe ;
- commande terminal normalisee depuis l'evenement terminal ;
- presence utilisateur et idle seconds ;
- lock/unlock et duree de session fournie par le runtime/session.

### Normalized

Ces donnees sont des reformulations deterministes :

- `terminal_command_base`
- `terminal_success`
- `terminal_duration_ms`
- metadata app alignee avec `recent_apps`
- listes recentes triees par fenetre temporelle

### Derived

Ces donnees sont calculees localement depuis les observations :

- `active_project`
- `active_file`
- `project_root`
- `edited_file_count_10m`
- `file_type_mix_10m`
- `dominant_file_mode`
- `rename_delete_ratio_10m`
- `work_pattern_candidate`
- `friction_score`
- `activity_level`
- `focus_level`
- `project_confidence`
- `project_status`

### Inferred

Ces donnees sont heuristiques et ne doivent pas etre presentees comme des faits :

- `probable_task`
- `task_confidence`
- `task_status`
- `project_hint`
- `project_hint_confidence`
- `safe_next_probes`
- evidence textuelle de `WorkContextCard`
- decision runtime recente affichee dans la carte

## Produit vs debug

Surface produit actuelle :

- `/state` expose les champs top-level, `present`, et peut aussi exposer `signals`, `decision`, `session_fsm`, `current_context` ou `recent_sessions` selon l'etat runtime et les callbacks fournis.
- `/state.present` est la projection la plus compacte, mais elle n'expose pas `task_confidence`.

Surface debug / transparence :

- `/debug/state` expose `store`, `runtime`, `signals`, `current_context`, `decision`, `session_fsm` quand disponibles.
- `/work-context` expose la carte explicable passive.
- `/insights` expose des events bruts recents, pas une interpretation.

Limite actuelle : la separation produit/debug n'est pas parfaite. `build_state_payload()` construit aussi le payload debug pour enrichir l'etat produit avec certains champs legacy. R3 devra tester ou corriger cette frontiere plus tard, mais R3a ne la modifie pas.

## Certitude et prudence

Lecture actuelle recommandee :

- `active_project` dans `PresentState` : projet courant derive, pas certitude utilisateur.
- `probable_task` : hypothese heuristique.
- `task_confidence` : confiance relative du scorer, pas probabilite statistique calibree.
- `activity_level` : classification comportementale bas niveau, plus sure que `probable_task` mais encore heuristique.
- `focus_level` : heuristique de presence/switchs/fichiers, pas mesure cognitive.
- `project_hint` : indice faible, ne doit pas etre promu en projet actif.
- `WorkContextCard.evidence` : explication lisible reconstruite, pas trace source du calcul interne.

## Limites explicites R3a

- `SignalScorer` ne retourne pas encore de trace detaillee des signaux actifs, poids ou preuves internes.
- `task_confidence` existe dans `Signals`, mais n'est pas expose dans `PresentState`.
- `/state.present` peut donc paraitre plus affirmatif que le niveau de confiance reel.
- `WorkContextCard` reconstruit une explication apres coup et n'est pas encore la preuve canonique du scorer.
- `WorkEvidenceResolver` explique surtout le projet, pas l'ensemble de `probable_task`, `activity_level` ou `focus_level`.
- Les routes `/state` et `/debug/state` melangent encore certaines surfaces legacy.
- R3b/R3c devront verrouiller les scenarios golden avant toute modification de scoring.

## Garde-fous R3

Ne pas utiliser ce contrat pour ajouter un LLM, des facts, de la memoire intelligente, DayDream, des propositions, de l'apprentissage, de l'adaptation ou de nouvelles categories de taches. R3a documente l'existant ; il ne rend pas Pulse plus intelligent.
