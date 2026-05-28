# C3 Memory / Learning Contract

## Statut

C3 est une phase de contrat, pas une phase d'implémentation.

Pulse Core observe l'activité locale, filtre du bruit, produit des signaux prudents, suit des sessions et conserve une mémoire minimale. Pulse Core ne doit pas encore apprendre automatiquement.

Le premier objectif n'est pas une mémoire intelligente. Le premier objectif est de définir les conditions minimales d'une mémoire candidate contrôlée, traçable, vérifiable et réversible.

Aucun code d'apprentissage ne doit être écrit avant validation explicite de ce contrat.

## Non-objectifs

C3 ne vise pas :

- l'apprentissage automatique ;
- un profil utilisateur automatique ;
- une mémoire projet automatique ;
- un vector store ;
- des embeddings ;
- des facts / profile produit ;
- DayDream ;
- un résumé LLM comme source de vérité ;
- une proposition intelligente autonome ;
- une action sans validation humaine ;
- une injection automatique de mémoire dans un LLM ;
- une adaptation silencieuse du comportement de Pulse.

Ces sujets restent Lab ou hors périmètre tant qu'ils n'ont pas été revalidés par contrat et par tests.

## Définitions

### Observation

Fait local observé directement.

Exemples :

- app active ;
- fichier actif ;
- fichier modifié ;
- commande terminal terminée ;
- session lock / unlock ;
- idle / présence utilisateur ;
- événement Git observé.

Une observation n'est pas une conclusion. Elle ne devient jamais mémoire directement.

### Signal

Interprétation dérivée d'observations récentes.

Exemples :

- `probable_task` ;
- `activity_level` ;
- `focus_level` ;
- `active_project` ;
- `session_status` ;
- `task_confidence`.

Un signal est temporel, fragile et contextualisé. Il ne devient jamais mémoire directement.

### Hypothèse

Conclusion provisoire formulée à partir de plusieurs signaux ou observations.

Exemple : "l'utilisateur semble travailler sur Pulse".

Une hypothèse peut être utile pour l'affichage ou la reprise, mais elle reste non validée.

### Pattern candidat

Hypothèse répétée ou corroborée sur plusieurs événements, sources ou sessions.

Exemple : "Pulse apparaît plusieurs fois comme projet actif sur plusieurs sessions avec fichiers source, terminal et Git cohérents".

Un pattern candidat peut justifier une mémoire candidate, pas une mémoire validée.

### Mémoire candidate

Hypothèse structurée, sourcée, non validée, visible pour review.

Elle doit avoir un statut `pending` par défaut, conserver ses preuves, sa confiance et sa date, et exiger une décision humaine avant toute promotion stable.

### Mémoire validée

Information acceptée explicitement par l'utilisateur.

Une mémoire validée peut être utilisée comme contexte stable, mais elle doit rester corrigeable, supprimable, contradicible et auditable.

### Mémoire rejetée

Candidate refusée par l'utilisateur.

Elle ne doit pas être reproposée immédiatement sans preuve nouvelle et nettement plus forte.

### Mémoire expirée

Candidate ou mémoire ancienne, non confirmée récemment, ou devenue trop faible pour être utilisée.

L'expiration doit réduire la confiance ou retirer la mémoire du contexte actif.

## Sources autorisées

Les sources ne se valent pas. Une source faible ne doit pas être promue seule.

### Sources fortes

- validation humaine explicite ;
- modification utilisateur d'une mémoire candidate ;
- commit / git context confirmé ;
- session répétée multi-événements ;
- combinaison cohérente app + fichier + projet + terminal ;
- action explicite de l'utilisateur dans l'UI.

### Sources moyennes

- `SessionMemory` ;
- `recent_sessions` ;
- `/feed` terminal notable ;
- fichiers modifiés significatifs ;
- app active + fichier actif cohérent ;
- commandes test / build / git cohérentes avec un projet.

### Sources faibles

- `/state.present` seul ;
- `probable_task` seul ;
- `active_project` seul ;
- commande terminal isolée ;
- `user_presence` ;
- window title seul ;
- clipboard metadata ;
- session unique courte ;
- contexte reconstruit après coup sans preuve directe.

### Sources interdites pour promotion directe

- commandes de diagnostic `curl` ;
- `/debug/state` brut ;
- `/insights` brut ;
- résumé LLM seul ;
- facts Lab non validés ;
- DayDream ;
- context probes non validés ;
- work intent expérimental ;
- données issues d'une session réparée sans preuve complémentaire ;
- payload debug ou Lab sans validation humaine.

Ces sources peuvent aider à enquêter. Elles ne doivent pas créer ou promouvoir une mémoire.

## Règles de promotion

Chaîne obligatoire :

```text
Observation -> Signal -> Hypothèse -> Pattern candidat -> Mémoire candidate -> Mémoire validée
```

Règles strictes :

- une observation ne devient jamais mémoire directement ;
- un signal ne devient jamais mémoire directement ;
- `/state` seul ne suffit jamais ;
- une commande terminal seule ne suffit jamais ;
- une session seule ne suffit normalement pas ;
- une mémoire candidate exige plusieurs preuves ou plusieurs sessions ;
- une mémoire validée exige une validation humaine explicite ;
- toute mémoire doit conserver source, preuve, timestamp, confidence et statut ;
- toute promotion doit être explicable sans LLM ;
- toute promotion doit pouvoir être refusée, corrigée ou supprimée.

Si la chaîne de preuve n'est pas claire, Pulse doit rester au niveau hypothèse ou pattern candidat.

## Conditions minimales pour créer une mémoire candidate

Une mémoire candidate peut être envisagée seulement si plusieurs critères sont satisfaits.

Critères possibles :

- même projet observé sur plusieurs sessions ;
- activité significative sur fichiers projet ;
- commandes test / build / git cohérentes avec le même projet ;
- durée de session suffisante ;
- répétition dans le temps ;
- absence de contradiction récente ;
- preuves issues d'au moins deux familles différentes, par exemple fichier + terminal, ou app + Git ;
- aucun signal sensible ou privé non validé dans la claim.

Critères bloquants :

- preuve principalement issue de `curl`, debug ou diagnostic Pulse ;
- preuve principalement issue de `/debug/state` ou `/insights` ;
- preuve issue uniquement d'une session `stale_repair` ;
- preuve issue uniquement d'un résumé LLM ;
- preuve issue uniquement d'un titre de fenêtre ;
- preuve issue uniquement de `user_presence` ;
- contradiction récente non résolue.

Règle stricte : si la preuve vient surtout de `curl`, debug ou diagnostic Pulse, ne pas créer de candidate.

## Validation humaine

Une mémoire candidate doit être visible et révisable avant toute stabilisation.

L'utilisateur doit pouvoir :

- accepter ;
- modifier ;
- refuser ;
- archiver ;
- supprimer.

Règles :

- aucune mémoire stable sans validation humaine ;
- un refus doit être mémorisé pour éviter une reproposition immédiate ;
- une modification utilisateur devient la source la plus forte ;
- une acceptation doit enregistrer qui a validé, quand, et quelle version de la claim ;
- une validation ne doit pas être déduite d'une absence de refus ;
- une action automatique ne vaut jamais validation humaine.

## Correction / oubli / contradiction

Toute mémoire validée doit rester réversible.

Exigences :

- toute mémoire validée doit être corrigeable ;
- toute mémoire validée doit être supprimable ;
- Pulse doit pouvoir marquer une mémoire comme contradite ;
- les contradictions ne doivent pas être écrasées silencieusement ;
- l'ancien contexte doit rester auditable localement si nécessaire ;
- les données anciennes doivent expirer ou perdre en confiance ;
- une mémoire contredite ne doit pas rester injectée comme contexte stable ;
- une mémoire supprimée ne doit pas être recréée immédiatement depuis les mêmes preuves.

Une contradiction doit produire un état explicite, pas un remplacement silencieux.

## Données sensibles et interdictions

Interdictions strictes :

- ne jamais mémoriser secrets, tokens, clés API ou mots de passe ;
- ne jamais mémoriser contenu clipboard brut ;
- ne jamais mémoriser données médicales, financières, administratives ou personnelles sensibles sans validation explicite ;
- ne jamais mémoriser contenu terminal brut contenant credentials ;
- ne jamais transformer un titre de fenêtre en vérité durable ;
- ne jamais apprendre depuis un LLM halluciné ;
- ne jamais apprendre une préférence utilisateur sans preuve forte ou validation ;
- ne jamais mémoriser une identité, intention ou habitude sensible depuis observation passive seule ;
- ne jamais promouvoir un contenu Lab comme mémoire Core stable sans review.

En cas de doute sur la sensibilité, Pulse doit refuser la promotion ou exiger une validation explicite.

## Core vs Lab

Core peut produire, après décision séparée et tests dédiés :

- observations ;
- signaux ;
- hypothèses prudentes ;
- patterns candidats ;
- éventuellement des memory candidates `pending`.

Core ne doit pas produire automatiquement :

- mémoire validée ;
- profil utilisateur ;
- profil projet ;
- préférence durable ;
- adaptation de comportement ;
- injection LLM stable.

Lab peut expérimenter :

- summaries ;
- facts ;
- DayDream ;
- context probes ;
- vector store ;
- embeddings ;
- resume cards intelligentes ;
- work intent.

Mais les sorties Lab ne doivent pas promouvoir automatiquement vers Core.

Tout passage Lab -> Core exige validation humaine explicite et preuve conservée.

## Format minimal d'une mémoire candidate

Schéma conceptuel. Ce n'est pas une demande d'implémentation immédiate.

```yaml
id:
status: pending | accepted | edited | rejected | expired | contradicted
memory_type: project_pattern | user_preference | workflow_pattern | tool_usage | caution
claim:
confidence:
created_at:
updated_at:
evidence:
  - source_type:
    event_ids:
    session_id:
    timestamp:
    summary:
human_review:
  required: true
  reviewed_at:
  decision:
  edited_claim:
sensitivity:
  level:
  reason:
```

Règles associées :

- `status` commence à `pending` ;
- `human_review.required` est toujours `true` pour une promotion stable ;
- `evidence` doit être lisible sans consulter un LLM ;
- `claim` doit être courte, falsifiable et non sensible ;
- `confidence` ne remplace jamais une validation humaine.

## Premier MVP autorisé plus tard

Le seul MVP acceptable après C3 serait limité à `memory_candidates`.

Contraintes du MVP :

- `memory_candidates` uniquement ;
- statut `pending` par défaut ;
- lecture seule ou validation humaine explicite ;
- aucune injection automatique dans LLM ;
- aucun apprentissage silencieux ;
- aucune promotion automatique ;
- UI ou endpoint de review explicite ;
- tests de non-promotion automatique ;
- stockage local auditable ;
- refus, correction et suppression dès le départ.

Tout MVP qui écrit une mémoire stable sans validation humaine est hors contrat.

## Ce qu'il ne faut pas coder après ce document sans décision séparée

Interdits sans décision séparée :

- vector store ;
- embeddings ;
- facts / profile automatiques ;
- DayDream memory ;
- summaries LLM automatiques ;
- profile injection ;
- smart suggestions ;
- action autonome ;
- memory sync avancée en Core ;
- apprentissage depuis `/state` ;
- apprentissage depuis `/insights` ;
- apprentissage depuis Lab.

Ce document n'autorise pas ces travaux.

## Tests à prévoir plus tard

Tests futurs à créer avant toute implémentation :

- pas de mémoire depuis `/state` seul ;
- pas de mémoire depuis diagnostic `curl` ;
- pas de mémoire depuis résumé LLM seul ;
- candidate exige preuves multiples ;
- candidate reste `pending` ;
- validation humaine requise ;
- rejet empêche reproposition immédiate ;
- suppression fonctionne ;
- correction fonctionne ;
- contradiction marque la mémoire comme `contradicted` ;
- données sensibles refusées ;
- Lab ne promeut pas vers Core ;
- session `stale_repair` seule ne crée pas de candidate ;
- `user_presence` seul ne crée pas de candidate ;
- window title seul ne crée pas de candidate.

Ces tests doivent précéder le premier patch produit de mémoire candidate.

## Décision finale

C3 ne code rien.

C3 autorise seulement une future conception de `memory_candidates`, sous statut `pending`, avec validation humaine obligatoire avant toute mémoire stable.

Pulse ne doit pas apprendre automatiquement.

La prochaine étape après ce document sera soit de définir un MVP ultra-minimal de mémoire candidate, soit de passer par C4 Architecture Cleanup si ce contrat révèle des blocages Core.
