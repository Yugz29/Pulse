# Architecture Cleanup Plan

Internal phase: C4

## Statut

Ce document est documentation-only. Aucun code n'est autorisé dans ce patch.

C4 est une phase de nettoyage architectural. C4 ne lance pas R7, ne lance pas l'apprentissage, ne lance pas l'UI memory candidates et ne lance pas de générateur de candidates.

C4 ne doit pas devenir un refactor massif.

## Pourquoi C4 existe

R1-R6 ont stabilisé le Core.

C1 / C2 ont audité et durci le Core.

C3 a posé les contrats mémoire / apprentissage.

C4-mini et C4-mini.1 ont ajouté une surface isolée `memory_candidates`, sans génération.

Le code contient encore des dettes acceptées : `main.py`, route registration, `RuntimeOrchestrator`, `/insights`, `FactEngine`, periodic sync worker, `StateStore` et constantes d'événements.

Avant de faire UI, générateur ou apprentissage, il faut réduire les couplages structurels.

## Sources

Sources publiques :

- `docs/core-reset-roadmap.md`
- `docs/decisions/core-reset-foundation-closure.md`

Contexte historique : C4-mini et C4-mini.1 avaient ajouté une surface isolée `memory_candidates`, sans génération.

## Décision

C4 est autorisé comme phase de cleanup progressif.

C4 doit :

- réduire les couplages ;
- clarifier les surfaces ;
- préserver les URLs existantes ;
- préserver le comportement Core validé ;
- conserver les gates Lab ;
- garder `memory_candidates` séparé de Core live et Lab mémoire ;
- être découpé en petits patchs test-first.

C4 ne doit pas :

- modifier le sens produit de Pulse ;
- créer d'apprentissage ;
- créer de générateur ;
- ajouter d'UI ;
- supprimer brutalement des routes ;
- casser `/state.signals` ou `/insights` sans migration ;
- réécrire `RuntimeOrchestrator` en une fois.

## Découpage proposé

### C4a — Route registration / surface boundaries

Objectif : clarifier l'enregistrement des routes Core, debug, Lab, MCP et memory candidates.

Autorisé :

- documenter l'inventaire actuel ;
- extraire des helpers de registration si minimal ;
- regrouper les registrations par surface ;
- ajouter ou ajuster tests d'inventaire ;
- conserver toutes les URLs existantes.

Interdit :

- supprimer brutalement des routes Lab ;
- modifier le payload `/state` ;
- brancher memory candidates au runtime live ;
- modifier Swift.

Validation :

- tests d'inventaire routes ;
- `/health/core`, `/state`, `/feed`, `/memory/candidates` inchangés ;
- Lab reste marqué ou gaté.

### C4b — main.py boot safety minimal

Objectif : réduire les effets de bord au boot.

Autorisé :

- clarifier composition root ;
- préparer séparation entrypoint / factory ;
- éviter les imports qui créent du runtime trop tôt si possible ;
- garder compatibilité lancement existant.

Interdit :

- refactor massif ;
- changement port / protocole ;
- changement Swift launch ;
- migration complète de daemon boot.

Validation :

- daemon démarre comme avant ;
- conflit port / daemon actif restent sûrs ;
- tests existants passent.

### C4c — Core/Lab service lifecycle cleanup

Objectif : rendre `FactEngine`, periodic sync worker et services Lab plus lazy / no-op en Core.

Autorisé :

- rendre certaines instanciations lazy si sûr ;
- vérifier que le periodic sync worker ne produit rien en Core ;
- documenter les no-op.

Interdit :

- supprimer brutalement Lab ;
- modifier facts / profile produit ;
- activer mémoire avancée ;
- brancher LLM.

Validation :

- Core démarre sans Lab requis ;
- `FactEngine` / `MemoryStore` ne participent pas au flux Core ;
- tests de non-contamination.

### C4d — StateStore legacy clarification

Objectif : clarifier le rôle legacy de `StateStore`.

Autorisé :

- documentation ;
- tests de non-vérité produit ;
- réduction d'usage si ciblée.

Interdit :

- migration massive ;
- changement payload `/state` incompatible ;
- suppression sans migration Swift.

Validation :

- `PresentState` reste source live ;
- `StateStore` n'est pas utilisé comme vérité produit.

### C4e — /insights replacement plan

Objectif : préparer le remplacement progressif de `/insights` côté UI par des surfaces bornées.

Autorisé :

- documenter usages actuels ;
- identifier consommateurs Swift ;
- créer plan de migration.

Interdit :

- supprimer `/insights` maintenant ;
- casser dashboard ;
- créer une nouvelle surface produit trompeuse.

Validation :

- aucun changement runtime obligatoire ;
- plan clair avant patch.

### C4f — Event type constants cleanup

Objectif : centraliser progressivement les constantes de types d'événements.

Autorisé :

- inventaire ;
- module constants si minimal ;
- tests de compatibilité.

Interdit :

- renommage massif ;
- migration de tous les events en une fois.

Validation :

- events existants compatibles ;
- tests ingestion / feed / session passent.

## Ordre recommandé

Ordre recommandé :

1. C4a — Route registration / surface boundaries
2. C4b — main.py boot safety minimal
3. C4c — Core/Lab service lifecycle cleanup
4. C4d — StateStore legacy clarification
5. C4e — /insights replacement plan
6. C4f — Event type constants cleanup

C4a vient d'abord car elle réduit le risque d'ajouter de nouvelles surfaces au mauvais endroit.

## Ce qui reste explicitement reporté

Sujets reportés :

- UI memory candidates ;
- générateur offline dry-run ;
- apprentissage utilisateur ;
- mémoire stable ;
- profil utilisateur / projet ;
- adaptation ;
- propositions intelligentes ;
- refactor massif `RuntimeOrchestrator` ;
- suppression Lab.

## Tests attendus pour chaque patch C4

Chaque patch C4 doit prévoir selon son périmètre :

- tests ciblés ;
- tests route inventory ;
- tests `/state` payload boundaries ;
- tests Core health ;
- tests memory candidates non-contamination si surface concernée ;
- dogfooding terrain si le patch touche boot / routes / UI.

## Documentation attendue

Chaque sous-phase C4 doit documenter sa décision si elle change une frontière.

Tout dogfooding terrain doit être conservé dans les notes locales privées.

Toute évolution memory candidates doit être documentée avant implémentation.

## Décision finale

C4 Architecture Cleanup est autorisé uniquement comme cleanup progressif.

La première sous-phase recommandée est C4a route registration / surface boundaries.

Aucune UI, aucun générateur, aucun apprentissage n'est autorisé par ce document.
