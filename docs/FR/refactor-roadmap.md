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

- Fin de la phase `Foundation`
- Réduction du couplage structurel dans le runtime
- Sortie des contrats structurés minimaux
- Unification de la gestion de session autour d'une seule source de vérité

### Ce qui manque encore

- Mesure terrain sur la qualité réelle des signaux et frontières
- Système d'épisodes explicite
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

**Statut** : prochaine phase

**Objectif**

Mesurer le comportement réel du système stabilisé avant d'ouvrir Episode System.


**Livrables**

- Instrumentation de debug et d'audit ciblée
- Jeux de scénarios réels de sessions
- Validation des frontières de session sur cas terrain
- Validation du `CurrentContext` comme vue temps réel exploitable
- Liste priorisée des écarts observés, sans correction opportuniste

### Méthode d’observation

- Utilisation réelle du système sur sessions de développement
- Logging systématique dans `docs/observation-log.md`
- Analyse des divergences :
  - activité réelle vs `activity_level`
  - tâche réelle vs `probable_task`
  - frontières de session perçues vs FSM
- Capture de cas concrets (courts extraits) pour audit ultérieur

**Hors périmètre**

- Implémentation d'épisodes
- Changement heuristique non justifié par observation
- Refonte mémoire
- Agentique

**Condition de sortie**

- Les frontières de session sont jugées suffisamment stables sur cas réels
- Les zones faibles sont identifiées et classées
- Le point d'entrée Episode System est défini à partir d'observations, pas d'intuition

### Phase 2 — Episode System V1

**Statut** : non démarrée

**Objectif**

Introduire l'épisode comme unité de sens intra-session, sans casser les couches existantes.

**Livrables**

- Modèle d'épisode explicite
- Détection d'épisodes à partir du runtime stabilisé
- Intégration `episode -> session`
- Export exploitable par mémoire et proposition
- Transparence minimale sur l'épisode courant et les épisodes clos

**Hors périmètre**

- Agentique
- Refonte complète de la mémoire
- Automatisation d'actions

**Condition de sortie**

- Les épisodes ont une sémantique stable
- Les frontières d'épisode sont compréhensibles et auditables
- La session peut agréger plusieurs épisodes sans bricolage

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

- `Observation terrain -> Episode System V1`
  - Cas réels observés et documentés
  - Frontières de session jugées stables
  - Besoins d'épisode formulés à partir de données terrain

- `Episode System V1 -> Smart Proposals`
  - Épisode courant et épisodes clos exploitables
  - Agrégation sessionnelle stable
  - Transparence suffisante sur les transitions

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

À ce stade, Pulse doit permettre :

- d’observer en temps réel :
  - activité
  - tâche
  - contexte
- de comprendre les transitions de session
- de valider visuellement la cohérence du système

Aucune suggestion avancée ni automatisation n’est attendue à ce stade.

## Référence d'usage

Ce document sert à arbitrer l'ordre des travaux.

Il ne sert pas à justifier :

- un refactor sans cap
- une feature prématurée
- une généralisation abstraite non nécessaire
- un saut direct vers l'agentique
