# Relecture de l'audit de Pulse — 6 septembre 2026, soir

État examiné : `main`, commit `65986f3c8870f307181d3983854642710d2ac92c` (dernier
merge de code `fa01a05`, PR #67 ; `65986f3` est le commit de suivi documentaire).
Core 0.5.6 ; Intelligence 0.1.0 ; prompt par défaut `v2`.

Relecture demandée en lecture seule. Aucun fichier du dépôt n'a été modifié,
aucune branche créée, aucun test ajouté. L'index GitNexus a été régénéré avec
l'autorisation donnée dans la demande. Ce rapport est le seul nouveau fichier
produit ; écrit à la racine, non suivi, puis déplacé ici et suivi. Les rejeux utilisent des bases temporaires, un faux
Core de test ou un vrai Core jetable en sous-processus sur une base vide ; les
données de `~/.pulse_v2` et `~/.pulse_intelligence` n'ont pas été lues.

Documents de référence : l'audit du matin, [`audit-2026-09-06.md`](audit-2026-09-06.md)
(non suivi au moment de la relecture, depuis déplacé ici et suivi), et le suivi
[`2026-09-06-suivi.md`](2026-09-06-suivi.md), treize PR
de #56 à #69.

## Mon avis

**Les onze corrections tiennent sur le scénario exact que l'audit du matin avait
reproduit : neuf critères sont satisfaits tels qu'écrits, deux le sont
partiellement, et aucune correction n'a rouvert un défaut voisin.** Le point
faible n'est pas une correction isolée mais une interaction entre deux d'entre
elles : le vidage de la file `pending` (#63) et le budget par identité (#64)
laissent une session définitivement hors du `run` automatique dès qu'un payload
figé est abandonné, ce qui contredit la lettre du critère 5 et couvre mal le cas
« restauration de sauvegarde » nommé par le critère 3. Je fermerais cette
interaction, avec ses deux tests, avant d'ouvrir le lot B ; le reste est prêt.

## Ce qui a été examiné et exécuté

Lecture intégrale des diffs des douze PR de code (#56 à #67, #69), du suivi, des
quatre décisions du 6 septembre, des tests nommés par le suivi et des deux
workflows CI ; relecture de l'état courant de `state.py`, `session_summary.py`,
`context_snapshot.py`, `ingest.py`, `outbox_worker.py`, `producer_outbox.py`,
`runtime_config.py` et `llm/mlx.py` sur `main`.

| Vérification exécutée | Résultat |
| --- | --- |
| Suite Python Core, `tests_v2` | **578 tests réussis**, 22,48 s |
| Suite Python Intelligence | **171 tests réussis**, 1 `slow` désélectionné, 42,01 s |
| Tests d'intégration, isolation et exécution unique, en verbeux | 9 réussis, Core servi par `core/.venv/bin/python` (3.14.7) |
| CI GitHub sur `65986f3` | `core` et `intelligence` verts ; Intelligence : 171 réussis, aucun `skipped` |
| Rejeux des onze scénarios du matin | scripts temporaires, résultats ci-dessous |
| GitNexus | index régénéré sur `65986f3` (`--index-only`, sans PDG) ; impacts et `detect-changes --scope compare` |

Le test MLX réel n'a pas été lancé ; aucun modèle n'a été chargé. Le runtime
`mlx_lm` 0.31.3 installé a été interrogé sans poids, ce qui suffit pour le
défaut 11. Les journaux HTTP des faux Core ont été laissés dans les sorties de
script ; ils ne contiennent que des identifiants synthétiques.

## Les onze défauts

Pour chacun : le critère du matin cité mot pour mot, ce que le test nommé par le
suivi prouve réellement, ce que donne le rejeu du scénario du matin aujourd'hui,
puis le verdict.

### 1. P1 — Session fermée par verrouillage encore courante (#59)

**Critère du matin.** « Juste après verrouillage ou veille, aucune vue ne réouvre
la session fermée ; les tests de passage de jour restent verts. »

**Le test.** `test_a_session_just_closed_explicitly_is_never_current`
(`core/tests_v2/test_context_snapshot.py`), paramétré sur `screen_locked` et
`system_sleep`, rejoue exactement le scénario : modifications à 10:00 et 10:05,
fermeture à 10:06, lecture à 10:07. Il vérifie `current_session is None`, la
session listée `is_open: false` et sa présence dans `recent_sessions`. Deux
contrôles l'encadrent : sans fermeture, la session reste courante dans le gap ;
lue à 00:10, une session de la veille fermée en `day_boundary` reste courante.
Le test prouve le critère au niveau des deux fonctions de vue, en UTC ; il ne
passe pas par les routes HTTP ni par le fuseau de reconstruction par défaut.

**Rejeu.** Par les fonctions et par `GET /context` / `GET /context/sessions`
sur une application Flask jetable, fuseau par défaut :

```text
[lib] screen_locked  current=None closed=[('c150ba4e46fb50ee', False)] recent=['c150ba4e46fb50ee']
[lib] system_sleep   current=None closed=[('0e93109bc8eef39c', False)] recent=['0e93109bc8eef39c']
[http] /context current: None recent: ['c5a9367884b7c141']
[http] /context/sessions: 200 [('c5a9367884b7c141', False, None)]
[http] après reprise current: ('43700797e2f9d4ad', '2026-09-02T10:21:00+00:00') recent: ['c5a9367884b7c141']
```

Le correctif est un filtre d'une ligne sur `end_reason`
([context_snapshot.py:296](../../core/daemon_v2/context_snapshot.py:296)) : une session
fermée par un type de `LOCK_RESUME_TYPES` n'est jamais candidate, même dans le
gap. Le défaut `is_open=True` de la conversion existe toujours, mais n'est plus
atteignable pour ces sessions. Les deux notes de #59 restent ouvertes en #70 et
#71 ; elles ne conditionnent pas le critère.

**Verdict : satisfait.**

### 2. P1 — Deux exécutions Intelligence perdent leurs écritures (#60)

**Critère du matin.** « Deux lancements simultanés ne perdent aucune entrée et ne
génèrent pas deux fois le même travail. »

**Le test.** `test_a_second_loader_of_the_same_state_is_refused_and_nothing_is_lost`
rejoue le scénario du matin (deux `JobState` du même fichier, `e1` puis `e2`)
avec `lock=True` : le second chargement lève `StateLocked`, `e1` survit, `e2`
arrive après libération. `test_two_simultaneous_runs_generate_once_and_the_loser_exits_locked`
lance deux `cli.main(run --once)` dans deux threads : codes `[0, 5]`, un appel
modèle, un POST. Le suivi dit honnêtement que c'est en threads. C'est un
substitut valable : `flock` est attaché à la description de fichier ouverte, et
deux `os.open` séparés dans un même processus se comportent comme deux
processus. Ce que les tests ne prouvent pas : le passage par un vrai processus
CLI, son code de sortie réel, et l'absence d'écriture quand le verrou est pris.

**Rejeu.** Quatre parties, la quatrième avec deux processus réels dont le premier
est retenu sur une FIFO le temps que le second arrive :

```text
A. sans verrou (lock=False) : reste ['e2']
B. second chargement verrouillé refusé : StateLocked ; après libération, reste ['e1', 'e2']
C. run --once pendant qu'un autre processus tient le verrou → exit 5 en 0.09s ; état écrit ? False
   après libération → exit 0 : candidates=1 created=1
D. premier (bloqué sur la FIFO, verrou tenu) → exit 0 : candidates=1 created=1
   second (lancé pendant) → exit 5 : état : un autre passage tient le verrou
   POST reçus par Core : 1 | entrées emitted : 1
```

La partie A est attendue : le verrou est pris par `_load` pour `run` et
`summarize` seulement ([cli.py:121](../../intelligence/pulse_intelligence/cli.py:121)) ;
`JobState.load()` en bibliothèque reste un couple lecture-puis-réécriture sans
protection. Aucun appelant ne l'utilise ainsi aujourd'hui ; c'est une frontière
à connaître, pas un défaut de la décision.

**Verdict : satisfait**, inter-processus compris. Le wrapper launchd propage le
code 5 sans rien en faire (#74, lot C).

### 3. P1 — Après perte d'état, le rejeu ne retrouve pas l'idempotence du vrai Core (#61)

**Critère du matin.** « Récupération après perte d'état ou restauration de
sauvegarde, sans régénération conflictuelle ni doublon sémantique. » Avec :
« Préserver le refus `409` » et « Ajouter un test d'intégration entre
Intelligence et le vrai Core, sans démarrer les watchers. »

**Le test.** `test_lost_state_recovers_the_summary_core_already_accepted`
lance `daemon_v2.main` en sous-processus sur une base vide, sans watchers ni
outbox, sème une session close éligible par trente `file_changed`, résume avec
un état A, puis avec un état B vide : `created` puis `already_known`, un seul
appel modèle, la copie locale égale à `GET /activities/<id>`, et un contenu
différent sous le même identifiant refusé `409`. Il prouve la perte d'état et le
`409`. Il ne rejoue pas de restauration de sauvegarde : un état ancien qui
contient encore un `pending`, ou un `failed`, pour une identité que Core connaît.

**Rejeu.** Contre le vrai Core :

```text
interpréteur Core : /Users/Yugz/Projets/Pulse/core/.venv/bin/python
1re émission : created | 2e (état vide) : already_known — récupéré depuis Core
appels modèle : 1 | état B connaît l'événement : True origin=core
régénération manuelle sous le même event_id → Core 409 (409 préservé : True)
rejeu octet pour octet de l'événement accepté → Core 200 duplicate=True
état restauré avec pending (copie Core) → duplicate, appels modèle=1
```

Le scénario du matin (`tentative 1: Core 409`) ne se produit plus : avant tout
appel modèle, `summarize_session` demande à Core ce qu'il a déjà accepté
([session_summary.py:327](../../intelligence/pulse_intelligence/session_summary.py:327)).
Une sauvegarde qui contient un `pending` identique à ce que Core a accepté
rejoue en `duplicate`, sans modèle.

La sauvegarde qui contient un `pending` **différent** de ce que Core a accepté
n'est pas récupérée, voir la sonde B dans « Vu en passant » : le rejeu du
`pending` précède la récupération, reçoit `409` trois fois, puis la session est
abandonnée et ignorée par `run` alors que Core détient le résumé. Ce cas existe
dès qu'un état a été perdu puis régénéré entre la sauvegarde et sa restauration.

**Verdict : partiellement.** Perte d'état : satisfait, contre le vrai Core.
Restauration de sauvegarde : satisfait seulement si le `pending` restauré est
identique à l'événement accepté ; non couvert et non satisfait sinon.

### 4. P2 — Les payloads `pending` sortis de la fenêtre ne sont plus rejoués (#63)

**Critère du matin.** « Un payload vieux de plusieurs jours est accepté après
rétablissement, sans appel au modèle et sans nécessiter une commande manuelle
datée. »

**Le test.** `test_a_pending_out_of_the_window_is_drained_as_frozen_without_the_model`
gèle un payload le jour J (faux Core en `503`), relance `run_pass` à J+3 avec
`lookback_days=1` : `candidates=0`, `replayed=1`, `created`, le POST est
l'octet-pour-octet du payload refusé, aucun nouvel appel modèle, aucun nouvel
appel `/context`. Il prouve le critère avec le faux Core ; le vrai Core accepte
un `occurred_at` ancien, ce que le test d'intégration montre indirectement en
postant des événements du 2 septembre le 6.

**Rejeu.**

```text
[4] jour J : [('failed', 'tentative 1: Core 503')] | pending = 1
[4] J+3 : candidates=0 replayed=1 outcomes=[('created', 'rejeu pending')] | POST=1 appels modèle=1 /context=1
[4] payload rejoué == payload figé : True | pending restant = {}
```

**Verdict : satisfait.** Le vidage précède la sélection et marque la session
comme traitée ([session_summary.py:449](../../intelligence/pulse_intelligence/session_summary.py:449)) ;
c'est ce marquage, appliqué aussi aux entrées abandonnées, qui produit
l'interaction décrite plus bas.

### 5. P2 — Un échec définitif bloque aussi les nouvelles versions (#64)

**Critère du matin.** « Changer de version ouvre réellement une nouvelle
tentative ; une panne temporaire n'empoisonne pas définitivement une session. »

**Le test.** `test_a_new_prompt_version_gets_a_real_attempt_after_a_given_up`
rejoue le scénario du matin : trois sorties invalides, `given_up`, puis prompt
`v2` et modèle valide : `created`, un appel au nouveau modèle, l'abandon de `v1`
intact. `test_transient_provider_errors_never_reach_given_up` : trois
`SummarizerError` puis une sortie valide, `failed` trois fois, `failures` vide.
S'y ajoutent le refus d'entrée qui consomme le budget, le modèle indisponible
qui arrête le passage (code 2), l'état ancien à clé session respecté, et
`summarize --retry`. Les tests prouvent le critère pour les échecs de
**génération**. Ils ne couvrent pas l'abandon d'un payload figé en `pending`
que Core refuse trois fois.

**Rejeu.**

```text
[5] ['failed', 'failed', 'given_up'] appels = 3
[5] prompt v2 : ['created'] appels au nouveau modèle = 1 | POST prompt_version = v2
[5] modèle other/model (prompt v1) : ['created'] appels = 1
[5] transitoire x3 puis ok : ['failed', 'failed', 'failed', 'created'] | failures = {} failed = {}
```

Puis la sonde A, même session, mais l'abandon vient de trois refus Core d'un
payload figé (le cas du défaut 4) :

```text
[sonde A] v1 : ['failed', 'failed', 'given_up'] | pending v1 sur disque = True
[sonde A] run prompt v2, passage 1 : candidates=1 outcomes=[('given_up', "Core 503")] appels modèle v2=0 POST=0
[sonde A] run prompt v2, passage 2 : candidates=1 outcomes=[('given_up', "Core 503")] appels modèle v2=0 POST=0
```

Le changement de prompt n'ouvre pas de tentative dans `run` : la boucle de
vidage ajoute la session à `drained` avant de constater l'abandon, et la boucle
des candidates ignore toute session `drained`, quelle que soit l'identité
([session_summary.py:470](../../intelligence/pulse_intelligence/session_summary.py:470)).
`summarize <id> --retry` contourne le vidage et génère bien `v2` ; le chemin
automatique, lui, reste fermé tant que le `pending` abandonné est sur disque.

**Verdict : partiellement.** Satisfait pour les échecs de génération et les
pannes transitoires ; non satisfait pour une session dont le payload figé a été
abandonné, cas introduit par la combinaison #63 + #64. La note #73 (transitoire
jamais `given_up`) est un choix assumé, pas un écart au critère.

### 6. P2 — Une longue coupure épuise le budget HTTP de l'outbox (#65, #69)

**Critère du matin.** « De nombreuses déconnexions suivies d'un `503` puis d'un
`201` finissent par livrer l'événement sans intervention. »

**Le test.** `test_a_long_outage_then_a_first_503_keeps_the_event_retryable`
rejoue les 21 échecs de connexion, le `503`, puis l'acquittement : 22 `retry`
puis `sent`, aucune dead-letter. Quatre tests l'entourent : `503` seuls
atteignent toujours le plafond, les déconnexions seules ne comptent jamais, le
compteur survit à un redémarrage du worker, une base d'avant la colonne est
migrée et livrable, un rejeu de dead-letter repart à zéro. Pour #69,
`test_concurrent_first_opens_of_an_old_database_add_the_column_once` rend la
course déterministe par une barrière posée après `PRAGMA table_info`, sur trois
rounds de quatre ouvreurs. C'est la course exacte vue en CI sur `013e8ef`
(`duplicate column name: http_attempts`). Les tests prouvent le critère et la
régression de #65.

**Rejeu.**

```text
MAX_DELIVERY_ATTEMPTS = 20
issues : {'sent': 1, 'retry': 22} | 22e = retry | 23e = sent
dead_letter : None | pending : None | counts : (0, 0)
entremêlé (40 déconnexions et 19 x 503 alternés) : dernier = sent | dead-letter = False
503 seuls : 19 retry puis dead-letter
```

Deux compteurs : `attempts` pour le backoff, `http_attempts` pour le plafond
([outbox_worker.py:127](../../core/daemon_v2/outbox_worker.py:127)) ; la migration est
sérialisée par `BEGIN IMMEDIATE` avant la lecture du schéma
([producer_outbox.py:144](../../core/daemon_v2/producer_outbox.py:144)).

**Verdict : satisfait.**

### 7. P2 — Le replay hivernal dépend du décalage horaire actuel (#66)

**Critère du matin.** L'audit n'a pas écrit de ligne « Critère » ici. La
correction à viser : « Définir explicitement le fuseau de reconstruction avec ses
règles calendaires. Tester hiver/été, journées de changement d'heure et replay à
plusieurs dates d'exécution. Décider aussi ce que signifie un changement de
fuseau de la machine pour un historique déjà produit. »

**Le test.** `test_a_january_day_replayed_in_summer_keeps_its_late_session`
force la machine en `TZ=XXX-2` et rejoue les deux événements du 1er janvier à
22:10 et 22:20 UTC : une session, `timezone: Europe/Paris`, 0 activité le 2.
`test_the_same_day_read_in_winter_and_in_summer_gives_the_same_sessions` lit le
même magasin sous `XXX-1` puis `XXX-2` : mêmes identifiants, version 3.
`test_dst_days_have_23_or_25_hours_without_losing_or_duplicating_activity`
compte 24/23/24 et 24/25/24 activités sur les trois jours des deux changements
d'heure, somme exacte. Un fuseau invalide fait échouer `create_app` ; la
variable est honorée. Ces tests couvrent les trois demandes de test. La
quatrième demande, la décision, est écrite : constante explicite, historique
rejoué sous le fuseau configuré, identifiants proches de minuit susceptibles de
changer au premier replay, `RECONSTRUCTION_VERSION` 3.

**Rejeu.** Trois exécutions sur trois magasins neufs, plus la route HTTP :

```text
TZ machine=XXX-2, PULSE_RECONSTRUCTION_TZ=(défaut) → zone=Europe/Paris
  1er janvier : sessions=1 timezone=Europe/Paris version=3 | trace 01: 2 act. | trace 02: 0 act.
TZ machine=XXX-1, PULSE_RECONSTRUCTION_TZ=(défaut) → zone=Europe/Paris
  1er janvier : sessions=1 timezone=Europe/Paris version=3 | trace 01: 2 act. | trace 02: 0 act.
TZ machine=XXX-2, PULSE_RECONSTRUCTION_TZ=UTC → zone=UTC
  1er janvier : sessions=1 timezone=UTC version=3
ValueError: PULSE_RECONSTRUCTION_TZ must be an IANA zone name (got 'Mars/Olympus')
```

Les identifiants diffèrent entre mes trois exécutions parce que chaque magasin
est neuf ; l'égalité hiver/été sur un même magasin est prouvée par le test, pas
par ce rejeu. Il ne reste qu'un `datetime.now().astimezone()` dans `daemon_v2`,
pour l'horodatage d'une ligne de journal (`event_logger.py:45`) ; il ne touche
pas la reconstruction.

**Verdict : satisfait.**

### 8. P2 — `details.type` contourne la validation du type canonique (#58)

**Critère du matin.** « Un événement mal formé ne peut pas stocker deux types
contradictoires. »

**Le test.** `test_details_type_cannot_bypass_the_canonical_type_validation`
rejoue le POST du matin : `400`, `invalid_event`, champ `details.type`, zéro
ligne. Même chose pour `details.occurred_at`, et un contrôle que les deux
chemins d'ingestion, canonique et plat, passent toujours. Le faux Core
d'Intelligence a reçu le même refus. Le test prouve le critère pour les deux
champs réservés que la projection plate porte.

**Rejeu.**

```text
[8] type=unsupported + details.type=app_activated → 400 {'code': 'invalid_event', 'field': 'details.type'}
[8] details.occurred_at → 400 details.occurred_at
[8-sonde] details.summary / details.source / details.timestamp → 201, ligne inchangée (source, summary, occurred_at de l'enveloppe)
[8] lignes avec type != activity_type : 0
```

Les trois sondes montrent que les autres clés qu'un producteur pourrait glisser
dans `details` ne remplacent rien : la projection plate ne porte que `type` et
`occurred_at` ([ingest.py:714](../../core/daemon_v2/ingest.py:714)), et
`normalize_activity` calcule `source` et `summary` lui-même.

**Verdict : satisfait.**

### 9. P2 — Le filtrage des secrets diverge et oublie `project` (#67)

**Critère du matin.** « Des marqueurs synthétiques dans chaque champ pertinent
ne réapparaissent pas par un autre chemin `show`. »

**Le test.** `test_both_show_paths_display_the_event_core_accepted_with_secrets_redacted`
(vrai Core) reprend les deux marqueurs du matin, `doing` et `structured.project`,
émet par `run --once --fake`, puis vérifie `show <id> --json`, `show <id>`
(fiche), `show latest`, la sortie de `run` et `state.json` : aucun marqueur,
`project` stocké `TOKEN=[REDACTED]`, entrée `origin: core`. Côté Core,
`test_every_declared_free_text_field_is_redacted_and_undeclared_ones_are_refused`
énumère les sept champs libres du schéma, marque chacun, et vérifie qu'un champ
hors schéma dans `reprise` ou `structured` est refusé. Le premier prouve le
critère pour deux champs et trois chemins `show` ; le second prouve la rédaction
de tous les champs, mais sans `show`.

**Rejeu.** Marqueurs dans les six champs libres du modèle, neuf chemins CLI,
vrai Core :

```text
run --once → 0 | fuites stdout/stderr : []
  show <id>            → 0 fuites=[] redactions=3      show latest        → 0 fuites=[] redactions=3
  show <id> --json     → 0 fuites=[] redactions=6      show latest --json → 0 fuites=[] redactions=3
  show <id> --md       → 0 fuites=[] redactions=3      show latest --md   → 0 fuites=[] redactions=3
  show <id> --all      → 0 fuites=[] redactions=3      show latest --all  → 0 fuites=[] redactions=3
  list                 → 0 fuites=[]
state.json : fuites = [] | origin = ['core']
show <id> sans état local → 0, fuites = [], relu depuis Core par identité
```

Côté Core, `GET /activities/<id>`, `GET /context`, `GET /trace/<jour>` et
`GET /trace/<jour>.md` ne laissent passer aucun des six marqueurs ;
`structured.notes` est refusé `400`. Une septième sonde, hors critère, est dans
« Vu en passant » : une clé inconnue au **niveau `details`**, hors `reprise` et
`structured`, est encore recopiée telle quelle.

**Verdict : satisfait.** Les entrées `emitted` antérieures, sans `origin`,
restent non rédigées et sont signalées comme telles dans la fiche ; c'est la
limite écrite dans la décision.

### 10. P2 — `run --once` sort en 0 quand la génération échoue (#56)

**Critère du matin.** « Un passage ayant tout raté ne peut pas être interprété
comme sain à partir de son exit code ; les erreurs temporaires et les abandons
restent distinguables. »

**Le test.** `test_cli_run_once_exits_3_when_the_only_candidate_fails` et
`test_cli_run_once_given_up_outranks_failed`, plus le succès partiel en 3 et
la séquence 3, 3, 4. Ils prouvent le critère sur la valeur de retour de
`cli.main`, pas sur le code de sortie d'un processus ; `raise SystemExit(main())`
fait le lien.

**Rejeu.** En processus réels, faux Core, une candidate :

```text
[proc] sortie invalide, passage 1 : exit 3  candidates=1 created=0 failed=1 given_up=0
[proc] sortie invalide, passage 2 : exit 3
[proc] sortie invalide, passage 3 : exit 4  failed=0 given_up=1
[proc] sortie valide, autre état  : exit 0  created=1
[inproc] Core injoignable : 2
```

Depuis #64, un modèle indisponible sort aussi en 2 et une panne transitoire du
modèle en 3 ; au niveau du code de sortie, une sortie invalide et une panne
transitoire se confondent en 3, la distinction est sur stderr. Le wrapper
launchd fait `exec` de la CLI, donc le code remonte à launchd ; rien ne
l'exploite (#74).

**Verdict : satisfait.**

### 11. P2 — La température configurée n'est pas appliquée par MLX (#57)

**Critère du matin.** « Le réglage change effectivement l'appel d'inférence et
ses paramètres effectifs sont tracés. »

**Le test.** `test_the_temperature_reaches_the_runtime_and_changes_the_call`
installe un faux module `mlx_lm` **et** un faux `mlx_lm.sample_utils` : à `0.0`
et `1.0`, les deux appels à `generate` diffèrent par un `sampler`, rien n'est
retiré, stderr trace `temperature=…`. `test_a_runtime_without_make_sampler_drops_the_temperature_loudly`
prouve le refus bruyant. Ces tests prouvent le câblage dans le provider ; ils ne
prouvent pas que le runtime installé accepte ce câblage, puisque
`make_sampler` est lui aussi une doublure. Le test `slow` existant charge le
modèle mais ne touche pas à la température.

**Rejeu.** Runtime `mlx_lm` 0.31.3 réel, `make_sampler` réel, chargement et
`generate` remplacés par des doublures, aucun poids chargé :

```text
temperature=0.0  → kwargs={max_tokens, verbose, sampler <mlx_lm.sample_utils>} dropped=() | sampler([1,5,2]) sur 200 tirages → [1]
temperature=1.0  → kwargs={… sampler <mlx_lm.sample_utils>}                    dropped=() | sampler([1,5,2]) sur 200 tirages → [0, 1, 2]
temperature=None → kwargs={max_tokens, verbose}                                 dropped=() | stderr : temperature=absente (argmax du runtime)
```

Les signatures réelles confirment la chaîne : `generate(model, tokenizer,
prompt, verbose, **kwargs)` transmet à `generate_step(…, sampler=…)`, et
`make_sampler(temp=…)` existe. À `0.0`, le sampler réel est un argmax ; à `1.0`
il tire les trois indices.

**Verdict : satisfait**, à un chargement réel près ; un passage `slow` avec deux
températures fermerait le point sur le runtime.

## Vérifications transverses

### Les quatre exceptions au gel

| Exception | Ce qu'elle prétend | Ce que le diff montre | Tenu ? |
| --- | --- | --- | --- |
| #61 `GET /activities/<event_id>` | lecture pure, ligne stockée dans la forme de l'export JSON | `TraceStore.activity_by_event_id` : un `SELECT` ; la route appelle `export_stored_activity` ; aucune écriture, `404` sinon ; test compare le corps à l'export de `/trace` champ pour champ | oui |
| #61 `export_stored_activity` | déplacement pur hors de `build_daily_trace` | le dictionnaire extrait est identique clé pour clé à l'ancien littéral ; `build_daily_trace` l'appelle en compréhension ; forme vérifiée par le même test | oui |
| #65 `events.http_attempts` | schéma additif, rétrocompatible, migration idempotente | `ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT 0` gardé par `PRAGMA table_info` ; `mark_retry` incrémente sur option ; `replay_dead_letters` réinsère sans la colonne, donc repart à 0 ; `PendingEvent` gagne un champ, seul constructeur `_pending_from_row` ; sérialisé par #69 | oui ; le `CREATE TABLE` n'a pas reçu la colonne, une base neuve passe donc aussi par l'`ALTER`, ce qui est inoffensif |
| #67 champ hors schéma refusé en 400 | durcissement de contrat sous gel, là où il était recopié brut | avant : clés inconnues de `structured` recopiées telles quelles, clés inconnues de `reprise` silencieusement ignorées ; après : `400` avec le champ nommé, dans les deux sections | oui, mais c'est un resserrement visible du contrat `POST` pour le type `session_summary` ; documenté dans le README Core, un seul producteur existe, la PR #54 devra s'y tenir |

Aucune des quatre ne touche `GET /context`, n'ajoute une source ni un type
d'événement.

### Les quatre décisions du 6 septembre

**Modèle local Qwen.** `DEFAULT_MODEL = "mlx-community/Qwen3.8-27B-4bit"`,
plafond `llm_max_input_tokens` à 30 000 refusé avant le prefill, `thinking`
coupé quand le template le connaît, tout réversible par `llm_provider` et
`model_id`. Le code fait ce que la décision dit. Le spike B v2 « à remesurer »
est une mesure en attente, pas un écart.

**Exécution unique.** Point par point : `flock` non bloquant pris dans
`JobState.load(lock=True)` **avant** la lecture du fichier
([state.py:262](../../intelligence/pulse_intelligence/state.py:262)) ; pris pour `run`
et `summarize` seulement, tenu jusqu'au `finally` de `main` ; `StateLocked`
sort en 5 sans lire ni écrire ; `list` et `show` ne le prennent pas ; `save`
passe par `mkstemp` dans le dossier de l'état puis `os.replace`, mode 0600 ;
format de `state.json` inchangé. Conforme.

**Fuseau de reconstruction.** `ZoneInfo(PULSE_RECONSTRUCTION_TZ)`, `Europe/Paris`
par défaut, résolu une fois par processus et vérifié au démarrage
([runtime_config.py:22](../../core/daemon_v2/runtime_config.py:22)) ; `context_snapshot`,
`daily_trace`, `timeline` et la route `/context/sessions` l'utilisent ; le nom
du fuseau est dans `/context`, `/context/sessions` et le `meta` des traces ;
`RECONSTRUCTION_VERSION` vaut 3. Conforme.

**Rédaction des champs libres.** Core rédige les sept champs libres et refuse
les clés inconnues des deux sections ; Intelligence relit `GET /activities/<id>`
après un `201` et enregistre cette copie avec `origin: "core"` ; sans relecture
possible, l'entrée est enregistrée sans `event` et `show` passe par Core. Le
code fait ce que la décision dit, avec une nuance de formulation : la décision
dit que les entrées `emitted` « n'ont plus qu'une forme » ; il en existe trois
sur disque (ancienne sans `origin`, `origin: core` avec `event`, `origin: core`
sans `event`), et `show` traite les trois.

### Les tests d'intégration Intelligence ↔ vrai Core en CI

Ils tournent. Le workflow `intelligence.yml` s'exécute sur `ubuntu-latest`,
Python 3.14, avec `pip install -e '.[dev]'`, soit `requests`, `pytest` et un
`flask>=3` non épinglé. Le fichier de test choisit l'interpréteur : la venv de
Core si elle existe, sinon `sys.executable`
([test_real_core_integration.py:33](../../intelligence/tests/test_real_core_integration.py:33)).
En CI il n'y a pas de venv Core : **Core est servi par l'interpréteur
d'Intelligence, sous Linux, avec le Flask que `pip` a résolu ce jour-là**, pas
avec `core/requirements.txt`. Le journal du run `34057005999` sur `65986f3`
donne `171 passed, 1 deselected` sans `skipped` ; un `skip` du fixture
apparaîtrait dans ce résumé, et le compte local est identique. Localement, les
deux tests passent sous `core/.venv/bin/python` 3.14.7.

Ce qu'ils prouvent que les faux ne prouvent pas : le `409` par empreinte de
contenu, que le faux Core a dû apprendre dans #61 ; la rédaction, que le faux ne
fait pas du tout ; l'éligibilité d'une session réellement reconstruite par Core
à partir d'événements bruts, avec ses fichiers réels dans `central_files` ; la
forme réelle de `GET /activities/<id>`. Ce qu'ils ne prouvent pas : Core avec
ses dépendances épinglées, couvertes à part par `core.yml` sur macOS ; une
régression de démarrage de Core sous Linux ferait rougir le job Intelligence,
pas le job Core, ce qui trompe sur l'origine.

### Le garde d'isolation, principe 1

Le principe, dans la spec du 3 septembre : « Core ne sait pas qu'Intelligence
existe. Intelligence lit Core par HTTP … Aucun import de `daemon_v2` depuis
`intelligence/`, vérifié par un test. » Le garde, `intelligence/tests/test_isolation.py`,
a trois tests : aucune ligne `from`/`import` de `daemon_v2`, `core` ou
`scripts` dans le paquet et les tests ; aucun `sys.path` vers `core` ; les huit
modules s'importent sans Core sur le chemin. Les trois passent sur `main`.

Toujours intact après #61 : le test d'intégration lance Core par
`subprocess.Popen([interpréteur, "-m", "daemon_v2.main"])`, une chaîne, pas un
import, et le faux Core a reçu le `409` sans recopier la formule d'empreinte de
Core. Toujours pertinent : c'est lui qui force le couplage à rester HTTP, et
#61 est justement le moment où la tentation d'importer `trace_store` pour
« relire » aurait été forte. Deux limites à connaître : le garde ne lit que
`pulse_intelligence/` et `tests/`, il n'y a pas d'autre `.py` aujourd'hui ; et
depuis #61 la suite Intelligence dépend de la présence de `core/` sur disque,
un couplage de système de fichiers que le garde ne voit pas, assumé par un
`skip` explicite.

## Vu en passant

Pas de recherche systématique. Ce qui est apparu pendant les rejeux, par ordre
d'importance.

**1. Une session au `pending` abandonné sort définitivement du `run`
automatique.** Deux sondes, faux Core. Sonde A, déjà citée au défaut 5 : après
trois refus Core d'un payload figé, changer de prompt ne rouvre rien dans
`run`, zéro appel au nouveau modèle, à chaque passage. Sonde B, le cas
« restauration de sauvegarde » du défaut 3 : un état sauvegardé avec un
`pending` T1, l'état vivant perd ce `pending`, régénère T2 que Core accepte,
puis la sauvegarde est restaurée :

```text
[sonde B] après restauration, 4 passages : [('failed', 'rejeu pending · tentative 2: Core 409')],
          [('given_up', 'rejeu pending · tentative 3')], [('given_up', 'Core 409')], [('given_up', 'Core 409')]
[sonde B] Core détient le résumé ; l'état local le connaît : False ; pending toujours sur disque : True
```

Le rejeu du `pending` précède la récupération depuis Core, reçoit `409`, épuise
le budget, et la session est ensuite ignorée par la boucle des candidates
([session_summary.py:449](../../intelligence/pulse_intelligence/session_summary.py:449)
et [470](../../intelligence/pulse_intelligence/session_summary.py:470)). La
récupération de #61 n'est jamais atteinte. `summarize <id> --retry` s'en sort à
la main. Deux corrections circonscrites : ne pas marquer `drained` une entrée
abandonnée, ou clé par identité ; et sur `409` au rejeu d'un `pending`,
consulter `GET /activities/<id>` pour réconcilier plutôt que compter une
tentative. Chaque sonde est un test prêt à écrire.

**2. Une clé inconnue au niveau `details` d'un `session_summary` est stockée
telle quelle.** `details.extra_top = "TOKEN=top-level-stray"` : `201`, et le
marqueur ressort de `GET /activities/<id>`. Le README Core dit précisément « un
champ hors schéma dans `reprise` ou `structured` est refusé », donc la
documentation est exacte ; la phrase de la décision, « tout champ texte libre
d'un `session_summary` », est plus large que le code. Intelligence n'émet
aucune clé de ce genre. À trancher en une ligne : refuser aussi au niveau
`details`, ou restreindre la phrase.

**3. `summarize` imprime l'événement d'avant normalisation si la relecture
échoue.** `_emit` renvoie `event=accepted or event` ; `run_summarize` l'affiche
en JSON ([cli.py:278](../../intelligence/pulse_intelligence/cli.py:278)). Ce n'est pas
un chemin `show`, et l'état local n'en garde rien, mais c'est la sortie brute du
modèle sur stdout au moment même où Core vient de la rédiger. Cas rare, Core
tombant entre le `POST` et le `GET`.

**4. Documentation.** Le suivi, suivi par git, lie `../audit-2026-09-06.md`,
qui n'est pas suivi : le lien ne résout que sur ce poste. La demande de ce soir
situe l'audit « à la racine » ; il est dans `docs/`. Le bloc GitNexus de
`CLAUDE.md` annonce toujours `Pulse_Core`, 1 435 nœuds et 123 flux, dérive déjà
signalée le matin, inchangée.

**5. `CREATE TABLE events` sans `http_attempts`.** Chaque base neuve est créée
sans la colonne puis migrée dans la même ouverture. Inoffensif, et couvert par
la sérialisation de #69 ; à porter dans le `CREATE` à la prochaine occasion pour
que la migration ne serve qu'aux bases anciennes.

## GitNexus

Index régénéré sur `65986f3` avec `analyze --index-only`, runner 1.6.11, sans
`--pdg` : **3 006 nœuds, 8 215 relations, 122 communautés, 257 flux**. Les
10 637 nœuds du matin comptaient les nœuds PDG ; les deux chiffres ne se
comparent pas. Avertissements d'analyse : 62 points d'entrée écartés, 94 non
explorés, 35 flux déduits abandonnés, 381 appelés coupés par le branchement ;
un flux absent ne signifie pas un chemin absent.

`detect-changes --scope compare --base-ref ef14ea9` : 46 fichiers, 269
symboles, 130 processus touchés, risque `critical`. C'est attendu pour un lot
qui touche l'ingestion et la reconstruction, et cela dit l'étendue, pas la
gravité. Impacts amont des symboles corrigés :

| Symbole | Risque GitNexus | Processus touchés |
| --- | --- | --- |
| `normalize_activity` | **CRITICAL** | 5 |
| `_activity_from_event` | **CRITICAL** | 5 |
| `_select_current_session` | **HIGH** | 4 |
| `run_pass` | LOW | 0 |

Le `LOW` de `run_pass`, avec zéro processus, est un silence du graphe côté
Intelligence, pas une absence d'appelants : la CLI et le wrapper launchd
l'appellent, et c'est précisément là que se trouve le point 1 ci-dessus. Le
statut est à lire comme `UNKNOWN`. Les analyses d'impact n'ont précédé aucune
modification, puisqu'il n'y en a pas eu.

## Rejouer les vérifications

```sh
# Depuis core/
PYTHONDONTWRITEBYTECODE=1 PULSE_CORE_EVENT_LOG=0 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests_v2

# Depuis intelligence/, y compris les deux tests contre le vrai Core
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider -v tests/test_real_core_integration.py tests/test_isolation.py tests/test_single_execution.py

# Rejeux du défaut 7 (fuseau), depuis core/
TZ=XXX-2 PYTHONPATH=. .venv/bin/python -B -m pytest -q tests_v2/test_reconstruction_timezone.py
```

Les rejeux des onze scénarios et les sondes sont des scripts temporaires, dans
le bac à sable de la session, écrits avec les fixtures des suites (`FakeCore`,
`real_core`, `Clock`, `Script`) et `PULSE_INTELLIGENCE_HOME` pointé sur un
dossier vide. Les sondes A et B du point 1 méritent d'entrer dans
`tests/test_drain_pending.py` telles quelles.

## Ce que je ferais avant d'ouvrir le lot B

1. Fermer l'interaction #63 × #64 : une entrée `pending` abandonnée ne doit
   pas exclure sa session des candidates d'une autre identité, et un `409` au
   rejeu d'un `pending` doit déclencher la réconciliation avec Core plutôt que
   consommer le budget. Deux tests, les sondes A et B. C'est le seul point qui
   ramène un critère P1 à « partiellement ».
2. Trancher la clé inconnue au niveau `details` d'un `session_summary` : refus
   ou phrase de décision restreinte. Une ligne de code ou une ligne de texte.
3. Faire résoudre le lien du suivi vers l'audit, en suivant le fichier ou en
   déplaçant le lien, et corriger le bloc GitNexus de `CLAUDE.md`.
4. Rendre visible, dans le job Intelligence, quel interpréteur sert Core ; ou
   faire tourner les deux tests d'intégration sur macOS avec les dépendances
   épinglées de Core. Sans cela, une rougeur du job Intelligence peut être une
   panne de Core sous Linux.
5. Un passage `slow` avec deux températures, pour fermer le défaut 11 sur le
   runtime réel plutôt que sur ses signatures.

Rien ici n'est bloquant pour concevoir le lot B ; le point 1 l'est pour compter
sur `run` sans surveillance, ce qui était la définition d'un P1 le matin.
