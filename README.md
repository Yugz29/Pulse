# Pulse

Pulse est un runtime local-first de diagnostic du contexte de travail sur macOS.

Il observe l'activité locale, filtre le bruit, produit des signaux prudents, suit des sessions de travail, écrit un historique minimal vérifiable et contrôle certaines propositions MCP sous validation humaine.

Pulse n'est pas un agent intelligent. Il n'apprend pas encore les habitudes utilisateur, ne possède pas de profil utilisateur ou projet fiable, et ne doit pas agir de manière autonome.

## Statut actuel

Le Core Reset R1-R6 est validé côté Python.

- R1 — Baseline Runtime
- R2 — Baseline Observation
- R3 — Baseline Interprétation
- R4 — Baseline Sessions
- R5 — Baseline Mémoire minimale
- R6 — Baseline Propositions contrôlées

Dernière validation complète documentée :

```bash
./scripts/test_all.sh
# 1216 tests OK
```

La prochaine étape saine est la validation terrain du Core en `PULSE_MODE=core`, sans démarrer R7 et sans ajouter de nouvelle feature intelligente.

## Ce que Pulse Core fait aujourd'hui

Pulse Core couvre maintenant :

- le démarrage daemon en mode `core` par défaut ;
- `/ping`, `/state`, `/debug/state`, `/feed` et `/health/core` sans dépendance aux services Lab ;
- l'ingestion `/event` vers `EventBus` ;
- le filtrage du bruit technique ;
- la classification d'apps, fichiers, terminal et acteur ;
- la normalisation des événements terminal ;
- un `SignalScorer` prudent, verrouillé par scénarios golden ;
- des payloads d'état qui exposent le présent runtime ;
- `SessionFSM` avec états réels `idle`, `active`, `locked` ;
- la persistance minimale des sessions via `SessionMemory` SQLite ;
- des snapshots et exports historiques minimaux ;
- un journal minimal avec hidden payload et `truth_layers` ;
- des routes mémoire en lecture historique ;
- un flux MCP contrôlé où une commande n'est autorisée que si la proposition passe en `accepted`.

Lecture correcte : Pulse produit des hypothèses locales et traçables, pas des certitudes sur le travail ou l'utilisateur.

## Ce que Pulse ne fait pas encore

Pulse Core ne garantit pas :

- une compréhension profonde du travail utilisateur ;
- l'apprentissage d'habitudes ;
- un profil utilisateur fiable ;
- un profil projet fiable ;
- une mémoire sémantique stable ;
- des résumés LLM fiables ;
- une recherche vectorielle produit ;
- des propositions intelligentes ;
- des actions autonomes ;
- une adaptation du comportement ;
- une séparation parfaite produit/debug dans toutes les surfaces ;
- une robustesse terrain prolongée au-delà des tests Python.

Les tests prouvent une baseline. Ils ne prouvent pas encore plusieurs jours d'usage réel macOS.

## Core vs Lab

### Pulse Core

Pulse Core est le chemin stable à valider en usage réel :

- runtime daemon ;
- observation locale ;
- feed et événements filtrés ;
- interprétation prudente ;
- sessions ;
- mémoire minimale ;
- dashboard diagnostic ;
- MCP approval contrôlé.

### Pulse Lab

Pulse Lab contient les surfaces expérimentales ou prématurées :

- DayDream ;
- facts / profile ;
- `MemoryStore` comme mémoire durable produit ;
- vector store ;
- embeddings ;
- résumés LLM ;
- lightweight LLM queue en produit Core ;
- context probes ;
- work intent ;
- resume cards intelligentes ;
- smart proposals ;
- context injection Lab/dev auto-`executed` ;
- commit episode linking ;
- dashboard avancé ;
- apprentissage utilisateur / projet ;
- adaptation ;
- corrections autonomes.

Ces éléments peuvent rester dans le dépôt et être testés comme Lab, mais ils ne font pas partie du chemin Core par défaut.

## Documentation de référence

Documents autoritaires actuels :

- [Synthèse Core Reset R1-R6](./docs/CORE_RESET_VALIDATION_SUMMARY.md)
- [Roadmap Core Reset](./docs/ROADMAP_CORE_RESET.md)
- [Contrat observation](./docs/OBSERVATION_CONTRACT.md)
- [Contrat interprétation](./docs/INTERPRETATION_CONTRACT.md)
- [Contrat sessions](./docs/SESSION_CONTRACT.md)
- [Contrat mémoire minimale](./docs/MINIMAL_MEMORY_CONTRACT.md)
- [Contrat propositions contrôlées](./docs/PROPOSAL_CONTRACT.md)

Les anciennes roadmaps, notes d'architecture, documents mémoire, agent, DayDream, facts, propositions et dashboard sont secondaires si elles contredisent ces documents.

## Lancer le daemon

```bash
cd Pulse
python3 -m venv .venv
source .venv/bin/activate
pip install -r daemon/requirements.txt
python daemon/main.py
```

Le daemon écoute sur `http://127.0.0.1:8765`.

Pour valider le chemin Core explicitement :

```bash
PULSE_MODE=core python daemon/main.py
```

## Routes Core utiles

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/ping` | Health check simple |
| GET | `/health/core` | Santé Core sobre |
| GET | `/state` | État runtime courant |
| GET | `/debug/state` | État runtime enrichi/debug |
| GET | `/feed` | Feed lisible d'événements |
| POST | `/event` | Ingestion d'événements locaux |
| GET | `/scoring/status` | Statut scoring |
| POST | `/daemon/pause` | Pause runtime |
| POST | `/daemon/resume` | Reprise runtime |
| GET | `/mcp/pending` | Proposition MCP risquée en attente |
| POST | `/mcp/decision` | Décision humaine allow/deny |

Les routes facts, memory write/remove, LLM, context probes, resume cards et surfaces avancées restent Lab/debug sauf indication contraire dans les contrats Core.

## Développement / tests

Entrée standard pour la suite Python :

```bash
cd Pulse
./scripts/test_all.sh
```

Cette commande utilise le venv local du projet et Python 3.11+.

Tests à garder comme référence immédiate :

- tests runtime Core ;
- tests observation golden ;
- tests `SignalScorer` golden ;
- tests sessions ;
- tests mémoire minimale ;
- tests MCP approval ;
- tests Core/Lab guards.

## App Swift

Ouvre `App/Pulse.xcodeproj` dans Xcode et lance la target macOS.

L'app macOS sert à :

- observer le système local ;
- envoyer les événements utiles au daemon ;
- afficher le contexte courant ;
- exposer les contrôles runtime ;
- servir de surface diagnostic.

Les surfaces UI avancées doivent rester Lab si elles affichent DayDream, facts/profile, LLM summaries, smart proposals, context probes ou adaptation comme capacités produit.

## Stack

- Swift / SwiftUI pour l'app macOS ;
- Python 3.11+ pour le daemon ;
- SQLite pour la persistance locale minimale ;
- Ollama ou autre provider local uniquement pour les chemins Lab/LLM, pas pour le fonctionnement Core.

## Prochaine étape

Valider Pulse Core en usage réel :

1. lancer Pulse en `PULSE_MODE=core` ;
2. observer les logs daemon ;
3. vérifier `/health/core`, `/state`, `/debug/state` et `/feed` pendant une vraie session ;
4. comparer ce que Pulse affiche avec ce qui s'est réellement passé ;
5. vérifier que le dashboard reste diagnostic ;
6. relancer `./scripts/test_all.sh` après observation.

Ne pas démarrer R7 tant que le Core n'a pas été validé sur usage terrain.
