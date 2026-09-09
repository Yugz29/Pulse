# Une seule reconstruction des sessions de travail

Décision du 2026-09-08, mise en œuvre à partir de `3504d4d`.
Périmètre : stockage des événements, reconstruction, lecteurs directs et tests.
Ce chantier est explicitement autorisé dans Core malgré le gel fonctionnel.

## Diagnostic et concepts

| Notion avant | Identité / persistance | Rôle réel |
| --- | --- | --- |
| Session de stockage (`models.Session`) | UUID aléatoire, colonne `activities.session_id` | Attribution à chaque insertion selon la proximité temporelle de toutes les anciennes lignes ; sans workspace ni fermeture système |
| Groupe de trace (`trace.sessions`) | Ancien UUID, éventuellement celui du premier groupe fusionné | Regroupement des lignes par UUID puis fusion des chevauchements ; immédiatement remis à plat par la reconstruction |
| Session de travail (`activity_kind=work`) | 16 hex du SHA-256 des `event_id` sources triés ; calculée en lecture | Travail observé, workspace, bornes, provenance et fermeture ; notion consommée par le produit |
| Activité isolée / arrière-plan | Même famille de vues, identités par sources | Catégories distinctes d'une session de travail, exclues des sessions à résumer |
| Présence non attribuée (`unresolved_sessions`) | Ordinal d'affichage `unresolved-N` | Groupes d'activations d'applications sans preuve de travail ; aucune identité produit persistante |
| Session d'agent | Identifiant Claude/Codex dans `details.session_id` ; événement dérivé et archive séparée | Une conversation/transcript, pas une session de travail ; peut être émise après coup |
| `SessionView` Intelligence | Vue HTTP de la session de travail | Lecture et sélection de candidates ; aucune reconstruction locale |
| `session_summary` | Événement dérivé UUID5(session, prompt, modèle) | Référence au hash de la session, aux sources et à la version ; ne participe pas à sa reconstruction |

Avant :

```text
événement → SELECT de tout l'historique → select_session → ligne + UUID
                                                         ↓
                              groupes par UUID → fusion → remise à plat
                                                         ↓
                                               reconstruction → journal

lignes → projection /context → faux groupe « sessions » → même reconstruction
                                                         ↓
                                                /context → Intelligence
```

Le regroupement historique était inutile à la reconstruction produit. Il
ajoutait un scan et un tri de toute la table sous la transaction d'écriture,
et transportait une identité sans sens pour Intelligence.

## Propriétaire unique

`analysis.timeline.reconstruct_session_views(activities, day, zone, now)`
possède les règles de composition, de bornes, d'identité et de fermeture.
Son entrée est une liste plate d'événements exportés, avec un instant de
référence explicite. Elle ne lit ni stockage, ni horloge, ni modèle.

`daily_trace.build_daily_trace` charge une journée locale jusqu'à l'instant de
référence, exporte les lignes et appelle cette reconstruction une fois.
Le journal et `context_snapshot` utilisent ce même chargement. Les renderers
et `/context` consomment `end_reason`, sans décider à nouveau si une session
est ouverte. Les synthèses et projections restent propres à chaque lecteur.

```text
producteurs → outbox durable → ingestion / masquage → événements SQLite
                                                           ↓
                                  build_daily_trace : journée + référence
                                                           ↓
                          reconstruct_session_views : règles déterministes
                                                           ↓
                                         vues de travail et autres catégories
                                         ├── journal HTML / Markdown / JSON
                                         └── /context et /context/sessions
                                                      └── Intelligence
```

Aucun SessionManager, cache ou nouveau moteur n'est introduit. Le chargement
peut être invoqué plusieurs fois par des requêtes différentes : unicité du
propriétaire des règles ne signifie pas cache global ou exécution unique.

## Identité conservée

`reconstruction_version` reste **3** : même découpage à événements, journée,
fuseau et référence identiques. SHA-256 tronqué à 16 hex, liste triée des
sources et labels `work-N` restent identiques. Les bornes et la version ne
sont pas dans le hash ; elles restent des métadonnées. Les événements tardifs
qui changent la composition donnent toujours une autre identité. Les résumés
anciens continuent de référencer leurs sources initiales, sans réécriture.

Le tri de reconstruction reste `(occurred_at, id SQLite)` : à timestamps
égaux, l'ordre enregistré départage les événements. Le déterminisme porte
sur les mêmes événements **stockés**, identifiants de lignes compris ; ce
chantier ne change pas la politique de départage lors d'un import qui
réattribuerait ces identifiants. Le fallback d'identité `id:<rowid>`, utilisé uniquement par d'anciennes
fixtures, est supprimé. Les lecteurs du store donnent toujours un `event_id`,
y compris `legacy-migrated:<id>` pour le très ancien format, comme avant ce
chantier. Aucune identité de donnée stockée ne dépendait de ce fallback.

## Suppressions et compatibilité ciblée

Supprimés : `session_tracker.py`, `models.Session`, `StoredActivity.session_id`,
`TraceStore._sessions`, attribution à l'insertion, groupes et fusion de trace,
projection `_activity_view` et enveloppe factice de `/context`, reconstructions
implicites des renderers, alias `_passive_sessions`, `_unresolved_sessions`,
`_work_session_views` et repli `_session_has_recent_strong_activity`.

- Base neuve : ni colonne `session_id` ni index correspondant.
- Base ancienne : colonne, index et valeurs historiques laissés en place,
  ignorés par la lecture métier. Une chaîne vide satisfait uniquement le
  `NOT NULL` historique lors d'une nouvelle insertion. Ce n'est pas une
  attribution ni un identifiant. Un booléen établi à l'ouverture choisit la
  forme de l'INSERT ; aucun scan historique lors d'`append_event`.
- Un ancien binaire exigeant cette colonne ne sait pas ouvrir une base neuve
  créée sans elle : le downgrade de ces bases ne fait pas partie du contrat.
  Les bases historiques conservent leur schéma ; aucune bascule utilisateur
  n’est effectuée dans ce chantier.
- L'ancien backfill des métadonnées canoniques / UTC reste nécessaire à la
  lecture des bases pré-canoniques. Ce chantier n'en change pas les règles.
- Triggers append-only, fingerprints, index `event_id`, transactions, WAL,
  permissions et rédaction restent en place. Aucun accès à la base personnelle
  ni bascule de service n'est requis pour développer ou tester ce changement.
- Les outils ponctuels de migration du 2026-09-05 sont historiques et ciblent
  leurs copies de base d'époque ; ils ne deviennent pas un framework de
  migration des nouveaux schémas. Voir leur note de décision.

## Export et comportement

L'export du journal (`/trace/...`) porte désormais `schema_version: 2` et
`reconstruction_version`. `activities` contient les événements de la journée
jusqu'à la référence, y compris les événements système et dérivés hors travail.
`work_sessions`, `work_session_count`, `unresolved_sessions` et
`unresolved_activity_count` restent les vues produit. Les anciens champs
`sessions`, `session_count` (groupes de stockage) et `passive_sessions` sont
retirés. Une activité exportée et `GET /activities/<event_id>` gardent le même
format. Les routes ne changent pas.

Consommateurs vérifiés : routes, renderers, synthèses, résolveurs de projet,
scripts producteurs, Swift, Intelligence, tests et outils de migration. Une
recherche des appels dans les autres projets locaux n'a trouvé aucun client
de ces anciens groupes. Intelligence utilise `/context/sessions`, dont le
schéma reste **2**, sans modification de son entrée LLM. Cela n'est pas une
preuve d'absence de tout script privé inconnu ; le changement d'export est
annoncé ici et dans le README, jamais déguisé en format inchangé.

Deux divergences corrigées :

1. Une session fermée à minuit est récente, jamais courante et ouverte dans
   `/context`. Le découpage journalier existait déjà ; seule l'exception du
   lecteur de contexte disparaît.
2. Le journal ignore les événements datés après sa référence, comme `/context`.
   Ils restent stockés et accessibles par `event_id`, puis apparaissent quand
   la référence les atteint. Une trace historique exhaustive peut être lue
   avec une référence postérieure à la fin de sa journée.

Les résumés, la collecte d'agents, le sens des signaux forts/faibles, les
seuils de temps, le masquage, l'outbox et MLX ne sont pas refondus.

## Mesures

Mesures sur cette machine, bases SQLite temporaires avec mêmes colonnes et
index que le code de chaque version. Historique prérempli hors chronométrage ;
25 insertions canoniques distinctes par taille, normalisation hors mesure,
connexion/transaction/commit inclus. Ni donnée personnelle ni daemon actif.
Script : [`tools/benchmark_session_reconstruction.py`](../../tools/benchmark_session_reconstruction.py).
Exécution depuis la racine :
`PYTHONPATH=core core/.venv/bin/python tools/benchmark_session_reconstruction.py`.
Les mesures brutes (`before.json`, `after.json`) ont été retirées du dépôt le
2026-09-09 (historique Git) ; le tableau ci-dessous les résume.

Un passage par version, à interpréter comme ordre de grandeur, sans promesse
sur la latence en production. Le cas vide inclut surtout les coûts de fichiers.

| Lignes préexistantes | Avant, médiane ms | Après, médiane ms |
| ---: | ---: | ---: |
| 0 | 1,814 | 1,145 |
| 1 000 | 1,289 | 0,460 |
| 10 000 | 6,355 | 0,729 |
| 50 000 | 30,669 | 0,727 |

À 50k : environ **42×** dans ce passage. L'insertion garde les opérations
SQLite indexées ; le coût de reconstruction O(N) par insertion a disparu,
sans prétendre que toute écriture SQLite devient strictement O(1).

| Dimension | Avant | Après |
| --- | --- | --- |
| Modèles concurrents pour les sessions de travail | attribution persistée + reconstruction | reconstruction seule |
| Formes sur le chemin journal | événements → UUID → groupes → fusion → événements → vues | événements → vues |
| Préparations de reconstruction en production | journal, contexte et replis implicites | chargement partagé, appel explicite unique |
| Décision d'ouverture côté consommateurs | règles/replis indépendants | `end_reason` de la reconstruction |
| Écriture | lookup idempotence + scan/groupement historique + INSERT | lookup idempotence + INSERT |
| Compatibilité liée aux sessions de stockage | modèle, écriture, groupes, alias | seul remplissage neutre de l'ancienne contrainte SQL |

Bilan du code de production `core/daemon_v2` : **245 lignes nettes retirées**
(214 ajoutées, 459 retirées ; déplacements d'indentation compris). Ce chiffre
exclut les tests, la documentation et le script de mesure.

Les groupes de présence, activités isolées/arrière-plan, sessions d'agent et
résumés restent des concepts utiles, pas des moteurs concurrents à fusionner.

## Validation

Avant : **578 tests Core passent**. Les **217 appels de reconstruction**
capturés pendant cette suite ont permis de comparer le refactor initial :
217 résultats identiques. Vérification sur le code final : les **169 appels
avec des événements canoniques donnent 169 résultats strictement identiques**,
identités, sources, bornes et catégories comprises. Les 48 autres appels
utilisaient des fixtures sans `event_id` ; ces fixtures fournissent désormais
explicitement leur provenance et sont couvertes par la suite finale. Les tests de contrat sont adaptés pour consommer les événements
plats au lieu des groupes historiques.

Tests ajoutés : budget d'instructions SQL avec 10k lignes (création, doublon,
conflit), ancien schéma sans perte des colonnes d'époque, permutations des
événements stockés, concordance journal/contexte en UTC et Europe/Paris,
horizon de lecture commun, intégration vrai Core → sélection Intelligence →
résumé → identité inchangée. Les résultats des suites finales sont consignés
dans le rapport du chantier : **584 tests Core passent**, **244 tests
Intelligence passent**, **7 tests lents désélectionnés** (dont MLX, non exécuté).
Le test d’intégration ajouté utilise un modèle faux et un vrai Core HTTP
sur une base temporaire. Aucun changement des producteurs ni du transport.
`git diff --check` est propre.

## Limites et suite

Aucun nouveau cache ; les grandes lectures journalières et le statut peuvent
encore coûter cher. L'identité change toujours si un événement tardif rejoint
la session. La politique de remplacement/invalidation des résumés est un
chantier distinct. Les limites d'observation à minuit (par exemple un verrou
survenu la veille) ne sont pas redessinées ici.

Prochaine frontière recommandée : la projection des faits vers Intelligence
(chronologie utile, provenance conservée hors texte envoyé au modèle), sans
changer la reconstruction désormais commune.
