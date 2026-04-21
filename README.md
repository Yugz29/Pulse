# Pulse

Pulse est une couche locale d'observation, de structuration de contexte, de mémoire et de contrôle autour des outils IA sur macOS.

Aujourd'hui, Pulse sait :
- observer l'activité locale utile
- structurer le contexte courant
- consolider une mémoire sessionnelle et des faits utilisateur
- intercepter certaines commandes agents via MCP
- produire des propositions explicables

Pulse n'est pas :
- un agent autonome
- un système qui comprend parfaitement le travail utilisateur
- un système à épisodes déjà en production

La fondation du runtime est en place. La prochaine étape logique du projet est l'observation terrain du système stabilisé, avant toute ouverture d'un vrai chantier `Episode System`.

---

## Vue d’ensemble

Pulse combine :
- une app Swift macOS centrée sur l'encoche et l'observation système
- un daemon Python local qui qualifie les événements, calcule les signaux, gère le cycle de session, produit du contexte et alimente la mémoire
- une couche LLM optionnelle pour les cas où l'approche déterministe ne suffit plus

Principe fondamental :

> Tout ce qui peut être décidé sans LLM doit être décidé sans LLM.

---

## Ce que Pulse fait aujourd’hui

- **Observation locale** : apps actives, fichiers touchés, clipboard, lock/unlock écran, événements utiles au runtime
- **Contexte courant** : construction d’un `CurrentContext` temps réel à partir des signaux de session
- **Cycle de session** : gestion unifiée du lifecycle via `SessionFSM`
- **Projection de session** : production d’un `SessionSnapshot` structuré, exposé avec compat legacy
- **Mémoire locale** : extraction rétrospective de résumés de session et consolidation de faits utilisateur
- **Proposals locales** : production de `ProposalCandidate`, puis conversion vers le transport legacy `Proposal`
- **Interception MCP** : traduction et arbitrage de certaines commandes risquées avant exécution
- **Chat contextuel** : injection du contexte local et de la mémoire consolidée dans les échanges assistant

Ce que Pulse ne fait pas encore :
- segmenter le travail en épisodes exploitables
- structurer la mémoire autour des épisodes
- contextualiser finement les propositions par continuité de travail
- agir de manière autonome

---

## Architecture actuelle

```text
macOS events
    ↓
Swift observation layer
    ↓
Python daemon
    ├─ qualification d’événements
    ├─ scoring et interprétation locale
    ├─ CurrentContext
    ├─ SessionFSM
    ├─ SessionSnapshot
    ├─ ProposalCandidate
    └─ mémoire locale
    ↓
optional LLM enrichment
```

Le runtime actuel repose notamment sur :
- `CurrentContext` : vue synthétique temps réel
- `SessionSnapshot` : projection structurée de session
- `ProposalCandidate` : contrat métier avant transport legacy
- `SessionFSM` : source de vérité du lifecycle de session

Références :
- [Architecture](./docs/architecture.md)
- [Contrat sémantique](./docs/semantic_contract.md)
- [Roadmap](./docs/refactor-roadmap.md)

---

## Structure du projet

```text
Pulse/
├── App/                            # App macOS SwiftUI
│   └── App.xcodeproj
├── AppTests/                       # Tests Swift
├── daemon/                         # Daemon Python local
│   ├── main.py
│   ├── runtime_orchestrator.py
│   ├── runtime_state.py
│   ├── cognitive.py
│   ├── core/
│   │   ├── contracts.py
│   │   ├── current_context_builder.py
│   │   ├── current_context_adapters.py
│   │   ├── session_fsm.py
│   │   ├── signal_scorer.py
│   │   ├── decision_engine.py
│   │   ├── proposal_candidate_adapter.py
│   │   ├── proposals.py
│   │   ├── event_actor.py
│   │   ├── event_bus.py
│   │   ├── state_store.py         # encore présent pour compat
│   │   └── git_diff.py
│   ├── memory/
│   │   ├── session.py
│   │   ├── session_snapshot_builder.py
│   │   ├── extractor.py
│   │   ├── facts.py
│   │   └── store.py
│   ├── routes/
│   │   ├── runtime.py
│   │   ├── assistant.py
│   │   ├── memory.py
│   │   ├── facts.py
│   │   └── mcp.py
│   ├── mcp/                        # Serveur MCP
│   ├── interpreter/                # Interprétation de commandes
│   ├── llm/                        # Runtime et providers LLM
│   └── scoring/                    # Scoring structurel de code
├── docs/                           # Documentation de référence
├── launchd/                        # Intégration LaunchAgent
├── scripts/
│   ├── start_pulse_daemon.sh
│   ├── test_all.sh
│   └── install_launch_agent.sh
└── tests/                          # Tests Python
```

---

## Lancer le daemon

```bash
cd Pulse
python3 -m venv .venv
source .venv/bin/activate
pip install -r daemon/requirements.txt
python daemon/main.py
```

Le daemon écoute sur `http://127.0.0.1:8765`.

---

## Routes principales

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/ping` | Health check |
| GET | `/state` | État courant legacy-compatible du runtime |
| GET | `/insights` | Activité récente issue du bus |
| POST | `/event` | Entrée d’événements depuis l’app Swift |
| POST | `/ask` | Question assistant avec contexte local |
| POST | `/ask/stream` | Streaming assistant |
| GET | `/facts` | Faits utilisateur consolidés |
| GET | `/facts/profile` | Bloc mémoire injecté dans le prompt |
| GET | `/memory` | Entrées du `MemoryStore` |
| GET | `/mcp/pending` | Commande agent en attente |
| POST | `/mcp/decision` | Autoriser ou refuser une commande |

---

## Mémoire locale

```text
~/.pulse/
├── facts.db
├── cooldown.json
├── memory.db
├── session.db
└── memory/
    ├── MEMORY.md
    ├── facts.md
    ├── projects.md
    └── sessions/
        └── YYYY-MM-DD.md
```

### Ce que mémorise Pulse aujourd’hui

- sessions de travail rétrospectives
- faits utilisateur dérivés d’observations répétées
- projets connus
- résumés de commit quand un commit confirmé sert de frontière fiable

La mémoire actuelle reste principalement :
- session-centrique
- heuristique
- locale

Elle n’est pas encore structurée par épisodes.

---

## Intégration MCP

Ajoute dans `~/.claude/settings.json` :

```json
{
  "mcpServers": {
    "pulse": {
      "type": "sse",
      "url": "http://127.0.0.1:8766/mcp"
    }
  }
}
```

Pulse peut alors :
- intercepter certaines commandes
- les traduire
- scorer leur risque
- attendre une décision utilisateur

---

## Tests

Entrée standard :

```bash
cd Pulse
./scripts/test_all.sh
```

Cette commande :
- force le venv local
- utilise Python 3.11+
- évite les faux négatifs liés au Python système macOS

Le repo contient actuellement :
- 43 fichiers de tests Python dans `tests/`
- des tests ciblés sur les contrats et verrous récents :
  - `CurrentContext`
  - `SessionSnapshot`
  - `ProposalCandidate`
  - `SessionFSM`
  - compat legacy golden sur `build_context_snapshot()`, `/state`, `export_session_data()`

La documentation de test détaillée est dans [docs/testing.md](./docs/testing.md).

---

## App Swift

Ouvre `App/App.xcodeproj` dans Xcode et lance la target macOS.

L’app :
- observe le système local
- envoie les événements utiles au daemon
- affiche le contexte courant
- expose les contrôles runtime
- sert de point d’entrée UX pour le chat et les décisions MCP

---

## Stack

- Swift / SwiftUI pour l’app macOS
- Python 3.11+ pour le daemon
- SQLite pour la mémoire locale
- Ollama local ou provider configuré pour les enrichissements LLM

---

## Niveau de maturité

Le projet est aujourd’hui dans une phase où :
- la fondation runtime est stabilisée
- la compat legacy est verrouillée
- le système est assez structuré pour être observé sérieusement

La prochaine étape logique n’est pas d’ajouter des features lourdes.
La prochaine étape logique est de mesurer le comportement réel du système stabilisé avant d’ouvrir un chantier Episode.
