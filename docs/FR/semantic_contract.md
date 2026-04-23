# Contrat sémantique de Pulse

Ce document définit les contrats sémantiques de Pulse.

Il distingue explicitement :
- le **contrat actuel** : ce que le code fait aujourd'hui
- les **limites connues** : ce que le système fait de manière faible, incomplète ou risquée
- les **évolutions cibles** : ce que Pulse devra faire plus tard

Il ne décrit pas un système idéal.

---

# Partie 0 — Contrat du présent runtime

Le présent runtime a maintenant un contrat clair.

## 0.1 Source de vérité

`PresentState`, stocké dans `RuntimeState`, est la seule source de vérité canonique du présent.

Le présent canonique regroupe aujourd'hui :
- l'état de session (`session_status`, `awake`, `locked`)
- le contexte de travail courant (`active_file`, `active_project`, `probable_task`, `activity_level`, `focus_level`)
- quelques champs de surface directement utiles (`friction_score`, `clipboard_context`, `session_duration_min`, `updated_at`)

## 0.2 Producteurs autorisés

Le présent n'a que deux producteurs métier :
- `SessionFSM` pour l'état de session
- `SignalScorer` pour le contexte de travail courant

`RuntimeState.update_present()` stocke ce résultat.
Il ne le recalcule pas.

## 0.3 Ce qui n'est pas canonique

- `signals` : couche de détails et d'enrichissement, utile mais non canonique
- `CurrentContext` : rendu du présent pour la lecture assistant/UI
- `StateStore` : shim legacy
- `SessionMemory` : persistance historique
- `EpisodeFSM` : segmentation temporelle secondaire

Interdits explicites :
- `signals` ne sont pas une source de vérité du présent
- `signals` ne doivent pas être utilisés pour une décision métier
- `signals` ne doivent pas servir à dériver le contexte métier principal
- les épisodes ne participent pas aujourd'hui à la vérité du présent ni à la décision courante

## 0.4 Snapshot atomique

Le runtime expose un snapshot atomique de lecture.

Il existe pour éviter de lire :
- `present`
- `signals`
- `decision`

à des instants différents et de fabriquer un état hybride.

Règle d'implémentation :
- toute lecture qui combine `present`, `signals` et `decision` doit passer par `get_runtime_snapshot()`
- lire ces champs séparément est incorrect

## 0.5 Règle lock / session

Règle produit actuelle :

> verrou court ≠ nouvelle session

Cette règle est implémentée dans `SessionFSM`.
Elle ne doit pas être réinterprétée ailleurs.

## 0.6 `/state`

`/state` reste une projection composite pour compatibilité.

Règle de lecture :
- `present` est le seul noyau canonique
- les champs top-level existent pour compat UI et sont dépréciés
- `debug` est non contractuel
- une nouvelle feature ne doit jamais partir des champs top-level de `/state`

## 0.7 Marqueur de lock legacy

Le marqueur de lock legacy n'est pas canonique.

Il ne doit être utilisé que pour :
- filtrage d'ingress
- debug
- compat

Il ne doit jamais être utilisé comme source métier.

---

# Partie 1 — Contrat de la mémoire

La mémoire actuelle de Pulse reste principalement :
- session-centrique
- heuristique
- rétrospective

---

## 1. Problème à éviter

Pulse peut donner l'impression de comprendre alors qu'il approxime à partir de sessions et d'heuristiques.

Le risque principal est simple :

- une observation modeste
- répétée assez souvent
- promue en fait
- injectée au LLM avec un ton trop affirmatif

L'illusion de compréhension apparaît quand :
- le ton est plus fort que la preuve
- le statut de l'information n'est pas clair
- la documentation décrit comme robuste ce qui reste encore heuristique

---

## 2. Contrat actuel

### 2.1 Nature réelle du système mémoire

Aujourd'hui, Pulse ne comprend pas le travail au sens fort.

Il fait ceci :
- observe des sessions
- projette ces sessions dans un format exploitable
- extrait quelques observations heuristiques
- compte leurs répétitions
- promeut certaines observations en faits
- injecte une partie des faits consolidés dans le contexte LLM

Le système mémoire actuel est donc :
- **session-centrique**
- **heuristique**
- **déterministe jusqu'à la compression LLM**
- **susceptible de se tromper**

Il ne repose pas encore sur :
- des épisodes
- une segmentation fine du travail
- une compréhension causale du comportement utilisateur

### 2.2 Niveaux réels d'information

Le pipeline actuel peut être lu en 5 niveaux.

#### Niveau 1 — Constat local

Ce que Pulse a vu sans interprétation.

Exemples :
- app active
- fichier touché
- durée brute
- friction calculée

Origine :
- événements runtime
- session courante

Statut :
- ponctuel
- non durable

#### Niveau 2 — Contexte courant

Ce que Pulse agrège sur le travail en cours.

Exemples :
- `PresentState`
- `probable_task`
- `focus_level`
- `session_duration_min`

Origine :
- runtime live
- `SessionFSM`
- `SignalScorer`
- `RuntimeState.update_present()`

Statut :
- utile pour le présent
- pas une vérité durable

`CurrentContext` n'est qu'un rendu de lecture de ce niveau.

#### Niveau 3 — Observation heuristique

Ce que Pulse dérive d'une session rétrospective.

Origine :
- `_extract_observations()` dans `facts.py`

Exemples actuels :
- créneau + type de tâche
- focus profond par créneau
- session longue
- friction élevée sur un projet

Statut :
- hypothèse sessionnelle
- pas un fait

#### Niveau 4 — Observation répétée

Une observation heuristique répétée plusieurs fois.

Règle actuelle :
- `count >= SIGNAL_THRESHOLD (3)`

Statut :
- signal plus crédible
- toujours pas un fait stable

#### Niveau 5 — Fait consolidé

Une observation promue dans la table `facts`.

Règle actuelle :
- `count >= FACT_THRESHOLD (5)`
- pas de fait existant sur la même `key`

Création actuelle :
- `confidence = 0.50`
- `autonomy_level = 0`
- `archived = 0`

Statut :
- fait consolidé au sens du système actuel
- pas certitude forte

### 2.3 Règles réelles de promotion

Aujourd'hui, la promotion repose sur :

```text
Observation -> count >= 3  -> signal répété
Observation -> count >= 5  -> création d'un fait
Fait -> confidence < 0.30  -> archivage
```

Le système applique réellement :
- un compteur de répétition
- une confiance initiale
- un decay temporel
- un archivage sous seuil

Le système n'applique pas aujourd'hui :
- une validation sémantique additionnelle au moment de la promotion
- un filtre sur `autonomy_level` avant injection
- un contrôle explicite de qualité des clés au moment de `_promote_pending()`

### 2.4 Rôle réel d'`autonomy_level`

Dans le code actuel :
- `autonomy_level` existe
- il monte sur `reinforce()`
- il baisse sur `contradict()`
- il est stocké dans `facts.db`

Mais :
- il **n'intervient pas** dans `render_for_context()`
- il **ne filtre pas** les faits injectés au LLM
- il n'a pas encore de rôle opérationnel dans une agentique, puisqu'elle n'existe pas

Conclusion :
- `autonomy_level` est actuellement une donnée persistée utile pour le futur
- pas une contrainte active du contrat d'injection

### 2.5 Règle réelle d'injection vers le contexte LLM

Aujourd'hui, `render_for_context()` fait exactement ceci :
- prend les faits actifs
- filtre sur `confidence >= 0.60`
- limite à 8 entrées
- n'utilise pas `autonomy_level`

Ce filtre est le contrat actuel.

Il faut donc lire un fait injecté comme :
- un fait suffisamment répété pour avoir été promu
- encore assez confiant pour passer le seuil 0.60
- pas nécessairement fortement validé par l'utilisateur

### 2.6 Ce que le système mémoire fait réellement bien

Le système actuel est utile pour :
- garder une mémoire locale simple
- éviter de tout réapprendre à chaque session
- injecter des tendances de travail plausibles
- fournir une base déterministe avant toute sophistication ultérieure

Il est cohérent si on l'interprète comme :
- un moteur de tendances
- pas un moteur de compréhension profonde

---

## 3. Limites connues

### 3.1 Le système reste largement heuristique

Les faits dérivent de sessions et de règles simples.

Cela implique :
- une clé mal conçue peut produire un fait trompeur
- la répétition d'une heuristique faible augmente sa fréquence, pas sa vérité
- le système peut consolider un pattern approximatif

### 3.2 Le ton peut rester plus fort que la preuve

Le risque demeure :
- certaines formulations de faits peuvent sembler plus solides qu'elles ne le sont

Le danger n'est pas seulement le stockage.
Le danger est le ton utilisé au moment de l'injection.

### 3.3 `_promote_pending()` est mécanique

La promotion actuelle :
- ne vérifie pas la qualité sémantique de la clé au moment de promouvoir
- ne requalifie pas la robustesse de l'observation
- se contente de créer le fait si le compteur a atteint le seuil

### 3.4 `render_for_context()` est simple, pas robuste

Le filtre actuel par `confidence >= 0.60` est honnête et simple.

Mais il ne distingue pas :
- fait fraîchement promu
- fait confirmé plusieurs fois
- fait à `autonomy_level` plus élevé

### 3.5 L'absence de contradiction n'est pas une preuve

Le système ne contredit pas activement ses propres faits.

### 3.6 La mémoire n'est pas encore structurée par continuité de travail

Elle n'est pas encore organisée par :
- épisodes
- transitions fines
- séquences de travail

Cette limite est structurelle et assumée à ce stade.

---

## 4. Évolutions cibles (mémoire)

Cette section décrit ce que Pulse devra faire plus tard.
Ce n'est **pas** le contrat actuel.

- Rendre l'injection plus sélective : tenir compte d'`autonomy_level`
- Rendre la promotion moins mécanique
- Mieux calibrer le langage des faits
- Séparer plus nettement mémoire utile et mémoire risquée

---

## 5. Règles de lecture et de travail (mémoire)

### Ce qu'il faut considérer comme vrai aujourd'hui

- la mémoire est principalement dérivée des sessions
- les faits sont promus par répétition d'observations heuristiques
- `render_for_context()` filtre par confiance, pas par `autonomy_level`
- le système peut produire des approximations utiles sans vraie compréhension

### Ce qu'il ne faut pas supposer

- qu'un fait injecté est fortement validé
- qu'`autonomy_level` pilote déjà le comportement
- qu'une promotion implique une validation sémantique forte
- que la mémoire reflète déjà une structuration fine du travail

### Ce qu'il faut éviter dans le code

- coder une feature mémoire en supposant que les faits sont plus robustes qu'ils ne le sont
- ajouter des règles implicites non documentées
- parler de "compréhension" quand il s'agit encore d'agrégation heuristique
- documenter comme actuel un comportement seulement souhaité

---

## 6. Résumé opérationnel (mémoire)

- Pulse observe des sessions
- Pulse extrait quelques observations heuristiques déterministes
- Pulse promeut ces observations en faits selon des seuils simples
- Pulse injecte au LLM une sous-partie des faits selon un filtre de confiance

Ce contrat est utile. Il est aussi limité.
Il doit être traité comme une base mémoire exploitable,
pas comme un système de compréhension avancée.

---

---

# Partie 2 — Contrat de l'épisode (Phase 2a + 2b actuel)

Cette section définit le contrat actuel de l'épisode dans Pulse.

Elle couvre :
- les frontières temporelles portées par `EpisodeFSM`
- la sémantique live portée par `PresentState`, avec `signals` comme enrichissement secondaire
- la sémantique figée portée uniquement par les épisodes clos

---

## 7. Ce qu'est un épisode dans Pulse

Un épisode est une **unité temporelle de travail délimitée**, à l'intérieur d'une session.

Il répond à une question simple :
> Pendant combien de temps, et sur quoi, l'utilisateur était-il concentré ?

Un épisode a :
- un début explicable
- une fin explicable
- une durée calculable
- un rattachement à une session
- une sémantique figée seulement lorsqu'il est clos

Un épisode n'est pas :
- une session (plus large, contient plusieurs épisodes)
- la source de vérité sémantique du présent
- la source de vérité du présent
- un journal (résumé rétrospectif, produit après coup)
- un fait (observation promue, pas une unité temporelle)
- un signal (mesure ponctuelle, pas une durée)

---

## 8. Ce qu'un épisode n'est pas aujourd'hui

Le système actuel ne prétend pas résoudre :
- l'intention derrière l'activité
- la distinction fine activité utilisateur vs activité assistée au niveau épisode
- `origin`
- l'enrichissement LLM de l'épisode
- la continuité inter-session via les épisodes

La lecture live du présent reste portée par `PresentState`, pas par `current_episode`.

---

## 9. Modèle actuel de l'épisode

Un épisode porte aujourd'hui :

```
Episode:
  id            : identifiant unique
  session_id    : rattachement à la session parente
  started_at    : timestamp de début (ISO 8601)
  ended_at      : timestamp de fin (null si épisode actif)
  boundary_reason : raison de clôture de l'épisode (null si actif)
  duration_sec  : durée calculée (null si épisode actif)
  probable_task : sémantique figée à la clôture (null si épisode actif)
  activity_level : sémantique figée à la clôture (null si épisode actif)
  task_confidence : sémantique figée à la clôture (null si épisode actif)
```

Règle actuelle :
- épisode actif : vérité essentiellement temporelle ; la lecture live vient de `PresentState`
- épisode clos : snapshot sémantique figé à la clôture

Le runtime garantit qu'un épisode clos ne garde pas de champs sémantiques nuls :
- `probable_task = "unknown"` si aucun snapshot valide n'existe
- `activity_level = "idle"` si aucun snapshot valide n'existe
- `task_confidence = 0.0` si aucun snapshot valide n'existe

Il ne porte pas aujourd'hui :
- `origin` (user_driven / assistant_driven)
- résumé ou enrichissement LLM

---

## 10. Cycle de vie d'un épisode

```
ACTIF -> SUSPENDU -> CLOS
  |                    ^
  +--------------------+
     (frontière détectée)
```

**ACTIF** : un épisode en cours. Il existe un `started_at`, pas de `ended_at`.
Il y a au plus un épisode ACTIF par session à tout moment.

**SUSPENDU** : état intermédiaire optionnel pour les gaps courts
(ex. verrou écran < seuil de frontière dure).
L'épisode n'est pas clos mais est en attente de reprise ou de clôture.

**CLOS** : épisode terminé. `ended_at` est posé,
`duration_sec` est calculé, `boundary_reason` est documentée,
et la dernière sémantique live connue est figée sur l'épisode clos.

Un épisode clos ne peut pas être rouvert.
Il peut être lu rétrospectivement, mais pas rescored par `EpisodeFSM`.

---

## 11. Frontières d'épisode

### 11.1 Signaux durs (frontière certaine)

Ces signaux créent une frontière sans ambiguïté.
Ils clôturent l'épisode courant et en ouvrent un nouveau.

| Signal | End reason | Start reason du suivant |
|---|---|---|
| Verrou écran + gap > seuil | `screen_lock` | `screen_unlock` |
| Commit git confirmé | `commit` | `activity_resumed` |
| Gap d'inactivité > `EPISODE_TIMEOUT_MIN` | `idle_timeout` | `activity_resumed` |

### 11.2 Signaux mous (indice, pas frontière)

Ces signaux suggèrent un possible changement d'épisode
mais ne le déclenchent pas seuls.
Ils sont accumulés et observés, sans déclencher de frontière automatique.

- Changement de type de fichier dominant (source -> docs)
- Friction qui chute brutalement après avoir été élevée
- Changement d'app active vers une catégorie différente
- Gap d'activité fichier > 5 min sans verrou écran
- Changement de projet actif (dérivé du fichier actif — trop fragile pour être signal dur)

### 11.3 Timeout d'épisode

`EPISODE_TIMEOUT_MIN` : gap d'inactivité au-delà duquel un épisode est clos.

Valeur de départ : **20 minutes**.

Ce seuil est distinct de `SESSION_TIMEOUT_MIN` (30 min).
Un épisode peut se terminer sans que la session se termine.

**Sémantique de `ended_at` pour `idle_timeout` :**
`ended_at = last_meaningful_activity_at + EPISODE_TIMEOUT_MIN`

Ce timestamp est calculé au moment de la détection du timeout,
pas au moment où une nouvelle activité reprend.
Cela garantit que la durée de l'épisode reflète le travail réel,
et non le gap d'inactivité qui suit.

---

## 12. Relation épisode / session

```
Session
  └── Episode 1 (clos)
  └── Episode 2 (clos)
  └── Episode 3 (actif)
```

Une session contient zéro ou plusieurs épisodes.
Un épisode appartient à exactement une session.
La clôture d'un épisode ne clôture pas la session.
La clôture d'une session clôture l'épisode actif en cours.

---

## 13. Règles d'implémentation actuelles

### Ce qui doit être vrai dans le code

- Il existe au plus un épisode ACTIF par session à tout instant
- `EpisodeFSM` est la source de vérité des frontières — pas `SessionFSM`, pas le scorer
- `EpisodeFSM` reçoit des signaux normalisés depuis l'orchestrateur — elle ne re-scanne pas le bus seule
- `SignalScorer` reste l'unique source du calcul sémantique (`probable_task`, `activity_level`, `task_confidence`)
- `RuntimeOrchestrator` garantit l'ordre `events -> signals -> freeze -> persist` à la clôture
- Toute frontière détectée produit un `boundary_reason` loggé
- La clôture d'une session clôture l'épisode actif
- Les épisodes sont persistés en SQLite dans `~/.pulse/session.db` (même base que les sessions)
- L'épisode courant est exposé dans `/state` comme champ top-level `current_episode`
- `/state` est une projection composite du runtime, pas une source de vérité
- Un épisode clos porte toujours une sémantique figée non nulle, quitte à utiliser le fallback déterministe

### Ce qu'il faut éviter dans le code

- Déduire la frontière depuis `probable_task` (trop fragile)
- Ouvrir plusieurs épisodes en parallèle
- Confondre fin d'épisode et fin de session
- Recalculer la sémantique dans `EpisodeFSM`
- Utiliser le LLM pour détecter les frontières
- Faire re-déduire à `EpisodeFSM` l'activité significative depuis le bus

### Ce qui est encore hors périmètre aujourd'hui

- `Episode.origin`
- Résumé d'épisode
- Export épisode vers mémoire ou proposals
- Injection de l'épisode dans le contexte LLM
- `project_change` comme signal dur

---

## 14. Ce que le système actuel doit permettre d'observer

Dans le dashboard actuel :

- L'épisode courant est visible : début, durée en cours
- La lecture sémantique du présent vient de `PresentState`, pas de l'épisode actif
- Un historique récent des épisodes clos est visible
- Pour chaque épisode clos : durée, `boundary_reason`, sémantique figée

---

## 14bis. Décisions figées avant implémentation

- Un `Episode` ne porte qu’un seul `boundary_reason`, qui décrit la raison de clôture de l’épisode.
- Pour une clôture par `idle_timeout`, `ended_at` correspond au moment exact d’expiration du seuil d’inactivité, et non au moment de la reprise détectée.
- `project_change` est traité comme un signal opportuniste de frontière, non comme un signal dur garanti.
- La définition de l’activité significative reste celle de la `SessionFSM`, utilisée comme source de vérité par la couche épisode.

---

## 15. Résumé opérationnel (épisode actuel)

Le contrat actuel de l'épisode est le suivant :

- Un épisode reste d'abord une unité temporelle
- Ses frontières sont détectées par des signaux durs déterministes
- `ended_at` pour `idle_timeout` = `last_meaningful_activity_at + EPISODE_TIMEOUT_MIN`
- `project_change` est un signal mou, pas un signal dur
- Il est persisté dans `session.db`, exposé dans `/state`, visible dans le dashboard
- `PresentState` reste la source live du présent
- Un épisode clos porte une sémantique figée (`probable_task`, `activity_level`, `task_confidence`)
- Cette sémantique est figée à la clôture depuis la dernière valeur live connue, avec fallback `unknown / idle / 0.0`
- Il ne sait pas distinguer finement activité utilisateur et activité assistée

Ce contrat reste volontairement borné.
Sa valeur est dans la fiabilité des frontières et dans la stabilité du snapshot des épisodes clos.
