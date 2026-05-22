# Contrat propositions controlees Pulse

État courant au moment de R6e Core Reset. Ce document décrit le comportement existant. Ce n'est pas une architecture cible et il n'introduit aucun nouveau comportement.

## Perimetre

R6 commence apres les baselines runtime, observation, interpretation, sessions et memoire minimale :

```text
Decision / MCP request -> ProposalCandidate -> ProposalStore -> pending -> decision -> response / history
```

R6 doit prouver qu'aucune proposition produit n'est executee sans validation humaine explicite. R6 ne couvre pas l'autonomie agentique, les context probes automatiques, work intent intelligent, correction autonome, generation LLM de propositions, apprentissage ou adaptation.

## Surfaces principales

| Surface | Role actuel | Core R6 strict |
|---|---|---|
| `Proposal` | Objet transport historique pour une proposition | oui |
| `ProposalStore` | File en memoire, resolution bloquante et historique leger | oui |
| `proposal_candidate_to_proposal()` | Adaptateur `ProposalCandidate` -> `Proposal` | oui |
| `daemon.mcp.handlers` | Flux MCP risky command approval | oui |
| `/mcp/pending` | Lecture de la commande MCP en attente | oui |
| `/mcp/decision` | Reception allow / deny | oui |
| `/mcp/proposals` | Historique recent des propositions | oui |
| `DecisionEngine` | Peut emettre `inject_context` depuis signaux locaux | non comme preuve R6 controlee |
| `RuntimeOrchestrator._attach_context_proposal_if_needed()` | Cree une proposition `context_injection`; Core la laisse `pending`, Lab/dev conserve l'auto-`executed` historique | mixte, hors preuve Core controlee |
| Context probes | Cycle request / approve / execute pour collecte de contexte | Lab / debug pendant R6 |
| Work intent candidates | Intentions issues notamment de probes | Lab / hors R6 strict |
| Resume cards | Resume deterministe ou enrichi pour reprise | Lab / hors R6 strict |

## `Proposal`

`Proposal` est defini dans `daemon/core/proposals.py`.

Champs actuels importants :

- `id`
- `type`
- `trigger`
- `title`
- `summary`
- `rationale`
- `evidence`
- `confidence`
- `proposed_action`
- `status`
- `created_at`
- `updated_at`
- `decided_at`
- `lifecycle`
- `metadata`

Contraintes actuelles :

- une proposition nouvelle doit demarrer avec `status == "pending"` ;
- `type`, `trigger` et `proposed_action` doivent etre en snake_case ;
- `confidence` doit etre entre `0.0` et `1.0` ;
- `metadata` n'accepte aujourd'hui que les namespaces `transport` et `details` ;
- `lifecycle` contient au minimum `created` puis `pending`.

Limite importante : `Proposal` ne contient pas aujourd'hui de champ `decided_by`, `decision_source`, `human_approved` ou equivalent. Une proposition resolue ne permet donc pas, seule, de prouver qui a decide.

## Statuts

Statuts valides actuels :

- `pending`
- `accepted`
- `refused`
- `expired`
- `executed`

Statuts terminaux actuels :

- `accepted`
- `refused`
- `expired`
- `executed`

`ProposalStore.resolve()` accepte tout statut terminal, donc `pending -> executed` est possible techniquement. Ce comportement existe aujourd'hui et doit etre traite comme dangereux pour R6 Core tant qu'il n'est pas separe ou restreint.

## `ProposalStore`

`ProposalStore` est une file en memoire avec historique leger.

Comportement actuel :

- `add()` n'accepte que les propositions `pending` ;
- `get_pending()` retourne la premiere proposition `pending`, avec filtre optionnel par type ;
- `list_pending()` liste les propositions en attente ;
- `resolve()` applique un statut terminal si la proposition existe encore en `pending` ;
- `wait_for_resolution()` bloque jusqu'a resolution ou expiration ;
- `list_history()` retourne les propositions recentes, pending incluses ;
- `clear()` vide le store, surtout pour les tests.

Le store ne modele pas l'execution reelle d'une action. Il ne sait pas si une commande shell a effectivement tourne, ni si une injection de contexte a ete appliquee par une interface. Il stocke seulement un statut.

## Flux MCP risky command approval

Le flux MCP principal vit dans `daemon/mcp/handlers.py`.

Flux actuel :

```text
intercept_command(command, tool_use_id)
-> interpreter.interpret(command)
-> optional LLM translation si `needs_llm`
-> _build_risky_command_candidate()
-> proposal_candidate_to_proposal()
-> proposal_store.add(pending)
-> wait_for_resolution(timeout=60)
-> status accepted/refused/expired
-> response decision allow/deny, allowed true/false
```

Dans ce flux, une commande est autorisee seulement si le statut resolu est `accepted`. MCP ne s'appuie pas sur le statut `executed` pour autoriser une commande.

Mapping actuel :

- decision `allow` -> status `accepted`
- decision `deny` -> status `refused`
- timeout -> status `expired`, decision `deny`, `allowed: false`
- status inconnu ou `executed` -> decision `deny` dans `_decision_from_proposal_status()`

Conclusion R6a : MCP est proche d'un flux controle, mais il doit encore etre teste comme surface Core avec une preuve explicite qu'aucun `allowed: true` ne sort sans `accepted`.

## Routes MCP

### `/mcp/pending`

Retourne la premiere proposition `risky_command` en attente via `get_pending_command()`.

Comportement actuel :

- retourne `204` si rien n'est pending ;
- retourne le payload de proposition si une commande MCP est en attente ;
- ignore les propositions non `risky_command`.

### `/mcp/decision`

Recoit `tool_use_id` et `decision`.

Comportement actuel :

- appelle `receive_decision(tool_use_id, decision)` ;
- publie toujours un evenement `mcp_decision` sur le bus avec `tool_use_id` et `decision` ;
- retourne `{"ok": true}` si une proposition pending a ete resolue ;
- retourne `{"ok": false}` si l'id est inconnu, deja terminal ou si la decision est invalide.

Limite importante : l'evenement `mcp_decision` peut donc etre publie meme quand `receive_decision()` retourne `False`. Cet evenement ne doit pas etre lu comme preuve d'approbation humaine.

### `/mcp/proposals`

Retourne l'historique recent depuis `get_proposal_history(limit)`.

Comportement actuel :

- inclut les propositions pending et terminales ;
- expose le `lifecycle` issu de `Proposal.to_dict()` ;
- conserve les champs legacy attendus par l'UI Swift MCP.

## `accepted` vs `executed`

La distinction est critique.

Dans MCP :

- `accepted` signifie que l'utilisateur a autorise la commande ;
- le daemon retourne `allowed: true` ;
- l'execution effective appartient au client appelant, pas au `ProposalStore`.

Dans `ProposalStore` :

- `executed` est seulement un statut terminal ;
- le store n'impose pas que `executed` arrive apres `accepted` ;
- aucune trace `accepted -> executed` n'est modelisee.

R6 ne doit pas traiter `executed` comme une validation humaine. En l'etat actuel, `executed` est trop ambigu pour etre une preuve Core.

## Context injection

`RuntimeOrchestrator._attach_context_proposal_if_needed()` etait la contradiction centrale de R6a. Depuis R6d, le comportement est separe par mode.

Flux Core actuel :

```text
DecisionEngine -> Decision(action="inject_context", reason="context_ready")
-> _build_context_injection_candidate()
-> proposal_candidate_to_proposal()
-> proposal_store.add(pending)
-> reste pending
```

Flux Lab/dev actuel :

```text
DecisionEngine -> Decision(action="inject_context", reason="context_ready")
-> _build_context_injection_candidate()
-> proposal_candidate_to_proposal()
-> proposal_store.add(pending)
-> proposal_store.resolve(proposal.id, "executed")
```

En Core, cette proposition ne doit pas etre lue comme une action executee ni comme une validation humaine. En Lab/dev, l'auto-`executed` est conserve comme comportement historique experimental. Il reste hors Core R6 strict et ne doit pas etre presente comme proposition produit controlee.

## Context probes

Les context probes vivent surtout dans `daemon/routes/runtime_probe_routes.py` et les modules `daemon/core/context_probe_*`.

Flux actuel general :

```text
create request -> pending -> approve/refuse/abort -> execute si approved -> result
```

Le modele de transition des probes est plus explicite que `context_injection`, mais la surface touche la collecte de contexte, le runtime context, et peut creer des work intent candidates. Pendant R6 Core strict, les probes restent Lab / debug. Elles ne doivent pas etre utilisees pour prouver le controle produit des propositions.

Les probes ont leur propre lifecycle `pending -> approved/refused/expired/cancelled -> executed`. Elles ne passent pas par `ProposalStore` et ne doivent pas etre confondues avec le flux Core de propositions controlees MCP.

## Hors R6 strict

Ces surfaces restent hors Core R6 tant qu'elles ne sont pas explicitement separees et testees :

- context probes automatiques ;
- work intent intelligent ;
- context injection Lab/dev auto-`executed` ;
- resume cards ;
- propositions generees par LLM ;
- corrections autonomes ;
- actions proactives ;
- apprentissage et adaptation ;
- dashboard avance de propositions.

## Limites explicites R6

- `pending -> executed` est possible via `ProposalStore.resolve()`.
- MCP n'utilise pas `executed` pour autoriser une commande ; il retourne `allowed: true` apres `accepted`.
- `context_injection` reste `pending` en Core depuis R6d, mais l'auto-`executed` Lab/dev reste dangereux si on le confond avec une validation humaine.
- `/mcp/decision` publie un evenement meme si `receive_decision()` retourne `False`.
- `Proposal` n'a pas de champ `decided_by`, `decision_source` ou `human_approved`.
- `accepted` ne prouve pas l'execution effective ; `executed` ne prouve pas l'approbation humaine.
- Context probes, work intent, resume cards et propositions intelligentes restent Lab / debug pendant R6.

## Garde-fous R6

Ne pas utiliser R6 pour ajouter de l'autonomie. Le premier objectif est de prouver le flux MCP controle et de neutraliser les faux signaux d'execution, pas de creer de nouvelles propositions.
