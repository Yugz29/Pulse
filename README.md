# Pulse

> **Statut actuel : Core Reset**
>
> Pulse est en phase de recadrage. Tant que le Core Reset n'est pas terminé, [`docs/ROADMAP_CORE_RESET.md`](./docs/ROADMAP_CORE_RESET.md) est le document maître prioritaire sur les anciennes roadmaps, notes d'architecture, documents mémoire, agent, apprentissage, DayDream, facts, propositions et extensions dashboard.
>
> **Pulse Core** désigne le chemin à stabiliser : runtime daemon, observation locale, événements filtrés, signaux explicables, sessions, journal minimal et dashboard de diagnostic.
>
> **Pulse Lab** désigne les capacités expérimentales ou prématurées : DayDream, facts/profile, vector store, résumés LLM, work intent, context probes, propositions avancées, apprentissage et adaptation.

Pulse est aujourd'hui recentré comme runtime local de diagnostic du contexte de travail sur macOS.

Aujourd'hui, Pulse sait :
- observer l'activité locale utile
- maintenir un présent runtime canonique
- structurer des sessions et des blocs de travail dérivés
- produire un journal minimal et des surfaces de diagnostic
- exposer, en Pulse Lab, des capacités expérimentales de mémoire, Resume Cards, Context Probes, MCP, LLM et propositions

Pulse n'est pas :
- un agent autonome
- un système qui comprend parfaitement le travail utilisateur
- un système qui structure déjà parfaitement toute sa mémoire et ses propositions autour de la continuité de travail
- une mémoire intelligente ou un système d'apprentissage utilisateur fiable

La fondation du runtime est en place. Pulse est maintenant recentré autour d'un présent canonique, de `current_context`, de `recent_sessions` et de `work_blocks` dérivés des événements significatifs. Les anciens champs d'épisodes et `work_window_*` restent lisibles comme alias de compatibilité, mais ils ne sont plus le modèle produit.

---

## Vue d’ensemble

Pulse combine :
- une app Swift macOS centrée sur l'encoche et l'observation système
- un daemon Python local qui qualifie les événements, gère le cycle de session, calcule les signaux, met à jour le présent canonique et alimente un historique minimal
- des couches Lab optionnelles pour mémoire avancée, LLM, propositions, probes et expérimentations

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
- **Journal minimal** : historique sessionnel local issu d'observations et de signaux dérivés
- **Lab - Resume Cards** : cartes de reprise déterministes ou LLM, encore expérimentales pendant le Core Reset
- **Lab - Context Probes** : demandes ponctuelles de contexte supplémentaire, validées et masquées avant exposition quand nécessaire
- **Lab - Mémoire avancée** : extraction rétrospective de résumés, facts utilisateur, profil et vector store
- **Lab - Proposals locales** : production de `ProposalCandidate`, puis conversion vers le transport legacy `Proposal`
- **Lab - Interception MCP** : traduction et arbitrage de certaines commandes risquées avant exécution
- **Lab - Chat contextuel** : injection du contexte local et de mémoire consolidée dans les échanges assistant
- **Dashboard diagnostic** : fenêtre macOS indépendante pour visualiser en temps réel session, événements, signaux et état système ; les onglets avancés restent Lab

Ce que Pulse ne fait pas encore :
- modéliser parfaitement les blocs de travail et la continuité inter-session
- corréler systématiquement sessions, commits, journal et reprises de contexte
- contextualiser finement les propositions par continuité de travail
- apprendre des habitudes utilisateur fiables
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
SessionFSM / SignalScorer
    ↓
RuntimeState.update_present()
    ↓
DecisionEngine
    ↓
SessionMemory
    ↓
work projections / journal / Resume Card
```

Rôles structurants du runtime actuel :
- `PresentState` : seule vérité canonique du présent
- `SessionFSM` : seule source de vérité du lifecycle de session
- `SignalScorer` : seule source du contexte de travail courant
-- `RuntimeOrchestrator` : orchestration du pipeline, déclencheurs proactifs et effets de bord contrôlés, pas source de vérité
- `CurrentContextBuilder` : renderer pur pour les lectures assistant/UI
- `SessionMemory` : persistance historique et projections de travail, pas writer du présent

Le runtime expose aussi un **snapshot atomique** via `RuntimeState.get_runtime_snapshot()`.
Il contient `present`, `signals`, `decision` et quelques métadonnées runtime.
Il existe pour éviter les lectures hybrides où `present`, `signals` et `decision` seraient lus à des instants différents.

Règle d'implémentation :

> toute lecture qui combine `present`, `signals` et `decision` doit passer par `get_runtime_snapshot()`

Lire ces champs séparément est incorrect.

## Sources de vérité

- `RuntimeState` / `PresentState` : vérité live du présent runtime
- `session.db` et les événements significatifs : vérité temporelle persistée
- `work_blocks` / `work_block_*` : projections temporelles dérivées, utilisées par la mémoire, les commits et les Resume Cards
- `sessions/*.md` : projection lisible et dérivée, jamais source primaire
- `facts.md`, `projects.md`, `MemoryStore`, vector store et `DayDream` : couches Lab hors chemin critique tant qu'elles n'apportent pas une valeur observable stable

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
│   └── Pulse.xcodeproj
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
│   │   ├── resume_card.py
│   │   ├── work_context.py
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
│   │   ├── context_probes.py
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
| GET | `/work-context` | Lecture explicative du contexte courant |
| POST | `/debug/resume-card` | Génération debug d’une Resume Card déterministe |
| POST | `/debug/resume-card/llm` | Génération debug d’une Resume Card LLM avec diagnostic |
| POST | `/event` | Entrée d’événements depuis l’app Swift |
| POST | `/ask` | Question assistant avec contexte local |
| POST | `/ask/stream` | Streaming assistant |
| GET | `/facts` | Lab : faits utilisateur consolidés |
| GET | `/facts/profile` | Lab : bloc mémoire injecté dans le prompt |
| GET | `/memory` | Lab : entrées du `MemoryStore` |
| GET | `/memory/sessions` | Journaux de session exposés pour le dashboard |
| GET/POST | `/context-probes/requests` | Lab : demandes ponctuelles de contexte supplémentaire avec validation |
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
- Lab : faits utilisateur dérivés d’observations répétées
- Lab : projets connus
- Lab : résumés de commit quand un commit confirmé sert de frontière fiable
- blocs de travail dérivés pour le bilan de journée et les reprises de contexte
- Lab : entrées de journal utilisées comme contexte court pour les Resume Cards

La mémoire Core actuelle doit rester principalement :
- session-centrique
- heuristique
- locale

Elle n’est pas encore une mémoire riche de continuité, ni un système d'apprentissage utilisateur. Les `work_blocks` et `recent_sessions` servent de base actuelle, plus simple et plus stable que l'ancien modèle d'épisodes.

---

## Limites actuelles

- `CurrentContext` reste un rendu. Il dépend encore partiellement de `signals` pour quelques champs secondaires (`task_confidence`, terminal, MCP, résumés de signaux).
- `signals` ne sont pas une source de vérité du présent. Ils ne doivent pas être utilisés comme base d'une décision métier ou d'une nouvelle feature de contexte principal.
- `/state` garde des champs top-level et des blocs legacy pour compat UI et debug. Ces champs top-level sont dépréciés. Toute nouvelle lecture doit passer par `present`.
- Le marqueur de lock legacy existe encore dans `RuntimeState` pour filtrage, debug et compat. Il n'est pas canonique et ne doit jamais servir de source métier.
- Les alias legacy `work_window_*` et `closed_episodes` existent encore pour compatibilité. Toute nouvelle lecture doit utiliser `current_context`, `recent_sessions`, `work_blocks` et `work_block_*`.
- La Resume Card préparée est stockée en mémoire uniquement et disparaît si le daemon redémarre.
- Il n’existe pas encore de route debug dédiée au cycle complet `prepared_resume_card` (`prepare`, `peek`, `consume`, `expire`).
- Les Context Probes sont des demandes ponctuelles validées ; elles ne sont ni une mémoire, ni un mécanisme d’auto-approval.

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

Le repo contient des tests ciblés sur les contrats et verrous récents :
- `PresentState`
- `CurrentContext`
- `SessionSnapshot`
- `ProposalCandidate`
- `SessionFSM`
- `ResumeCard`
- `work_blocks` / `work_block_*`
- `ContextProbeRequest`
- compat legacy golden sur `build_context_snapshot()`, `/state`, `export_session_data()` et les alias mémoire temporaires

La documentation de test détaillée est dans [docs/testing.md](./docs/FR/testing.md).

---

## App Swift

Ouvre `App/Pulse.xcodeproj` dans Xcode et lance la target macOS.

L’app :
- observe le système local
- envoie les événements utiles au daemon
- affiche le contexte courant
- expose les contrôles runtime
- sert aussi de point d’entrée UX Lab pour le chat et les décisions MCP

---

## Stack

- Swift / SwiftUI pour l’app macOS
- Python 3.11+ pour le daemon
- SQLite pour la mémoire locale
- Ollama local ou provider configuré pour les enrichissements LLM

---

## Niveau de maturité

Le projet est aujourd’hui dans une phase où :
- le Core Reset est prioritaire
- la fondation runtime existe mais doit être vérifiée en mode Core
- la compat legacy est verrouillée
- le système expose un dashboard technique et une observabilité plus explicite
- les capacités avancées doivent être traitées comme Pulse Lab tant que le Core n'est pas stabilisé

Le premier périmètre Episode a été retiré du runtime produit.
Les chantiers encore ouverts concernent surtout :
- la baseline runtime Core ;
- la baseline observation et scoring ;
- la fiabilité des sessions ;
- le journal minimal vérifiable ;
- la séparation explicite des surfaces Lab.
