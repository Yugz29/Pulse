# Contrat sémantique de Pulse

> Boussole de décision pour le code. Pas une spec idéale — une description de ce que
> Pulse fait réellement, avec les règles qui doivent gouverner chaque couche.

---

## Le problème à éviter

Pulse peut donner l'impression de *comprendre* alors qu'il résume des signaux locaux.

Un fait qui apparaît dans `render_for_context()` avec le ton "Travaille principalement le
soir en mode développement" semble une vérité durable. Mais à l'origine, c'est une
heuristique produite par `_extract_observations()` à partir d'une seule session, répétée
cinq fois. La répétition d'une lecture modeste ne la rend pas plus vraie — elle la rend
juste plus fréquente.

**L'illusion de compréhension naît quand le statut d'une information ne correspond pas à
son ton et à l'usage qu'on en fait.**

---

## Les 5 niveaux de Pulse

Chaque information dans Pulse appartient à exactement un de ces niveaux. Le niveau
détermine ce que Pulse a le droit d'en faire.

### Niveau 1 — Constat local
*Ce que Pulse a vu, sans interprétation.*

Exemples : app switch vers Xcode, modification de `facts.py`, durée brute de session.

- Origine : événements Swift, `session_data` entrant dans le daemon
- Stockage : `session.db`, tier `ephemeral` du MemoryStore
- Ce que Pulse peut en dire : **rien de durable** — c'est une observation ponctuelle

### Niveau 2 — Contexte courant
*L'état agrégé de la session en cours.*

Exemples : projet actif = Pulse, tâche probable = coding, focus = deep, durée = 47 min.

- Origine : `StateStore`, `SignalScorer`
- Stockage : `session.db`, tier `session` du MemoryStore (TTL 7 jours)
- Ce que Pulse peut en dire : **ce qui se passe maintenant**, pas ce qui est vrai en général

### Niveau 3 — Lecture heuristique
*Ce que Pulse infère d'une session, sans confirmation extérieure.*

Exemples : `_extract_observations()` produit "Travaille souvent le soir en mode
développement" à partir d'une session à 21h avec `task=coding`.

- Origine : `facts.py::_extract_observations()`
- Stockage : table `observations`, `count = 1`
- Ce que Pulse peut en dire : **une hypothèse de travail**, pas un fait

> ⚠️ C'est ici que l'illusion de compréhension se forme le plus souvent.
> Le wording généré par `_extract_observations()` est déjà assertif ("Travaille souvent…")
> alors qu'il vient d'une seule observation.

### Niveau 4 — Observation répétée
*Une lecture heuristique qui s'est vérifiée plusieurs fois.*

- Origine : table `observations`, `SIGNAL_THRESHOLD (3) ≤ count < FACT_THRESHOLD (5)`
- Ce que Pulse peut en dire : **un signal qui se confirme** — toujours pas un fait stable

### Niveau 5 — Fait consolidé
*Une observation répétée qui a passé le seuil de promotion et survécu au temps.*

- Origine : table `facts`, `count ≥ 5`, `confidence ≥ 0.50`, non archivé
- Ce que Pulse peut dire au LLM : **une affirmation calibrée**, à nuancer selon `autonomy_level`

---

## Règle de formulation par niveau

Les descriptions de **niveau 3** (observations) sont sessionnelles et neutres :
elles décrivent ce qui s'est passé dans cette session, pas ce qui est vrai en général.

Les descriptions de **niveau 5** (facts) sont comportementales :
elles décrivent un pattern qui s'est confirmé dans le temps.

```
❌ Observation : "Travaille souvent le soir en mode développement"
✅ Observation : "Session soir (21h) — mode coding"
✅ Fait issu de 5+ de ces observations : "Tendance à coder le soir"
```

Cette séparation est implémentée dans `_extract_observations()` via deux champs distincts :
`obs_description` (stocké dans la table `observations`) et `fact_description`
(utilisé par `_promote_pending()` lors de la création du fait).

---

## Critère d'existence d'un fait — SUNA

Un type d'observation ne mérite d'entrer dans `_extract_observations()` que s'il
satisfait les 4 critères suivants :

- **Stable** : le pattern peut se vérifier sur plusieurs semaines sans changer de sens
- **Univoque** : la clé est assez spécifique pour ne capturer qu'un seul type de réalité
- **Non-trivial** : ce n'est pas une propriété de l'environnement technique (OS, IDE)
- **Actionnable** : ça change ce que Pulse injecte ou comment il se comporte

Si un type d'observation ne satisfait pas les 4, il ne doit pas exister dans le pipeline.
Pas être filtré en sortie — mais ne jamais être généré.

La contrainte s'applique à la conception de chaque entrée dans `_extract_observations()`,
pas à un filtre dynamique. Ajouter un nouveau type d'observation nécessite de valider
SUNA explicitement avant de l'écrire.

---

## Règles de promotion

Ces règles définissent ce qui a le droit de monter d'un niveau.

```
Niveau 3 → Niveau 4   count >= SIGNAL_THRESHOLD (3)
Niveau 4 → Niveau 5   count >= FACT_THRESHOLD (5)
Niveau 5 → archivé    confidence < ARCHIVE_THRESHOLD (0.30)
```

**Ce qui ne donne pas le droit de monter :**

- La répétition d'une même heuristique peu fiable. Si `_extract_observations()` génère
  une clé à partir de données faibles (une session courte, un créneau unique), répéter
  l'observation cinq fois ne la rend pas plus vraie.
- L'ancienneté seule. Un fait vieux et non revu devrait descendre en confiance (le decay
  est en place : `DECAY_PER_DAY = 0.02` après `DECAY_START_DAYS = 3`).
- L'absence de contradiction. Pulse ne contradite pas activement ses propres faits — c'est
  la neutralité silencieuse qui laisse des faits incorrects survivre trop longtemps.

---

## Ce qui a le droit d'atterrir dans `render_for_context()`

`render_for_context()` est le point de sortie vers le LLM. C'est là que le contrat est
le plus critique.

**Règle actuelle :** facts actifs avec `confidence >= 0.60`, limités à 8.

`autonomy_level` n'intervient pas dans ce filtre. Il est réservé au futur système
d'action autonome de Pulse — quand Pulse agira, pas seulement quand il parlera.

La séparation est intentionnelle :
- **Parler** (injection LLM) → régi par `confidence`
- **Agir** (futures actions autonomes) → sera régi par `autonomy_level`

Un fait avec `confidence >= 0.60` a survécu à suffisamment de répétitions et au decay
pour mériter d'être mentionné au LLM. C'est le seul critère pertinent aujourd'hui.

---

## Ce que Pulse ne doit jamais faire

- **Inférer une intention depuis un pattern** : voir "Xcode + soir" n'est pas comprendre
  que tu développes le soir par préférence.
- **Promouvoir une heuristique faible par accumulation** : si la clé d'observation est
  trop large (par ex. `slot:soir:task:coding`), elle capturera des sessions très diverses
  sous la même étiquette.
- **Injecter un fait nouveau-né avec un ton affirmatif** : c'est l'origine directe de
  l'illusion de compréhension.
- **Confondre absence de contradiction avec confirmation** : Pulse ne contradite pas
  automatiquement — le silence n'est pas un vote de confiance.

---

## Ce que ça implique concrètement pour le code

Trois zones à reprendre après lecture de ce document :

**1. `_extract_observations()` dans `facts.py`**
Le wording des descriptions générées doit être calibré selon la force réelle du signal,
pas selon ce que l'observation "semble être". Revoir les formulations assertives.

**2. `render_for_context()` dans `facts.py`**
Ajouter le filtre `autonomy_level >= 1` et moduler le seuil de confiance par niveau.
Un fait tout juste promu (`autonomy_level = 0`) ne doit pas être injecté.

**3. `_promote_pending()` dans `facts.py`**
Vérifier que la clé d'observation est suffisamment spécifique avant promotion.
Une clé trop générique produit des faits qui semblent solides mais couvrent des réalités
très différentes.

---

*Document de référence Pulse — à consulter avant toute modification du pipeline mémoire.*
*Ancré sur le code réel au 20 avril 2026.*
