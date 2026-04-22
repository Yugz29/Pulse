# Pulse Roadmap

## 1. Vision de Pulse

### Positionnement

Pulse est un système d'observation locale du travail qui qualifie l'activité en temps réel, structure la continuité du travail, consolide une mémoire utile, et propose des actions explicables.

La chaîne cible reste :

Observation -> Qualification -> Activity -> Interpretation -> Episode -> Session -> Memory -> Proposal

### Ce que Pulse veut devenir

- Un observateur fiable du travail réel, pas un simple détecteur de "tâche probable"
- Un système capable d'identifier des unités de sens stables dans une session
- Une base de mémoire exploitable pour des suggestions pertinentes et traçables
- Un assistant capable de proposer, puis plus tard d'agir sous contrôle strict

### Ce que Pulse n'est pas encore

- Un système à épisodes exploitable en production
- Un moteur de proposition vraiment contextualisé sur la continuité du travail
- Une mémoire consolidée riche et pilotée par épisodes
- Un agent autonome

## 2. État actuel

### Stabilisé

- `CurrentContext` existe et alimente le runtime
- `SessionSnapshot` structure la projection de session
- `ProposalCandidate` découple le métier du transport legacy
- `SessionFSM` centralise le lifecycle de session
- La compat legacy est verrouillée sur :
  - `build_context_snapshot()`
  - `/state`
  - `export_session_data()`
- Le shim FSM de compat est documenté et borné

### Ce qui vient d'être terminé

- Phase 0 Foundation : contrats structurés, compat legacy verrouillée, lifecycle session unifié
- Phase 1 Observation terrain : instrumentation, dashboard technique, observations terrain documentées dans `OBS.md`

### Ajouté en Phase 1

- `activity_level` et `task_confidence` exposés dans `/state`
- `session_fsm` exposé dans `/state`
- Instrumentation : logs `CurrentContextBuilder`, fallback mémoire explicite, transitions FSM loggées
- Dashboard technique (`DashboardWindow`) : fenêtre indépendante glassmorphism
- Route `/memory/sessions` exposant les journaux de session

### Ce qui manque encore

- Proposition intelligente basée sur épisodes et mémoire enrichie
- Mémoire session -> épisode -> faits plus robuste
- Cadre agentique contrôlé

## 3. Roadmap globale

### Phase 0 — Foundation

**Statut** : terminée

**Objectif**

Rendre le runtime structurable sans changer le comportement observable.

**Livrables**

- `CurrentContext`
- `SessionSnapshot`
- `ProposalCandidate`
- `SessionFSM`
- Adaptateurs legacy verrouillés
- Compat de sortie testée

**Hors périmètre**

- Episode System
- Nouvelles heuristiques métier
- Mémoire enrichie
- Agentique

**Condition de sortie**

- Une source de vérité sessionnelle
- Contrats runtime et session structurés
- Sorties legacy inchangées
- Shim de compat documenté

### Phase 1 — Observation terrain

**Statut** : terminée

**Objectif**

Mesurer le comportement réel du système stabilisé avant d'ouvrir Episode System.

**Livrables**

- Instrumentation de debug et d'audit ciblée
- Jeux de scénarios réels de sessions
- Validation des frontières de session sur cas terrain
- Validation du `CurrentContext` comme vue temps réel exploitable
- Liste priorisée des écarts observés, sans correction opportuniste

**Observations terrain** (synthèse — détails dans `OBS.md`)

- Timeout de session trop court hors workflows orientés fichiers : les apps non-dev sont invisibles pour la FSM
- Injection de contexte LLM trop plate : tout est injecté sans filtre de pertinence
- Mémoire confirmée comme principalement session-centrique en usage réel
- Pas de continuité structurée inter-session au-delà de `last_session_context`

**Méthode d'observation**

- Utilisation réelle du système sur sessions de développement
- Prise de notes d'observation terrain hors repo, de manière libre et systématique
- Analyse des divergences : activité réelle vs `activity_level`, tâche réelle vs `probable_task`, frontières de session perçues vs FSM
- Capture de cas concrets pour audit ultérieur

**Hors périmètre**

- Implémentation d'épisodes
- Changement heuristique non justifié par observation
- Refonte mémoire
- Agentique

**Condition de sortie — validée**

- ✓ Frontières de session stables sur cas réels
- ✓ Zones faibles identifiées et classées (voir `OBS.md`)
- ✓ Point d'entrée Episode System défini à partir d'observations terrain

---

### Phase 2a — Episode Boundaries

**Statut** : terminée

**Objectif**

Poser des frontières d'épisodes fiables et observables, sans sémantique imposée.
La question à résoudre : délimiter du temps de travail réel de façon déterministe et auditable.

Principe : un épisode est d'abord une unité temporelle fiable. La sémantique vient ensuite, en Phase 2b.

**Livrables**

- Modèle `Episode` minimal : id, started_at, ended_at, session_id
- Détection des frontières par signaux durs : gap d'inactivité, changement de projet, commit confirmé, verrou écran
- `EpisodeFSM` : lifecycle actif / suspendu / clos, source de vérité des frontières
- Intégration `episode -> session` : une session agrège plusieurs épisodes
- Exposition dans `/state` : épisode courant visible dans le dashboard
- Persistance minimale en SQLite

**Hors périmètre**

- Sémantique de tâche sur l'épisode (Phase 2b)
- Injection LLM de l'épisode
- Agentique
- Refonte mémoire

**Condition de sortie**

- Les frontières d'épisode sont visibles dans le dashboard et correspondent à la réalité terrain
- Une session agrège plusieurs épisodes sans bricolage
- Les frontières sont auditables : on peut expliquer pourquoi un épisode a commencé ou fini

---

### Phase 2b — Episode Semantics

**Statut** : terminée (scope actuel)

**Objectif**

Ajouter de la sémantique sur les épisodes délimités en 2a.
Un épisode devient une unité de sens : quelle tâche, quel contexte, quelle origine.

**Livrables**

- `probable_task` et `activity_level` portés au niveau de l'épisode
- `task_confidence` porté au niveau de l'épisode
- Sémantique figée à la clôture de l'épisode, sans rescoring dans `EpisodeFSM`
- Transparence sur l'épisode courant et les épisodes clos dans le dashboard

**Hors périmètre**

- Agentique
- Refonte complète de la mémoire
- Détection LLM des épisodes
- `origin`
- Résumé d'épisode
- Export épisode vers mémoire ou proposals

**Condition de sortie**

- Un épisode clos porte une sémantique lisible et auditable
- La sémantique est construite de façon déterministe, sans LLM obligatoire
- Le présent continue d'être lu via `signals`, pas via la sémantique de l'épisode actif

---

### Phase 3 — Smart Proposals

**Objectif**

Faire évoluer les propositions de suggestions locales vers des propositions contextualisées par session, épisode et mémoire.

**Livrables**

- Proposal flow enrichi par `CurrentContext + Episode + Session + Memory`
- Priorisation des propositions
- Explicabilité renforcée
- Déduplication et arbitrage des suggestions

**Hors périmètre**

- Exécution autonome
- Agentique multi-étapes

**Condition de sortie**

- Les propositions sont plus pertinentes qu'un simple trigger local
- Les faux positifs baissent
- Les suggestions restent transparentes et contrôlables

### Phase 4 — Mémoire enrichie

**Objectif**

Faire passer la mémoire d'un résumé de session à une mémoire structurée par continuité de travail.

**Livrables**

- Consolidation mémoire à partir des épisodes
- Meilleure séparation temps réel / rétrospectif
- Faits et résumés mieux alignés sur le travail réellement produit
- Contrats mémoire préparant les usages propositionnels et agentiques

**Hors périmètre**

- Agent autonome
- Réécriture globale du stockage sans besoin démontré

**Condition de sortie**

- La mémoire devient utile pour expliquer et orienter les propositions
- Les résumés de travail cessent d'être trop plats ou trop session-centrés

### Phase 5 — Agentique contrôlée

**Objectif**

Ouvrir des capacités d'action sous contraintes strictes, à partir d'un système déjà fiable en observation, épisodes, propositions et mémoire.

**Livrables**

- Cadre d'autorisation explicite
- Traçabilité complète des actions proposées/exécutées
- Garde-fous de périmètre et de sécurité
- Mécanismes de validation utilisateur avant action significative

**Hors périmètre**

- Autonomie non supervisée
- Décisions opaques
- Exécution silencieuse

**Condition de sortie**

- Les actions restent auditées, explicables et bornées
- Pulse reste contrôlé, non autonome par défaut

## 4. Règles de passage

### Gates avant passage à la phase suivante

- `Foundation -> Observation terrain`
  - Contrats structurés en place
  - Compat legacy verrouillée
  - Lifecycle session unifié

- `Observation terrain -> Episode Boundaries (2a)`
  - Cas réels observés et documentés
  - Frontières de session jugées stables
  - Besoins d'épisode formulés à partir de données terrain

- `Episode Boundaries (2a) -> Episode Semantics (2b)`
  - Frontières d'épisode visibles et auditables dans le dashboard
  - Une session agrège plusieurs épisodes de façon stable
  - Correspondance terrain validée sur plusieurs sessions réelles

- `Episode Semantics (2b) -> Smart Proposals`
  - Épisode clos avec sémantique lisible
  - Agrégation sessionnelle stable

- `Smart Proposals -> Mémoire enrichie`
  - Proposals contextualisées mais encore limitées par la mémoire actuelle
  - Besoin démontré d'une mémoire structurée plus riche

- `Mémoire enrichie -> Agentique contrôlée`
  - Mémoire fiable
  - Proposals explicables
  - Cadre d'action et de validation défini

### Ce qu'on refuse de faire trop tôt

- Introduire Episode System sans observation terrain
- Changer des heuristiques faute de mesure
- Réécrire le stockage sans modèle stabilisé
- Ouvrir l'agentique avant d'avoir des propositions robustes
- Ajouter des abstractions "par anticipation" sans responsabilité réelle

## 5. Règles de chantier

- Pas de patch opportuniste sans rattachement explicite à une phase
- Pas de refactor sans objectif métier ou structurel clair
- Pas de feature sans critère d'entrée et de sortie
- Pas de dette invisible : tout shim, compat layer ou compromis doit être documenté
- Pas de big bang rewrite
- Une seule source de vérité par responsabilité critique
- Toute modification comportementale doit être assumée comme telle et sortir du simple chantier de structure

## 6. Output utilisateur attendu

À la fin du scope actuel de Phase 2, Pulse doit permettre :

- de voir l'épisode courant dans le dashboard en temps réel
- de comprendre pourquoi une frontière d'épisode a été détectée
- de visualiser un historique récent des épisodes clos
- de lire la sémantique live via `signals` et la sémantique figée via les épisodes clos

`origin`, le résumé d'épisode et l'export vers mémoire/proposals restent hors périmètre du scope actuel.

## Référence d'usage

Ce document sert à arbitrer l'ordre des travaux.

Il ne sert pas à justifier :

- un refactor sans cap
- une feature prématurée
- une généralisation abstraite non nécessaire
- un saut direct vers l'agentique
