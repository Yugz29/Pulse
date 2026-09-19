# TODOS — Intelligence

## Résumé de session

### `show <id>` lit l'état local avant Core

**What:** `show <id>` lit d'abord la copie locale de l'événement émis, puis Core en repli (`/context.last_session_summary` seulement, Core n'a pas de route par identifiant). À l'étape 5 (service résident), décider si l'API doit vérifier contre Core pour voir les résumés produits par d'autres processus.

**Déclencheur:** étape 5 du §12 de `docs/specs/2026-09-03-session-summary.md`.

**Effort:** S
**Priority:** P3
**Depends on:** Service résident

### `list` et `run` ne jugent pas « déjà résumée » avec le même modèle

**What:** `run_list` appelle `classify_sessions(model_id=config.model_id or "fake/summarizer")`, alors que `run_pass` utilise `summarizer.model_id`, c'est-à-dire le modèle réellement servi par le provider (PR 2 de l'étape 3). Les deux coïncident dès que `model_id` est renseigné dans `config.toml` — ce que `require_model()` encourage déjà. Ils divergent quand `PULSE_LLM_MODEL` surcharge un `model_id` différent : `list` peut alors annoncer candidate une session que `run` considère déjà résumée, et inversement. Affichage seulement : aucune émission, aucun état local n'en dépend.

**Pourquoi ce n'est pas corrigé :** aligner `list` sur le modèle réellement servi obligerait à construire le provider, donc à exiger les trois variables d'environnement pour une commande de lecture seule. Le repli `"fake/summarizer"` en dur dans `run_list` est le vrai reste à traiter.

**Déclencheur:** un `list` trompeur observé en usage réel, ou l'étape 5 (service résident) qui rendra la question structurante.

**Effort:** S
**Priority:** P3
**Depends on:** Cas réel observé

### L'annexe `previous_summary` dépend du fuseau de la machine

**What:** `previous_summary_annex` ne garde le résumé précédent que s'il s'est terminé le même jour **local** que la session (`ended.astimezone().date() == session.day`), et le jour local vient du fuseau du processus. La même vue Core donne donc une entrée différente — et un autre `input_hash` — selon le fuseau : sur la PR #53, le test de l'extension du corpus était vert à Paris et rouge sur le runner en UTC (`a0aacd1f` finit le 05 à 22:39 UTC, le 06 à Paris). En production le fuseau est celui du poste, stable ; c'est la reproductibilité de `eval` hors du poste qui est en cause. Contournement : le test rejoue le corpus dans son fuseau de capture (`TZ=Europe/Paris`). À trancher : fixer le fuseau de la règle (celui du `context.timezone` servi par Core, plutôt que celui du processus).

**Déclencheur:** `eval` lancé hors du poste (CI, autre machine), ou tout changement de `previous_summary_annex`.

**Effort:** S
**Priority:** P3
**Depends on:** —

### Deux résumés d'une même session coexistent après un changement de `prompt_version`

**What:** `summary_event_id(session_id, prompt_version, model_id)` fait qu'un changement de prompt rend candidates à nouveau les sessions déjà résumées (jour 2 : six sessions du 2026-09-05 régénérées en v2, trace append-only, aucune collision). Deux événements `session_summary` valides décrivent alors la même session. Rien ne dit lequel **fait foi** : `show <id>` rend le dernier émis localement, Core sert le dernier en `last_session_summary`, l'annexe `previous_summary` d'une session suivante prend celui que Core sert. Conséquence déjà vue : une régénération ne reçoit pas d'annexe (son propre résumé antérieur masque le précédent, voir l'entrée ci-dessus) — elle n'est donc pas comparable à l'original, l'entrée diffère.

**À définir à l'étape 5 :** la règle de préséance (dernier émis ? version de prompt la plus haute ? celle de la config courante ?), et si l'annexe doit remonter au résumé d'une **autre** session plutôt qu'au dernier tout court — ce qui demande soit une règle côté Intelligence sur `recent_sessions`, soit une route Core (possible depuis la levée du gel le 2026-09-09, avec décision datée si le contrat `/context` change).

**Déclencheur:** étape 5 (service résident), ou le premier `show` trompeur.

**Effort:** M
**Priority:** P2
**Depends on:** Service résident

### Les résumés héritent de l'immutabilité de `trace.db` par effet de bord

**What:** Un `session_summary` est une **interprétation** (sortie d'un modèle, sous un prompt et une version données), pas un fait observé ; il entre pourtant dans `trace.db` par la même route que le brut (`POST /activities`), append-only, sans possibilité de le retirer ni de le marquer dépassé. Deux conséquences déjà rencontrées : (1) quand deux résumés d'une même session coexistent (entrée « Deux résumés d'une même session coexistent… »), rien ne dit lequel fait foi ; (2) le 2026-09-07 au soir, la bascule vers le prompt v3 a été retenue tout en sachant qu'une part des `open` régénérés serait fausse (D6, `docs/dogfooding.md`, jour 3) — on émet donc sciemment des interprétations partiellement fausses que rien ne pourra ensuite déclasser. L'append-only reste **correct pour le brut observé** ; il est subi pour les interprétations.

**Piste à creuser (Intelligence d'abord ; Core possible depuis la levée du gel) :** une **filiation** entre résumés — `supersedes` / `superseded_by` portés par Intelligence (dans `details`, ou dans l'état local, ou les deux), une régénération désignant explicitement le résumé qu'elle remplace ; `show`, l'annexe `previous_summary` et un futur service suivraient la tête de filiation plutôt que « le dernier émis ». Questions ouvertes, sans conception ici : où vit la filiation (Core la recopie sans la lire, ou Intelligence seule ?), ce que devient un résumé dépassé pour `GET /context` (aujourd'hui `last_session_summary` sert le dernier tout court ; le faire suivre la filiation est un changement de contrat, décision datée), et si un résumé reconnu faux doit pouvoir être **retiré** de la reprise sans être effacé de la trace.

**Déclencheur:** avant l'étape 5 (service résident), qui figerait la règle « dernier émis » par défaut ; ou le premier résumé faux qu'on voudrait déclasser.

**Effort:** M
**Priority:** P2
**Depends on:** Service résident ; entrée « Deux résumés d'une même session coexistent… »

### `details.workspace` peut désigner la session suivante (`1f931a43`, 2026-09-06)

**What:** Le résumé v2 de `1f931a43c3b7149f` (work-4 du 2026-09-06, 07:44–08:47 UTC) porte `structured.project: "Pulse"` — juste, la vue dit `projects: ["Pulse"]` et les fichiers sont sous `intelligence/` — mais `details.workspace: /Users/Yugz/Projets/Cortex`. Diagnostic (trace relue en lecture seule le 2026-09-07) : `last_activity_at` de la session vaut `08:47:25.998428`, qui est l'horodatage d'un `file_changed` **dans Cortex** (`electron.vite.config.…`, premier événement du travail suivant) que la reconstruction du jour a absorbé dans work-4 par la règle de proximité temporelle. `summarize_session` lit `GET /context?at=<last_activity_at>` ; à cet instant précis, `_select_current_session` de Core rend une session **ouverte** dans Cortex (work-5, `projects: ["Cortex"]`) et `workspace.resolution: "session"` suit cette session — alors qu'à `at − 1 s`, la session courante est bien work-4 et le workspace Pulse. `details.workspace` vient de ce `context.workspace.path` ; `structured.project` vient du modèle, qui lit la vue. Les deux routes de Core ne s'accordent donc pas sur l'appartenance de l'événement frontière (même famille que le défaut 1 de l'audit 2026-09-06 : `is_open` selon la route lue), et Intelligence prend le workspace de l'instant sans vérifier qu'il est celui de la session résumée. Aucune donnée n'a été modifiée : le résumé émis reste tel quel, `input_hash` compris.

**Correction proposée (Intelligence, ou Core — les deux sont ouverts depuis le 2026-09-09) :** dans `summarize_session`, ne retenir `context.workspace.path` que si `context.current_session.id == session.id` (ou si `workspace.resolution` n'est pas `"session"`) ; sinon omettre `details.workspace` (champ optionnel) et l'écrire sur stderr. Variante : lire le contexte à `last_activity_at − 1 µs`, comme la capture du corpus le fait à fin − 1 s — mais cela change l'`input_hash` de tous les résumés à venir pour un cas frontière. Côté Core (correctif, pas de changement de contrat) : à `at == last_activity_at` d'une session close, `_select_current_session` devrait rendre cette session, cohérente avec `/context/sessions`. Le résumé de `1f931a43` n'est pas à réécrire : une régénération sous la même identité serait refusée (409), et le champ n'entre pas dans la reprise.

**Déclencheur:** validation de la correction par l'utilisateur ; ou un second cas de workspace incohérent.

**Effort:** S
**Priority:** P2
**Depends on:** —

### Conserver la sortie brute d'une tentative rejetée

**What:** Quand `parse_model_output` rejette une sortie, il ne reste que le
message du validateur dans `run.log` et un compteur dans `state.json`
(`failures`). La sortie du modèle n'est conservée nulle part : le diagnostic
exige un rejeu (`summarize --dry-run`), donc une nouvelle génération, sur une
entrée qui peut avoir changé. Cas du 2026-09-12 : `057a0f5602f4f62e`
(work-5 du 11), rejet `central_files: config.yml absent de l'entrée`, contenu
produit inconnu. À décider : où la garder (`run.log`, `state.json`, fichier
hors dépôt) et combien de temps, en tenant compte de ce qu'une sortie rejetée
n'est pas rédigée par Core.

**Effort:** S
**Priority:** P2
**Depends on:** Aucun

### `central_files` n'accepte que les faits `file`

**What:** `input_paths` ne retient que les chemins des faits `file` de la
ligne de temps. Un chemin littéralement présent dans un fait `command`
observé (`cat config.yml`, `git add config.yml`, work-5 du 2026-09-11) n'est
donc pas admissible dans `central_files`, alors que le modèle l'a lu dans
l'entrée. Le workspace n'était pas surveillé, aucun `file_changed`. À
décider, pas à implémenter : admettre un chemin cité tel quel dans une
commande observée, avec quelle forme (relative au `cwd` de la commande ?) et
quelle garantie contre l'invention.

**Premier cas mesuré sur la forme (benchmark du 2026-09-15, `2ce34456`,
fiche 04).** Aucun fait `file`. Gemma cite `devops_culture_git/README.md`,
écrit tel quel dans o14 (`git add README.md devops_culture_git/README.md`),
bloc lancé depuis `…/holbertonschool-devops-formation/devops_culture_git` et
terminé en code 1, sortie non collectée.

- Forme littérale, rejouée sans modèle : la sortie passe, point `open` faux
  compris (il décrit o10 en citant o14). Résolu depuis le cwd de o14, le
  chemin désigne `…/devops_culture_git/devops_culture_git/README.md`,
  qu'aucun fait de la session ne montre ; le `README.md` créé par o6 est
  `…/devops_culture_git/README.md`, que le même texte désigne lu depuis le
  dossier parent (cwd de o4 et o5). La forme littérale admet donc un chemin
  qui, résolu là où la commande tourne, ne correspond à rien d'observé.
- Le fichier existe : o6 le crée (`touch README.md`, code 0, cwd
  `…/devops_culture_git`). La vue n'a aucun fait `file` parce que le watcher
  n'a rien remonté ce jour-là : aucun événement `file_changed` le 2026-08-22,
  pour aucun chemin. C'est donc la forme du chemin qui est en cause, pas son
  existence.
- Forme relative au cwd : non rejouée. Elle écarte ce chemin si la citation
  du modèle doit égaler le chemin résolu, pas si la citation est elle-même
  résolue depuis le même cwd.
- Ministral cite aussi `devops_culture_git/0-environment.md` (même bloc, même
  cas) et `README.md`, qui, résolu depuis ce cwd, désigne le fichier de o6.

Détail et rejeu : `docs/decisions/2026-09-14-benchmark-modeles-en-local.md`.

**Effort:** S
**Priority:** P3
**Depends on:** Décision sur l'admissibilité

### Citation de `command_failure` non littérale

**What:** Sur 02 o41 (rejeu v7-superseded), le point `command_failure`
réécrit la commande citée : `git add . && git commit -m "…" && git push`
alors que le fait contient trois lignes sans `&&`. La fiche juge la
citation réécrite nuisible telle que produite. `recorded_statement` exige
une citation littérale du message de commit ; `command_failure` n'exige
rien du texte. À décider : exiger la citation exacte de la commande (ou de
sa première ligne utile) comme pour `recorded_statement`, ou rendre la
commande par le validateur et non par le modèle.

**Cas mesurés au benchmark du 2026-09-15** (prompt v7, `eval/observed`,
`docs/decisions/2026-09-14-benchmark-modeles-en-local.md`) : quatre points
`command_failure` valides dont le texte dit plus que la preuve, deux de
Gemma 4 26B-A4B, deux de Qwen3.8-27B. La vérification est symétrique : elle
ne départage pas les modèles. Familles déjà relevées par l'audit du
2026-09-09 (`OMISSIONS.md` E02 à E04, `COLLECTE.md`).

- **Exemple type — Gemma, `8faf4569` (fiche 02), o41** : « Échec de la
  commande git commit (exit code 128) ». Le code 128 porte sur le bloc entier
  (`git add .`, `git commit`, `git push`) ; rien n'attribue l'échec à
  `git commit`. Le texte répond d'avance, et sans preuve, à la question que
  la fiche 02 jugeait utile (« la sérialisation des scans a-t-elle été
  committée ? »). Famille E03 (échec de bloc changé en échec certain de
  commit, déjà vu sur 04 o14), localisation arbitraire que `COLLECTE.md`
  citait sur o41.
- **Qwen, `8faf4569`, o41** : le bloc cité avec des `&&` qu'il ne contient
  pas, cas d'origine de cette entrée (E04) ; fiche 02 : « utile comme
  question, nuisible tel que produit ».
- **Gemma, `d047b37b` (fiche 06), o34** : « Les commandes de migration
  échouent systématiquement avec des codes de sortie différents (127, 2) »,
  o34 seule en preuve (code 2) ; le 127 est celui de o33, non cité. Recoupe
  « Préfixe d'interpréteur » (06 o33/o34). La fiche 06 tient pour
  information n°1 que la migration a vraisemblablement abouti par une autre
  voie.
- **Qwen, `d047b37b`, o33** : « a échoué avec le code 127 (commande non
  trouvée) » ; commande citée exactement, interprétation du 127 ajoutée
  (E02), « juste ici, mais non collectée » selon la fiche 06.

Trois textes réécrivent ou débordent la commande citée ; le quatrième la cite
exactement et ajoute une interprétation, qu'une exigence de citation
littérale n'attraperait pas.

**Effort:** S
**Priority:** P2
**Depends on:** Décision v7 du 2026-09-12 (limite connue)

### Clause cwd de `superseded_observed` trop stricte (cas 04 o7)

**What:** Un échec n'est dépassé que par un succès similaire dans le même
cwd connu. Sur 04, `bash check-setup.sh` échoue en 127 dans un répertoire
(mauvais dossier) puis réussit dans un autre : l'échec reste
`unresolved_observed`, citable, et v7 le cite ; la fiche le juge nuisible.
Relâcher la clause risque de clore un échec par un succès sans rapport. À
décider sur des cas réels : même dépôt (`git_root`) plutôt que même cwd,
ou description dans le prompt.

**Effort:** S
**Priority:** P3
**Depends on:** Cas réels sous v7

### Reports au backlog dans les messages de commit cités comme points (09)

**What:** v7 cite en `recorded_statement` des phrases de commit qui sont
des reports (« le build Swift n'est pas dans la CI pour l'instant »,
« authentification des producteurs locaux reportée ») : justes, inutiles à
la reprise selon la fiche 09. Un report explicite n'est pas un point
ouvert de la session. À décider : décrire la distinction dans une version
ultérieure du prompt, ou l'accepter comme bruit borné (deux points max).

**Effort:** S
**Priority:** P3
**Depends on:** Jours réels sous v7

### Préfixe d'interpréteur : deux clés pour une même commande (06 o33/o34)

**What:** `manage.py migrate` (127) puis `python3 manage.py migrate` (2),
17 s d'écart, même cwd : deux clés dans `command_outcomes`, deux points
`command_failure`, la fiche juge le premier nuisible (doublon). La
similarité de #89 compare la tête de commande, qu'un préfixe
d'interpréteur change. À décider : normaliser la tête (`python3`, `bash`,
`node`, `sh` suivis d'un script), ou décrire le doublon dans le prompt.

**Effort:** S
**Priority:** P3
**Depends on:** Décision v7 du 2026-09-12 (question ouverte)

### Garde-fous de source pour `schema_version` et `observation_version`

**What:** `test_known_version_matches_core_code` lit `RECONSTRUCTION_VERSION`
dans la source de Core et fait échouer la CI si `KNOWN_RECONSTRUCTION_VERSION`
ne suit pas (ce qui a rattrapé le passage à 4 le 2026-09-12). Rien
d'équivalent pour les deux autres contrats consommés : `EXPECTED_SCHEMA_VERSION`
(`core_client.py`, 3) n'est vérifié qu'à l'exécution, en refusant une réponse
d'un autre schéma que 2 ou 3, jamais contre `context_snapshot.SCHEMA_VERSION` ;
`observation_version` n'a aucune constante côté Intelligence, la valeur servie
est recopiée dans les résumés sans être comparée à `work_observations.OBSERVATION_VERSION`
(passée de 1 à 2 le 2026-09-12 sans qu'aucun test Intelligence ne le voie).
À décider : un test de source par contrat, sur le modèle du premier, et une
constante `KNOWN_OBSERVATION_VERSION` annoncée comme la reconstruction.

**Effort:** S
**Priority:** P2
**Depends on:** Aucun

### Résumés dans la journée

- **Besoin :** reprendre après une bascule de projet ou une pause, sans attendre le lot du matin.
- **Piste retenue d'abord :** déclencheur à la fermeture de session, puis benchmark de petits modèles sous v7 (9B, Qwen3-4B-Instruct-2507, Qwen3.5-4B, Qwen3.5-2B) à entrée inchangée.
- **Piste écartée pour l'instant :** état continu mis à jour par patches (brouillons, révisions), tant que la fermeture de session n'a pas montré ses limites.

**Effort:** M
**Priority:** P3
**Depends on:** Aucun

### `run.log` n'écrit ni `prompt_version`, ni modèle, ni sessions écartées

- **Constat (jour 13, 2026-09-17) :** un passage `run` n'écrit que la ligne de compteurs et les `created`. Pour vérifier un lot, `prompt_version` et modèle se lisent dans les événements Core, et les sessions écartées (id, durée, activités, commit ou non) ne se retrouvent qu'en rejouant le classement à l'heure du lot.
- **À décider :** une ligne d'en-tête par passage (`prompt_version`, `model_id`) et une ligne par session écartée avec sa raison, comme `list` les donne déjà.

**Effort:** S
**Priority:** P3
**Depends on:** Aucun

### Exposer au modèle les titres de terminal (noms de session Claude Code), pas toutes les fenêtres

- **Constat (jour 15, 2026-09-19) :** les faits `window` sont masqués au modèle par `FACT_KINDS_HIDDEN_FROM_MODEL` (`session_input.py`, addendum du 13 : 85 % des tokens d'une session refusée). Sur les 11 résumés v7 du lot du 19, le titre du terminal portait l'objectif de la session en work-16 et work-17 (« Codex sessions et tâches en cours », le nom de la session Claude Code), et les fenêtres faisaient l'essentiel de work-10 (28 sur 51 faits), work-11 (PR gstack lues) et work-12 (réunion Zoom) ; aucun résumé ne peut le dire.
- **À faire :** n'exposer que les titres de terminal débarrassés du spinner et de la taille (le nom de session Claude Code, `Pulse — Codex sessions et tâches en cours`), dédoublonnés, pas les autres fenêtres ; version d'entrée et prompt qui les décrit.
- **Quand :** pas avant la fin de l'évaluation v8 (premier lot le 20), pour que la comparaison v7/v8 reste à entrée égale.

**Effort:** M
**Priority:** P2
**Depends on:** Fin de l'évaluation v8

### Marquer « veille » une durée de génération quand horloge murale et `CLOCK_UPTIME_RAW` divergent

- **Constat (jour 15, 2026-09-19) :** `generation_ms` mesure l'horloge murale ; un lot parti dans un DarkWake sur batterie y met le temps de veille (3 h 06 et 1 h 19 le 19 pour deux sessions calculées en quelques minutes). Le journal l'a d'abord lu comme deux générations anormales ; seule la lecture de `pmset -g log` a tranché. La [décision du 15](../docs/decisions/2026-09-15-compteur-etape-4-veille-du-mac.md) demande de marquer ces durées non significatives, à la main.
- **À faire :** mesurer chaque génération sur deux horloges, `time.monotonic()` (`CLOCK_UPTIME_RAW` sur macOS, arrêtée pendant la veille) et l'horloge murale ; quand elles divergent au-delà d'une tolérance, écrire `generation_ms` avec un indicateur `slept` (ou la durée de veille) dans `details`, et le dire dans `run.log`. Le détail est un ajout de champ dans `details` : version des observations inchangée, à vérifier.
- **Contexte :** la [garde du 19](../docs/decisions/2026-09-19-lot-capot-ouvert-batterie.md) évite le départ en DarkWake ou capot fermé ; le marquage couvre ce qu'elle laisse passer (source illisible, veille en cours de lot).

**Effort:** S
**Priority:** P2
**Depends on:** Aucun

### Intelligence n'a ni VERSION ni CHANGELOG, rien ne relie un lot à une version

- **Constat (2026-09-17) :** `__version__` et `pyproject.toml` disent `0.1.0` depuis l'origine ; aucun fichier VERSION, aucun CHANGELOG. La valeur part pourtant dans chaque résumé (`producer.version`), identique pour tous : elle ne distingue ni le correctif des sessions courtes à commit (#98), ni celui de la citation des points `open` (#106), dont l'effet ne vaut que pour les résumés à venir. Avec l'install éditable, un lot exécute le code du checkout à l'heure du lot : le 17, c'était celui d'une branche expérimentale, et seul le recalcul des `input_hash` a montré que v7 n'en était pas affecté.
- **À décider :** une version qui bouge avec le comportement (au moins à chaque changement de ce qui est émis), un CHANGELOG sur le modèle de Core, et ce que le lot en écrit dans `run.log` ; voir l'entrée « `run.log` n'écrit ni `prompt_version`, ni modèle, ni sessions écartées » ci-dessus, et côté Core « Core n'expose sa version nulle part » (`core/TODOS.md`) : même manque, des deux côtés.

**Effort:** S
**Priority:** P3
**Depends on:** Aucun

## Completed

### Une session qui porte un commit est écartée pour sa durée (cas `dd06e6c8`, 2026-09-15)

**What:** `classify` écarte une session close quand `duration_minutes` est
sous `min_session_minutes` (10) **et** `activity_count` sous
`min_session_activities` (30), seuils du §7 de la spec du 2026-09-03, sans
regarder ce qu'elle contient. Le 2026-09-15, work-9 `dd06e6c8`
(14:59:51–15:03:37, 3 min, 20 activités) se termine sur le commit 86c0348, le
verdict du benchmark de modèles ; work-10 `8069a1f4` (15:04:14–15:04:49,
0 min, 5 activités) porte 626bbad, la règle du compteur de l'étape 4. Les
deux décisions durables de la journée n'ont aucun résumé, alors que six
sessions de documentation courante en ont un. À décider : un fait
`git_commit` rend la session candidate quelle que soit sa durée, ou un seuil
séparé pour les sessions à commit. Mesurer d'abord combien de sessions
courtes à commit le lot écarterait et ce que v7 en ferait : une session de
5 activités donne peu à `doing`.

**Déclencheur:** jour 12 du dogfooding (`docs/dogfooding.md`), cas
`dd06e6c8` et `8069a1f4`.

**Effort:** S
**Priority:** P2

**Résolution:** `classify` n'applique plus les deux seuils à une session qui
porte au moins un commit observé (fait `commit` de la chronologie du schéma 3,
ou `git.commits` d'une vue héritée) : elle est candidate quelle que soit sa
durée. Pas de seuil séparé, pas de mesure préalable sur le lot : le correctif
ne rend candidates que des sessions qui contiennent une décision durable, et
v7 fera de leurs cinq activités ce qu'il peut. Deux tests de régression sur
les formes réelles de `dd06e6c8` (3 min, 20 activités) et `8069a1f4` (0 min,
5 activités). Le journal de Core (`_absence_status`) garde la règle sans
l'exception : il classe encore ces sessions « sous les seuils » (cf. README §1).

**Completed:** 2026-09-16

### Le corpus `eval/` ne porte aucune session à `previous_summary`

**What:** Aucune des dix sessions gelées n'avait d'annexe `previous_summary` : la consigne du prompt v2 sur la réévaluation de `open` (défaut D1) n'était mesurable qu'à l'œil sur le dogfooding.

**Résolution:** Deux sessions réelles ajoutées à `eval/corpus/`, hors gel (champ `added = "2026-09-06"`, les dix d'origine restent la référence) : `1e420dda8b6eee77` (cas D1 du jour 1) et `eef4956b36dd37ce` (cas D1 du jour 2). Contexte pris à fin − 1 s pour contourner le piège de capture (le résumé de la session elle-même masque le précédent) ; règle notée dans `eval/README.md`. L'entrée de `eef4956b` reproduit l'`input_hash` du résumé v2 émis.

**Completed:** 2026-09-06

### CI rouge : cinq tests de CLI dépendaient de la date du jour

**What:** Les vues rejouées par le faux Core sont ancrées sur `REFERENCE = 2026-09-02 16:00 UTC` et la fenêtre de sélection vaut « aujourd'hui plus la veille » (`lookback_days = 1`). La CLI lisait l'heure réelle, donc la suite passait le jour où elle a été écrite puis échouait deux jours plus tard : le 2026-09-05, `list`, `summarize --dry-run`, `run --once`, `show <id>` et le test de permissions ne trouvaient plus aucune session close. Vert sur ce commit exact le 2026-09-03, rouge le 2026-09-05, sans qu'une ligne de code ait bougé.

**Résolution:** L'horloge est gelée, pas les fixtures — décaler les dates n'aurait reporté la panne que de quelques mois. La couture d'injection existait déjà sous la CLI (`lookback_days`, `classify_sessions`, `find_session`, et `run_pass` qui accepte `now` depuis toujours) ; seule `cli.py` lisait l'heure en quatre endroits, dont un qui ne la transmettait pas à `run_pass`. Tout passe désormais par `cli._now()`, et les tests le remplacent par une fixture autouse ancrée sur `at(120)`. Ni freezegun ni dépendance nouvelle. Suite Intelligence à 62.

**Completed:** 2026-09-05
