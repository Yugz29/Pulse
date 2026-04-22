# Contrat sémantique de Pulse

Ce document définit les contrats sémantiques de Pulse.

Il distingue explicitement :
- le **contrat actuel** : ce que le code fait aujourd'hui
- les **limites connues** : ce que le système fait de manière faible, incomplète ou risquée
- les **évolutions cibles** : ce que Pulse devra faire plus tard

Il ne décrit pas un système idéal.

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
- `CurrentContext`
- `probable_task`
- `focus_level`
- `session_duration_min`

Origine :
- runtime live
- `SignalScorer`
- `CurrentContext`

Statut :
- utile pour le présent
- pas une vérité durable

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

# Partie 2 — Contrat de l'épisode (Phase 2a)

Cette section définit le contrat sémantique de l'épisode pour Phase 2a — Episode Boundaries.

Elle couvre uniquement les frontières temporelles.
La sémantique de tâche et l'origine de l'activité sont documentées en Phase 2b.

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

Un épisode n'est pas :
- une session (plus large, contient plusieurs épisodes)
- une tâche (concept interprétatif, pas encore structurel en Phase 2a)
- un journal (résumé rétrospectif, produit après coup)
- un fait (observation promue, pas une unité temporelle)
- un signal (mesure ponctuelle, pas une durée)

---

## 8. Ce qu'un épisode n'est pas encore en Phase 2a

Phase 2a ne prétend pas résoudre :
- l'intention derrière l'activité
- la distinction activité utilisateur vs activité assistée
- la sémantique de tâche portée par l'épisode
- l'enrichissement LLM de l'épisode
- la continuité inter-session via les épisodes

Ces éléments appartiennent à Phase 2b.

Tout document ou code qui laisse croire que ces capacités existent
en Phase 2a décrit la cible, pas le présent.

---

## 9. Modèle minimal de l'épisode

En Phase 2a, un épisode porte uniquement :

```
Episode:
  id            : identifiant unique
  session_id    : rattachement à la session parente
  started_at    : timestamp de début (ISO 8601)
  ended_at      : timestamp de fin (null si épisode actif)
  boundary_reason : raison de la frontière de début
  duration_sec  : durée calculée (null si épisode actif)
```

Il ne porte pas encore en Phase 2a :
- `probable_task`
- `activity_level`
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
`duration_sec` est calculé, `boundary_reason` est documentée.

Un épisode clos ne peut pas être rouvert.
Il peut être annoté rétrospectivement (Phase 2b).

---

## 11. Frontières d'épisode

### 11.1 Signaux durs (frontière certaine)

Ces signaux créent une frontière sans ambiguïté.
Ils clôturent l'épisode courant et en ouvrent un nouveau.

| Signal | Boundary reason |
|---|---|
| Verrou écran suivi d'un gap > seuil | `screen_lock` |
| Changement de projet actif | `project_change` |
| Commit git confirmé | `commit` |
| Gap d'inactivité > `EPISODE_TIMEOUT_MIN` | `idle_timeout` |

### 11.2 Signaux mous (indice, pas frontière)

Ces signaux suggèrent un possible changement d'épisode
mais ne le déclenchent pas seuls.
Ils sont accumulés dans un scorer d'épisode.

- Changement de type de fichier dominant (source -> docs)
- Friction qui chute brutalement après avoir été élevée
- Changement d'app active vers une catégorie différente
- Gap d'activité fichier > 5 min sans verrou écran

### 11.3 Timeout d'épisode

`EPISODE_TIMEOUT_MIN` : gap d'inactivité au-delà duquel
un épisode est considéré clos.

Valeur de départ : **20 minutes**.

Ce seuil est distinct de `SESSION_TIMEOUT_MIN` (10 min).
Un épisode peut se terminer sans que la session se termine.

---

## 12. Relation épisode / session

```
Session
  └── Épisode 1 (clos)
  └── Épisode 2 (clos)
  └── Épisode 3 (actif)
```

Une session contient zéro ou plusieurs épisodes.
Un épisode appartient à exactement une session.
La clôture d'un épisode ne clôture pas la session.
La clôture d'une session clôture l'épisode actif en cours.

---

## 13. Règles d'implémentation pour Phase 2a

### Ce qui doit être vrai dans le code

- Il existe au plus un épisode ACTIF par session à tout instant
- `EpisodeFSM` est la source de vérité des frontières — pas `SessionFSM`, pas le scorer
- Toute frontière détectée est accompagnée d'une `boundary_reason` loggée
- Les épisodes sont persistés en SQLite dans `~/.pulse/`
- L'épisode courant est exposé dans `/state`

### Ce qu'il faut éviter dans le code

- Déduire la frontière depuis `probable_task` (trop fragile)
- Ouvrir plusieurs épisodes en parallèle
- Confondre fin d'épisode et fin de session
- Ajouter des champs sémantiques sur `Episode` avant Phase 2b
- Utiliser le LLM pour détecter les frontières

### Ce qui est hors périmètre Phase 2a

- `Episode.probable_task`
- `Episode.origin`
- Résumé d'épisode
- Export épisode vers mémoire ou proposals
- Injection de l'épisode dans le contexte LLM

---

## 14. Ce que Phase 2a doit permettre d'observer

À la sortie de Phase 2a, dans le dashboard :

- L'épisode courant est visible : début, durée en cours, raison de démarrage
- L'historique des épisodes de la session est visible
- Pour chaque épisode clos : durée, raison de frontière début et fin
- La session affiche le nombre d'épisodes qu'elle contient

Si ces 4 points ne sont pas vrais, Phase 2a n'est pas terminée.

---

## 15. Résumé opérationnel (épisode Phase 2a)

Le contrat de l'épisode en Phase 2a est le suivant :

- Un épisode est une unité temporelle, pas une unité de sens
- Ses frontières sont détectées par des signaux durs déterministes
- Il est persisté, exposé dans `/state`, visible dans le dashboard
- Il ne porte pas de sémantique de tâche
- Il ne sait pas distinguer activité utilisateur et activité assistée

Ce contrat est volontairement minimal.
Sa valeur est dans la fiabilité des frontières, pas dans leur richesse.
