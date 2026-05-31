# C4b — Boot Import Audit

## Statut

Cet audit est documentaire.

Aucun code n'est modifié, aucun comportement n'est corrigé et aucune route n'est modifiée.

Ce document décrit le comportement réel observé par test.

## Pourquoi cet audit existe

C4b vise à réduire les effets de bord au boot.

Avant toute correction, il faut savoir ce que `import daemon.main` fait réellement.

Le test C4b.1 documente ce comportement dans un sous-processus isolé avec `HOME` temporaire, afin de ne pas écrire dans l'environnement réel.

## Test source

Source :

- `tests/test_main_runtime_state.py`
- `test_import_main_documente_les_effets_de_bord_boot_actuels`

## Effets de bord confirmés à l'import

L'import de `daemon.main` crée déjà :

- un `RuntimeBundle` global ;
- une app Flask globale ;
- des routes enregistrées ;
- `.pulse/logs` ;
- des DB / fichiers sous `.pulse` ;
- `memory/candidates.sqlite`.

Les routes observées incluent notamment :

- `/health/core` ;
- `/state` ;
- `/feed` ;
- `/memory/candidates`.

Ce comportement est une dette C4b confirmée.

Il n'est pas corrigé dans C4b.1.

## Ce qui ne démarre pas à l'import

L'import ne démarre pas :

- le serveur Flask ;
- `RuntimeOrchestrator` ;
- le file flush worker ;
- le periodic sync worker ;
- le thread idle heartbeat.

L'import a donc des effets de bord disque et composition, mais il ne démarre pas encore les workers ou le serveur les plus dangereux.

## Lecture architecture

`daemon.main` reste composition root, app factory, route hub et glue legacy.

Le comportement actuel est toléré temporairement parce qu'il est maintenant documenté et couvert par test.

Il ne doit pas être confondu avec un boot sain définitif.

C4b doit réduire cette dette progressivement, sans refactor massif et sans modifier les routes ou payloads.

## Risques

Risques confirmés :

- tests ou imports peuvent créer des fichiers inattendus ;
- DB / stores peuvent être initialisés avant besoin réel ;
- un conflit de port peut être détecté après création runtime ;
- dogfooding et redémarrage peuvent produire des traces parasites ;
- des modifications futures peuvent aggraver les effets de bord si elles ne sont pas testées.

## Décision provisoire

La dette est acceptée temporairement.

Ne pas corriger brutalement.

La prochaine étape recommandée est C4b.2 — entrypoint guard minimal.

La correction du timing runtime doit rester pour C4b.3 ou pour une décision dédiée.

## Mise à jour C4b.2 — entrypoint explicite

`main()` existe maintenant comme entrypoint exécutable explicite.

`if __name__ == "__main__"` délègue à `main()`.

Le lancement serveur / workers reste inchangé.

L'import de `daemon.main` ne lance toujours pas `Flask.run`.

Le test d'import vérifie que `Flask.run` n'est pas appelé à l'import.

Un test dédié vérifie que `main()` délègue le lancement exécutable sans changer le boot.

La création runtime globale à l'import n'est pas corrigée par C4b.2.

Cette dette reste pour C4b.3.

## Mise à jour C4b.3-prep — accessors de compatibilité

`get_runtime()` et `get_app()` existent maintenant.

Ils ne sont pas encore lazy.

Ils retournent les globals existants :

- `get_runtime()` retourne `runtime` ;
- `get_app()` retourne `app`.

Ils ne réduisent pas encore les effets de bord d'import.

Ils créent une surface de migration progressive avant toute tentative de lazy réel.

Les tests vérifient que ces accessors retournent les mêmes objets que les globals.

Les tests vérifient que les aliases legacy restent alignés sur le `RuntimeBundle` global.

Les tests vérifient que les routes principales sont toujours présentes via `get_app().url_map`, notamment :

- `/health/core` ;
- `/state` ;
- `/feed` ;
- `/memory/candidates`.

La dette principale reste inchangée : `runtime` et `app` sont encore créés à l'import.

La prochaine étape possible est de migrer progressivement les consommateurs vers `get_runtime()` et `get_app()` avant toute tentative de lazy réel.

## Mise à jour C4b.3 — migration partielle des consommateurs

Une partie des consommateurs de test a été migrée vers les accessors explicites.

Les clients Flask de test utilisent maintenant `get_app().test_client()` sur les principales suites full-app.

Les inventaires de routes utilisent maintenant `get_app().url_map`.

Le test d'import utilise `get_runtime()` et `get_app()` pour lire le type runtime / app tout en vérifiant que ces accessors retournent encore les globals existants.

Les usages directs de `app` et `runtime` sont conservés uniquement dans les tests de compatibilité legacy :

- vérification que `get_app()` retourne `app` ;
- vérification que `get_runtime()` retourne `runtime` ;
- vérification que les aliases legacy restent alignés sur `runtime` ;
- vérification que `app` reste disponible temporairement.

Les globals restent disponibles temporairement pour compatibilité.

Le timing de création runtime / app à l'import reste inchangé.

## Garde-fous avant correction

Tout patch boot doit :

- conserver les routes existantes ;
- préserver `/health/core`, `/state`, `/feed` et `/memory/candidates` ;
- lancer les tests route inventory ;
- être dogfoodé après redémarrage ;
- mettre à jour `docs/audits/CORE_DOGFOODING_NOTES.md` si le boot change.

## Prochaine étape recommandée

C4b.3 :

- continuer la migration progressive des consommateurs vers `get_runtime()` et `get_app()` ;
- garder les globals disponibles tant que les consommateurs legacy existent ;
- ne pas rendre les accessors lazy avant que la compatibilité soit couverte par tests ;
- ne pas déplacer la création runtime globale sans patch C4b.3 dédié et dogfooding post-redémarrage.
