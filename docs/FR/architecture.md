# Pulse — Architecture progressive

Ce document décrit l'architecture de Pulse de manière exploitable pour le code actuel.

Il distingue explicitement :
- ce qui est **implémenté aujourd'hui**
- ce qui est **stabilisé**
- ce qui relève encore de la **cible**
- ce qui n'a **pas encore commencé**

La feuille de route de référence reste [refactor-roadmap.md](/Users/yugz/Projets/Pulse/Pulse/docs/refactor-roadmap.md).

---

## 1. Positionnement

Pulse est un système local d'observation du travail qui :
- capte des événements système et de travail
- les qualifie et les transforme en signaux utiles
- structure le contexte courant
- consolide une mémoire locale
- émet des propositions explicables

Pulse n'est pas un agent autonome.

Pulse reste aujourd'hui un système :
- d'observation
- d'interprétation limitée
- de mémoire locale
- de suggestions

L'architecture cible reste :

Observation -> Qualification -> Activity -> Interpretation -> Episode -> Session -> Memory -> Proposal

Mais toutes ces couches ne sont pas au même niveau de maturité.

---

## 2. État réel du système

### Implémenté et stabilisé

- Observation des événements locaux via l'app Swift et le daemon Python
- Qualification d'événements côté runtime (`actor`, `noise_policy`, domaine implicite selon le type de fichier ou d'action)
- Calcul temps réel des signaux de travail
- `activity_level` et `task_confidence` exposés dans `/state`
- `session_fsm` exposé dans `/state`
- `CurrentContext` comme vue synthétique du runtime
- `SessionSnapshot` comme projection structurée de session
- `ProposalCandidate` comme contrat métier avant transport legacy
- `SessionFSM` comme source de vérité du lifecycle de session
- `EpisodeFSM` comme source de vérité des frontières temporelles d'épisode
- Persistance SQLite des épisodes dans `session.db`
- `current_episode` et `recent_episodes` exposés via `/state` comme projection runtime
- Sémantique d'épisode figée uniquement à la clôture (`probable_task`, `activity_level`, `task_confidence`)
- Dashboard technique côté app (`DashboardWindow`) dans une fenêtre indépendante avec rendu glassmorphism
- Observabilité Phase 1 : logs `CurrentContextBuilder`, fallback mémoire explicite dans `freeze_memory()`, transitions FSM loggées
- Route `/memory/sessions` pour exposer les journaux de session
- Compat legacy verrouillée sur :
  - `build_context_snapshot()`
  - `/state`
  - `export_session_data()`

### Implémenté mais encore transitoire

- `StateStore` reste présent pour compat
- Le snapshot Markdown de contexte reste exposé pour la couche assistant/LLM
- Un shim de compat existe entre `RuntimeState` et `SessionFSM` autour du marqueur de lock

### Non démarré

- Proposals réellement contextualisées par épisode
- Mémoire enrichie pilotée par épisodes
- Agentique contrôlée

---

## 3. Architecture cible vs état actuel

| Couche | Rôle cible | État actuel |
|---|---|---|
| Observation | capter les événements bruts | implémenté |
| Qualification | attribuer source et politique de traitement | implémenté |
| Activity | décrire ce que fait l'utilisateur maintenant | partiellement implémenté via `activity_level` |
| Interpretation | inférer tâche, friction, patterns | implémenté |
| Episode | segmenter le travail en segments temporels puis porter une sémantique figée | implémenté, encore limité à des frontières temporelles + snapshot figé à la clôture |
| Session | contenir le travail entre frontières temporelles | implémenté, avec épisodes persistés mais sans exploitation riche côté mémoire/proposals |
| Memory | consolider des faits et résumés rétrospectifs | implémenté, encore principalement session-centrique |
| Proposal | suggérer des actions explicables | implémenté, encore local et limité |

Le point clé : **Pulse possède maintenant une couche Episode exploitable pour les frontières temporelles et l'historique récent, mais pas encore une exploitation riche par mémoire et proposals**.

---

## 4. Couches actuelles du runtime

### 4.1 Observation

**Statut** : implémenté

Pulse reçoit des événements bruts tels que :
- `file_modified`
- `file_created`
- `app_activated`
- `clipboard_updated`
- `screen_locked`
- `screen_unlocked`
- événements liés au commit via observation des fichiers git

Un event reste une observation brute :
- `type`
- `payload`
- `timestamp`

À ce niveau, il n'y a pas d'interprétation métier.

### 4.2 Qualification

**Statut** : implémenté

Avant le scoring, Pulse enrichit certains événements avec des métadonnées d'attribution :
- `actor`
- `noise_policy`
- scores ou marqueurs liés à l'origine probable de l'événement

But :
- distinguer activité utilisateur, système, et activité assistée
- réduire la pollution dans le scoring

Cette couche existe déjà dans le code, même si elle n'est pas encore modélisée comme un contrat dédié de premier ordre.

### 4.3 Activity

**Statut** : partiellement implémenté

Pulse expose aujourd'hui `activity_level` dans les signaux et dans `CurrentContext`.

Cette couche répond à :
- que fait l'utilisateur concrètement maintenant ?

Exemples :
- `editing`
- `reading`
- `executing`
- `navigating`
- `idle`

Important :
- `Activity` n'est pas `Task`
- elle est calculée aujourd'hui
- elle existe déjà dans le runtime
- elle constitue une donnée fiable du contexte courant
- mais elle n'est pas encore traitée comme une couche structurante autonome du système
- elle ne porte pas encore de logique propre ni de responsabilité architecturale indépendante (contrairement à une future couche Episode)

### 4.4 Interpretation

**Statut** : implémenté

Pulse infère aujourd'hui :
- `probable_task`
- `task_confidence`
- `focus_level`
- `friction_score`
- `work_pattern_candidate`

Cette couche reste probabiliste.

Elle ne dit pas :
- "ce qui est vrai"

Elle dit :
- "ce que le runtime estime le plus probable à partir des signaux actuels"

### 4.5 Session

**Statut** : implémenté

La session actuelle est un conteneur temporel délimité par :
- gap d'activité significatif
- verrou / déverrouillage écran
- règles de reset déjà stabilisées

Le lifecycle de session est maintenant centralisé dans `SessionFSM`.

Important :
- une session existe aujourd'hui
- son lifecycle est unifié
- et elle agrège maintenant des épisodes persistés

### 4.6 Memory

**Statut** : implémenté, encore intermédiaire

Pulse possède aujourd'hui :
- une mémoire de session
- un export structuré de session (`SessionSnapshot`)
- une extraction mémoire rétrospective
- un moteur de faits utilisateur
- des sorties Markdown et SQLite

La mémoire actuelle reste encore largement :
- session-centrique
- orientée résumé et faits

Elle n'est pas encore :
- organisée autour d'épisodes
- assez fine pour porter seule des propositions plus avancées

### 4.7 Proposal

**Statut** : implémenté, scope limité

Pulse sait aujourd'hui :
- produire des décisions locales
- construire des `ProposalCandidate`
- convertir ces candidats vers le transport legacy `Proposal`
- conserver transparence et evidence

Mais le proposal flow actuel reste encore :
- local
- peu contextualisé par continuité de travail
- non piloté par épisodes

### 4.8 Episode

**Statut** : implémenté, encore limité

Cette couche existe maintenant comme système runtime exploitable pour les frontières temporelles.

Concrètement, Pulse a aujourd'hui :
- un modèle `Episode` persisté dans `session.db`
- un `current_episode` exposé en top-level dans `/state`
- une agrégation `Session -> Episodes` via la persistance et l'exposition runtime
- une sémantique figée uniquement sur les épisodes clos

Important :
- `EpisodeFSM` reste temporelle uniquement
- `SignalScorer` reste l'unique source du calcul sémantique
- l'épisode actif reste essentiellement temporel ; la lecture live vient des `signals`
- `current_episode` n'est pas porté par `CurrentContext`
- mémoire et proposals ne sont pas encore pilotées par les épisodes

---

## 5. Contrats structurants actuels

### CurrentContext

**Statut** : implémenté

`CurrentContext` est la vue synthétique temps réel du runtime.

Il sert à :
- fournir un point d'accès unifié au contexte courant
- alimenter `build_context_snapshot()`
- alimenter `/state` via adaptateur legacy

Important :
- `CurrentContext` ne doit pas devenir un objet actif
- il ne contient pas de `current_episode`
- il ne doit pas porter de mémoire rétrospective

### SessionSnapshot

**Statut** : implémenté

`SessionSnapshot` est la projection structurée de la session courante ou clôturée.

Il sert à :
- structurer le passage vers la couche mémoire
- conserver une compat stricte avec `export_session_data()`

Important :
- il ne contient pas d'épisodes aujourd'hui
- il reste un snapshot de session, pas un modèle cible complet de mémoire

### ProposalCandidate

**Statut** : implémenté

`ProposalCandidate` découple :
- la construction métier d'une proposition
- son transport legacy final

Il ne porte pas :
- `id`
- `status`
- lifecycle de stockage

### SessionFSM

**Statut** : implémenté

`SessionFSM` est la source de vérité du lifecycle de session.

Elle centralise :
- `active`
- `idle`
- `locked`
- les transitions de frontière de session

Important :
- `RuntimeState` peut encore porter des marqueurs de compat
- mais ne doit plus décider du lifecycle

---

## 6. Concepts cibles non encore implémentés

Les éléments suivants appartiennent à l'architecture cible, pas au système actuel.

### current_episode dans CurrentContext

Cible :
- vue temps réel d'un épisode provisoire en cours

Réel aujourd'hui :
- absent volontairement
- non introduit pendant `Foundation`

### Session contenant des épisodes

Cible :
- une session agrégera plusieurs épisodes

Réel aujourd'hui :
- la session agrège déjà des épisodes persistés, mais cette structure n'est pas encore exploitée par `SessionSnapshot`, mémoire et proposals

### Mémoire enrichie par épisodes

Cible :
- mémoire plus fine, plus contextuelle, moins plate

Réel aujourd'hui :
- mémoire encore principalement construite depuis la session et les faits

### Smart Proposals

Cible :
- suggestions contextualisées par continuité réelle du travail

Réel aujourd'hui :
- proposals encore locales et limitées

### Agentique contrôlée

Cible :
- actions bornées, explicables, validées

Réel aujourd'hui :
- non démarré

---

## 7. Principes de design

### Séparation stricte temps réel / rétrospectif

Le runtime ne doit pas mélanger :
- calcul du contexte courant
- consolidation mémoire
- projection rétrospective

Le temps réel sert à observer et qualifier.
Le rétrospectif sert à résumer, consolider, corriger et mémoriser.

### Transparence obligatoire

Toute proposition ou inférence importante doit pouvoir être reliée à :
- ses signaux
- sa confiance
- son evidence set

### Pas de future washing dans le code ni dans la doc

Un concept futur doit être documenté comme futur.

En particulier :
- une capacité épisode non implémentée ne doit pas être présentée comme présente
- une mémoire non structurée par épisodes ne doit pas être décrite comme déjà mature
- une agentique non lancée ne doit pas être décrite comme en place

### Une seule source de vérité par responsabilité

Exemples actuels :
- lifecycle de session -> `SessionFSM`
- contexte temps réel -> `CurrentContext`
- projection de session -> `SessionSnapshot`
- transport de proposition -> `Proposal`

---

## 8. Prochaine phase logique

La prochaine phase logique n'est plus l'introduction des épisodes eux-mêmes.

Objectif :
- mieux exploiter les épisodes pour les proposals
- mieux articuler mémoire et épisodes
- rendre plus lisible la séparation entre signaux live et lecture rétrospective

---

## 9. Lecture correcte de ce document

Ce document doit être lu comme une architecture progressive.

Il ne dit pas :
- "tout cela existe déjà"

Il dit :
- "voici la structure cible"
- "voici ce qui existe réellement aujourd'hui"
- "voici les couches encore futures"

Si une ambiguïté apparaît entre :
- ce document
- le code réel
- la roadmap

la priorité est :
1. le code réel
2. [refactor-roadmap.md](/Users/yugz/Projets/Pulse/Pulse/docs/refactor-roadmap.md)
3. ce document
