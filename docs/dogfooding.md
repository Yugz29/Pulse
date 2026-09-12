# Dogfooding — résumé de session (pas 3)

Journal du dogfooding du modèle local (`Qwen3.8-27B-4bit`, décision
[2026-09-06](decisions/2026-09-06-modele-local-qwen.md)). Un jour par entrée :
les reprises lues et jugées, les défauts trouvés. Critère de sortie (spec du
2026-09-03, §12) : au terme de cinq jours, **quatre reprises sur cinq jugées
justes et utiles** → service résident (étape 5) ; sinon on itère le prompt ou le
modèle sur le corpus `eval/`, et le service attend.

## Point d'état — 2026-09-09

Vérification du dépôt à `8c282e2`, des commits récents, du code et de l'état
local, sans génération de modèle ni modification de configuration.
**Verdict : socle opérationnel ; reprise v5 livrée mais utilité encore à
valider.**

- Core tourne, watchers fichiers/apps et worker actifs ; outbox : 0 pending,
  0 dead-letter. Le producteur d'agents est périodique (une heure), dernier
  code de sortie 0 ; son absence de processus entre deux passages est normale.
- La config personnelle épinglait `prompt_version = "v3"` (ligne retirée le
  09 à 21:25, jour 5 : le défaut du code s'applique). Le constructeur
  courant produit l'entrée v3, qui exige le prompt v5 ou v6 (défaut v6
  depuis la PR #83). Le journal du 09 à
  06:45 confirme 10 candidates refusées, 0 nouveau résumé et 1 pending rejoué
  comme doublon ; launchd rapporte le code 3. Le 08, le lot avait été interrompu
  par un timeout Core après deux créations. La collecte Core reste active.
- Tests exécutés : Core **598 réussis** ; Intelligence **261 réussis,
  8 tests MLX exclus**. Le premier essai Intelligence était bloqué par les
  sockets du bac à sable ; le rejeu avec accès aux serveurs locaux passe.
  Aucun nouveau jugement de modèle : les 14/14 valides et 2/4 attentes
  humaines de la v5 restent les résultats historiques du dernier rejeu.
- Suite recommandée : essai v5 contrôlé avec relecture avant reprise du lot
  quotidien ; commencer par quelques cas utiles des fiches existantes pour
  juger rappels et omissions, puis décider du format de reprise. Service
  résident, mémoire sémantique et proactivité restent des étapes ultérieures.

Rejeu technique : depuis `core/`, `.venv/bin/python -m pytest tests_v2 -q`
et `make status` ; depuis `intelligence/`, `.venv/bin/python -m pytest -q`.
État opérationnel : `~/.pulse_intelligence/config.toml`,
`~/.pulse_intelligence/logs/run.log` et `launchctl print` pour les jobs Pulse.

## Reprise — état historique à la fin du 2026-09-07

**Reprise au 2026-09-11 au soir (ajout du jour 7).** Core de production
redémarré à 20:48:19 (`launchctl kickstart -k gui/501/com.pulse.daemon`,
pid 51875, code de main) : `GET /context` sert `schema_version 3`. Le
jugement suivant se fait sur le **lot launchd du 2026-09-12 à 06:30**, pas
sur une requalification des fiches 15 à 18 ni sur un v7 : chaque résumé
créé devra porter un `input_hash` différent des cinq résumés v6 émis
depuis l'entrée héritée (1eb35865 `5707e25d…`, a1040f4f `60757890…`,
f8aab73b `b06105c1…`, 32ca64e5 `2a93c8bd…`, d283f6dd `00f5198c…`), et
son entrée devra contenir `observations` et non `legacy_aggregates`.
`open` reste attendu vide sous v6 (gabarit `"open": []`, jour 7) ; ce
n'est pas le critère de demain.

**Clôture du 2026-09-11, 22:00.** Mergées le soir : #85 (repli sur la vue
héritée bruyant, code de sortie 6), #86 (`make status` écrit STALE), #88
(prompt v7 enregistré, v6 reste le défaut), #87 (journal Swift horodaté).
Observateur reconstruit et réinstallé, daemon, outbox-worker et
file-watcher relancés sur le code mergé, `make status` sans STALE.
Mesures hors dépôt dans `corpus/docs/audits/2026-09-11-rejeu-open/` :
`v7-corpus/` (14/14 valides, 13 points : 9 `command_failure`, 4
`recorded_statement`) et `v7-superseded/`. **PR #89 poussée sans merge** :
état net des commandes, `superseded_observed` avec `superseded_by` dans
`command_outcomes`, validateur inchangé sur `unresolved_observed`. Mesure
v7-superseded conforme à l'attendu : 4 disparitions (03 : o16→o17,
o20→o23, o22→o23 ; 04 : o10→o11), 9 points restants dont 5
`command_failure` (04 : o7, o14 ; 02 : o41 ; 06 : o33, o34) et 4
`recorded_statement` (13 : o20 ; 09 : o194, o195 ; 14 : o19). Sans verdict.
Deux questions ouvertes pour la revue de #89 : filtrer les
`superseded_observed` de l'entrée du modèle ou les décrire dans un v7.1 ;
le doublon d'interpréteur en 06 (`manage.py migrate` puis `python3
manage.py migrate`, deux points pour un même échec).

**Ordre de demain, 2026-09-12.** Lot launchd de 06:30 (critère ci-dessus)
→ jour 8 → revue et merge de #89 → jugement des 9 points restants contre
les fiches → requalification des fiches 15 à 18 → décision v7.

**Reprise au 2026-09-12 (ajout du jour 8).** Lot de 06:30 jugé : premier
lot à entrée schéma 3, **3/3 vraies, 0/3 utiles**, `open` vide 3/3 ;
verdicts et compteur dans « Jour 8 » en fin de journal.

**Décision v7, 2026-09-12 (après-midi).** Jugement des 9 points
`v7-superseded` contre les fiches d'adjudication : **4 justes et utiles**
(14 o19 ; 04 o14 ; 02 o41, avec citation réécrite ; 13 o20, mineur),
**1 à moitié** (06 o34, manque « la base a changé après »), **2 justes
inutiles** (09 o194 et o195 : reports au backlog cités comme points),
**2 nuisibles** (04 o7 : dépassé par un succès dans un autre cwd ; 06 o33 :
doublon d'interpréteur). Aucun point inventé. Fiches 15 à 18 : jugées sur
entrée schéma 2, invalides. **Décision : v7 activé tel quel**
(`prompt_version = "v7"` dans la config de production, le défaut du code
reste v6), les deux nuisibles restent des limites connues à observer sur les
jours réels. #89 mergée : les `superseded_observed` ne sont pas filtrés de
l'entrée, visibles pour `doing`, non éligibles pour `open`. Note :
[`decisions/2026-09-12-prompt-v7.md`](decisions/2026-09-12-prompt-v7.md).
**Le compteur de l'étape 4 repart au premier lot v7 à entrée schéma 3, Mac
éveillé.**

**Clôture du 2026-09-12, 15:10.** Mergées en rebase, CI verte à chaque
étape : #90 (contexte de fenêtre `window_focused`, Core 0.7.0.0), #91
(tests de réentrance de `observe(_:)`, entrée TODOS close), #92 (seuil
avant split, `reconstruction_version` 4, Core 0.8.0.0,
`KNOWN_RECONSTRUCTION_VERSION` 4 côté Intelligence). Prod sur `main`
depuis 15:02 : daemon, worker, file-watcher et observateur relancés,
`make status` sans STALE, `GET /context` en schéma 3,
`observation_version` 2, `reconstruction_version` 4 sur les vues servies.
v7 actif (`prompt_version = "v7"` en config). Contexte de fenêtre en
production avec l'autorisation Accessibilité, normalisation du titre avant
dédoublonnage et filet de 30 s par application (31 `window_focused` sur
15 minutes d'usage réel, Terminal 4) ; domaines de messagerie web refusés
à l'ingestion. GitNexus réindexé.

**Prochaine étape : lot du 2026-09-13 à 06:30**, premier lot v7 à entrée
schéma 3 et reconstruction 4 → jour 9, premier jour du compteur.
Chantiers suivants décidés, non commencés : règle « même `git_common_dir`
= même projet », puis état net par chemin.



**Convention.** Un « jour » de dogfooding est une **date civile**, jugée à la
reprise du matin suivant : le lot launchd de 06:30 résume les sessions de la
veille, on les lit et on les juge dans la journée. Le 2026-09-06 est le
**jour 2 étendu** (jours 1 et 2 dans la nuit, jugements, `show`, corpus dans
la journée). Le **jour 3 = 2026-09-07**, après le passage launchd de 06:30.

**Où on en est (fin du 2026-09-07).**

- Jours 1, 2 et 3 faits : 7/7, 8/8 puis **13/13** résumés créés sur la trace
  réelle, tous jugés. Cumul `doing`/`stopped_at` **23/23** ; `open` juste
  2/22 (0/13 au jour 3). Le jour 3 requalifie D1 : pas une recopie, un
  **report sans réévaluation d'un point que la vue ne peut pas clore** (le
  push), qui fait boule de neige sur les enchaînements. D3, D4, D5 et le cas
  `created` ∩ `deleted` réapparaissent tous malgré la consigne v2.
- **`prompt_version = "v3"` activé le 2026-09-08 à 00:24** (config de
  dogfooding, sauvegarde `config.toml.bak-v2-2026-09-08`), après le merge
  de la PR #77 (D6). `llm_provider = "mlx"`, `Qwen3.8-27B-4bit` inchangés.
- **Un seul v3 désormais.** La PR #54 (v3.1 textuelle, CONFLICTING, 115
  fichiers derrière main) est **fermée comme remplacée** par le v3 de main
  (7865f0f : schéma `open` typé `observed` / `carried_over` / `requested`,
  validateur, attentes annotées), qui reprend ses quatre consignes. Le v3 de
  main est arrivé par commits directs sur main, sans PR — écart de process
  assumé et consigné au jour 3.
- **D6 corrigé (PR #77, mergée à 00:20).** Dry-run v3 sur les 13 sessions
  du lot : D5 et D4 à zéro, D3 déclaré en `requested` mais faux sur le fond
  dans 4 fiches, et un gabarit D6 — « fichier modifié et aucun commit de la
  session ne le nomme » — contredit par git dans 20 points sur 27. Le
  validateur rejette désormais ce point dès que la session montre un commit ;
  sur le corpus, le gabarit passe de 9 sorties sur 14 à 2, toutes deux sur
  des sessions sans commit, au prix de 2 rejets (12/14 valides).
- launchd a tiré à **06:42** sur un DarkWake batterie, le Mac s'est rendormi
  2 s après : premier résumé « généré » en 2 h 40 d'horloge, lot complet à
  09:32 au réveil. La fenêtre 06:30 n'est nominale que Mac éveillé.

**Jour 4 (2026-09-08), dans l'ordre.**

1. Lot launchd de 06:30, **premier passage v3**. `list` à 00:25 donne
   4 candidates, toutes du 07 (`lookback_days = 1`, les sessions du 06 sont
   sorties de la fenêtre) : `5accd3c0` et `3e9fee12` régénérées **sans
   annexe** (deuxième résumé), `78765707` (09:25–09:43) et `d78708a6`
   (23:26–23:51) fraîches, **avec annexe** — plus les sessions closes dans
   la nuit. Premier vrai test de D1 en `carried_over`.
2. Lecture avec `show` : compter les rejets (D6 attrapé = résumé non émis,
   `failed` puis `given_up` — à reprendre par `summarize --retry` après
   retouche), les `requested` faux sur le fond, les `carried_over` et leur
   `reason_kept`. Vérifier `run.log` et l'heure réelle du passage (veille).
3. Jugement de la grille sur le lot ; corpus : geler les cas D6 réels si le
   lot en produit.

**Décisions en attente de moi.**

- Relever ou non `llm_max_input_tokens` ; `eval/out` hors du watcher ; règle
  de préséance entre résumés d'une même session (voir aussi la nouvelle
  entrée « filiation des résumés » d'`intelligence/TODOS.md`) — inchangées.
- Un `checkout main` non expliqué à 23:48:30 le 07 dans le dépôt (reflog),
  pendant l'eval : les deux commits D6 ont d'abord atterri sur `main` local
  et ont été remis sur la branche avant la PR. À élucider si ça se reproduit.

## Jour 1 — 2026-09-06

**`pulse-intel run --once` sur la trace réelle : 7 candidates, 7/7 créées.**
Sessions du 2026-09-05 20:09 au 2026-09-06 00:39.

### Reprises jugées

| session | durée | jugement |
| --- | --- | --- |
| `1e420dda8b6eee77` (work-26) | 88 min | **juste** — `doing`, `stopped_at` et `intents` collent à la session |
| les 6 autres | — | à lire jour 2 |

### Défauts trouvés

**D1 — `open` recopié du résumé précédent, périmé.** Sur `1e420dda`, le `open`
de Qwen reprend celui du `previous_summary` (« PR #28 et migration restent à
vérifier ») au lieu de le réévaluer à la fin de *cette* session — un point clos
depuis des heures. **Cause : le prompt v1.** L'entrée annexe `previous_summary`
(sa `reprise`), mais le prompt v1 ne dit nulle part comment s'en servir ; le
modèle recopie son `open` faute de consigne. → candidat pour la **v2 du prompt**
(voir plus bas), à mesurer sur le corpus avec la consigne sur les sessions sans
fichier, avant activation.

**D2 — `central_files` vide alors que la session a écrit du code.** `1e420dda`
a modifié `provider.py`, `fake.py`, `provider_summarizer.py`… mais la vue de
session ne les portait pas, donc le modèle a rendu `central_files: []` — correct
au vu de son entrée. **Cause en amont : le watcher.** `watched_workspaces` ne
couvrait que `Pulse/core`, pas la racine du repo unique ; les écritures sous
`intelligence/` étaient invisibles. Corrigé à la main (racine ajoutée +
`launchctl kickstart -k`, journal OK, pas de bruit constaté). Ce n'est pas un
défaut du modèle : entrée incomplète, sortie honnête.

### Angle mort du filtre d'ignore (suite de D2)

La racine du repo étant désormais observée, le filtre d'ignore du watcher
(`IGNORED_DIRECTORY_NAMES`) doit couvrir les dossiers d'outillage sous la racine.
Vérifié :

| dossier | couvert ? | par |
| --- | --- | --- |
| `intelligence/.venv` | oui | `.venv` |
| `core/macos_observer/.build` | oui | `.build` |
| `intelligence/eval/out` | **non** | `out` absent du filtre |

`eval/out/` est ignoré par git mais **pas** par le watcher : un futur
`pulse-intel eval` (qui écrit sous `intelligence/eval/out/`, dans l'arbre
observé) générerait du `file_changed` parasite dans la trace — le même symptôme
que `.gitnexus` avant qu'il ne soit ignoré. Sans impact sur le dogfooding, qui
n'utilise que `run`. À traiter : soit ajouter `out` au filtre (changement de
Core, gelé — justification à peser, `out` est un nom générique), soit faire
écrire `eval` hors de l'arbre observé par défaut. Décision reportée, hors lot.

### Mesure du jour 1 — prompt v2 sur le corpus

La v2 ajoute deux consignes à la v1 : `open` réévalué sur la session courante,
jamais recopié de `previous_summary` (D1) ; session sans fichier →
`central_files: []`, avec un exemple à zéro fichier (réserve n°1 de la décision
Qwen). Passage `eval` sur les dix sessions gelées, les deux providers, avant
activation. `fich.` = fichiers modifiés dans la vue ; `cf` = taille de
`central_files` ; `—` = rejeté par le garde-fou.

**Qwen local `Qwen3.8-27B-4bit` — v1 → v2**

| session | fich. | v1 | v2 | cf v1 | cf v2 | note |
| --- | --- | --- | --- | --- | --- | --- |
| `071bbd62` | 2 | ok | ok | 2 | 2 | |
| `247f2062` | 60 | ok | ok | 5 | 5 | confidence medium → high |
| `2ce34456` | 0 | **rejeté** | **ok** | — | 0 | #8 ambiguë → `[]` |
| `3cabaefb` | 60 | ok | ok | 5 | 5 | |
| `6a416635` | 0 | **rejeté** | **ok** | — | 0 | #6 → `[]`, plus de `vite.config.js` inventé |
| `7bbaca78` | 1 | ok | ok | 1 | 1 | |
| `8faf4569` | 25 | ok | ok | 5 | 5 | |
| `cda6ccce` | 29 | ok | ok | 5 | 5 | |
| `d047b37b` | 33 | ok | ok | 5 | 5 | |
| `eb652ce9` | 38 | ok | ok | 5 | 5 | |

Valides **8/10 → 10/10**, aucune perte ; les huit sessions à fichiers gardent
le même compte (moyenne 4,1 → 4,1), 3 à 5 chemins sur 5 identiques entre v1 et
v2, les substitutions restant des fichiers présents dans l'entrée.

**Référence `claude-sonnet-5` — v1 → v2**

| session | fich. | v1 | v2 | cf v1 | cf v2 | note |
| --- | --- | --- | --- | --- | --- | --- |
| `071bbd62` | 2 | ok | ok | 2 | 2 | |
| `247f2062` | 60 | ok | ok | 5 | 5 | confidence medium → high |
| `2ce34456` | 0 | **rejeté** | **ok** | — | 0 | #8 → `[]` |
| `3cabaefb` | 60 | ok | ok | 5 | 5 | |
| `6a416635` | 0 | ok | ok | 0 | 0 | #6 → `[]`, confidence medium → low |
| `7bbaca78` | 1 | ok | ok | 1 | 1 | |
| `8faf4569` | 25 | ok | ok | 5 | 5 | |
| `cda6ccce` | 29 | ok | ok | 5 | 4 | seul cran perdu |
| `d047b37b` | 33 | ok | ok | 5 | 5 | |
| `eb652ce9` | 38 | ok | ok | 5 | 5 | |

Valides **9/10 → 10/10**, aucune perte, moyenne 4,1 → 4,0 — pas de frilosité.

**D1 non mesurable sur le corpus** : aucune des dix sessions gelées ne porte
d'annexe `previous_summary`. Le corpus prouve que la consigne ne dégrade rien ;
elle se juge au jour 2 sur les sessions enchaînées de la journée. Une session
réelle à `previous_summary` est à ajouter au corpus, hors gel
(`intelligence/TODOS.md`).

**Décision : v2 adoptée**, `prompt_version = "v2"` dans la config de dogfooding
à partir du jour 2. Les résumés du jour 1 restent des résumés v1.

### Suite

Jour 2 : lecture des 6 autres reprises, `run --once` sur les sessions du jour
avec la v2 — premier jugement de D1 sur des sessions enchaînées.

## Jour 2 — 2026-09-06

Prompt v2 adopté et activé (PR #48 ; `prompt_version = "v2"` dans la config,
défaut du code aligné par PR #49). **`run --once` : 8 candidates, 8/8 créées**,
Qwen local, 20–47 s par session.

Six des huit sont des **régénérations v2 des sessions du 2026-09-05** — le
changement de `prompt_version` les rend candidates à nouveau (autre `event_id`,
trace append-only, pas de collision ; deux résumés par session coexistent
désormais, voir `intelligence/TODOS.md`). Les deux autres sont les sessions de
la nuit (`a0aacd1f` 00:26–00:39, `eef4956b` 01:29–02:24).

### Reprises v2

| session | durée | `doing` (résumé) | `open` v2 | cf | conf | jugement |
| --- | --- | --- | --- | --- | --- | --- |
| `8af930d9` work-2 (05) | 17 min | état des lieux post-migration | « L'état de la PR #28 et la branche courante n'ont pas été confirmés. » | 0 | low | **à moitié** — `open` = D3 |
| `2808ac8a` work-3 (05) | 13 min | watcher + fichiers privés | « Les modifications sur file_watcher.py et private_files.py ne sont pas committées ni testées. » | 4 | medium | **juste** |
| `eadb7573` work-13 (05) | 12 min | doc et versions Core 0.5.6 | « Le commit n'a pas été poussé ; l'état de la PR #28 reste à vérifier. » | 0 | medium | **à moitié** — `open` = D3 |
| `58874e67` work-20 (05) | 3 min | watcher, privés, Swift | « Les modifications ne sont pas committées. L'état de la PR #28 et la branche courante n'ont pas été vérifiés. » | 5 | medium | **à moitié** — `open` = D3 |
| `d9877899` work-24 (05) | 12 min | tests + horloge de la CLI | « L'état de la PR #28 et la migration du nouveau MacBook Pro M3 Max n'ont pas été confirmés dans cette session. » | 0 | medium | **à moitié** — `open` = D3 |
| `1e420dda` work-26 (05) | 88 min | couche LLMProvider | « Les commits locaux ne sont pas poussés. La divergence list/run sur le modèle est documentée mais non résolue. » | 0 | medium | **juste** |
| `a0aacd1f` work-2 (06) | 13 min | corpus gelé, eval, MLXProvider | « Le push n'a pas été observé ; la configuration de llm_max_tokens et le passage de référence restent à valider. » | 0 | medium | **à moitié** — `open` périmé : commits 7cfb797 et 1e3af23 lus comme points ouverts (**D4**, nouveau) |
| `eef4956b` work-3 (06) | 54 min | garde d'entrée, doc du dogfooding | « Le push n'a pas été effectué ; la configuration de llm_max_tokens et le passage de référence restent à valider. » | 3 | high | **à moitié** — `open` = D1 |

### Bilan des huit

**2 justes, 6 à moitié, 0 faux.** `doing` et `stopped_at` justes **8/8** ;
`open` juste **2/8**. Toutes les erreurs de `open` viennent d'une source lue
sans consigne d'usage : D3 ×4 (annexe `agent_session`), D1 ×1
(`previous_summary`), D4 ×1 (`git.commits`). D4, nouveau : sur `a0aacd1f`, les
commits 7cfb797 (« passage de référence ») et 1e3af23 (« `llm_max_tokens` par
défaut à 2048 ») sont dans la vue, et le modèle en fait deux points « restant
à valider » — le `open` était périmé au moment où il a été écrit.

Mesure : D3 et D4 sont mesurables sur le corpus, qui porte des annexes
`agent_session` et des `git_commit` ; D1 seulement après gel des deux sessions
à annexe (`1e420dda`, `eef4956b`, `intelligence/TODOS.md`).

Décision : **v3 justifiée sur D3 + D4** ; D1 y sera intégré si le lot du 07 le
confirme. **Aucune v3 activée avant lecture du lot launchd du 07 à 06:30** —
un changement de `prompt_version` rendrait les huit candidates à nouveau et
brouillerait le jugement de D1 sur les enchaînements du jour.

### D1 sur du réel — ce que le jour 2 montre vraiment

**Quelle session a reçu une annexe `previous_summary` ?** Vérifié par
`input_hash` (reconstitution de l'entrée avec et sans annexe, hash identique à
celui de l'événement émis) :

| session | annexe pendant le run v2 | pourquoi |
| --- | --- | --- |
| les 6 régénérations du 05 | **aucune** | `GET /context?at=<fin>` rend le résumé **v1 de la session elle-même** (même instant) ; `previous_summary_annex` l'écarte (même id) sans repli sur le précédent |
| `a0aacd1f` (06) | aucune | première de sa journée locale |
| `eef4956b` (06) | **oui** : `a0aacd1f` v2 | seule session enchaînée résumée avec annexe |

Conséquence : **`1e420dda` v2 n'est pas un test de D1.** Son `open` v2
(« commits non poussés ; divergence list/run documentée mais non résolue ») est
juste et réévalué sur la session — mais produit **sans** annexe, là où le v1
(« PR #28 et migration restent à vérifier ») recopiait celle de work-24. Les
deux ne se comparent pas : l'entrée diffère.

**Le seul vrai cas D1 du jour, `eef4956b`, échoue.** Annexe = `open` de
`a0aacd1f` : « Le push n'a pas été observé ; la configuration de
`llm_max_tokens` et le passage de référence restent à valider. » Sortie v2 :
« Le push n'a pas été effectué ; la configuration de `llm_max_tokens` et le
passage de référence restent à valider. » — recopie à un mot près. La vue de
la session montrait pourtant autre chose : `session_summary_v2.md` créé,
`docs/dogfooding.md`, la spec et `TODOS.md` modifiés, aucun commit. Un `open`
réévalué aurait dit « prompt v2 écrit, ni mesuré ni commité ». Circonstance
atténuante : rien dans la vue ne montre les deux points précédents *traités*
(`config.toml` et les sorties d'`eval` vivent hors de l'arbre observé), donc
la consigne « si traité, ne le répète pas » n'avait pas prise — mais la
consigne « réévalue sur les faits de cette session » n'a pas été suivie. **D1
n'est pas réglé par la v2 seule** ; un cas, à confirmer au jour 3 sur d'autres
enchaînements.

### D3 — l'annexe `agent_session` porte la demande initiale, pas l'état

« L'état de la PR #28 … reste à vérifier » apparaît dans le `open` de quatre
sessions du 05 (`8af930d9`, `eadb7573`, `58874e67`, `d9877899`), **sans**
annexe `previous_summary`. Source : l'annexe `agent_session`, dont le `summary`
est le **premier prompt** de la session d'agent (« … Peux-tu vérifier : 1. État
git : la PR #28 … est-elle mergée ? … »), attachée à chaque session de travail
qui la chevauche (16:01 → 21:30 UTC, toute la soirée). Le modèle lit une
question posée à 18:00 comme un point encore ouvert à 22:00. Ce n'est pas D1
(pas de recopie de `open`), c'est le même mécanisme un cran plus haut : une
annexe sans consigne d'usage. Candidat pour une **v3** du prompt (« la demande
initiale de l'agent n'est pas ce qui reste ouvert »), à mesurer sur le corpus —
qui, lui, porte des annexes `agent_session`.

### Fausse alerte Core — le commit « postérieur » ne l'était pas

Première lecture : `eef4956b` (close à 02:24) portait dans `session.git.commits`
le commit `1dc191e` (prompt v2), que je croyais fait le matin. Vérifié dans la
trace (`git_commit`, `occurred_at 2026-09-06T02:22:52+02:00`, `recorded_at`
trois secondes plus tard par le hook) : le commit date de **02:22:52, dans la
fenêtre de la session**. La reconstruction est juste, le `stopped_at` du modèle
(« Après le commit 1dc191e (prompt v2), sans push observé ») aussi. L'erreur
était sur l'heure du commit, pas dans Core. Rien à consigner dans
`core/TODOS.md`.

### Décisions du jour 2

- **Pas de bug Core** : l'alerte « commits postérieurs absorbés par la dernière
  session close » était une erreur d'horodatage de ma part (voir ci-dessus) ;
  rien n'entre dans `core/TODOS.md`.
- **D1 + D3** : candidats groupés pour une **v3** du prompt, mais rien ne
  s'écrit avant le jour 3 — un cas ne fait pas une statistique.
- **D1 est en partie un problème de périmètre d'observation**, pas seulement de
  prompt : `~/.pulse_intelligence/config.toml` et les sorties d'`eval` vivent
  hors de l'arbre observé, donc la vue de `eef4956b` ne pouvait pas montrer les
  deux points précédents comme traités. Un `open` réévalué sur ce que la vue
  montrait aurait quand même été meilleur, mais la consigne « si traité, ne le
  répète pas » n'a rien à quoi s'accrocher quand le travail est invisible.

### Suite du jour 2 (matin)

**`1f931a43` (work-4 du 06, 09:44–10:47, résumée à 11:15 par un `run --once`
manuel) : à moitié.** `doing` et `stopped_at` justes — **10/10 cumulé** sur
ces deux champs. `open` réévalué sur la session, sans recopie du `open` de
`eef4956b` reçu en annexe : **D1 réussi** sur ce cas, soit en réel 1 recopie
(`eef4956b`) pour 1 réévaluation (`1f931a43`). Mais deux points faux dans le
`open` :

1. **« Les scripts launchd ont été créés puis supprimés ; leur statut final
   est incertain. »** Trace : créés 10:03, supprimés 10:13:48 (6 s après le
   commit b2fbfe3 sur `ship/intelligence-launchd`, retour sur `main` qui ne
   les portait pas encore), recréés 10:21:23 (rebase, puis PR #50), modifiés
   jusqu'à 10:28. En fin de session les scripts existent. La vue de Core rend
   `files.created`, `files.modified`, `files.deleted` comme trois listes
   cumulées, sans ordre ni heure par fichier : une bascule de branche y
   ressemble à une suppression. Défaut de la vue, pas du modèle — famille D2,
   consigné dans `core/TODOS.md` (état net par chemin en fin de session).
2. **« Le push n'a pas été effectué. »** — **D5**, nouveau : présent dans
   **9 `open` sur 9** (les huit du jour 2 et celle-ci), parce que Core
   n'observe pas les pushs — `push_observed` n'est jamais vrai, aucun
   événement `git_push` n'existe. Le modèle lit « push non observé » comme
   « push non fait ». Remèdes : consigne v3 (« l'absence d'observation n'est
   pas une absence de push ») ou, côté Core, un hook `pre-push` émettant
   `git_push` — consigné dans `core/TODOS.md`.

### v3.1 rédigée et mesurée (après-midi)

**Prompt v3.1** (PR #54, branche `ship/intelligence-prompt-v3`, non mergée,
`prompt_version` reste `"v2"`) : la v2 intégrale plus quatre consignes avec
exemple — D3 (l'annexe `agent_session` est une demande, pas un état), D4 (un
commit est un fait accompli), D5 (le push n'est pas observable, jamais dans
`open`), chemins présents à la fois dans `created` et `deleted` (état inconnu,
ignoré en silence). Consigne D1 de la v2 inchangée. Une première rédaction
(v3) puis deux retouches (v3.1) : l'exemple D3 ne propose plus « rien
d'identifiable en suspens », que les deux modèles recopiaient en gabarit, et
la règle « `open` vide seulement si aucun fait ne suggère un reste, jamais une
formule de vide » est explicite.

**Mesure `eval`, 12 entrées + `a0aacd1f` ad hoc** (entrée capturée à fin − 1 s,
reproduit l'`input_hash` du résumé v2, hors dépôt), Qwen local v2 → v3 → v3.1 :
**12/12 → 12/12 → 12/12**, 1/1 partout en ad hoc. Tableaux complets dans la
PR #54.

- **D4 et D5 à zéro** : le push était dans 6 `open` sur 13 en v2, 0 en v3 et
  v3.1 ; `a0aacd1f` ne cite plus ses commits comme points ouverts.
- **Points ouverts retrouvés** : `7bbaca78` « README.md non committé »,
  `3cabaefb` « spec context-api créée hors commit » — la v3 initiale perdait
  le premier (formule de vide). Les autres `open` sont à un fait de la
  session, chemins précis.
- **Coût Qwen inchangé** : complétion 150–300 tokens, durées 30–195 s ;
  **+~1 000 tokens d'entrée** (la plus grosse passe de 20 901 à 22 025,
  plafond 30 000 inchangé, marge 1,36×). `central_files` et `confidence`
  stables à un cran près.
- **Deux résidus laissés au réel** : `eb652ce9` écrit encore « fichiers
  créés puis supprimés, d'état inconnu » malgré la consigne du silence ; et
  `a0aacd1f` / `eef4956b` rendent « Aucun point ouvert identifié dans les
  faits de la session » — la règle anti-formule de vide est lue, pas suivie.
  À lire avec méfiance sur le lot du 07 : un `open` de vide n'est pas une
  preuve qu'il n'y a rien.
- **Artefact de délibération de la référence** : sur `claude-sonnet-5`, la v3
  fait exploser la complétion (262 → 767, 394 → 1 953, 1 543 → 2 048) pour un
  JSON de même taille ; `eb652ce9` sature le plafond de 2 048 avec une sortie
  vide, reproduit 3/3, et passe à 4 096. Noté, **sans changement de
  `llm_max_tokens`** : la référence n'est pas le modèle du dogfooding, et Qwen
  ne délibère pas.
- **D1 non tranché** : `eef4956b` recopiait l'annexe en v3, ne la recopie plus
  en v3.1 mais la remplace par la formule de vide ; `1e420dda` ne recopie pas.
  Un cas ne fait pas une statistique : le lot du 07 juge.

D3 n'est pas mesurable sur ce corpus, dont aucune entrée ne porte l'un des
quatre cas du jour 2 : `d9877899` et `8af930d9` sont ajoutés hors gel dans la
foulée (voir plus bas).

### Suite

Jour 3 : `run --once` sur les sessions du jour ; D1 à confirmer sur les
enchaînements de la journée (toutes auront une annexe, aucune n'ayant de résumé
antérieur) ; jugements de la colonne « à juger » ci-dessus. Corpus : geler
`1e420dda` et `eef4956b` avec annexe (`intelligence/TODOS.md`, piège de capture).

## Jour 3 — 2026-09-07

**Premier lot launchd : 13 candidates, 13/13 créées**, prompt v2, Qwen local,
sessions du 06 10:47 au 07 02:21. Entrée de chacune reconstituée (vue Core à
la fin de session, annexe de la chaîne) et vérifiée : les 13 hashes retombent
sur l'`input_hash` émis. Les jugements confrontent `open` au journal git et au
reflog des pushs.

### La veille du Mac à 06:42

`pmset -g log` : DarkWake batterie à 06:42:20 (pas 06:30 — launchd attend un
réveil), retour en veille à 06:42:22. Le premier résumé (`9abe3e88`) porte
`generation_ms` = 9 591 s : l'horloge a couru pendant la veille ; les 12
autres font 21 à 67 s. Le lot n'a été complet qu'à 09:32, au réveil. Le
`generation_ms` du premier résumé ne mesure rien, et la fenêtre 06:30 n'est
nominale que Mac éveillé et branché.

### Reprises v2

`doing` et `stopped_at` justes **13/13** (23/23 cumulé). `open` :

| session | `open` v2 (abrégé) | `open` | défaut |
| --- | --- | --- | --- |
| `9abe3e88` work-6 | push non effectué ; erreur `run --once` | à moitié | D5 ; l'erreur est réelle |
| `8eb40fb9` work-7 | push non effectué ; l'erreur précédente n'apparaît plus | à moitié | D5 faux (push 12:03) ; réévaluation D1 visible |
| `df34583f` work-9 | push de 24bb012 toujours pas fait ; cortex-snapshot non commité | à moitié | D5 faux (poussé avant la session) |
| `d32c9766` work-11 | 5 commits non poussés ; 3 fichiers « plus présents sur disque » | faux | D5 faux ; `created` ∩ `deleted`, les 3 existent |
| `708e2f0a` work-13 | 3 commits non poussés ; les 5 de work-11 aussi | faux | 3 vrais à 14:53 (push 15:03) ; les 5 poussés depuis 13:10 |
| `758ac159` work-15 | 12 + 3 non poussés | faux | pushs 15:36, 15:55, 16:15 en session |
| `92dd9887` work-17 | 15 + 12 non poussés | faux | 4 PR mergées en session |
| `55866a1e` work-18 | 5 + 15 non poussés | faux | PR #64, #65 mergées en session |
| `b0c0dfb2` work-19 | 8 + 20 non poussés | faux | pushs 20:53, 20:58, 21:12 |
| `783a423d` work-25 | 7 + 28 non poussés ; défaut 10 non traité | faux | D5 faux ; **D3** |
| `7b7408b8` work-27 | commits non poussés ; défaut 10 reste à traiter | faux | push 23:37 en session ; **D1 recopie** de work-25 |
| `5accd3c0` work-1 | aucun push observé, modifs locales ; validation v3 non confirmée | à moitié | vrai à 01:41 (push 02:21) ; mission d'agent reformulée |
| `3e9fee12` work-2 | aucun push observé, modifs locales ; version de reconstruction à vérifier | faux | push 02:21:38, dernière activité 02:21:59 ; **D4** (commit a8ba1c8) |

Grille du jour 2 : **0 juste, 13 à moitié, 0 faux** ; `open` seul : 0 juste,
4 à moitié, 9 faux.

### D1 requalifié — report sans réévaluation d'un point non observable

Les 12 sessions enchaînées ont reçu une annexe (`work-1` ouvre sa journée).

- **La réévaluation marche sur les points observables** : le point launchd
  (reçu de `1f931a43`), l'erreur `run --once` (work-6 → work-7) et
  cortex-snapshot (work-9 → work-11) sont abandonnés dès que la vue suivante
  ne les montre plus. Recopie stricte : 2 sur 12 (work-27 reprend « défaut
  10 » de work-25 ; work-2 reprend mot pour mot la phrase push de work-1).
- **Elle ne marche pas sur l'inobservable** : le point push est repris dans
  12 annexes sur 12 et, de work-13 à work-25, fait boule de neige — « les N
  commits de la précédente restent non poussés », de 3 à 28. La consigne v2
  « si traité, ne le répète pas » n'a rien à quoi s'accrocher : Core
  n'observe pas les pushs. C'est la circonstance atténuante de `eef4956b`
  au jour 2, devenue systématique.
- D1 n'est donc pas un défaut de recopie mais de **report d'un point que la
  vue ne peut jamais clore**. Seule une règle sur la nature du point le
  règle : le `carried_over` déclaré, avec sa raison, du v3 de main.

### D3, D4, D5 et `created` ∩ `deleted` malgré la v2

- **D3, 2 cas nets + 1 faible.** L'annexe `agent_session` de 14:45 à 22:07
  dit « Cette session ne traite QUE le défaut 10 ». À 22:07, work-25 écrit
  « le défaut 10 n'a pas été traité », alors qu'il l'a été en work-13 (PR
  #56 mergée 15:32) et que le suivi d'audit du 06 (retiré du dépôt le 09-09), dans la vue,
  l'affiche mergé. work-27 le reporte ; work-1 reformule la mission de
  l'agent en « validation non confirmée ».
- **D4, 1 cas** : work-2 lit le commit a8ba1c8 comme « reste à vérifier ».
- **D5, 13/13**, dont 9 faux au reflog ; 11 en forme affirmée, 2 en « aucun
  push observé ; restent locales ».
- **`created` ∩ `deleted`, 1 cas faux** (work-11) sur 8 sessions qui
  portaient une telle intersection.

### Le v3 de main : provenance et écart de process

Commit 7865f0f (`session_summary_v3.md`, 01:46), au milieu de 15 commits
directs sur `main` entre 01:26 et 02:12, produits par une session Claude Code
lancée à 01:17 sur une mission écrite (« rendre le champ `open`
vérifiable » : références stables, schéma typé, validateur, attentes,
prompt v3, eval MLX, rapport). La mission disait « commits atomiques, pas
de push » et ne nommait aucune branche ; la session a travaillé sur `main`
tel que checkout. Le push d'`origin/main` à 02:21:38 a été fait hors de la
session (aucune commande push dans sa transcription). Validation : suite
rapide 239 tests, 6 tests `slow` avec MLX, eval 14/14 (rapport de validation
retiré du dépôt le 09-09, voir `docs/audits/README.md`). **Aucune PR, aucune
relecture.** v2 et v3 sont épinglés par hash dans les tests ; le défaut de
`Config` reste v2, rien n'est activé.

Écart avec la pratique du 06 : le code y passait par PR (#56 à #75, une par
défaut), les prompts par branche `ship/` (v2 par la PR #48, v3.1 par la PR
#54) ; seuls docs et chores allaient sur `main` en direct. Le premier commit
de code direct sur `main` est 6e93fd5 (23:37, session codex), puis la série
de nuit, prompt v3 inclus. Un prompt versionné est du comportement, pas de
la doc. Décision à prendre : écart assumé et noté ici, ou régularisé.

### Dry-run v3 sur les 13 sessions du lot

`summarize --dry-run`, config temporaire `prompt_version = "v3"`, aucune
émission, état intact, 43 à 116 s par session chargement compris (18 min).
Entrée **sans annexe** (Core rend le résumé v2 de la session elle-même,
écarté sans repli) : D1 n'est pas testable ici, `carried_over` = 0.

**13/13 valides, 0 rejet.** 34 points : 28 `observed`, 6 `requested`, une
liste vide (work-13, la session qui a réglé le défaut 10 — juste).

| session | `open` v2 | `open` v3 | ce qui change |
| --- | --- | --- | --- |
| work-6 | à moitié | **juste** | erreur `run --once` + cortex-snapshot créé, tous deux vrais |
| work-7 | à moitié | **juste** | `session_summary_v3.md` créé non commité : vrai à 12:12 |
| work-9 | à moitié | **juste** | cortex-snapshot ; `requested` inutile (« l'agent devait lire… ») |
| work-11 | faux | faux | D6 : 4 fichiers « sans commit », tous commités en session ; `created` ∩ `deleted` tu, comme demandé |
| work-13 | faux | **juste** | `[]` |
| work-15 | faux | à moitié | `requested` « défaut 10 non couvert par les commits » : faux, réglé en work-13 |
| work-17 | faux | faux | D6 ×5, tous commités ; `doing` contaminé par la demande d'agent |
| work-18 | faux | faux | D6 (17 chemins, tous commités) + `requested` défaut 10 |
| work-19 | faux | faux | D6 (10 chemins sur 15 commités) + `requested` défaut 10 |
| work-25 | faux | faux | D6 (2 sur 4) + `requested` défaut 10 ; `doing` contaminé |
| work-27 | faux | à moitié | D6 : 2 faux, 3 vrais (commités le lendemain seulement) |
| work-1 | à moitié | faux | D6 ×5, tous commités |
| work-2 | faux | faux | D6 3 faux, 1 vrai ; `requested` rapporte la mission accomplie |

- **D5 : 0/13** (13/13 en v2). **D4 : 0/13** (1 en v2). `created` ∩
  `deleted` : silence dans les 8 sessions concernées.
- **D3 : déplacé, pas réglé.** 6 `requested` ; 4 (work-15, 18, 19, 25)
  affirment que le défaut 10 « n'est pas couvert par les commits », faux sur
  le fond, légal pour le validateur, visible dans la fiche. Et la demande
  contamine désormais `doing` sur 3 fiches (work-15, 17, 25 : « en
  commençant par le défaut 10 »), que la v2 rendait juste 13/13.
- **D6, nouveau** : « fichier modifié et aucun commit de la session ne le
  nomme » — 27 points sur 10 sessions, **20 contredits par git** (le fichier
  est dans un commit de la fenêtre). Littéralement vrai de l'entrée (la vue
  donne hash et message, jamais les fichiers d'un commit), faux comme état.
  Cause : l'exemple du prompt v3 (« `workspaces.py` est modifié et aucun
  commit de la session ne le nomme ») est appliqué à chaque fichier modifié
  dont le nom n'est pas dans un message. Le validateur l'accepte (preuve
  `path:` présente) : c'est le trou « pertinence d'une preuve » du rapport.
  Remède prompt : la vue ne montre pas les fichiers d'un commit, donc « aucun
  commit ne le nomme » n'est pas une observation ; un fichier modifié n'est
  un reste que si la session ne montre aucun commit après lui, ce que la vue
  ne date pas — donc jamais, sauf session sans commit.
- `open` v3 : **4 justes, 2 à moitié, 7 faux** (v2 : 0, 4, 9). Le modèle
  remplace un gabarit (push) par un autre (D6) ; les faux de v3 tiennent à
  une seule phrase de prompt, comme ceux de v2.

### D6 corrigé et mesuré (soirée, PR #77)

Correctif en branche `ship/intelligence-prompt-v3-d6`, mergé à 00:20 le 08 :

- **Validateur** : un point `observed` qui affirme qu'un fichier n'est pas
  commité (« aucun commit ne le nomme », « sans commit associé »,
  « n'apparaît dans aucun commit », « non commité »…) est rejeté **dès que la
  session montre un commit** (`InputReferences.commits`). Sans aucun commit
  dans la vue, c'est un fait, permis. Même esprit que D5 : mieux vaut pas de
  résumé qu'un `open` faux.
- **Prompt v3** : consigne « un commit ne liste pas ses fichiers »,
  définition d'`observed` sans l'exemple copiable, premier exemple réécrit
  (test rouge). +160 à +170 tokens d'entrée par session, la plus grosse à
  23 013, marge 1,30×.
- Tests : 243 verts (4 nouveaux, dont `eef4956b` rejetée et `7bbaca78`
  acceptée sur le corpus). L'attente d'`eef4956b` passe le point « sans
  commit qui les nomme » d'`optional` à `must_not`.

**Corpus, MLX, argmax, 14 entrées** (archive retirée du dépôt le 09-09,
voir `docs/audits/README.md`) :

| | nuit du 07 (v3) | v3 + D6 |
| --- | --- | --- |
| valides | 14/14 | 12/14 |
| gabarit D6 dans les sorties valides | 9 | 2, sur des sessions sans commit |
| sessions à commits rendant `[]` | 1 | 4 (`3cabaefb`, `cda6ccce`, `eb652ce9`, `d9877899`) |
| rejets | 0 | 2 (`247f2062`, 1 commit ; `eef4956b`, 5 commits) |
| attentes annotées | 3/4 | 2/4 (`eef4956b` rejetée ; `1e420dda` écart connu) |

Les deux rejets écrivent encore « les modifications sur … ne sont pas
committées » : la consigne ne suffit pas seule, le validateur fait le reste.
`eb652ce9` passe de cinq points D6 à `[]`. Le résidu du jour 2 (`1e420dda`
reprend la PR #28 en `carried_over`) est inchangé.

**Les 13 sessions du lot, rejouées en dry-run sous le v3 corrigé** (00:05 à
00:39, sans annexe, les 11 du 06 avec `--date`) : **12 valides, 1 rejet**
(`783a423d` work-25, 7 commits : « ne sont pas committées », attrapé). Aucun
point D6 faux : le seul « sans commit associé » restant est cortex-snapshot
sur work-9, session sans commit. Push : 0. Cinq `[]` (work-7, 13, 27, 1, 2),
dont work-27 qui tait trois fichiers réellement non commités à 23:58 — un
silence, pas une erreur. `open` : **7 justes, 5 à moitié, 0 faux, 1 rejeté**
(v3 tel quel : 4, 2, 7 ; v2 : 0, 4, 9). Les cinq « à moitié » sont les
mêmes qu'avant : quatre `requested` « défaut 10 non couvert par les
commits » (work-15, 17, 18, 19 — faux sur le fond, réglé en work-13) et
work-11 qui relit le message du commit 2ecc77b (« non activé ») en point
ouvert, un D4 sous forme `observed` avec preuve `commit:`. `doing` reste
contaminé par la demande d'agent sur work-15 et work-17. Reste à traiter en
v3, dans cet ordre : le `requested` qui affirme un état (« non couvert »,
« pas confirmée ») et le message de commit cité comme reste.

### Décisions du jour 3

- **PR #54 fermée** comme remplacée par le v3 de main, branche conservée.
- **Écart de process 7865f0f assumé et noté** (ci-dessus) ; règle pour la
  suite : un prompt versionné est du comportement, il passe par une PR.
- **`prompt_version = "v3"` activé** le 08 à 00:24, après merge de la PR #77
  et mesure corpus. Le lot du 08 juge D1 en `carried_over` sur le réel.
- Sujet posé dans `intelligence/TODOS.md` : les résumés héritent de
  l'immutabilité de `trace.db` par effet de bord ; piste d'une filiation
  `supersedes` / `superseded_by` côté Intelligence, avant l'étape 5.

## Jour 5 — 2026-09-09

**Contexte.** Lot launchd de 06:45 : 10 candidates refusées à la tentative 1
(« Cette entrée exige prompt_version = 'v5' ») — la config épinglait v3 alors
que Core 0.6.0 sert le schéma 3. Le jour 4 (08) n'a pas été jugé : son lot a
créé 2 résumés puis Core est tombé en timeout à 09:56.

**Passage manuel de 21:26.** Ligne `prompt_version = "v3"` retirée de
`config.toml` (défaut du code : v5), rien d'autre. `run --once` : 11
candidates (9 du 08, `1eb35865` et `a1040f4f` du 09), **11/11 créées, 0
échec, 0 given_up**, 6 min 38 s chargement compris, 23 à 43 s par session.
Pas de timeout Core. Machine pendant le passage : mémoire libre de 87 % à
23 % au plus bas, processus Intelligence 5,2 Go de RSS, charge ≤ 2,8. Une
première tentative a été interrompue à la main à 21:25 avant la première
sortie (relance hors du shell d'outil) : aucun budget d'échec consommé, aucun
pending. Les 10 compteurs d'échec de l'identité v3 restent dans `state.json`,
entrées mortes sans effet.

**Défaut du jour : la recopie change de champ.** `open` est vide 11/11 (texte
fixe du rendu). Mais **6 résumés sur 11 recopient mot pour mot `doing` et
`stopped_at` de l'annexe `previous_summary`** : `66859fef`, `b19a6fc3`,
`a6474bfc`, `4e2aae08` héritent de `901a5aaf` ; `96c8f48e` de `c64cb39d` ;
`a1040f4f` de `1eb35865`. L'annexe est marquée `evidence_eligible=false` et le
prompt la dit « interprétation antérieure, faillible » ; le modèle s'en sert
comme gabarit dès que la session n'a ni commit ni terminal (agent qui édite
des fichiers, aucune app). D1, chassé de `open` par la v5, revient dans
`doing` / `stopped_at`. Les cinq résumés justes sont les cinq sessions à
commits ou premières de chaîne.

**Relecture, session par session.**

- `d4dc40e0` (00:13–01:06, 3 commits). Juste : `doing` (D6, doc, archive de
  l'eval) et `stopped_at` sur 3504d4d, dernier commit vu ; `open` vide.
  Manque : le merge de la PR #77 à 00:20, hors vue. Trop : rien.
- `9346b55d` (01:30–01:47, 2 commits). Juste : reconstruction unique,
  dernier commit 48162d1. Manque : le merge de la PR #78 à 01:39, hors vue.
  Trop : rien.
- `901a5aaf` (10:05–10:19, fichiers seuls). Juste : `doing` générique mais
  exact, `stopped_at` « sans commit ni test ». Manque : nommer
  `file_policy.py` et le prompt v4, les deux nouveautés. Trop : « fichiers de
  configuration » (`config.py` modifié, rien créé).
- `66859fef` (10:22–10:42). Recopie. Juste : `central_files`. Manque : la
  capture du corpus (`intelligence/eval/observed/*.json`, 20 créés), l'objet
  réel de la session. Trop : `doing` et `stopped_at` hérités.
- `b19a6fc3` (10:44–11:01). Recopie. Juste : `central_files`. Manque : la
  décision `observations-ordonnees.md` et son audit, créés ici. Trop :
  hérités.
- `a6474bfc` (15:51–16:06). Recopie, `confidence` low, **`central_files`
  vide** alors que la session crée `resumption.py`, le prompt v5,
  `test_resumption.py` et la décision reprise fondée. Manque : tout. Trop :
  hérités. Le pire des onze.
- `4e2aae08` (16:54–16:59). Recopie. Juste : `central_files`. Manque : le
  rejeu before/after de l'audit reprise fondée (20 créés, 9 supprimés).
  Trop : hérités.
- `c64cb39d` (23:40–23:46). Juste : `doing` (scénarios d'audit, tests
  d'intégration), `stopped_at` sans commit. Manque : rien pour six minutes.
  Trop : rien.
- `96c8f48e` (23:49–23:54). Recopie. Juste : `central_files` (README et
  `validation.md` de l'audit, décision, `core/README.md`). Manque : que la
  session écrit de la doc, pas des scénarios. Trop : hérités.
- `1eb35865` (09, 00:07–01:01, 21 commits). Juste : `doing` (refonte v3,
  prompts v4/v5, `corpus/`, 0.6.0.0), `central_files`. Manque : la vraie fin,
  PR #79 à #82 mergées entre 00:45 et 01:01 (hors vue) ; `stopped_at` cite le
  premier commit (wip 65367d5, 00:25) comme dernier. Trop : « sans rapport
  final de vérification du travail d'Astra » — la demande d'agent (annexe)
  rendue comme un reste : D3 dans `stopped_at`.
- `a1040f4f` (09, 19:50–20:01, 2 commits). Recopie, `confidence` low.
  Juste : `central_files` (audits déplacés vers `corpus/audits-retired`).
  Manque : ses deux commits pourtant dans la vue (9691e73 adjudication,
  8c282e2 levée du gel), donc toute la session ; « 14 fiches à compléter »
  dans le message de 9691e73 aurait pu porter un `open`. Trop : `doing`,
  `stopped_at` et `intents` qui décrivent la nuit précédente.

**À trancher.** L'annexe `previous_summary` fait plus de mal que de bien
sous v5 : 6 recopies, 0 apport visible. La retirer de l'entrée, ou n'en
garder que `open`, est un choix de prompt/entrée qui passe par une PR.

**Tranché le soir même : prompt v6 = v5 sans annexes** (PR #83, mergée).
Sous v5, `previous_summary:0` et `agent_request:0` étaient lisibles mais
jamais citables ; v6 retire les deux annexes de l'entrée et leurs mentions
du prompt, `build_model_input(annexes=False)`. Dry-run v6 sur les 11
sessions du 08–09 : **11/11 décrivent leur propre session**, contre 5/11
sous v5 ; les 4 justes sous v5 le restent. Défaut de `Config` passé à v6 ;
la config de production reste sans `prompt_version`. Aucune réémission
des sessions du 08. `open` vide 11/11 reste un sujet ouvert, hors PR #83.

## Jour 6 — 2026-09-10

**Lot launchd de 06:42, premier passage réel sous v6.** 3 candidates, **3/3
créées, 0 échec** : `1eb35865` et `a1040f4f` réémises sous v6 (l'identité
d'un résumé inclut la version du prompt ; les 9 sessions du 08 ne sont pas
réémises, la sélection ne remonte qu'à la veille), plus `f8aab73b`
(09, 20:43–20:58, prompt v6 et fiches 15 à 18). **Les trois décrivent leur
propre session**, ce que le dry-run de la veille annonçait : `1eb35865`
donne la refonte v3, file_policy, prompts v4/v5 ; `a1040f4f` cite son
dernier commit 9691e73 au lieu de la nuit précédente ; `f8aab73b` cite
01062ea. `open` vide 3/3, texte fixe du rendu.

**Durée faussée par la veille du Mac.** Lancé à 06:42 pendant un réveil
sombre, le lot n'a avancé que par tranches de deux à trois minutes tous les
quarts d'heure (DarkWake, `pmset -g log`) et s'est terminé à 13:48 : sept
heures pour trois sessions, `generation_ms` de 2 à 3 h par session. Ce
n'est pas Intelligence qui est lente, c'est la machine qui dort ; les
durées enregistrées ce jour-là ne se comparent pas aux 23 à 43 s du 09.
Même cause que la veille du jour 3.

**Adjudication des 18 fiches**, faite le soir même : réponses,
registre des trous de collecte et synthèse dans
`docs/audits/2026-09-09-adjudication-reprise/`. Résultat qui compte pour
le journal : `open` vide n'est pas le validateur (0 rejet en production,
14/14 replays où le brut du modèle égale le validé), c'est le modèle sous
le prompt. Rejeu en trois variantes décidé le 11, pas encore lancé.

## Jour 7 — 2026-09-11

**Le Core de production servait encore le schéma 2.** Constaté en
préparant le rejeu : le daemon launchd (`com.pulse.daemon`, KeepAlive)
tourne sans redémarrage depuis le 06 à 23:56, et le schéma 3 est sur main
depuis le 09 à 00:35 (2ed558b). Il sert la vue héritée `files / git /
terminal`, sans `observations` ; Intelligence l'accepte en lecture et
bascule sur `legacy_aggregates`, donc sans aucune référence `oN`. Preuve :
le hash d'entrée des cinq résumés v6 émis en production (1eb35865,
a1040f4f, f8aab73b le 10 ; 32ca64e5, d283f6dd le 11) est identique à
l'entrée reconstruite aujourd'hui depuis la vue schéma 2. Conséquence pour
le jour 6 : `open` vide 3/3 n'était pas un choix du modèle, c'était une
entrée sans rien de citable. La conclusion de la synthèse (§3.2) reste
valable pour les fiches 01 à 14, rejouées sur l'export schéma 3 de
`eval/observed` ; complément §3.3. Un merge Core ne change rien en
production tant que le daemon n'est pas redémarré : à ajouter à la
procédure de déploiement, redémarrage non fait (production, à décider).

**Rejeu `open` en trois variantes de v6, décidé le matin, fait le soir.**
Paramètres : Qwen3.8-27B-4bit (mlx), `llm_max_tokens = 2048`, température
absente (argmax), entrée constante, 4 prompts × 4 sessions, 16/16 sorties
valides, 23 minutes de lot à 19:56–20:24 (50 à 213 s par session, Mac
éveillé). Sessions : 09 `eb652ce9`, 13 `1e420dda` et 14 `eef4956b` telles
quelles depuis `eval/observed` ; 16 `a1040f4f` figée sous le schéma 3
depuis un Core jetable (code de main, copie `sqlite3 .backup` de
`trace.db`, port 8799, arrêté ensuite), contexte à fin − 1 s. Prompts :
`v6` témoin ; `v6-sans-phrase` (sans « [] est préférable à un reste
hypothétique ») ; `v6-sans-exemple` (l'exemple `"open": []` du gabarit
remplacé par un objet `recorded_statement`) ; `v6-sans-phrase-ni-exemple`.
Données de travail : `corpus/docs/audits/2026-09-11-rejeu-open/`
(entrées, configs, `run-batch.sh`, sorties, `run.log`).

| Session | attendu (adjudication) | v6 | sans phrase | sans exemple | sans les deux |
| --- | --- | --- | --- | --- | --- |
| 09 | auth reportée (o67…), Swift hors CI (o65…) | [] | [] | [] | **2** : o194 Swift hors CI, o195 auth reportée |
| 13 | list/run « Non corrigé » (o20) | [] | [] | **1** : o20 | **1** : o20 |
| 16 | « 14 fiches à compléter » (o85) | [] | [] | **1** : o85 | **1** : o85 |
| 14 (contrôle) | D1 capté sous v5 (carried_over) | [] | **1** : o19 « D1 n'est pas mesurable… à juger au jour 2 » | **1** : o19 | **1** : o19 |

Tous les points produits sont des `recorded_statement`, citation exacte,
validés du premier coup ; aucun `command_failure`, aucun point hors
attente. Sur 09, la variante complète cite les dernières occurrences
après rebase (o194, o195), pas les premières.

**Verdict : c'est l'exemple `"open": []` du gabarit qui vide `open`.**
Retirer la phrase seule ne change presque rien (1/4, sur le contrôle) ;
remplacer l'exemple remplit 3/4 ; les deux ensemble remplissent 4/4 avec
exactement les déclarations que l'adjudication jugeait essentielles ou
utiles (fiche 09 C2 et C3, fiche 13 o20, fiche 16 T6). Le modèle sait
sélectionner une déclaration de commit dès que le gabarit ne lui montre
pas une liste vide comme sortie type. Les autres champs bougent avec le
prompt (intitulés d'`intents`, un `central_files` de plus sur 14 et 16,
`confidence` high → medium sur 16 sous les deux variantes à exemple) :
rien de faux repéré à la lecture, à juger par l'utilisateur.

**Rien n'est activé.** Les trois variantes sont livrées comme prompts
versionnés (PR `ship/intelligence-rejeu-open-v6`), aucune n'est le
défaut ; `config.toml` de production reste sans `prompt_version`. Suite
possible, à décider : faire de `v6-sans-phrase-ni-exemple` un v7 et le
passer sur les 14 sessions de `eval/observed` avant activation ; et
redémarrer le Core de production, sans quoi un v7 ne recevrait toujours
rien de citable.

## Jour 8 — 2026-09-12

**Contexte.** Premier lot à entrée schéma 3 : les trois `input_hash`
(`0dd080f9…`, `ff789af5…`, `6d93a857…`) diffèrent des cinq résumés hérités,
`observation_sources` présentes (27, 25 et 45 références),
`observation_version` 1. Lot launchd 06:33 → 12:10, veille du Mac
04:00 → 12:08 : `generation_ms` non significatif (2 h 46 min pour le premier,
puis 1 min 58 s et 1 min 02 s). 4 candidates, 3 créées, 1 rejetée. Prompt v6,
`Qwen3.8-27B-4bit`, `confidence: high` 3/3, `open` vide 3/3.

**Verdicts (lecture humaine).**

| Session | Verdict | Détail |
| --- | --- | --- |
| work-12 `cc4aa106` | **à moitié** | `doing` juste sur le fond mais fond le constat « prod au schéma 2 » dans l'action du rejeu ; `stopped_at` juste ; `open` vide alors que le point ouvert réel était le redémarrage du Core de production (fait à 21:29). |
| work-13 `a48ebc2f` | **juste, inutile** | `doing` et `stopped_at` exacts ; `open` vide alors que le lot corpus tournait et que trois PR attendaient, rien dans les faits ne le portait. Attribution au worktree `/private/tmp/…/intelligence-legacy-view-loud` au lieu de `~/Projets/Pulse`. |
| work-18 `1320b475` | **juste, inutile** | `doing` juste ; `stopped_at` juste avec une inférence (« signalant la fin ») ; `open` vide alors que #89 venait d'être poussée sans merge. |
| work-5 `057a0f56` | **rejeté** | Validateur : `central_files: config.yml absent de l'entrée`. Le nom figure dans trois faits `command` (o1, o2, o6), le workspace `conflit-demo` n'est pas surveillé, donc aucun fait `file`. |

**Bilan.** 3/3 vraies, 0/3 utiles. `doing` et `stopped_at` fiables sous v6 ;
`open` vide systématique, ce qui confirme le rejeu du 11 (l'exemple
`"open": []` du gabarit).

**Compteur étape 4.** La règle (spec du 2026-09-03, §12) : « au terme des
cinq jours, quatre reprises sur cinq jugées justes **et** utiles ». Jour 8 :
0/3 justes et utiles. La spec ne dit pas comment compter une reprise vraie
mais inutile (comme un échec au critère, ou hors compte), ni quels lots
forment les « cinq jours » depuis le changement d'entrée (schéma 3) et de
prompt (v6). Question ouverte, non tranchée ici.

**TODOS ouverts par ce jour** (sans traitement) : attribution d'une session à
un worktree git (`core/TODOS.md`) ; conservation de la sortie brute d'une
tentative rejetée, et admissibilité dans `central_files` d'un chemin présent
dans un fait `command` (`intelligence/TODOS.md`).

**Décision v7 (après-midi) et compteur.** Verdict des 9 points
`v7-superseded` et activation dans la section « Reprise » ci-dessus. Le
compteur de l'étape 4 ne cumule pas les lots v6 : **il repart au premier lot
v7 à entrée schéma 3, Mac éveillé**. Les jours 5 à 8 sous v6 restent des
mesures, pas des jours du critère.
