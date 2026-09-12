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

## Completed

### Le corpus `eval/` ne porte aucune session à `previous_summary`

**What:** Aucune des dix sessions gelées n'avait d'annexe `previous_summary` : la consigne du prompt v2 sur la réévaluation de `open` (défaut D1) n'était mesurable qu'à l'œil sur le dogfooding.

**Résolution:** Deux sessions réelles ajoutées à `eval/corpus/`, hors gel (champ `added = "2026-09-06"`, les dix d'origine restent la référence) : `1e420dda8b6eee77` (cas D1 du jour 1) et `eef4956b36dd37ce` (cas D1 du jour 2). Contexte pris à fin − 1 s pour contourner le piège de capture (le résumé de la session elle-même masque le précédent) ; règle notée dans `eval/README.md`. L'entrée de `eef4956b` reproduit l'`input_hash` du résumé v2 émis.

**Completed:** 2026-09-06

### CI rouge : cinq tests de CLI dépendaient de la date du jour

**What:** Les vues rejouées par le faux Core sont ancrées sur `REFERENCE = 2026-09-02 16:00 UTC` et la fenêtre de sélection vaut « aujourd'hui plus la veille » (`lookback_days = 1`). La CLI lisait l'heure réelle, donc la suite passait le jour où elle a été écrite puis échouait deux jours plus tard : le 2026-09-05, `list`, `summarize --dry-run`, `run --once`, `show <id>` et le test de permissions ne trouvaient plus aucune session close. Vert sur ce commit exact le 2026-09-03, rouge le 2026-09-05, sans qu'une ligne de code ait bougé.

**Résolution:** L'horloge est gelée, pas les fixtures — décaler les dates n'aurait reporté la panne que de quelques mois. La couture d'injection existait déjà sous la CLI (`lookback_days`, `classify_sessions`, `find_session`, et `run_pass` qui accepte `now` depuis toujours) ; seule `cli.py` lisait l'heure en quatre endroits, dont un qui ne la transmettait pas à `run_pass`. Tout passe désormais par `cli._now()`, et les tests le remplacent par une fixture autouse ancrée sur `at(120)`. Ni freezegun ni dépendance nouvelle. Suite Intelligence à 62.

**Completed:** 2026-09-05
