# Session Contract

Etat courant au moment de R4a Core Reset. Ce document decrit le comportement qui existe aujourd'hui. Ce n'est pas une architecture cible et il n'introduit aucun nouveau comportement.

## Perimetre

R4 commence apres l'observation R2 et l'interpretation R3 :

```text
EventBus -> SessionFSM -> RuntimeOrchestrator -> RuntimeState / SessionMemory -> /state
```

R4 doit prouver que Pulse suit les sessions de travail de maniere comprehensible et reparable. R4 ne couvre pas la memoire avancee, les facts, DayDream, les LLM, les propositions, les resume cards intelligentes, le commit episode linking, l'apprentissage ou l'adaptation.

## Surfaces principales

| Surface | Role actuel | Core R4 strict |
|---|---|---|
| `SessionFSM` | Cycle runtime minimal de session | oui |
| `RuntimeOrchestrator` | Branche les events, applique la FSM, met a jour runtime et persistence | oui, seulement chemins session |
| `RuntimeState` / `PresentState` | Projection runtime exposee dans `/state` | oui |
| `SessionMemory` | Persistance SQLite de la session courante et des events | oui, seulement persistence minimale |
| `SessionSnapshotBuilder` | Snapshot structure depuis SQLite + events recents | oui, comme adaptateur minimal |
| `RestartManager` | Reprise courte / partielle / ignoree apres restart | oui, sauf commit recovery |
| `/memory/sessions` | Lecture de journaux Markdown legacy | non comme preuve principale Core |
| `work_heartbeat.py` | Classification pour work blocks / summaries memoire | non pour R4 strict |

## Etats reels

La roadmap mentionne `started`, `active`, `idle`, `paused`, `resumed`, `closed`. Le code actuel ne modelise pas tout cela dans une seule FSM.

### `SessionFSM`

`SessionFSM` ne possede que trois etats :

- `idle`
- `active`
- `locked`

Il expose aussi :

- `session_started_at`
- `last_meaningful_activity_at`
- `last_screen_locked_at`
- `SessionTransition`, avec `boundary_detected`, `boundary_reason`, `should_reset_clock`, `should_start_new_session`, `should_clear_sleep_markers`, `sleep_minutes`

`started` n'est pas un etat FSM. C'est un instant (`session_started_at`) qui peut etre initialise, restaure ou remplace.

### Pause runtime

`paused` n'est pas un etat de session. C'est un flag de `RuntimeState`.

Quand le runtime est en pause, `RuntimeOrchestrator.handle_event()` retourne avant d'enregistrer l'event dans la session. La route `/event` renvoie aussi une reponse `paused` / `ignored` dans le contrat d'observation. Cette pause signifie "le runtime ignore les nouveaux events", pas "la session FSM est paused".

### Fermeture

`closed` n'est pas un etat FSM. C'est une persistance cote `SessionMemory` :

- `close()` renseigne `ended_at` et `session_duration_min` sur la ligne SQLite courante.
- `new_session()` ferme la session courante puis cree une nouvelle ligne SQLite.
- `_repair_stale_open_rows()` ferme au demarrage les lignes ouvertes d'une ancienne instance.

### Reprise

`resumed` n'est pas un etat FSM unique.

Aujourd'hui, la reprise signifie au minimum l'un de ces comportements :

- `RestartManager.apply()` restaure `session_started_at` dans `SessionFSM` pour un redemarrage court.
- `SessionMemory.resume_session()` realigne la session SQLite courante sur le `started_at` restaure.
- `SessionFSM.on_screen_unlocked()` remet l'etat a `active` apres un lock valide.

Ces cas doivent etre testes separement. Les appeler tous `resumed` masque des comportements differents.

## Cycle runtime actuel

### Activite significative

`SessionFSM.observe_recent_events()` cherche la derniere activite significative dans les events recents.

Activites fortes actuelles :

- `file_created`, `file_modified`, `file_renamed` si le chemin est `meaningful` ;
- `terminal_command_started`, `terminal_command_finished` ;
- app `dev_tool`, sauf le cas special actuel ou `Code` seul ne demarre pas une activite forte.

Activites de support :

- browser ou writing app active ;
- `local_exploration` ;
- `mcp_command_received` ;
- `mcp_decision`.

Une activite de support ne peut prolonger une session que si une activite forte existe deja dans la fenetre de timeout.

### Idle

`on_user_idle()` met la FSM a `idle`, sauf si elle est `locked`.

Sans nouvelle activite significative, `observe_recent_events()` remet aussi la FSM a `idle` quand l'ecart depuis `last_meaningful_activity_at` depasse `SESSION_TIMEOUT_MIN` (30 minutes).

### Lock / unlock

`on_screen_locked()` :

- enregistre `last_screen_locked_at` si la FSM n'etait pas deja `locked` ;
- met l'etat FSM a `locked`.

`on_screen_unlocked()` :

- ignore l'unlock si aucun lock valide n'est connu ;
- calcule `sleep_minutes` depuis `last_screen_locked_at` ;
- si `sleep_minutes >= sleep_session_threshold_min`, demarre une nouvelle session runtime en mettant `session_started_at` a l'heure d'unlock ;
- si le lock est court, conserve le `session_started_at` precedent et marque le lock comme ignore pour eviter une fausse frontiere ensuite ;
- remet l'etat FSM a `active` apres un lock valide.

`RuntimeState` maintient aussi des lock markers (`mark_screen_locked`, `mark_screen_unlocked`, `clear_sleep_markers`) pour filtrer les events et garder le premier timestamp de lock.

## Integration orchestrateur

`RuntimeOrchestrator.handle_event()` applique les contraintes runtime avant de traiter les sessions :

- ignore les events explicitement ignores ;
- ignore `resume_card` ;
- ignore tous les events si `RuntimeState` est paused ;
- pendant un lock, laisse passer seulement `screen_locked` et `screen_unlocked`.

Pour `screen_locked`, l'orchestrateur :

- appelle `SessionFSM.on_screen_locked()` ;
- appelle `RuntimeState.mark_screen_locked()` ;
- ne lance DayDream qu'en mode Lab.

Pour `screen_unlocked`, l'orchestrateur :

- peut reconstruire le lock dans la FSM depuis le marker `RuntimeState` ;
- appelle `SessionFSM.on_screen_unlocked()` ;
- appelle `RuntimeState.mark_screen_unlocked()` ;
- sur longue pause, rafraichit les signaux de fermeture puis appelle `SessionMemory.new_session()` ;
- en Core, ne declenche pas de sync memoire avancee pre-reset ; en Lab, le chemin legacy peut encore le faire.

`_process_signals()` est le chemin principal apres publication d'un event :

- applique `on_user_idle()` pour `user_idle` ;
- appelle `observe_recent_events()` ;
- calcule les signaux avec `session_started_at` fourni au scorer ;
- met a jour `RuntimeState.update_present()` avec l'etat FSM courant ;
- met a jour `SessionMemory.update_present_snapshot()` ;
- peut demander une sync memoire sur frontiere, mais `_sync_memory_background()` est gatee en Core.

## Duree de session

La duree exposee par `PresentState.session_duration_min` vient de `SignalScorer.compute()`, appele avec `session_started_at=self._session_fsm.session_started_at` et un `observed_now` derive des events / du present precedent.

`SessionMemory.update_present_snapshot()` ecrit ensuite cette duree dans SQLite. Les tests R4 devront donc verifier la chaine :

```text
SessionFSM.session_started_at -> SignalScorer.session_duration_min -> PresentState.session_duration_min -> SessionMemory.session_duration_min
```

`SessionMemory` garde aussi une duree derivee depuis les timestamps observes pour `record_event()`, `close()` et certains fallbacks. Cela ne doit pas etre confondu avec la duree runtime canonique affichee dans `/state`.

## Surfaces API

### `/state`

`build_state_payload()` expose notamment :

- `session_duration_min` au top-level ;
- `runtime_paused` ;
- `present`, qui contient `session_status`, `awake`, `locked`, `session_duration_min`, `updated_at` ;
- `session_fsm` seulement si un callback `get_session_fsm` est fourni ;
- `recent_sessions` seulement si un callback `get_recent_sessions` est fourni.

### `/debug/state`

`build_debug_state_payload()` expose les memes donnees enrichies :

- `debug.runtime.lock_marker_active`
- `debug.runtime.last_screen_locked_at`
- `debug.session_fsm` si disponible
- `debug.recent_sessions` si disponible

Les surfaces produit/debug ne sont pas encore parfaitement separees ; ce point reste aligne avec le contrat R3.

### `/memory/sessions`

`/memory/sessions` lit des fichiers Markdown sous `~/.pulse/memory/sessions`.

Cette route n'est pas la preuve principale de la session Core. Elle expose des journaux legacy / memoire minimale et peut contenir des payloads caches masques. R4 doit s'appuyer d'abord sur `SessionFSM`, `RuntimeState`, `SessionMemory` SQLite et les payloads `/state` / `/debug/state`.

## Session runtime, session persistante, work blocks, episodes, journal

Ces notions ne sont pas interchangeables :

- session runtime : etat courant de `SessionFSM` + projection `PresentState` ;
- session persistante : ligne SQLite `sessions` + events dans `SessionMemory` ;
- work blocks : clusters d'activite de travail construits depuis les events, utilises par les summaries / vues memoire ;
- episodes : regroupements plus riches dans la couche memoire / debug ;
- journal Markdown : sortie historique lisible, pas source canonique du runtime ;
- memoire avancee : facts, vector store, DayDream, LLM summaries, commit linking, hors R4 strict.

`daemon/memory/work_heartbeat.py` appartient a la couche memoire. Meme si son nom parle de work heartbeat, il ne doit pas etre traite comme moteur Core de session pendant R4.

## Restart

`RestartManager` applique trois cas :

- moins de 5 minutes : reprise transparente, `SessionFSM.restore_session_start()` et `SessionMemory.resume_session()` sont appeles ;
- 5 a 30 minutes : reprise partielle, contexte logue mais timer non restaure ;
- plus de 30 minutes : restart ignore.

`RestartManager.recover_missed_commits()` detecte et journalise des commits manques. Ce chemin est hors R4 strict parce qu'il touche commit recovery et journalisation memoire.

## Limites explicites R4a

- `SessionFSM.session_started_at` est initialise des la construction de la FSM. Il peut donc exister avant une vraie activite si on le lit sans `last_meaningful_activity_at` ou sans `session_status`.
- `started`, `paused`, `resumed` et `closed` ne sont pas des etats FSM actuels.
- `paused` est un flag runtime qui bloque l'ingestion / orchestration, pas une pause de session persistante.
- `closed` est une ligne SQLite fermee via `ended_at`, pas un etat runtime.
- `/memory/sessions` est une surface Markdown legacy, pas la preuve principale Core session.
- `SessionMemory.export_memory_payload()` contient encore des alias legacy (`work_window_*`, `closed_episodes`) pour compatibilite.
- `RestartManager.recover_missed_commits()` est hors R4 strict.
- `work_heartbeat.py` appartient au dossier memoire et ne doit pas etre promu en moteur Core session.
- `SessionFSM` ne doit pas devenir un moteur memoire.

## Garde-fous R4

Ne pas utiliser R4 pour ajouter ou reparer DayDream, facts, vector store, LLM summaries, resume cards intelligentes, commit episode linking, propositions, apprentissage ou adaptation. R4 doit seulement rendre la session runtime et sa persistence minimale comprehensibles, testables et reparables.
