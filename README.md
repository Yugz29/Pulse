# Pulse

Pulse est une couche ambiante locale entre toi et les outils IA sur macOS.

Il combine :
- une app Swift macOS qui vit autour de l'encoche,
- un daemon Python qui observe l'activité système et intercepte les commandes risquées,
- un moteur de mémoire et de contexte injecté dans les conversations IA.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Swift — Observation système                    │
│  FSEvents · NSWorkspace · Clipboard             │
└────────────────────┬────────────────────────────┘
                     │ events bruts
┌────────────────────▼────────────────────────────┐
│  Python — Moteur cognitif (daemon)              │
│  Signal Scoring · Decision Engine               │
│  Command Interpreter · Cortex Scoring           │
│  FactEngine · Memory · Git Diff                 │
└────────────────────┬────────────────────────────┘
                     │ seulement si nécessaire
┌────────────────────▼────────────────────────────┐
│  LLM — Ollama local / Claude API                │
│  Résumés de commit · Réponses chat              │
└─────────────────────────────────────────────────┘
```

**Règle fondamentale :** tout ce qui peut être décidé sans LLM est décidé sans LLM.

---

## Ce que Pulse fait

- **Interception MCP** — intercepte les commandes que Claude Code veut exécuter, les traduit en français avec un score de risque, et attend ta décision depuis l'encoche.
- **Contexte session** — observe le projet actif, les fichiers modifiés, le diff git en cours, le focus et la friction.
- **Mémoire utilisateur** — apprend tes habitudes de travail (créneau, outils, sessions longues) via un moteur de faits avec confiance dynamique et decay temporel.
- **Journal de session** — génère un journal quotidien avec une entrée par session. Sur commit, le résumé exploite le diff réel du commit.
- **Chat dans l'encoche** — répond à tes questions avec le contexte session + profil utilisateur injecté.

---

## Structure du projet

```
Pulse/
├── App/                        # Swift macOS app
│   └── App.xcodeproj
├── daemon/                     # Python daemon (port 8765)
│   ├── main.py
│   ├── core/
│   │   ├── event_bus.py
│   │   ├── signal_scorer.py
│   │   ├── decision_engine.py
│   │   ├── state_store.py
│   │   └── git_diff.py         # Diff git en temps réel
│   ├── interpreter/            # Command Interpreter (porté de Claude Code)
│   ├── scoring/                # Moteur Cortex embarqué
│   ├── memory/
│   │   ├── facts.py            # Moteur de faits utilisateur
│   │   ├── store.py            # MemoryStore SQLite
│   │   ├── session.py          # Session courante
│   │   └── extractor.py        # Extraction et journal de session
│   ├── mcp/                    # Serveur MCP SSE (port 8766)
│   ├── llm/                    # Router LLM (Ollama / Claude)
│   ├── routes/                 # Routes Flask
│   │   ├── assistant.py
│   │   ├── facts.py            # API /facts
│   │   ├── memory.py
│   │   ├── mcp.py
│   │   └── runtime.py
│   └── runtime_orchestrator.py
└── tests/                      # Suite de tests Python (75 tests)
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
| GET | `/state` | État courant (signals, projet, fichier actif) |
| POST | `/ask` | Question au LLM avec contexte session |
| POST | `/ask/stream` | Streaming SSE |
| GET | `/facts` | Faits utilisateur consolidés |
| GET | `/facts/profile` | Profil injecté dans le prompt |
| GET | `/facts/stats` | Statistiques du moteur de faits |
| POST | `/facts/<id>/reinforce` | Valider un fait |
| POST | `/facts/<id>/contradict` | Corriger un fait |
| POST | `/facts/<id>/archive` | Archiver un fait erroné |
| GET | `/memory` | Entrées MemoryStore |
| GET | `/search` | Recherche FTS5 dans les events |
| GET | `/mcp/pending` | Commande en attente de décision |
| POST | `/mcp/decision` | Autoriser ou refuser une commande |

---

## Mémoire locale

```
~/.pulse/
├── facts.db                    # Faits utilisateur (SQLite)
├── cooldown.json               # Curseur anti-doublon (persiste entre restarts)
├── memory.db                   # MemoryStore structuré
├── session.db                  # Session courante
└── memory/
    ├── MEMORY.md               # Index
    ├── facts.md                # Profil utilisateur (export lisible)
    ├── projects.md             # Projets connus
    └── sessions/
        └── 2026-04-13.md       # Journal quotidien (une entrée par session)
```

### Moteur de faits

`facts.py` implémente un pipeline déterministe :

```
Observation brute → Signal (5 occurrences) → Fait consolidé
Fait → Renforcement / Contradiction → Archivage si confiance < 0.30
Fait stale (3j sans observation) → Decay (−0.02/jour)
```

Chaque fait porte : `confidence`, `observations`, `autonomy_level`, `last_seen`.

### Journal de session

Un seul fichier par jour (`YYYY-MM-DD.md`). Chaque session ajoute une section `## HH:MM`. Le LLM est activé **uniquement sur commit** — il reçoit le diff réel du commit pour produire un résumé informatif.

---

## Intégration Claude Code (MCP)

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

---

## Tests

```bash
cd Pulse
./.venv/bin/python -m unittest discover -s tests -v
```

75 tests couvrant : moteur de faits, extractor, git diff, routes API, orchestrator, session, store.

---

## App Swift

Ouvre `App/App.xcodeproj` dans Xcode et lance la target macOS.

L'app :
- affiche le panel dans l'encoche,
- observe apps / filesystem / clipboard,
- envoie les events au daemon,
- affiche le dashboard, les insights et le chat.

---

*Stack : Swift (macOS 14+) + Python 3.11+*
*LLM : Ollama local (gemma, mistral, phi) ou Claude API*
*Moteur de scoring : porté de Cortex (TypeScript → Python)*
*Command Interpreter : inspiré de Claude Code source interne*
