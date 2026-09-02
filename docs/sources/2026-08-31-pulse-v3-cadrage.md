# Pulse V3 — Vision & Architecture

> Source datée : conversion Markdown du document `Pulse_V3_Vision_Architecture.docx`
> (31 août 2026), document de cadrage pour discussion technique avec Claude.
> Ce document est conservé tel quel comme source. Le document canonique, dégraissé
> selon les décisions prises depuis, est [`../VISION.md`](../VISION.md).

*Vers une IA personnelle locale, contextuelle, ambiante et proactive.*

## 1. Résumé exécutif

Pulse n'a pas vocation à devenir un simple chatbot local. L'objectif est de construire un système capable d'observer en continu l'environnement de travail, de conserver une mémoire exploitable, de reconstruire le contexte courant, de raisonner localement et, lorsque cela apporte réellement de la valeur, d'agir ou d'intervenir de manière proactive.

Le nouveau MacBook Pro M3 Max (14 CPU / 30 GPU, 36 Go de mémoire unifiée) change la faisabilité du projet : Pulse peut désormais être pensé comme une plateforme locale permanente, avec plusieurs services, une mémoire vectorielle et des modèles locaux de tailles différentes, plutôt que comme une expérimentation limitée par la machine.

Le principe directeur proposé pour V3 est de séparer strictement l'observation fiable de l'intelligence. Pulse Core reste minimal, déterministe et robuste. Les couches Intelligence et Agent consomment le contexte exposé par Core sans devenir nécessaires à son fonctionnement.

## 2. Vision produit

Vision : un système local-first qui comprend progressivement ce que l'utilisateur est en train de faire, ce qu'il essaye d'accomplir et ce qui s'est passé auparavant, sans exiger qu'il fournisse manuellement son contexte à chaque interaction.

Pulse doit tendre vers cinq capacités fondamentales :

- **Perception** : observer applications, fichiers, terminal, Git, projets et événements système pertinents.
- **Mémoire** : conserver l'historique brut et des représentations sémantiques exploitables.
- **Compréhension** : transformer les événements en sessions, intentions probables, résumés et contexte courant.
- **Action** : permettre à des agents d'utiliser des outils contrôlés (Git, fichiers, Cortex, DevNote, etc.).
- **Proactivité** : savoir quand une information mérite d'être présentée et, tout aussi important, quand rester silencieux.

## 3. Ce qui existe déjà

### Pulse Core / daemon_v2

- Daemon Flask local et base SQLite.
- Watchers terminal (zsh), fichiers et applications.
- Endpoints existants : activités, trace du jour, statut et historique par jours.
- Logique de sessions avec fenêtre temporelle et rattachement des activités.
- Base locale `~/.pulse_v2/trace.db`.
- Socle déjà fortement testé : 267 tests réussis lors du dernier état connu.

### Pulse Lab

- Interface / expérimentation SwiftUI + Python.
- sqlite-vec, Ollama et expérimentations MCP.
- Espace approprié pour les fonctions non critiques et l'intelligence expérimentale.

Le découpage Core / Lab constitue déjà une bonne intuition architecturale qu'il faut renforcer en V3.

## 4. Architecture cible proposée

```text
PULSE CORE
  │
  ├── Watchers / Collectors
  ├── Event Store
  ├── Session Engine
  ├── Normalisation
  └── Context API
          │
          ▼
PULSE INTELLIGENCE
  │
  ├── Context Engine
  ├── Summarization
  ├── Embeddings
  ├── Semantic Memory
  ├── Relevance / Salience
  └── Model Router
          │
          ▼
PULSE AGENT
  │
  ├── Decision / Policy
  ├── Tool Registry
  ├── Git / Files
  ├── Cortex
  ├── DevNote
  └── Future tools
          │
          ▼
PULSE INTERFACES
  ├── macOS
  ├── CLI
  ├── Notifications
  ├── DevNote
  ├── Cortex
  └── Quest 3
```

### 4.1 Pulse Core — la vérité factuelle

Core ne doit pas dépendre d'un LLM. Sa mission est de capturer, normaliser, stocker et exposer des faits. Si tous les modèles IA sont arrêtés, Core doit continuer à fonctionner normalement.

- Faible consommation CPU/RAM.
- Données structurées et versionnées.
- API locale stable.
- Tolérance aux pannes des consommateurs.
- Aucune décision irréversible prise par un modèle.

### 4.2 Pulse Intelligence — transformer les faits en contexte

Cette couche construit une représentation plus riche à partir des événements : activité courante, projet actif, résumés de sessions, changements importants, liens avec des événements historiques et récupération sémantique.

```text
events → sessions → context snapshots → summaries
                         │
                         ├── structured memory
                         └── vector memory
```

### 4.3 Pulse Agent — décider et utiliser des outils

L'agent ne devrait pas avoir un accès arbitraire à la machine. Il consomme un registre explicite d'outils avec permissions, paramètres, journalisation et politiques de confirmation adaptées au niveau de risque.

- Lire un git diff ou l'historique récent.
- Interroger Cortex sur la structure d'un repository.
- Chercher une note ou un contexte dans DevNote.
- Produire un résumé de reprise de travail.
- Proposer une action avant de l'exécuter lorsqu'elle modifie l'état du système.

## 5. Architecture IA locale

Le système ne devrait pas dépendre d'un modèle unique. Un routeur peut sélectionner le niveau de modèle selon la tâche afin d'éviter de maintenir un modèle lourd en mémoire en permanence.

```text
                 MODEL ROUTER
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
      FAST LLM     CODE LLM    LARGE LLM
       ~4–8B        ~7–14B      ~20–30B
          │           │           │
          └───────────┴───────────┘
                      │
                Embeddings
                      │
              Semantic Memory
```

Ollama peut rester une interface simple pour commencer. MLX mérite également d'être évalué sur Apple Silicon. Le choix définitif doit être basé sur des benchmarks réalisés sur la machine cible : latence, tokens/s, mémoire, temps de chargement, qualité et concurrence avec l'environnement de développement.

## 6. Mémoire : le cœur du problème

Une mémoire vectorielle seule ne suffit pas. Pulse devrait distinguer plusieurs types de mémoire afin de ne pas transformer chaque événement système en document sémantique.

| Type | Contenu | Usage |
|---|---|---|
| Événementielle | Apps, fichiers, commandes, timestamps | Reconstruction factuelle |
| Session | Périodes de travail et projet associé | Comprendre une activité continue |
| Sémantique | Résumés, décisions, concepts | Recherche par similarité |
| Épisodique | Ce qui s'est passé lors d'une session | Reprise de contexte |
| Long terme | Informations durablement utiles | Continuité entre semaines/mois |

## 7. Proactivité : le problème central

La qualité de Pulse ne se mesurera pas au nombre d'interventions produites. Une IA ambiante utile doit maximiser la pertinence et minimiser les interruptions.

```text
Signal détecté
     │
     ▼
Est-ce nouveau ?
     │
Est-ce pertinent maintenant ?
     │
L'utilisateur connaît-il déjà l'information ?
     │
L'interruption vaut-elle son coût ?
     │
 ┌───┴────┐
 ▼        ▼
NON      OUI
silence  intervention
```

La proactivité devrait donc être traitée comme un système de décision séparé, mesurable et ajustable, et non comme une simple instruction du type « sois proactif » envoyée au LLM.

## 8. Connexion avec Cortex, DevNote et Quest

### Cortex

Cortex peut devenir un outil spécialisé de Pulse pour comprendre la structure d'un repository : symboles, dépendances, complexité, churn, fan-in/fan-out et relations entre composants.

### DevNote

DevNote peut devenir une source de connaissance explicitement créée par l'utilisateur, complémentaire à la mémoire implicitement construite par Pulse.

### Quest 3 / Cortex Immersive

Le Quest ne doit pas exécuter l'intelligence lourde. Il peut agir comme une interface spatiale distante : sélection d'un nœud ou module dans Cortex Immersive, requête vers le Mac, analyse locale, puis restitution dans l'environnement XR.

```text
Quest 3
   │ WebSocket / HTTP
   ▼
Pulse / Cortex API — MacBook
   ├── repository context
   ├── semantic memory
   ├── local LLM
   └── agent tools
```

## 9. Exemple d'expérience cible

L'utilisateur ouvre Cortex après plusieurs jours sans travailler sur le projet. Pulse identifie le repository et la branche active, récupère la dernière session associée, observe les changements Git et rapproche le contexte des souvenirs pertinents.

> « Tu reprends Cortex Immersive. Lors de la dernière session, le prochain problème identifié était de rendre le graphe déplaçable et redimensionnable. La branche active est feature/immersive. Veux-tu que je reconstruise le contexte technique des derniers changements ? »

## 10. Ce qu'il ne faut pas faire

- Fusionner immédiatement Core, Lab, agents et interface dans un monolithe.
- Envoyer chaque événement brut au LLM.
- Indexer aveuglément toute l'activité dans une base vectorielle.
- Maintenir en permanence le plus gros modèle possible en mémoire.
- Donner à un agent un accès shell non contrôlé par défaut.
- Construire une nouvelle interface avant d'avoir stabilisé le modèle de contexte.
- Faire de la proactivité une simple notification générée périodiquement.

## 11. Proposition de roadmap V3

- **Phase 0 — Benchmark machine** — Installer le socle IA et mesurer plusieurs modèles / runtimes sur le M3 Max.
- **Phase 1 — Audit** — Cartographier précisément Core et Lab : composants réutilisables, dette, APIs, schéma DB, responsabilités.
- **Phase 2 — Context API** — Définir le contrat stable permettant de demander : activité courante, projet, session, historique et contexte.
- **Phase 3 — Context Engine** — Construire les snapshots de contexte sans dépendre d'une proactivité ou d'un agent.
- **Phase 4 — Memory** — Ajouter résumés, embeddings, recherche sémantique et politique de rétention.
- **Phase 5 — Model Router** — Séparer modèle rapide, modèle code et modèle lourd à la demande.
- **Phase 6 — Agent Tools** — Brancher Git, fichiers, Cortex et DevNote derrière des interfaces explicites.
- **Phase 7 — Proactivity Engine** — Concevoir scoring de pertinence, cooldown, historique des interventions et feedback.
- **Phase 8 — Interfaces** — macOS d'abord ; Cortex / Quest ensuite si l'architecture centrale est stable.

## 12. Questions à challenger avec Claude

- Cette séparation Core / Intelligence / Agent / Interfaces est-elle suffisamment nette ?
- Quel modèle de données adopter pour les événements, sessions, context snapshots et mémoires ?
- SQLite reste-t-il pertinent pour Core pendant que la mémoire sémantique utilise un autre stockage ?
- Faut-il conserver sqlite-vec, passer à pgvector, ou abstraire complètement le backend vectoriel ?
- Comment concevoir le Context Engine pour qu'il reste déterministe avant intervention d'un LLM ?
- Quel protocole interne privilégier entre services : HTTP, WebSocket, Unix socket, event bus ?
- Comment router les modèles sans complexifier prématurément l'architecture ?
- Comment mesurer la qualité d'une intervention proactive et apprendre du feedback utilisateur ?
- Quelle frontière de sécurité établir entre suggestion, lecture automatique et action modifiant le système ?
- Quelles parties du Pulse actuel faut-il conserver telles quelles, refactorer ou supprimer avant V3 ?

## 13. Principe directeur

Pulse doit connaître le contexte avant que l'utilisateur ne lui parle — mais il doit mériter le droit de l'interrompre.

Le prochain travail ne consiste donc pas à ajouter immédiatement des fonctionnalités. Il consiste à auditer l'existant et à déterminer l'architecture minimale qui permet de transformer Pulse d'un système de traçage expérimental en plateforme contextuelle personnelle.
