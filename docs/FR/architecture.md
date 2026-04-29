# Pulse — Architecture runtime actuelle

Ce document décrit le runtime tel qu'il existe dans le code actuel.

Il ne décrit pas une cible théorique.
Il ne décrit pas une vision produit.
Si le code et ce document divergent, le code a raison.

La roadmap de référence reste [refactor-roadmap.md](./refactor-roadmap.md).

---

## 1. Pipeline réel

Le pipeline runtime réel est :

```text
event
→ SessionFSM
→ SignalScorer
→ RuntimeState.update_present()
→ DecisionEngine
→ SessionMemory
```

Plus précisément :

```text
macOS / Swift observation
→ POST /event
→ EventBus
→ RuntimeOrchestrator
→ SessionFSM.observe_recent_events()
→ SignalScorer.compute()
→ RuntimeState.update_present()
→ DecisionEngine.evaluate()
→ SessionMemory.update_present_snapshot()
```

Le rôle de `RuntimeOrchestrator` est d'enchaîner ce flux.
Il ne doit pas redevenir une source de vérité métier parallèle.

---

## 2. Source de vérité du présent

`PresentState`, stocké dans `RuntimeState`, est la seule source de vérité canonique du présent.

Il regroupe aujourd'hui :
- `session_status`
- `awake`
- `locked`
- `active_file`
- `active_project`
- `probable_task`
- `activity_level`
- `focus_level`
- `friction_score`
- `clipboard_context`
- `session_duration_min`
- `updated_at`

Règle de lecture :
- si un lecteur veut savoir ce qui est vrai maintenant, il doit lire `RuntimeState.present`
- il ne doit pas reconstruire le présent depuis `signals`, `StateStore`, `SessionMemory` ou `CurrentContext`

---

## 3. Responsabilités réelles des couches

| Couche | Rôle réel aujourd'hui | Ce qu'elle ne doit pas faire |
|---|---|---|
| `EventBus` | transporter les événements récents | porter un état métier |
| `SessionFSM` | produire l'état de session et les frontières de session | calculer le contexte de travail |
| `SignalScorer` | produire le contexte de travail courant | stocker le présent |
| `RuntimeState` | stocker `PresentState` et exposer un snapshot atomique de lecture | recalculer la sémantique |
| `RuntimeOrchestrator` | coordonner le pipeline runtime | devenir une god-source de vérité |
| `DecisionEngine` | décider à partir de `PresentState` | reconsommer `signals` directement comme source principale |
| `CurrentContextBuilder` | rendre un `CurrentContext` à partir de `present` | devenir une source de vérité |
| `SessionMemory` | persister l'historique et les snapshots | corriger ou écrire le présent |
| `StateStore` | shim de compat legacy | dériver `active_file`, `active_project` ou l'état session |

---

## 4. Producteurs du présent

Le présent n'a que deux producteurs métier :

- `SessionFSM` produit l'état de session :
  - `session_status`
  - `awake`
  - `locked`
- `SignalScorer` produit le contexte de travail :
  - `active_file`
  - `active_project`
  - `probable_task`
  - `activity_level`
  - `focus_level`
  - `friction_score`
  - `clipboard_context`
  - `session_duration_min`

`RuntimeState.update_present()` assemble ces sorties et les stocke.
Il ne recalcule rien.

---

## 5. Snapshot atomique runtime

Le runtime expose un snapshot de lecture atomique via `RuntimeState.get_runtime_snapshot()`.

Il contient aujourd'hui :
- `present`
- `signals`
- `decision`
- `paused`
- `memory_synced_at`
- `latest_active_app`
- `lock_marker_active`
- `last_screen_locked_at`

Pourquoi il existe :
- éviter qu'une route ou un helper lise `present`, puis `signals`, puis `decision` à des instants différents
- éviter les réponses hybrides où le présent et la décision ne correspondent pas au même instant logique

Règle :
- les chemins de lecture runtime doivent lire ce snapshot atomique
- ils ne doivent plus faire plusieurs lectures séparées de `RuntimeState`
- toute lecture qui combine `present`, `signals` et `decision` doit passer par `get_runtime_snapshot()`
- lire `present`, `signals` et `decision` séparément est incorrect

---

## 6. Lecture et exposition

### `CurrentContext`

`CurrentContext` n'est plus une source de vérité.

C'est un rendu du présent pour les couches assistant/UI.

Ce qu'il lit depuis `present` :
- `active_project`
- `active_file`
- `session_duration_min`
- `activity_level`
- `probable_task`
- `focus_level`
- `clipboard_context`

Ce qu'il lit encore depuis `signals` :
- `task_confidence`
- métadonnées terminal
- métadonnées MCP
- `signal_summary`

Donc :
- `CurrentContext` est utile
- `CurrentContext` n'est pas canonique
- `signals` restent une dépendance secondaire bornée
- `signals` ne sont pas une source de vérité du présent
- `signals` ne doivent pas être utilisés pour une décision métier
- `signals` ne doivent pas servir à dériver le contexte métier principal

### `/state`

`/state` est une projection du snapshot runtime.

Règle de lecture :
- `present` = canonique
- top-level = compat temporaire et dépréciée
- `debug` = non contractuel

Ne pas utiliser `signals` comme source principale de vérité.
Ne pas utiliser les champs top-level comme base de nouvelles features.

Le payload `/state` actuel mélange encore :
- un noyau canonique :
  - `present`
- des champs top-level de compat :
  - `active_app`
  - `active_file`
  - `active_project`
  - `session_duration_min`
  - `runtime_paused`
- des blocs de compat/debug :
  - `signals`
  - `decision`
  - `session_fsm`
  - `current_context`
  - `recent_sessions`
  - `current_episode` alias legacy
  - `recent_episodes` alias legacy
  - `debug`

---

## 7. Règle lock / session

Règle produit actuelle :

> verrou court ≠ nouvelle session

Cette règle est implémentée dans `SessionFSM`.

Concrètement :
- un lock long peut fermer la session courante et en ouvrir une autre à la reprise
- un lock court conserve la session courante
- le premier event significatif après un lock court ne doit pas créer une session fantôme

L'orchestrateur ne corrige pas cette règle après coup.
La frontière est décidée dans `SessionFSM`.

---

## 8. Contexte et historique de travail

`EpisodeFSM` a été supprimé du runtime.

Le modèle actuel est plus simple :
- `current_context` : lecture produit du contexte courant
- `recent_sessions` : sessions fermées récentes, pour l'historique
- `work_blocks` : blocs de travail dérivés des événements significatifs
- `work_block_*` : fenêtre de travail utilisée par la mémoire et la ResumeCard

Les anciens noms restent exposés seulement pour compatibilité :
- `current_episode`
- `recent_episodes`
- `work_window_*`
- `closed_episodes`

Ces alias ne doivent pas servir à écrire de nouvelles features.

---

## 9. Couches legacy restantes

Les reliquats suivants existent encore :

- `StateStore` : shim passif de compat
- marqueur de lock legacy dans `RuntimeState` : utile pour filtrage d'ingress / debug / compat, non canonique
- payload top-level `/state` : conservé pour compat UI et déprécié
- adaptateurs markdown / legacy : encore alimentés par `signals` pour certains détails secondaires
- alias API : `current_episode`, `recent_episodes`, `work_window_*`, `closed_episodes`

Ces reliquats ne doivent pas être relus comme des sources de vérité concurrentes.

---

## 10. Limites actuelles

- `CurrentContext` dépend encore partiellement de `signals`
- `/state` garde encore du legacy pour compat UI et debug
- le marqueur de lock legacy existe encore en parallèle du `present.locked`
- l'extracteur mémoire contient encore du vocabulaire historique d'épisodes
- `SessionSnapshot` reste une projection de compat, pas la forme canonique du présent

---

## 11. Règle de lecture correcte

Pour lire le runtime correctement aujourd'hui :

1. lire `RuntimeState.present` pour le présent canonique
2. lire le snapshot atomique pour les chemins de lecture complets
3. lire `CurrentContext` comme un rendu
4. lire `signals` comme une couche de détails secondaires
5. lire `StateStore` et les champs top-level `/state` comme compat, pas comme vérité
6. lire `work_blocks` / `work_block_*` pour le temps de travail, pas les alias `work_window_*`
