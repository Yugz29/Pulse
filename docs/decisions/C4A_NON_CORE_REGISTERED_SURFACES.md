# C4a.7 — Non-Core Registered Surfaces

## Statut

Cette decision est documentation-only.

Aucun code n'est autorise dans ce patch. Aucune route n'est supprimee, aucun gating n'est ajoute, aucun payload n'est modifie et aucune modification Swift n'est autorisee.

Cette decision est une classification provisoire des surfaces non-Core encore enregistrees dans l'app complete.

## Pourquoi cette decision existe

C4a.6 a documente par tests que certaines routes non-Core restent enregistrees dans l'app complete en mode Core.

Ce comportement n'est pas automatiquement un bug immediat. Ces routes peuvent encore etre utiles au dashboard local, au dogfooding et a la compatibilite historique.

Les couper maintenant risquerait de casser des usages existants avant d'avoir identifie leurs consommateurs. Avant tout gating, suppression ou changement de payload, leur statut doit etre explicite.

## Routes concernees

Assistant / LLM legacy :

- `/ask`
- `/ask/stream`
- `/context`
- `/llm/model`
- `/llm/models`

Context probes :

- `/context-probes/*`

Work intent :

- `/work-intent/*`

## Decision provisoire

Ces routes sont :

- enregistrees en Core pour compatibilite locale et dogfooding ;
- non-Core minimal ;
- legacy / debug / Lab-tolerated ;
- interdites comme dependances de `/health/core` ;
- interdites comme dependances de `/state`, `/feed`, `memory_candidates` ou memoire canonique ;
- non autorisees comme preuve d'apprentissage ou d'adaptation.

## Ce que cette decision autorise

Cette decision autorise uniquement :

- laisser ces routes enregistrees temporairement ;
- les tester comme surfaces non-Core ;
- documenter leurs consommateurs avant migration ;
- envisager plus tard un marquage payload ou un gating progressif.

## Ce que cette decision interdit

Cette decision interdit :

- presenter ces routes comme Core stable ;
- les utiliser pour produire une memoire canonique ;
- les utiliser comme source directe de memory candidates ;
- les brancher a `RuntimeOrchestrator` Core ;
- les utiliser dans `/health/core` ;
- ajouter une UI produit autour d'elles sans decision separee ;
- les supprimer brutalement sans migration.

## Options futures

Trois options restent possibles apres inventaire des consommateurs :

1. conserver ces routes tolerees en Core ;
2. ajouter un marquage payload explicite, par exemple `surface=lab` ou `surface=debug` ;
3. ajouter un gating progressif en mode Core.

Aucune de ces options n'est appliquee par ce document.

## Tests existants

Les garde-fous actuels sont dans `tests/test_main_runtime_state.py`.

Ils documentent notamment :

- l'inventaire C4a.6 des routes assistant legacy, context probes et work intent comme surfaces non-Core ;
- l'independance de `/health/core` vis-a-vis des callbacks assistant, frozen memory, work intent, facts, DayDream, LLM et vector store.

## Prochaine etape recommandee

Avant tout gating :

- identifier les consommateurs Swift ;
- identifier les usages de dogfooding ;
- choisir une surface pilote si un gating devient necessaire ;
- documenter toute decision de gating dans une decision separee.

## Decision finale

C4a.7 classe ces routes comme surfaces non-Core enregistrees temporairement.

Aucun gating, suppression de route, changement de payload ou changement Swift n'est autorise par ce document.
