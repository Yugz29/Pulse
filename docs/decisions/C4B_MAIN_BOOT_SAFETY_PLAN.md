# C4b — main.py Boot Safety Plan

## Statut

Cette décision est documentation-only.

Aucun code n'est autorisé dans ce patch.

C4b n'est pas un refactor massif. C4b ne change pas le comportement produit, ne change pas les routes, ne change pas les payloads et ne change pas Swift.

## Pourquoi C4b existe

`daemon/main.py` reste à la fois composition root, entrypoint exécutable, route hub et glue legacy.

Le runtime peut être créé trop tôt au module import. Le boot doit être plus sûr avant d'ajouter d'autres surfaces produit ou de lancer une phase de cleanup plus profonde.

C4a a clarifié les routes et leurs frontières. C4b peut donc se concentrer sur le boot, la composition runtime et la frontière entre import et exécution.

## Problème ciblé

Les points ciblés par C4b sont :

- imports qui peuvent créer des effets de bord ;
- création runtime au chargement du module ;
- difficulté à distinguer factory importable et lancement exécutable ;
- risque de créer DB, logs ou runtime avant de détecter un conflit de port ;
- risque pour les tests, le dogfooding et le redémarrage daemon.

Le comportement actuel reste accepté tant qu'il est documenté et testé. C4b doit réduire cette dette progressivement, pas réécrire le daemon.

## Décision

C4b est autorisé comme phase limitée à :

- audit du boot réel ;
- tests de non-régression boot ;
- préparation progressive d'une factory importable plus sûre ;
- séparation plus claire entre `create_runtime()`, `create_app()` et lancement exécutable ;
- réduction ciblée des effets de bord si elle est testée.

## Ce que C4b autorise

C4b autorise :

- ajouter des tests autour de l'import de `daemon.main` ;
- ajouter ou renforcer des tests autour de `create_app()` et `create_runtime()` si pertinents ;
- extraire un `main()` exécutable si c'est minimal et compatible ;
- retarder une création runtime si cela ne casse ni les tests ni le lancement ;
- ajouter des commentaires si cela clarifie la composition root ;
- améliorer les garde-fous de port ou daemon actif si le changement est strictement localisé.

## Ce que C4b interdit

C4b interdit :

- refactor massif de `main.py` ;
- changement de port ;
- changement de protocole ;
- changement des routes ;
- changement de payload ;
- changement Swift launch ;
- déplacement massif de routes ;
- extraction de `RuntimeOrchestrator` ;
- suppression Lab ;
- changement `MemoryStore`, facts, DayDream, LLM ou vector store ;
- changement `SessionFSM`, `SignalScorer` ou `RuntimeState` ;
- changement `memory_candidates` ;
- nouvelle UI ;
- nouveau générateur.

## Découpage proposé

### C4b.1 — Boot/import audit tests

Objectif : vérifier ce que l'import de `daemon.main` fait réellement.

Autorisé :

- tests ou documentation du comportement réel ;
- vérifier si importer `daemon.main` crée runtime, DB, stores ou side effects ;
- ne pas corriger immédiatement si le comportement est risqué.

Validation :

- tests ciblés passent ;
- comportement réel documenté.

### C4b.2 — Entrypoint guard minimal

Objectif : préparer une frontière claire entre import et exécution.

Autorisé :

- s'assurer que le lancement exécutable passe par `if __name__ == "__main__"` ou fonction équivalente ;
- éviter de lancer le serveur à l'import ;
- préserver la commande actuelle de lancement.

Validation :

- daemon démarre comme avant ;
- tests existants passent.

### C4b.3 — Runtime creation timing

Objectif : réduire la création trop précoce du runtime si possible.

Autorisé :

- déplacer ou différer une création runtime uniquement si tests et lancement restent stables ;
- garder compatibilité `create_app(runtime)` si utilisée par tests ;
- ne pas casser l'app complète.

Validation :

- route inventory reste stable ;
- `/health/core`, `/state`, `/feed`, `/memory/candidates` restent OK ;
- tests boot / routes passent.

### C4b.4 — Port/conflict safety

Objectif : éviter création lourde inutile si le daemon ne peut pas binder ou si un daemon actif existe déjà.

Autorisé :

- audit d'abord ;
- patch minimal seulement si sûr.

Validation :

- dogfooding redémarrage daemon ;
- pas de sessions parasites nouvelles ;
- logs propres.

## Tests attendus pour C4b

Les patchs C4b doivent prévoir selon leur périmètre :

- tests import / boot ;
- tests `create_app()` / `create_runtime()` si pertinents ;
- tests route inventory ;
- tests `/health/core` ;
- tests `/state` ;
- tests memory candidates non-contamination ;
- dogfooding terrain après tout patch boot.

## Documentation attendue

Tout changement de boot doit être documenté.

Tout dogfooding post-redémarrage doit être ajouté à `docs/audits/CORE_DOGFOODING_NOTES.md`.

Si une dette est exposée mais non corrigée, elle doit être documentée comme dette acceptée.

## Décision finale

C4b autorise uniquement le cleanup minimal du boot `main.py`.

La première étape recommandée est C4b.1 — Boot/import audit tests.

Aucune modification de comportement, route, UI, mémoire ou génération n'est autorisée par cette décision.
