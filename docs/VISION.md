# Pulse — Vision et architecture

*Document canonique. Rédigé le 2026-09-02 à partir du cadrage V3 du 2026-08-31
([source](sources/2026-08-31-pulse-v3-cadrage.md)), dégraissé selon les
décisions prises depuis. En cas de contradiction, ce document prime.*

## Principe directeur

Pulse doit connaître le contexte avant que l'utilisateur ne lui parle — mais il
doit mériter le droit de l'interrompre.

L'observation fiable et l'intelligence sont strictement séparées. Pulse Core
reste minimal, déterministe et robuste. Les couches au-dessus consomment le
contexte exposé par Core sans jamais devenir nécessaires à son fonctionnement.

## Vision produit

Un système local-first qui comprend progressivement ce que l'utilisateur est en
train de faire, ce qu'il essaye d'accomplir et ce qui s'est passé auparavant,
sans exiger qu'il fournisse manuellement son contexte à chaque interaction.

Pulse tend vers cinq capacités :

- **Perception** : observer applications, fichiers, terminal, Git, projets et
  sessions d'agents.
- **Mémoire** : conserver l'historique brut et en dériver des représentations
  exploitables.
- **Compréhension** : transformer les événements en sessions, résumés et
  contexte courant.
- **Action** : permettre à des agents d'utiliser des outils contrôlés.
- **Proactivité** : savoir quand une information mérite d'être présentée et,
  tout aussi important, quand rester silencieux.

Philosophie de construction : composer avec des briques existantes
(bibliothèques, inférence) mais construire soi-même le cœur — orchestration,
mémoire, contexte.

## Architecture en quatre couches

Pulse désigne le système entier. Pulse Core désigne la couche observation et
garde son nom.

*Architecture cible à long terme. Ce qui est engagé est dans la roadmap ; le
reste est dans « Plus tard ».*

```text
PULSE CORE
  ├── Watchers / Collectors
  ├── Event Store
  ├── Session Engine
  ├── Normalisation
  └── Context API
          ▼
PULSE INTELLIGENCE
  ├── Context Engine
  ├── Summarization
  ├── Embeddings
  ├── Semantic Memory
  ├── Relevance / Salience
  └── Model Router
          ▼
PULSE AGENT
  ├── Decision / Policy
  ├── Tool Registry
  ├── Git / Files
  ├── Cortex
  ├── DevNote
  └── Future tools
          ▼
PULSE INTERFACES
  ├── macOS
  ├── CLI
  ├── Notifications
  ├── DevNote
  ├── Cortex
  └── Quest 3
```

### Core — la vérité factuelle

Core capture, normalise, stocke et expose des faits. Il ne dépend d'aucun
modèle : si toute l'IA est arrêtée, Core continue de fonctionner. Faible
consommation, données structurées et versionnées, API locale stable, aucune
décision irréversible prise par un modèle.

**État actuel : existe, gelé, version 0.3.0** (`core/`). Daemon Flask et
SQLite append-only (`~/.pulse_v2/trace.db`), watchers terminal, fichiers
(FSEvents), applications (Swift), hook Git, sessions d'agents Claude Code /
Codex en événements dérivés, services résidents sous launchd, vue HTML locale.
462 tests. Le Context API (`GET /context`, pas 2 de la roadmap) est livré en
0.3.0 : c'était le seul changement prévu dans Core, qui est de nouveau gelé.

### Intelligence — transformer les faits en contexte

Construit une représentation plus riche à partir des événements : activité
courante, projet actif, résumés de sessions, liens avec l'historique.

```text
events → sessions → context snapshots → summaries
```

**État actuel : à construire** (`intelligence/`). Un seul modèle local pour
commencer, servi par MLX sur Apple Silicon. Pulse ne dépend d'aucun runtime
d'inférence spécifique : le runtime est une brique remplaçable.

### Agent — décider et utiliser des outils

L'agent n'a pas d'accès arbitraire à la machine. Il consomme un registre
explicite d'outils avec permissions, journalisation et confirmation adaptée au
niveau de risque : lire un diff, produire un résumé de reprise, proposer une
action avant de l'exécuter lorsqu'elle modifie l'état du système.

**État actuel : plus tard.** Rien avant que le contexte et les résumés existent.

### Interfaces

**État actuel : HTML local existant** (rendu par Core). Interface native
macOS, CLI et notifications plus tard, une fois le modèle de contexte
stabilisé.

## Mémoire

Deux types de mémoire pour commencer :

- **Événementiel et sessions** : existe, c'est `trace.db`. Brut conservé
  indéfiniment, aucune purge. Les transcripts d'agents n'y entrent jamais en
  brut : événement dérivé `agent_session` plus archive zstd séparée.
- **Résumés** : à construire, stockés comme événements dérivés sur le même
  patron que `agent_session`.

Les mémoires sémantique, épisodique et long terme viendront quand il y aura des
résumés à indexer, pas avant.

## Ce qu'il ne faut pas faire

- Fusionner immédiatement Core, Lab, agents et interface dans un monolithe.
- Envoyer chaque événement brut au LLM.
- Indexer aveuglément toute l'activité dans une base vectorielle.
- Maintenir en permanence le plus gros modèle possible en mémoire.
- Donner à un agent un accès shell non contrôlé par défaut.
- Construire une nouvelle interface avant d'avoir stabilisé le modèle de
  contexte.
- Faire de la proactivité une simple notification générée périodiquement.

## Roadmap en trois pas

1. **Geler Core à 0.2.** Décidé le 2026-09-02, sur la 0.2.0 sortie le
   2026-08-31. Core ne bouge plus, sauf pour le pas 2.
2. **Context API.** `GET /context` déterministe, sans LLM : activité courante,
   projet, session, historique récent. C'est le contrat stable que les couches
   supérieures consomment. Livré le 2026-09-02 (Core 0.3.0), spec dans
   [`specs/2026-09-02-context-api.md`](specs/2026-09-02-context-api.md).
3. **Première boucle IA.** Résumé de session par un modèle local, stocké comme
   événement dérivé, même patron que `agent_session`. Le résumé alimente la
   reprise et servira de matière à la mémoire.

La proactivité vient après ces trois pas. Les phases benchmark et audit du
cadrage V3 sont supprimées : l'audit est fait, le benchmark se fera sur un
problème réel.

## Plus tard

- **Model Router** à plusieurs tiers : seulement quand un problème réel
  l'exigera. Un modèle suffit pour commencer.
- **Mémoires additionnelles** (sémantique, épisodique, long terme) : quand il y
  aura des résumés à indexer.
- **Proactivité** : un système de décision séparé, mesurable et ajustable (est-ce
  nouveau, pertinent maintenant, déjà connu, l'interruption vaut-elle son
  coût), jamais une instruction « sois proactif » envoyée au LLM.
- **Cortex, DevNote, Quest 3** : hors périmètre de la roadmap. Cortex (structure
  d'un dépôt) et DevNote (notes explicites) restent des sources d'enrichissement
  optionnelles, jamais structurantes : Pulse doit dégrader proprement si elles
  sont absentes. Le Quest n'exécute rien de lourd, c'est au mieux une interface
  distante.
- **Sources d'observation supplémentaires** présentes dans Lab et absentes de
  Core : presse-papiers, titre de fenêtre active via Accessibility, inactivité
  via IOKit. À reconsidérer si un besoin de contexte les réclame.

## Décisions prises

Les notes détaillées sont dans [`decisions/`](decisions/). Les décisions de
Core antérieures au gel sont consignées dans `core/TODOS.md` (section
« Completed ») et `core/CHANGELOG.md`.

- **2026-08-29** — Cinq lignes historiques à motif secret vérifiées : faux
  positifs, aucune donnée réécrite. Le prédicat d'audit est corrigé.
- **2026-08-30** — Rétention de `trace.db` : conservation infinie du brut, aucune
  purge, aucun résumé de substitution. Réexamen uniquement sur seuils
  falsifiables. Les transcripts d'agents n'entrent jamais en brut.
- **2026-08-30** — Prompts collés par erreur au shell : placeholder seul si la
  commande échoue, aucun texte conservé.
- **2026-08-30** — Qualification projet identique en vue live et archive : la
  preuve git vient des détails persistés, plus jamais de l'état du disque au
  rendu.
- **2026-08-30** — Résolveur de workspace unique et parseur `git status` unique
  partagés par tout le pipeline.
- **2026-08-30** — Un signal fort isolé ne crée plus une session : il devient
  une activité isolée.
- **2026-08-31** — Hook SessionEnd Claude Code : émission immédiate de
  `agent_session`, résumé figé à la première fin de session assumé.
- **2026-08-31** — Watcher fichiers et observateur d'apps deviennent des
  services résidents launchd, liste de workspaces déclarée explicitement.
- **2026-09-02** — Core gelé en version 0.2.0 (sortie le 2026-08-31) ;
  roadmap réduite à trois pas ; un seul modèle local, pas de
  Model Router ; deux types de mémoire ; runtime MLX sans Ollama, Pulse
  indépendant du runtime ; Cortex, DevNote et Quest hors périmètre ; composer
  avec des briques mais construire le cœur soi-même ; Pulse = le système,
  Pulse Core = la couche observation.
- **2026-09-02** — Restructuration en repo unique : Core déplacé dans `core/`
  avec son historique, Lab archivé dans `~/Projets/ARCHIVE/Pulse_Lab` sous le
  tag `archive/lab-2026-09`, `CLAUDE.md` et `AGENTS.md` désormais suivis par
  git.
