# Pulse

Pulse est une couche locale d'observation, de structuration de contexte, de mémoire et de contrôle autour des outils IA sur macOS.

Aujourd'hui, Pulse sait :
- observer l'activité locale utile
- maintenir un présent runtime canonique
- consolider une mémoire sessionnelle et des faits utilisateur
- intercepter certaines commandes agents via MCP
- produire des propositions explicables

Pulse n'est pas :
- un agent autonome
- un système qui comprend parfaitement le travail utilisateur
- un système qui structure déjà toute sa mémoire et ses propositions autour des épisodes

La fondation du runtime est en place. Pulse est maintenant recentré autour d'un présent canonique, de contextes de session récents et de blocs de travail dérivés des événements significatifs. Les anciens champs d'épisodes restent exposés comme alias de compatibilité, mais ils ne sont plus le modèle produit.

---

## Vue d’ensemble

Pulse combine :
- une app Swift macOS centrée sur l'encoche et l'observation système
- un daemon Python local qui qualifie les événements, gère le cycle de session, calcule les signaux, met à jour le présent canonique, décide et alimente la mémoire
- une couche LLM optionnelle pour les cas où l'approche déterministe ne suffit plus

Principe fondamental :

> Tout ce qui peut être décidé sans LLM doit être décidé sans LLM.

---

## Ce que Pulse fait aujourd’hui

- **Observation locale** : apps actives, fichiers touchés, clipboard, lock/unlock écran, événements utiles au runtime
- **Présent canonique** : `PresentState` dans `RuntimeState` est l'unique source de vérité du présent
- **Cycle de session** : `SessionFSM` produit l'état de session (`active` / `idle` / `locked`)
- **Contexte de travail** : `SignalScorer` produit `active_file`, `active_project`, `probable_task`, `activity_level`, `focus_level` et le contexte secondaire
- **Contexte rendu** : `CurrentContextBuilder` rend un `CurrentContext` depuis `present`, avec quelques détails secondaires encore lus depuis `signals`
- **Blocs de travail** : `SessionMemory` groupe les événements significatifs en `work_blocks` pour produire le bilan de journée et les blocs récents
- **Sessions récentes** : les sessions fermées sont exposées comme `recent_sessions` pour l'historique, avec alias legacy temporaire
- **Mémoire locale** : extraction rétrospective de résumés de session et consolidation de faits utilisateur
- **Proposals locales** : production de `ProposalCandidate`, puis conversion vers le transport legacy `Proposal`
- **Interception MCP** : traduction et arbitrage de certaines commandes risquées avant exécution
- **Chat contextuel** : injection du contexte local et de la mémoire consolidée dans les échanges assistant
- **Dashboard technique** : fenêtre macOS indépendante pour visualiser en temps réel session, mémoire, événements, MCP et état système

Ce que Pulse ne fait pas encore :
- structurer finement la mémoire autour des blocs de travail et de la continuité inter-session
- contextualiser finement les propositions par continuité de travail
- agir de manière autonome

---

## Architecture actuelle

```text
macOS events
    ↓
Swift observation layer
    ↓
daemon /event
    ↓
EventBus
    ↓
RuntimeOrchestrator
    ↓
SessionFSM
    ↓
SignalScorer
    ↓
RuntimeState.update_present()
    ↓
DecisionEngine
    ↓
SessionMemory
```

Rôles structurants du runtime actuel :
- `PresentState` : seule vérité canonique du présent
- `SessionFSM` : seule source de vérité du lifecycle de session
- `SignalScorer` : seule source du contexte de travail courant
- `RuntimeOrchestrator` : orchestration du pipeline, pas source de vérité
- `CurrentContextBuilder` : renderer pur pour les lectures assistant/UI
- `SessionMemory` : persistance historique, pas writer du présent

Le runtime expose aussi un **snapshot atomique** via `RuntimeState.get_runtime_snapshot()`.
Il contient `present`, `signals`, `decision` et quelques métadonnées runtime.
Il existe pour éviter les lectures hybrides où `present`, `signals` et `decision` seraient lus à des instants différents.

Règle d'implémentation :

> toute lecture qui combine `present`, `signals` et `decision` doit passer par `get_runtime_snapshot()`

Lire ces champs séparément est incorrect.

## Sources de vérité

- `RuntimeState` / `PresentState` : vérité live du présent runtime
- `session.db` et les `work_blocks` dérivés des événements significatifs : vérité temporelle persistée
- `sessions/*.md`, `facts.md`, `projects.md` : projections lisibles et dérivées, jamais source primaire
- `MemoryStore` et `DayDream` : couches de support hors chemin critique tant qu'elles n'apportent pas une valeur observable stable

Règle runtime importante :

> verrou court ≠ nouvelle session

Cette règle est implémentée dans `SessionFSM`.
Un lock court conserve la session courante ; il ne doit pas créer de frontière fantôme au premier event significatif suivant.

Références :
- [Architecture](./docs/FR/architecture.md)
- [Contrat sémantique](./docs/FR/semantic_contract.md)
- [Roadmap](./docs/FR/refactor-roadmap.md)

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
| GET | `/state` | Projection du snapshot runtime : `present` canonique, top-level déprécié pour compat UI, `debug` non contractuel |
| GET | `/insights` | Activité récente issue du bus |
| POST | `/event` | Entrée d’événements depuis l’app Swift |
| POST | `/ask` | Question assistant avec contexte local |
| POST | `/ask/stream` | Streaming assistant |
| GET | `/facts` | Faits utilisateur consolidés |
| GET | `/facts/profile` | Bloc mémoire injecté dans le prompt |
| GET | `/memory` | Entrées du `MemoryStore` |
| GET | `/memory/sessions` | Journaux de session exposés pour le dashboard |
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

Elle n’est pas encore une mémoire riche de continuité. Les `work_blocks` et `recent_sessions` servent de base plus simple que l'ancien modèle d'épisodes.

---

## Limites actuelles

- `CurrentContext` reste un rendu. Il dépend encore partiellement de `signals` pour quelques champs secondaires (`task_confidence`, terminal, MCP, résumés de signaux).
- `signals` ne sont pas une source de vérité du présent. Ils ne doivent pas être utilisés comme base d'une décision métier ou d'une nouvelle feature de contexte principal.
- `/state` garde des champs top-level et des blocs legacy pour compat UI et debug. Ces champs top-level sont dépréciés. Toute nouvelle lecture doit passer par `present`.
- Le marqueur de lock legacy existe encore dans `RuntimeState` pour filtrage, debug et compat. Il n'est pas canonique et ne doit jamais servir de source métier.
- Les alias legacy `work_window_*` et `closed_episodes` existent encore pour compatibilité. Toute nouvelle lecture doit utiliser `current_context`, `recent_sessions`, `work_blocks` et `work_block_*`.

---

## Intégration MCP

Pour l'usage réel actuel avec Claude Desktop, le transport MCP canonique de Pulse est `stdio`.

Le point d'entrée MCP réel est :

```bash
python3 -m daemon.mcp.stdio_server
```

Ce serveur `stdio` implémente les méthodes MCP visibles (`initialize`, `tools/list`, `tools/call`), puis relaie les commandes au daemon HTTP local sur `http://127.0.0.1:8765` via `/mcp/intercept`.

Exemple de configuration Claude Desktop dans `~/Library/Application Support/Claude/claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "pulse": {
      "command": "/abs/path/to/Pulse/.venv/bin/python3",
      "args": [
        "-m",
        "daemon.mcp.stdio_server"
      ],
      "env": {
        "PYTHONPATH": "/abs/path/to/Pulse"
      }
    }
  }
}
```

Pulse peut alors :
- intercepter certaines commandes
- les traduire
- scorer leur risque
- attendre une décision utilisateur

Un serveur SSE custom existe aussi sur `http://127.0.0.1:8766/mcp`, mais il est aujourd'hui secondaire et ne doit pas être lu comme la voie principale d'intégration Claude Desktop.

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
  - `PresentState`
  - `CurrentContext`
  - `SessionSnapshot`
  - `ProposalCandidate`
  - `SessionFSM`
  - compat legacy golden sur `build_context_snapshot()`, `/state`, `export_session_data()`

La documentation de test détaillée est dans [docs/testing.md](./docs/FR/testing.md).

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
- la phase `Observation terrain` est clôturée
- le système expose désormais un dashboard technique et une observabilité plus explicite

Le premier périmètre Episode a été retiré du runtime produit.
Les chantiers encore ouverts concernent surtout l’exploitation des blocs de travail par la mémoire et les proposals, ainsi que la lisibilité de l’historique utile.
