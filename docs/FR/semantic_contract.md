# Contrat sémantique de Pulse

Ce document définit le contrat sémantique de la mémoire de Pulse.

Il distingue explicitement :
- le **contrat actuel** : ce que le code fait aujourd'hui
- les **limites connues** : ce que le système fait de manière faible, incomplète ou risquée
- les **évolutions cibles** : ce que Pulse devra faire plus tard

Il ne décrit pas un système idéal.
Il ne décrit pas non plus Episode System.

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

### 2.4 Rôle réel d’`autonomy_level`

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

### 2.5 Règle réelle d’injection vers le contexte LLM

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

Même si `_extract_observations()` distingue aujourd'hui :
- `obs_description`
- `fact_description`

le risque demeure :
- certaines formulations de faits peuvent sembler plus solides qu'elles ne le sont

Le danger n'est pas seulement le stockage.
Le danger est le ton utilisé au moment de l'injection.

### 3.3 `_promote_pending()` est mécanique

La promotion actuelle :
- ne vérifie pas la qualité sémantique de la clé au moment de promouvoir
- ne requalifie pas la robustesse de l'observation
- se contente de créer le fait si le compteur a atteint le seuil

Autrement dit :
- la qualité du fait dépend presque entièrement de la qualité de `_extract_observations()`

### 3.4 `render_for_context()` est simple, pas robuste

Le filtre actuel par `confidence >= 0.60` est honnête et simple.

Mais il ne distingue pas :
- fait fraîchement promu
- fait confirmé plusieurs fois
- fait à `autonomy_level` plus élevé

Donc :
- l'injection actuelle est pragmatique
- elle n'est pas encore sémantiquement très fine

### 3.5 L’absence de contradiction n’est pas une preuve

Le système ne contredit pas activement ses propres faits.

Cela veut dire :
- un fait faible peut survivre longtemps
- le silence ne vaut pas validation
- la décroissance temporelle aide, mais ne résout pas tout

### 3.6 La mémoire n’est pas encore structurée par continuité de travail

La mémoire actuelle part principalement :
- de la session
- des faits dérivés de session

Elle n'est pas encore organisée par :
- épisodes
- transitions fines
- séquences de travail

Cette limite est structurelle et assumée à ce stade.

---

## 4. Évolutions cibles

Cette section décrit ce que Pulse devra faire plus tard.

Ce n'est **pas** le contrat actuel.

### 4.1 Rendre l’injection plus sélective

Cible possible :
- tenir compte d’`autonomy_level`
- distinguer plus finement les faits fraîchement promus et les faits consolidés dans le temps
- mieux calibrer le seuil d'injection

Aujourd'hui :
- ce n'est pas fait

### 4.2 Rendre la promotion moins mécanique

Cible :
- éviter qu'une clé heuristique trop large devienne un fait durable juste par répétition
- ajouter une discipline plus forte sur la qualité des observations promues

Aujourd'hui :
- cette validation supplémentaire n'existe pas

### 4.3 Mieux calibrer le langage des faits

Cible :
- rendre le ton d’un fait proportionnel à sa robustesse réelle
- éviter les formulations qui suggèrent une compréhension plus forte que la preuve disponible

Aujourd'hui :
- ce calibrage reste partiel

### 4.4 Séparer plus nettement mémoire utile et mémoire risquée

Cible :
- distinguer les faits vraiment utiles au contexte
- réduire les faits vagues ou trop génériques
- limiter l'injection de patterns fragiles

Aujourd'hui :
- le système repose surtout sur les seuils et la qualité des observations

### 4.5 Préparer la suite sans la raconter comme déjà faite

À plus long terme, Pulse devra probablement :
- mieux articuler mémoire, propositions et validation utilisateur
- mieux distinguer ce qui sert à parler de ce qui servira un jour à agir

Mais cela ne doit pas être présenté comme déjà présent.

En particulier :
- pas d'agentique active aujourd'hui
- pas de mémoire pilotée par épisodes aujourd'hui
- pas de logique d'action fondée sur `autonomy_level` aujourd'hui

---

## 5. Règles de lecture et de travail

### Ce qu’il faut considérer comme vrai aujourd’hui

- la mémoire est principalement dérivée des sessions
- les faits sont promus par répétition d'observations heuristiques
- `render_for_context()` filtre par confiance, pas par `autonomy_level`
- le système peut produire des approximations utiles sans vraie compréhension

### Ce qu’il ne faut pas supposer

- qu’un fait injecté est fortement validé
- qu’`autonomy_level` pilote déjà le comportement
- qu’une promotion implique une validation sémantique forte
- que la mémoire reflète déjà une structuration fine du travail

### Ce qu’il faut éviter dans le code

- coder une feature mémoire en supposant que les faits sont plus robustes qu’ils ne le sont
- ajouter des règles implicites non documentées
- parler de "compréhension" quand il s'agit encore d'agrégation heuristique
- documenter comme actuel un comportement seulement souhaité

---

## 6. Résumé opérationnel

Le contrat actuel de la mémoire Pulse est le suivant :

- Pulse observe des sessions
- Pulse extrait quelques observations heuristiques déterministes
- Pulse promeut ces observations en faits selon des seuils simples
- Pulse injecte au LLM une sous-partie des faits selon un filtre de confiance

Ce contrat est utile.

Il est aussi limité.

Il doit être traité comme :
- une base mémoire exploitable
- pas comme un système de compréhension avancée

Le bon usage de ce document est donc :
- comprendre ce que la mémoire fait aujourd'hui
- voir clairement ce qu'elle fait mal
- préparer les évolutions futures sans les présupposer déjà actives
