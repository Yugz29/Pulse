

# Work Context — Modèle de contexte de travail

## Objectif

Le Work Context clarifie ce que Pulse pense comprendre du travail en cours.

Il ne sert pas à observer plus.
Il ne sert pas à donner de l'autonomie à Pulse.
Il ne sert pas à déclencher automatiquement des demandes de contexte.

Son rôle est plus simple :

```text
état runtime existant
→ interprétation produit
→ explication lisible
→ contexte manquant
→ probes safe possibles
```

Le but est d'éviter que Pulse accumule des signaux sans pouvoir expliquer clairement :

```text
ce qu'il pense que l'utilisateur fait
pourquoi il le pense
ce qui manque pour être plus sûr
ce qu'il pourrait demander sans être intrusif
```

---

## Les quatre couches à ne pas confondre

### 1. `PresentState`

`PresentState` est la vérité runtime immédiate.

Il représente le **maintenant**.

Il répond à des questions comme :

```text
Quelle application est active ?
Quel projet est actif ?
Quelle activité est détectée ?
La session est-elle active, idle ou locked ?
Quel est le focus courant ?
```

`PresentState` ne doit pas devenir une couche d'explication longue.
Il doit rester une source de vérité compacte et exploitable.

---

### 2. `CurrentContext`

`CurrentContext` est le contexte produit courant.

Il transforme l'état runtime et les signaux en une lecture plus utile pour l'interface et les autres modules.

Il répond à :

```text
Quel est le contexte de travail courant ?
Quelle tâche Pulse croit-il détecter ?
Quel niveau d'activité est visible ?
Quelle confiance est associée à cette lecture ?
```

Dans le Dashboard, la carte **Contexte actuel** est la représentation principale de cette couche.

`CurrentContext` ne doit pas être dupliqué par une deuxième carte produit concurrente.

---

### 3. `WorkContextCard`

`WorkContextCard` n'est pas une nouvelle vérité.

C'est une couche d'explication passive construite au-dessus du contexte existant.

Elle sert à enrichir **Contexte actuel**, pas à le remplacer.

Elle expose :

```text
project
activity_level
probable_task
confidence
evidence
missing_context
safe_next_probes
```

Sa valeur principale n'est pas `project`, `activity_level` ou `probable_task`, car ces informations existent déjà ailleurs.

Sa vraie valeur est :

```text
evidence
missing_context
safe_next_probes
```

Autrement dit :

```text
Pourquoi Pulse pense ça ?
Qu'est-ce qui manque ?
Qu'est-ce que Pulse pourrait demander sans danger ?
```

`WorkContextCard` ne doit pas être affichée comme une grosse carte séparée si cela crée un doublon avec **Contexte actuel**.

---

### 4. `Context Probes`

Les Context Probes sont des demandes contrôlées de contexte supplémentaire.

Ils ne sont pas automatiques.

Ils passent par :

```text
policy
request
approval/refusal
execution gate
runner
redaction si nécessaire
audit safe
```

Aujourd'hui, les probes exécutables sont :

```text
app_context
window_title redacted
```

Les probes sensibles restent non exécutés :

```text
selected_text
clipboard_sample
screen_snapshot
```

Le Work Context peut indiquer qu'un probe serait safe ou utile, mais il ne doit pas le déclencher lui-même.

---

## Pipeline actuel

```text
SystemObserver / events
→ EventBus
→ SignalScorer
→ PresentState
→ CurrentContextBuilder
→ CurrentContext
→ WorkContextCard
→ Dashboard / Contexte actuel enrichi
```

Les Context Probes restent un flux séparé :

```text
WorkContextCard signale un manque éventuel
→ l'utilisateur reste en contrôle
→ Pulse peut créer une demande explicite
→ l'encoche ou le Dashboard demande validation
→ exécution seulement après approbation
```

---

## Ce que `/work-context` expose

La route :

```http
GET /work-context
```

retourne une carte passive :

```json
{
  "card": {
    "project": "Pulse",
    "activity_level": "editing",
    "probable_task": "debug",
    "confidence": 0.78,
    "evidence": [
      "Projet actif détecté : Pulse",
      "Niveau d'activité : editing",
      "Titre de fenêtre disponible"
    ],
    "missing_context": [
      "Objectif utilisateur non explicite"
    ],
    "safe_next_probes": [
      "app_context"
    ]
  }
}
```

Cette route ne doit pas :

```text
observer de nouvelles données
déclencher un probe
modifier la mémoire
prendre une décision autonome
approuver une demande
exécuter une action
```

---

## Règles produit

### Ne pas dupliquer la vérité UI

La carte principale dans le Dashboard reste :

```text
Contexte actuel
```

`WorkContextCard` doit enrichir cette carte avec :

```text
preuves
contexte manquant
probes safe possibles
```

Elle ne doit pas devenir une deuxième carte qui réaffiche projet/tâche/activité/confiance en concurrence avec le contexte actuel.

---

### Ne pas confondre manque et autorisation

Si `WorkContextCard` indique :

```text
Titre de fenêtre non disponible
safe_next_probes: ["window_title"]
```

cela signifie seulement :

```text
Pulse pourrait demander ce contexte proprement.
```

Cela ne signifie pas :

```text
Pulse peut le lire automatiquement.
```

---

### Pas d'autonomie implicite

Même si l'utilisateur accepte souvent un probe, le Work Context ne doit pas transformer cela en autorisation automatique.

L'autonomie viendra plus tard, si elle est ajoutée, avec des règles explicites comme :

```text
autoriser app_context pour cette session
autoriser window_title pour ce projet uniquement
ne jamais autoriser clipboard_sample automatiquement
```

Mais cette logique ne fait pas partie du Work Context actuel.

---

## Ce qui est volontairement hors scope

Le Work Context ne fait pas :

```text
- mémoire des décisions utilisateur
- auto-approve
- apprentissage de préférences
- scoring long terme
- sélection automatique de probes
- lecture de clipboard
- lecture de texte sélectionné
- capture écran
- OCR
```

---

## Principe directeur

Le Work Context doit aider Pulse à être plus clair, pas plus intrusif.

Le bon modèle est :

```text
observer avec les signaux existants
interpréter prudemment
expliquer ce qui est compris
montrer ce qui manque
proposer uniquement des probes safe
laisser l'utilisateur décider
```

Phrase de référence :

```text
Pulse ne doit pas seulement savoir plus de choses.
Pulse doit mieux expliquer ce qu'il croit savoir.
```