# Provenance, vérifications et limites de cette mission

## Périmètre vérifié

- Dépôt `/Users/Yugz/Projets/Pulse`, branche `main`, HEAD initial `0eb8667` (commit complet dans `sources-manifest.json`). Le dépôt était propre au démarrage.
- **249 fichiers suivis déjà présents** ont été empreintés au début puis comparés : aucun modifié, aucun supprimé. Cela inclut code, tests, prompts, configurations versionnées, corpus observé, anciennes annotations et documentation existante.
- Le seul ajout de cette mission est `docs/audits/2026-09-09-adjudication-reprise/` : documents de conception, fiches vierges, propositions JSON et manifeste de sources. Aucun contenu stagé, aucun commit ni push.
- La recommandation produit est une proposition à éprouver, pas une modification du contrat canonique ni une décision de déploiement. La VISION existante reste intacte.

## Sources du modèle et du corpus

Les replays bruts du troisième chantier sont maintenant rangés sous
`corpus/docs/audits/2026-09-08-reprise-fondee/after/`, selon le rangement indiqué
par `.gitignore`. Les rapports antérieurs mentionnent encore leur ancien
emplacement sous docs. Les nouveaux liens pointent vers leur emplacement réel.
Les fichiers n’ont été ni déplacés ni réécrits dans cette mission.

Les **14 sorties v5** ont été vérifiées contre les copies finales conservées du
passage précédent et contre les champs de la revue publiée. Les **14 entrées**
correspondent exactement au constructeur courant avec les mêmes sessions et
contextes figés. Le prompt v5 courant est identique à celui archivé pour le
passage final. Aucun replay nouveau n’est prétendu.

Le manifeste conserve **35 empreintes SHA-256** : 14 sessions observées, 14
replays, 4 annotations historiques, le prompt courant, le prompt archivé et
la revue v5. Les replays restent locaux et exclus de Git ; les fiches reprennent
le texte nécessaire à l’adjudication sans créer une nouvelle copie des traces
entières.

## Livrables vérifiés

- **14 fiches**, chacune avec identifiant, heures locales et UTC, workspace,
  résumé factuel, sortie v5 complète, intentions, inconnues, annotation
  historique lorsqu’elle existe et questions A–E.
- **70 réponses libres A–E vierges**, 67 propositions C sans jugement ;
  `user_responses_received=0`, tous les dossiers `awaiting_user`, aucune
  collection d’éléments adjudiqués inventée.
- **14 cas de benchmark préparés** : 7 erreurs, 4 contrôles, 3 sondes d’utilité
  sans notation avant vos réponses. Références et empreintes vérifiées.
- Les références des propositions existent dans la session ou l’annexe citée.
- **Hors de ce périmètre de vérification :** les fiches 15 à 18, ajoutées le
  2026-09-09 au soir (jour 5), sur des sessions des 8 et 9 septembre. Elles
  portent la vue Core, le résumé v5 émis et un dry-run v6 non émis, sans
  rappel proposé ni annotation historique.
  Les JSON sont lisibles et les liens relatifs des nouveaux documents résolus.
- Aucune exécution de tests de production n’était nécessaire : aucun code ni
  comportement n’a changé. Les vérifications concernent les documents, leurs
  sources et l’intégrité des fichiers existants. Les anciens résultats de
  tests ne sont pas présentés comme de nouveaux tests.

## GitNexus et limites de l’analyse

La compétence d’exploration GitNexus a été utilisée. L’index initial était en
retard ; il a été actualisé. Les appels de `build_model_input` depuis
`evaluate` et `summarize_session`, puis vers `command_outcomes` et les annexes,
ont été vérifiés avec le graphe et la lecture du code courant. Aucune fonction
n’a été éditée ou renommée, donc aucune analyse d’impact de modification de
code n’était à effectuer.

L’index actualisé comporte 3 469 nœuds, 9 479 arêtes et 287 parcours. Le moteur
signale encore ses limites de découverte (65 candidats écartés, 56 points
d’entrée non explorés, 27 budgets atteints, 368 appels non suivis). Le graphe
n’est pas utilisé comme preuve exhaustive de sûreté : l’absence de changement
de production est établie directement par les empreintes et l’état Git.

## Limites de preuve produit

La mission ne mesure aucun temps de reprise, aucun gain utilisateur ni nouveau
score de modèle. Les 14 sessions sont connues et anciennes ; le souvenir de
l’utilisateur pourra être incomplet. Les quatre annotations antérieures
contiennent des règles et justifications historiques qui doivent rester
visibles mais ne doivent pas imposer les réponses futures.

Les erreurs textuelles peuvent être constatées à partir des captures. En
revanche, le nombre de rappels réellement souhaités et de faux négatifs produit
reste à adjudication. Les suggestions de la fiche ne valent pas besoins
confirmés. Les transcripts complets, bases privées, sorties terminal et états
distants n’ont pas été inspectés pour combler artificiellement ces inconnues.

Aucun modèle nouveau ou existant n’a été exécuté, aucun téléchargement ni appel
à un service distant demandé. La collecte personnelle et la configuration de
production sont inchangées.

## Complément du 2026-09-11 : réponses reçues et vérifications de la synthèse

- Les 90 réponses A–E des 18 fiches ont été données par l'utilisateur le 2026-09-10 et consignées dans les fiches et `adjudications-a-completer.json` (`user_responses_received` = 18, `status` = `answered_pending_items`). `adjudicated_items` reste `null` : aucun élément atomique n'a encore été confirmé au format `ANNOTATION-PROPOSEE.md`.
- Provenance : aucune réponse ne vient d'un souvenir spontané ; 14 fiches depuis une reconstruction externe, 4 depuis la vue seule. Noté fiche par fiche (`provenance_note`).
- Vérifications faites pour `SYNTHESE.md` §3.2, sans modification de code : lecture de `_resumption_items` et de la gestion de `InvalidModelOutput` dans `session_summary.py` ; comptage des occurrences de rejet dans `~/.pulse_intelligence/logs/run.log` (0) ; comparaison `raw_output` / `open_items` sur les 14 replays archivés (identiques). Vérification pour la fiche 04 : la capture `eval/observed/2ce344566f7e85dc.json` contient 16 observations, toutes des commandes, aucun événement de fichier.
- Aucun modèle exécuté, aucun rejeu, aucun commit.
