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

## Garde-fous avant correction

Tout patch boot doit :

- conserver les routes existantes ;
- préserver `/health/core`, `/state`, `/feed` et `/memory/candidates` ;
- lancer les tests route inventory ;
- être dogfoodé après redémarrage ;
- mettre à jour `docs/audits/CORE_DOGFOODING_NOTES.md` si le boot change.

## Prochaine étape recommandée

C4b.2 :

- vérifier ou préparer une frontière claire entrypoint / import ;
- confirmer que serveur et workers ne démarrent pas à l'import ;
- ne pas encore déplacer la création runtime globale sauf décision C4b.3.
