# Memory Candidates MVP Contract

## Statut

Ce document est une suite du contrat `docs/contract/MEMORY_LEARNING_CONTRACT.md`.

Ce n'est pas une implémentation. Il ne crée aucune route, aucun modèle, aucun stockage et aucun comportement runtime.

Ce MVP ne crée pas de mémoire validée automatiquement. Il ne rend pas Pulse intelligent. Il prépare seulement une future surface de mémoire candidate contrôlée, reviewable et auditable.

La règle de base reste inchangée : aucune mémoire stable sans validation humaine explicite.

## Objectif du MVP

Le MVP doit définir uniquement le cycle de vie de `memory_candidates`.

Il doit préciser :

- ce qu'est une memory candidate ;
- comment elle peut être créée ;
- comment elle est reviewée ;
- comment elle est acceptée, éditée, rejetée, expirée ou contredite ;
- comment elle reste auditable ;
- quelles preuves sont obligatoires ;
- quelles sources sont insuffisantes ou interdites.

Le MVP doit rester ultra-prudent : candidates uniquement, statut `pending` par défaut, aucune promotion automatique, aucune injection automatique, review humaine obligatoire, refus / correction / suppression dès le départ.

## Non-objectifs

Ce MVP ne vise pas :

- un profil utilisateur automatique ;
- une mémoire projet automatique ;
- des facts / profile produit ;
- un vector store ;
- des embeddings ;
- DayDream memory ;
- un résumé LLM comme vérité ;
- une injection LLM automatique ;
- des suggestions intelligentes ;
- une action autonome ;
- une promotion Lab -> Core sans validation ;
- une adaptation silencieuse du comportement de Pulse.

Ces sujets restent hors MVP.

## Modèle conceptuel minimal

Modèle conceptuel, pas une exigence de code immédiate.

Champs obligatoires :

- `id` ;
- `status` ;
- `memory_type` ;
- `claim` ;
- `confidence` ;
- `sensitivity` ;
- `created_at` ;
- `updated_at` ;
- `expires_at` ou `expiration_policy` ;
- `evidence` ;
- `human_review` ;
- `rejection_policy` ;
- `contradiction_policy`.

Statuts autorisés :

- `pending` ;
- `accepted` ;
- `edited` ;
- `rejected` ;
- `expired` ;
- `contradicted` ;
- `archived`.

Types initiaux autorisés :

- `project_pattern` ;
- `workflow_pattern` ;
- `tool_usage` ;
- `caution`.

Types interdits pour le MVP :

- `medical` ;
- `financial` ;
- `identity` ;
- `private_life` ;
- `credential` ;
- `psychological_profile` ;
- `sensitive_preference`.

Une candidate doit contenir une claim courte, falsifiable et non sensible. Une phrase vague ou psychologisante doit être refusée.

## Sources autorisées pour créer une candidate

Sources acceptables :

- plusieurs sessions cohérentes ;
- app + fichier + projet cohérents ;
- terminal + Git + fichiers cohérents ;
- commits ou tests répétés ;
- action explicite utilisateur dans l'UI ;
- signal multi-source non contradit.

Sources insuffisantes :

- `/state` seul ;
- `probable_task` seul ;
- `active_project` seul ;
- une seule commande terminal ;
- `user_presence` ;
- window title seul ;
- clipboard metadata ;
- une seule session courte.

Sources interdites :

- commandes `curl` diagnostic ;
- `/debug/state` brut ;
- `/insights` brut ;
- résumé LLM seul ;
- DayDream ;
- facts Lab ;
- context probes non validés ;
- work intent expérimental ;
- session `stale_repair` seule.

Une source interdite peut aider à diagnostiquer un problème. Elle ne doit pas créer une candidate.

## Règles de création

Règles strictes :

- aucune candidate depuis une seule observation ;
- aucune candidate depuis une seule source faible ;
- aucune candidate depuis diagnostics Pulse ;
- aucune candidate si données sensibles détectées ;
- une candidate doit avoir au moins deux familles de preuves ou plusieurs sessions ;
- une candidate doit être falsifiable ;
- une candidate doit être courte ;
- une candidate doit indiquer pourquoi elle existe ;
- une candidate doit rester `pending`.

Exemple acceptable en principe :

```text
Claim: "Pulse semble être un projet de travail récurrent."
Preuves: plusieurs sessions, fichiers dans le repo, commandes pytest/git, commits cohérents.
Statut: pending.
```

Exemple refusé :

```text
Claim: "L'utilisateur préfère travailler le soir."
Preuves: une session tardive.
Statut: refusé, preuve insuffisante et préférence utilisateur non validée.
```

## Règles de review humaine

Actions disponibles :

- `accept` ;
- `edit` ;
- `reject` ;
- `archive` ;
- `delete` ;
- `mark_contradicted`.

Règles :

- `accept` crée seulement une mémoire validée si cette étape est explicitement prévue plus tard ;
- dans ce MVP, `accept` peut rester conceptuel ou produire un état `accepted`, mais sans injection automatique ;
- `edit` devient la source la plus forte ;
- `reject` empêche une reproposition immédiate ;
- `delete` supprime la candidate ;
- `mark_contradicted` bloque l'usage comme contexte stable ;
- aucune action automatique ne vaut validation humaine.

Une candidate non reviewée n'est pas une mémoire. C'est une hypothèse en attente.

## Expiration / decay

Règles d'expiration :

- les candidates `pending` expirent ;
- les candidates non reviewées perdent en priorité ;
- les candidates rejetées ne reviennent pas sans preuve nouvelle forte ;
- les candidates issues de patterns projet expirent si le projet n'est plus actif ;
- les données anciennes ne doivent pas rester actives par défaut ;
- une candidate contredite ne doit pas redevenir active sans review humaine.

Le decay doit réduire l'insistance de Pulse, pas masquer l'historique local nécessaire à l'audit.

## Sensibilité / sécurité

La classification `sensitivity` est obligatoire.

Règles :

- si doute, ne pas créer ;
- ne jamais créer de candidate avec secrets, tokens ou credentials ;
- ne jamais créer de candidate depuis contenu clipboard brut ;
- ne jamais créer de candidate sensible sans validation explicite ;
- ne jamais inférer santé, finances, identité, psychologie, relations ou vie privée depuis observation passive ;
- ne jamais stocker une claim qui expose inutilement des chemins privés, commandes sensibles ou contenus personnels.

Le MVP doit préférer un faux négatif à une mémoire intrusive.

## Surface API conceptuelle

Endpoints possibles plus tard, à titre conceptuel :

- `GET /memory/candidates`
- `GET /memory/candidates/<id>`
- `POST /memory/candidates/<id>/accept`
- `POST /memory/candidates/<id>/edit`
- `POST /memory/candidates/<id>/reject`
- `POST /memory/candidates/<id>/archive`
- `DELETE /memory/candidates/<id>`

Ces endpoints ne doivent pas être créés maintenant.

S'ils sont créés plus tard, ils devront :

- être Core-safe ;
- être testés avant exposition UI ;
- ne pas appeler LLM ;
- ne pas appeler DayDream ;
- ne pas appeler vector store ;
- ne pas appeler embeddings ;
- ne pas appeler facts Lab ;
- ne pas promouvoir automatiquement vers mémoire validée.

## Surface UI conceptuelle

Surface possible plus tard : une vue Review explicite.

Elle devra afficher :

- claim ;
- preuves ;
- sources ;
- confiance ;
- sensibilité ;
- statut ;
- date de création ;
- date d'expiration ;
- raison de proposition.

Actions UI minimales :

- accept ;
- edit ;
- reject ;
- archive ;
- delete.

Contraintes UI :

- pas d'acceptation implicite ;
- pas de mémoire cachée ;
- montrer pourquoi Pulse propose la candidate ;
- permettre à l'utilisateur de corriger la phrase avant acceptation ;
- rendre le rejet aussi simple que l'acceptation ;
- ne pas présenter une candidate comme vérité.

## Tests obligatoires avant implémentation

Tests futurs à écrire avant tout patch produit :

- pas de candidate depuis `/state` seul ;
- pas de candidate depuis `curl` ;
- pas de candidate depuis `/debug/state` ou `/insights` ;
- pas de candidate depuis LLM summary seul ;
- pas de candidate depuis `user_presence` seul ;
- pas de candidate depuis `stale_repair` seul ;
- candidate exige preuves multiples ;
- candidate démarre `pending` ;
- `reject` empêche reproposition immédiate ;
- `edit` conserve trace humaine ;
- `delete` supprime ;
- sensitive candidate refusée ;
- Lab ne promeut pas vers Core ;
- `accept` n'injecte rien automatiquement dans LLM.

Ces tests doivent précéder la première route ou UI de candidates.

## Risques

Risques principaux :

- apprendre des choses fausses ;
- surinterpréter les signaux ;
- confondre activité de diagnostic et travail réel ;
- faire passer Lab pour Core ;
- créer une UI anxiogène ;
- stocker des données sensibles ;
- créer un système difficile à corriger ;
- transformer une hypothèse utile en profil durable ;
- inciter l'utilisateur à accepter sans comprendre la preuve.

Le risque produit n'est pas seulement l'erreur technique. Le risque est de donner à Pulse une autorité qu'il n'a pas.

## Décision finale

Ce document n'autorise pas encore l'implémentation.

Il prépare seulement le cadre MVP pour `memory_candidates`.

Avant de coder, il faudra décider si C4 Architecture Cleanup est nécessaire pour isoler proprement Core, Lab, routes et stockage.

Le premier patch produit, s'il est autorisé plus tard, devra être test-first, local-only, pending-only et sans LLM.
