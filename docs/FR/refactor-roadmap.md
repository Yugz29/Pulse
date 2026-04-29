# Pulse Roadmap

## 1. Vision de Pulse

### Positionnement

Pulse est un système d'observation locale du travail qui qualifie l'activité en temps réel, structure la continuité du travail, consolide une mémoire utile, et propose des actions explicables.

La chaîne cible actuelle est :

Observation -> Qualification -> Current Context -> Work Blocks -> Session -> Memory -> Proposal

### Ce que Pulse veut devenir

- Un observateur fiable du travail réel, pas un simple détecteur de "tâche probable"
- Un système capable d'identifier des unités de sens stables dans une session
- Une base de mémoire exploitable pour des suggestions pertinentes et traçables
- Un assistant capable de proposer, puis plus tard d'agir sous contrôle strict

### Ce que Pulse n'est pas encore

- Un moteur de proposition vraiment contextualisé sur la continuité du travail
- Une mémoire consolidée riche et pilotée par blocs de travail
- Un agent autonome

## 1bis. État runtime après refocus

Le runtime actuel n'est plus organisé autour de plusieurs vues concurrentes.

Le pipeline réel est :

```text
event
→ SessionFSM
→ SignalScorer
→ RuntimeState.update_present()
→ DecisionEngine
→ SessionMemory
```

Points actés dans le code :
- `PresentState` est la seule source de vérité canonique du présent
- `SignalScorer` est la seule source du contexte de travail courant
- `SessionFSM` est la seule source de l'état de session
- `CurrentContext` est un rendu, pas une source de vérité
- `StateStore` est un shim legacy
- `EpisodeFSM` a été supprimé du runtime
- `current_context` remplace `current_episode` comme lecture produit
- `recent_sessions` remplace `recent_episodes` comme historique produit
- `work_blocks` / `work_block_*` remplacent progressivement `work_windows`
- `/state` expose `present` comme noyau canonique, avec compat et debug autour
- un snapshot runtime atomique existe pour éviter les lectures hybrides
- verrou court != nouvelle session

Interdits runtime :
- ne pas réintroduire `signals` comme source de vérité du présent
- ne pas construire de nouvelle feature depuis les champs top-level de `/state`
- ne pas lire `present`, `signals` et `decision` séparément
- ne pas recentraliser les épisodes ; le modèle produit courant est `current_context` + `work_blocks` + `recent_sessions`

## 2. État actuel

### Stabilisé

- `PresentState` porte le présent canonique
- `CurrentContext` existe comme rendu du présent
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
- Refocus 2026 : abandon du modèle produit `EpisodeFSM`, migration vers `current_context`, `recent_sessions` et `work_blocks`

### Ajouté en Phase 1

- `activity_level` et `task_confidence` exposés dans `/state`
- `session_fsm` exposé dans `/state`
- Instrumentation : logs `CurrentContextBuilder`, fallback mémoire explicite, transitions FSM loggées
- Dashboard technique (`DashboardWindow`) : fenêtre indépendante glassmorphism
- Route `/memory/sessions` exposant les journaux de session

### Ce qui manque encore

- Proposition intelligente basée sur blocs de travail et mémoire enrichie
- Mémoire session -> bloc de travail -> faits plus robuste
- Cadre agentique contrôlé

## 3. Roadmap globale

### Phase 0 — Foundation

**Statut** : terminée

**Objectif**

Rendre le runtime structurable sans changer le comportement observable.

**Livrables**

- `PresentState`
- `CurrentContext` comme rendu
- `SessionSnapshot`
- `ProposalCandidate`
- `SessionFSM`
- Adaptateurs legacy verrouillés
- Compat de sortie testée

**Hors périmètre**

- Modèle de blocs de travail
- Nouvelles heuristiques métier
- Mémoire enrichie
- Agentique

**Condition de sortie**

- Une source de vérité du présent et du lifecycle sessionnel
- Contrats runtime et session structurés
- Sorties legacy inchangées
- Shim de compat documenté

### Phase 1 — Observation terrain

**Statut** : terminée

**Objectif**

Mesurer le comportement réel du système stabilisé avant de structurer les blocs de travail.

**Livrables**

- Instrumentation de debug et d'audit ciblée
- Jeux de scénarios réels de sessions
- Validation des frontières de session sur cas terrain
- Validation du rendu `CurrentContext` comme projection utile du présent
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

- Implémentation prématurée d'un modèle temporel lourd
- Changement heuristique non justifié par observation
- Refonte mémoire
- Agentique

**Condition de sortie — validée**

- ✓ Frontières de session stables sur cas réels
- ✓ Zones faibles identifiées et classées (voir `OBS.md`)
- ✓ Besoin de continuité de travail défini à partir d'observations terrain

---

### Phase 2a — Work Block Boundaries

**Statut** : en cours après refocus

**Objectif**

Poser des frontières de blocs de travail fiables et observables, sans sémantique imposée.
La question à résoudre : délimiter du temps de travail réel de façon déterministe et auditable.

Principe : un bloc de travail est d'abord une fenêtre temporelle fiable dérivée d'événements significatifs.

**Livrables**

- `work_blocks` dérivés des événements significatifs
- `recent_sessions` dérivées des sessions fermées
- `work_block_*` dans les payloads mémoire et ResumeCard
- aliases legacy `current_episode`, `recent_episodes`, `work_window_*`, `closed_episodes` conservés temporairement

**Hors périmètre**

- Sémantique de tâche riche sur les blocs
- Injection LLM des blocs
- Agentique
- Refonte mémoire

**Condition de sortie**

- Les blocs de travail sont visibles dans le dashboard et correspondent à la réalité terrain
- Une session expose un historique lisible sans FSM d'épisodes parallèle
- Les durées sont dérivées des événements significatifs, pas des commits seuls

---

### Phase 2b — Context / Work Block Semantics

**Statut** : en cours

**Objectif**

Ajouter de la sémantique utile aux contextes et blocs de travail sans recréer une FSM d'épisodes.

**Livrables**

- `current_context` porte la lecture produit courante
- `work_blocks` portent les durées de travail
- `recent_sessions` portent l'historique fermé
- la ResumeCard lit `work_block_*` et `recent_sessions`

**Hors périmètre**

- Agentique
- Refonte complète de la mémoire
- Détection LLM des blocs
- `origin`
- Résumé riche de bloc
- Export complet des blocs vers mémoire ou proposals

**Condition de sortie**

- Un bloc ou une session récente porte une sémantique lisible et auditable
- La sémantique est construite de façon déterministe, sans LLM obligatoire
- Le présent continue d'être lu via `PresentState`, pas via l'historique

---

### Phase 3 — Smart Proposals

**Objectif**

Faire évoluer les propositions de suggestions locales vers des propositions contextualisées par session, bloc de travail et mémoire.

**Livrables**

- Proposal flow enrichi par `CurrentContext + WorkBlock + Session + Memory`
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

- Consolidation mémoire à partir des blocs de travail
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

Ouvrir des capacités d'action sous contraintes strictes, à partir d'un système déjà fiable en observation, blocs de travail, propositions et mémoire.

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

- `Observation terrain -> Work Block Boundaries (2a)`
  - Cas réels observés et documentés
  - Frontières de session jugées stables
  - Besoins de blocs de travail formulés à partir de données terrain

- `Work Block Boundaries (2a) -> Context / Work Block Semantics (2b)`
  - Frontières de blocs visibles et auditables dans le dashboard
  - Une session expose des blocs de façon stable
  - Correspondance terrain validée sur plusieurs sessions réelles

- `Context / Work Block Semantics (2b) -> Smart Proposals`
  - Blocs ou sessions récentes avec sémantique lisible
  - Agrégation sessionnelle stable

- `Smart Proposals -> Mémoire enrichie`
  - Proposals contextualisées mais encore limitées par la mémoire actuelle
  - Besoin démontré d'une mémoire structurée plus riche

- `Mémoire enrichie -> Agentique contrôlée`
  - Mémoire fiable
  - Proposals explicables
  - Cadre d'action et de validation défini

### Ce qu'on refuse de faire trop tôt

- Réintroduire un Episode System sans preuve terrain forte
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

- de lire le présent canonique via `PresentState`
- de voir le contexte courant dans le dashboard en temps réel
- de visualiser les blocs de travail et les sessions récentes
- de comprendre pourquoi une durée de travail a été calculée
- de lire la sémantique live via `current_context`

Le résumé riche de bloc et l'export complet vers mémoire/proposals restent hors périmètre du scope actuel.

## Référence d'usage

Ce document sert à arbitrer l'ordre des travaux.

Il ne sert pas à justifier :

- un refactor sans cap
- une feature prématurée
- une généralisation abstraite non nécessaire
- un saut direct vers l'agentique
