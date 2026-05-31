# C4a — Non-Core Route Consumers Inventory

## Statut

Cet inventaire est un audit documentaire.

Aucun code n'est modifié, aucun gating n'est décidé, aucune route n'est supprimée et aucun comportement n'est modifié.

## Pourquoi cet inventaire existe

C4a.7 a classé plusieurs routes comme non-Core minimal mais encore enregistrées temporairement en Core pour compatibilité locale et dogfooding.

Avant tout gating, marquage payload ou suppression, il faut savoir qui consomme ces routes, surtout côté Swift dashboard et dogfooding.

## Routes inspectées

Routes recherchées :

- `/ask`
- `/ask/stream`
- `/context`
- `/llm/model`
- `/llm/models`
- `/context-probes`
- `/context-probes/schema`
- `/context-probes/request-preview`
- `/context-probes/requests`
- `/work-intent`
- `/work-intent/candidates`
- `/insights`
- `/llm/lightweight`
- `/scoring/status`

Recherche effectuée dans :

- `App/`
- `AppTests/`
- `daemon/`
- `tests/`

## Résumé

| Route/famille | Consommateur Swift | Tests | Statut | Risque gating |
|---|---|---|---|---|
| `/ask` | Helper Swift présent, usage UI non trouvé | Oui | Legacy assistant, non-Core | Moyen |
| `/ask/stream` | Oui | Oui | Chat Swift legacy, non-Core | Fort |
| `/context` | Oui | Indirect | Snapshot contextuel legacy, non-Core | Fort |
| `/llm/model` | Oui | Oui | Réglage modèle LLM, non-Core | Fort |
| `/llm/models` | Oui | Oui | Inventaire modèle LLM, non-Core | Fort |
| `/context-probes/schema` | Non trouvé | Oui | Debug/schema probes | Faible |
| `/context-probes/request-preview` | Non trouvé | Oui | Preview debug/test | Faible |
| `/context-probes/requests*` | Oui | Oui | Dashboard / Notch context probes, Lab | Fort |
| `/work-intent/candidates*` | Oui | Oui | Dashboard work intent, Lab | Fort |
| `/insights` | Oui | Oui | Events raw-ish / dashboard | Fort |
| `/llm/lightweight/*` | Oui | Oui | Worker local + dashboard LLM Lab | Fort |
| `/scoring/status` | Oui | Oui | Dashboard diagnostic scoring | Moyen |

## Détails par surface

### Assistant / LLM legacy

`/ask`

- Consommateur Swift : `App/App/DaemonBridge+LLM.swift` expose `ask(_:)`.
- Usage UI Swift trouvé : aucun appel direct trouvé dans `App/App`.
- Tests : `tests/test_main_llm_models.py` couvre au moins le cas payload vide.
- Risque gating : moyen. Le helper existe, donc une suppression pourrait casser un usage futur ou externe, mais l'UI courante semble utiliser le stream.
- Alternative possible : conserver temporairement ou marquer comme legacy avant tout gating.

`/ask/stream`

- Consommateur Swift : `App/App/DaemonBridge+LLM.swift` expose `askStream`.
- Usage Swift : `App/App/PulseViewModel+Interactions.swift` utilise `bridge.askStream(...)` pour le chat.
- Tests Swift : `AppTests/DaemonBridgeLLMTests.swift`.
- Risque gating : fort. Un gating direct casserait le chat Swift.
- Alternative possible : déplacer le chat vers une surface explicitement Lab ou afficher un état indisponible avant gating.

`/context`

- Consommateur Swift : `App/App/DaemonBridge+LLM.swift` expose `getContext`.
- Usage Swift : `App/App/AppApp.swift` copie le contexte via raccourci.
- Risque gating : fort pour le dogfooding local si le raccourci est utilisé.
- Alternative possible : marquer le payload comme debug / legacy avant gating.

`/llm/models`

- Consommateur Swift : `App/App/DaemonBridge+LLM.swift`.
- Usages Swift : `App/App/PulseViewModel+Runtime.swift` et `App/App/DashboardViewModel.swift` rafraîchissent l'inventaire LLM.
- Tests Swift : `AppTests/PulseViewModelInteractionsTests.swift`.
- Risque gating : fort. La disponibilité LLM et le dashboard dépendent de cette route.
- Alternative possible : conserver une version read-only marquée Lab/debug.

`/llm/model`

- Consommateur Swift : `App/App/DaemonBridge+LLM.swift`.
- Usage Swift : `App/App/PulseViewModel+Interactions.swift` via `updateSelectedModel`.
- Tests Swift : `AppTests/PulseViewModelInteractionsTests.swift`.
- Risque gating : fort. Le changement de modèle depuis Swift dépend de cette route.
- Alternative possible : séparer inventaire read-only et mutation Lab avant gating.

### Context probes

`/context-probes/schema`

- Consommateur Swift : non trouvé.
- Tests : `tests/test_runtime_routes.py`.
- Statut : schema debug / consent, non-Core.
- Risque gating : faible si aucun consommateur externe n'existe.

`/context-probes/request-preview`

- Consommateur Swift : non trouvé.
- Tests : `tests/test_runtime_routes.py`.
- Statut : preview debug/test, non-Core.
- Risque gating : faible.

`/context-probes/requests*`

- Consommateur Swift : oui, `App/App/DaemonBridge+CoreAPI.swift`.
- Usages Swift :
  - `App/App/PulseViewModel.swift` gère les demandes pending dans le Notch ;
  - `App/App/AppApp.swift` soumet le texte focalisé via raccourci ;
  - `App/App/DashboardViewModel.swift` liste, approuve, refuse, exécute et lit les résultats ;
  - `App/App/DashboardRootView.swift` expose la section `Contexte (Lab)`.
- Tests Swift : `AppTests/PulseViewModelInteractionsTests.swift` et `AppTests/AccessibilityContextProbeServiceTests.swift`.
- Risque gating : fort. Ces routes alimentent une surface Lab visible et des raccourcis de dogfooding.
- Alternative possible : conserver temporairement, puis ajouter un marquage payload `surface=lab` avant gating.

### Work intent

`/work-intent/candidates*`

- Consommateur Swift : oui, `App/App/DaemonBridge+CoreAPI.swift`.
- Usages Swift :
  - `App/App/DashboardViewModel.swift` rafraîchit les candidates ;
  - `App/App/DashboardRootView.swift` affiche et permet accepter/refuser les intentions proposées.
- Tests Swift : `AppTests/PulseViewModelInteractionsTests.swift`.
- Risque gating : fort pour le dashboard Lab.
- Alternative possible : marquer explicitement comme Lab et éviter toute présentation comme Core stable.

### Autres surfaces proches

`/insights`

- Consommateur Swift : oui, `App/App/DaemonBridge+CoreAPI.swift`.
- Usages Swift :
  - `App/App/PulseViewModel+Runtime.swift` alimente les événements récents ;
  - `App/App/DashboardViewModel.swift` alimente le dashboard.
- Tests : `tests/test_main_runtime_state.py`, `tests/test_runtime_routes.py`, `tests/test_memory_candidate_routes.py` et `AppTests/PulseViewModelInteractionsTests.swift`.
- Risque gating : fort. La route est raw-ish/debug, mais elle a des consommateurs Swift actifs.
- Alternative possible : préparer une surface remplaçante bornée avant suppression ou gating.

`/llm/lightweight/*`

- Consommateur Swift : oui.
- Usages Swift :
  - `App/App/AppleFoundationWorker.swift` poll `/llm/lightweight/pending` et poste `/llm/lightweight/result` ;
  - `App/App/DashboardViewModel.swift` lit le statut ;
  - `App/App/DashboardRootView.swift` affiche l'état LLM lightweight.
- Tests : `tests/test_lightweight_llm_routes.py`, `tests/test_main_runtime_state.py`, `tests/test_runtime_routes.py`.
- Risque gating : fort. Le worker local et le dashboard dépendent de ces routes.
- Alternative possible : garder le polling read-only/no-op en Core ou migrer explicitement vers mode Lab.

`/scoring/status`

- Consommateur Swift : oui, `App/App/DaemonBridge+CoreAPI.swift`.
- Usage Swift : `App/App/DashboardViewModel.swift` et `App/App/DashboardRootView.swift` affichent le statut scoring.
- Tests : `tests/test_main_mcp_routes.py`, `tests/test_main_runtime_state.py`.
- Risque gating : moyen. C'est une surface diagnostic utile au dashboard ; elle est moins critique que `/state` mais visible.
- Alternative possible : conserver comme debug read-only ou inclure dans une future surface de health/debug bornée.

## Décision

Cet audit ne décide aucun gating.

Conclusions :

- routes à risque fort si gatées maintenant : `/ask/stream`, `/context`, `/llm/model`, `/llm/models`, `/context-probes/requests*`, `/work-intent/candidates*`, `/insights`, `/llm/lightweight/*` ;
- routes à risque moyen : `/ask`, `/scoring/status` ;
- routes à risque faible d'après la recherche actuelle : `/context-probes/schema`, `/context-probes/request-preview`.

Les routes non trouvées côté Swift peuvent devenir candidates à un gating futur, mais aucune suppression ou neutralisation n'est décidée ici.

## Prochaine étape recommandée

Avant tout gating :

- si Swift consomme fortement la route, préparer une migration ou un marquage payload avant gating ;
- si la route est tests-only ou non trouvée, proposer une décision de gating progressive séparée ;
- commencer par une surface pilote faible risque, comme `/context-probes/request-preview`, uniquement après décision ;
- documenter toute décision future avant code.
