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

**Clôture du 2026-09-16.** Mergées : #98 (Intelligence : une session qui
porte un commit n'est jamais « trop courte »), #99 (Core 0.8.3.0, même
exception dans le journal ; production relancée vers 17:10, `make status`
sans STALE), #100 (lot launchd sous `caffeinate -i`), #101 (second étage
public du hook de pré-poussée, `scripts/hooks/prepush_local.sh`) ; hook
local installé par `make hooks` le soir.

**Ordre pour le jour 14, 2026-09-18.** Verdict v8 (entrée compacte,
branche `exp/intelligence-compact-input`), puis cadrage des résumés en
continu. Le chantier suivant le jour 13 a été choisi et livré le 17 : #103,
références oN cliquables dans le journal, production en Core 0.8.4.0 depuis
14:42.

Piste « Résumés dans la journée » consignée dans `intelligence/TODOS.md`
(P3), non lancée.

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

**Reprise au 2026-09-13 (ajout du jour 9).** Le lot du 13 n'a rien produit :
1 candidate, 0 créée, entrée refusée au plafond de 30 000 tokens (détail
dans « Jour 9 »). **Jour 9 non jugeable, compteur de l'étape 4 toujours pas
démarré, aucun résumé v7 en production.** Mergée l'après-midi : #93
(résumés de session dans le journal HTML, Core 0.8.1.0), prod relancée à
17:22. Chantier suivant : filtrage des faits `window` dans l'entrée du
modèle (Intelligence), avant le prochain lot. La session refusée (`0ababe11`, 12,
126 min) sort de la fenêtre de sélection au lot du 14 (`lookback_days` 1) :
elle ne sera pas retentée d'elle-même.

**Soir du 2026-09-13.** #94 mergée (faits `window` hors de l'entrée du
modèle) ; `0ababe11` relancée à la main : **premier résumé v7 en
production**, jugé dans « Jour 9 ». Deux points à creuser et une limite de
la CLI y sont consignés. **Cette relance ne compte pas pour l'étape 4** : la
règle exige un lot launchd, c'était un passage manuel. Le compteur démarrera
au lot du 2026-09-14 s'il produit un résumé.



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
v7 à entrée schéma 3, Mac éveillé**. Les jours 5 à 8 restent des mesures,
pas des jours du critère. *(Précisé le 2026-09-13 : le jour 5 tournait sous
v5, les jours 6 à 8 sous v6 ; les jours 5, 6 et 7 avaient une entrée sans
observations, `open` vide forcé ; erratum dans la décision v7.)*

## Jour 9 — 2026-09-13

**Non jugeable : zéro résumé.** Lot launchd 06:30:34 → 07:31:55, prompt v7,
entrée schéma 3, reconstruction 4. 1 candidate, 0 créée, 1 échec à la
tentative 1 : `0ababe11` (work-3 du 12, 12:55–15:01, 126 min, 2 672
activités, Pulse et DevNote), « entrée de 174548 tokens au-dessus du plafond
30000 : refusée avant le prefill ». Ce n'est pas la veille du Mac : le refus
a lieu avant toute génération. **Le compteur de l'étape 4 n'a toujours pas
démarré ; aucun résumé v7 n'existe encore en production** (51 résumés
stockés : v1 à v6).

**Cause : les faits `window` historiques du 12.** La timeline de `0ababe11`
porte 2 451 faits, dont 2 212 `window` (Terminal 2 141). Sans eux, l'entrée
passe de 173 422 à 25 310 tokens (tokenizer du modèle, prompt non compris),
sous le plafond : les faits `window` pèsent **85 % des tokens, 86 % des
caractères**. 2 095 d'entre eux alternent deux titres qui ne diffèrent que
par le caractère d'animation de Claude Code (`◐` / `◑`), enregistrés de
13:26 à 14:59 (l'essentiel avant 14:30), avant la normalisation du titre
(a17e25e, en production à 15:02) : ces faits restent dans la trace. Mesure
rejouable depuis `intelligence/` :
`.venv/bin/python ../corpus/docs/audits/2026-09-13-lot-jour-9/breakdown.py 2026-09-12`
(entrée v7 par `build_model_input`, tokenizer local du modèle, Core de
production en lecture).

**Limite connue, hors périmètre : le plafond reste serré sans faits
`window`.** Sans eux, `0ababe11` pèse 25 310 tokens d'entrée plus 1 126 de
prompt et de gabarit, soit **environ 26 400 tokens sur 30 000** pour une
session de 126 min (26 436 mesurés à la relance du soir, ci-dessous). Une
session plus longue ou plus chargée en faits `file` peut dépasser le plafond
sans aucun fait `window`.

**Les trois autres sessions du 12 sont écartées légitimement.** Critère
(`intelligence/pulse_intelligence/selection.py`, `classify`) : close, pas
« trop courte » (moins de 10 min **et** moins de 30 activités), pas déjà
résumée sous la même version de prompt et le même modèle. Vue du 12 à la
référence du lot (`at` = 06:30:34) identique à la vue actuelle.

| Session | Bornes | Durée, activités | Raison | Contenu |
| --- | --- | --- | --- | --- |
| work-1 `172b2a51` | 03:04 | 0 min, 2 | trop courte | un commit d'agent (inventaire HTML) et son fichier |
| work-2 `b091edb2` | 12:39–12:49 | 9 min, 24 | trop courte | début du chantier contexte de fenêtre (`claude`, 18 fichiers), coupé par le verrouillage de 12:49 ; agent en arrière-plan jusqu'à 12:53 ; le travail reprend à 12:55 dans work-3, mêmes fichiers |
| work-4 `a536fd50` | 16:11 | 0 min, 2 | trop courte | un commit d'agent (clôture du 12 dans ce journal) et son fichier |

Rien à reprendre dans work-1 et work-4. Le contenu de work-2 est couvert par
work-3 : c'est le refus de work-3 qui prive le 12 de reprise, pas la
sélection.

**Diagnostic `open`, constat sans verdict.** Sur les 14 sessions de
`eval/observed`, le comptage des restes attendus dans les reprises idéales
des fiches d'adjudication donne **35 restes, dont 9 étayables par un fait de
la vue** : les autres sont hors vue (merges, PR, suites décidées hors
machine, commandes de l'agent). Le plafond d'`open` est donc d'environ un
quart des restes attendus, et v7 avec l'état net des commandes (#89) en
capte déjà l'essentiel (jugement des 9 points `v7-superseded` du 12 :
4 justes et utiles, 1 à moitié, 2 justes inutiles, 2 nuisibles). La suite se
jouera sur la collecte, pas sur le prompt, et elle attend un vrai lot v7.
Comptage analyste, non validé point par point. Données :
`corpus/docs/audits/2026-09-13-diagnostic-open/` (`stored_51.json` lu par
`GET /activities/<event_id>` sur le Core de production ; `q3_material.txt`
depuis `adjudications-a-completer.json`, `eval/expected` et les sorties v5,
v6, `v7-corpus`, `v7-superseded` ; `q3_comptage.md`). Aucun modèle exécuté.

### Relance manuelle de `0ababe11` (soir, après #94)

**Premier résumé v7 en production.** #94 mergée à 19:23 (faits `window`
retirés de l'entrée du modèle, addendum du 2026-09-13 à la décision contexte
de fenêtre). `pulse-intel summarize 0ababe1191379722 --date 2026-09-12`, sans
`--retry` (1 échec sur 3), Mac éveillé sur secteur, `caffeinate -i` :
`created`, event_id `0989d7d2-ada4-5acf-837e-10bfc3ab57ff` (même identité
que la tentative refusée du matin). Prompt v7, `Qwen3.8-27B-4bit`,
`max_tokens` 2048, température absente. **26 436 tokens d'entrée réels**
(25 310 d'entrée, 1 126 de prompt et de gabarit : mesuré, plus déduit,
avec le tokenizer et le rendu du provider MLX sur l'entrée dont
l'`input_hash` `3ee44764…` est celui du résumé émis). `generation_ms`
221 583, **3 min 42 s** chargement compris (19:26:47 → 19:30:29).
`observation_sources` : 246 références, aucune d'un fait `window`.

**Sortie.**

- `doing` : « Développement du contexte de fenêtre (window_focused) pour
  l'observateur Pulse, incluant la déduplication des titres et la gestion des
  domaines ignorés, ainsi que la correction du seuil de split de session. »
- `stopped_at` : « La session s'est terminée après la modification des
  fichiers de tests et de documentation (o2450) et l'ajout d'une entrée dans
  le CHANGELOG (o2423), sans nouvelle commande ou commit ultérieur. »
  (`o2450` : `intelligence/tests/test_reconstruction_version.py` ; `o2423` :
  `core/CHANGELOG.md`.)
- `open` : un point `recorded_statement` sur `o2422` (commit `ea9cde8`,
  « fix(intelligence): KNOWN_RECONSTRUCTION_VERSION suit Core en 4 »),
  citation « TODOS pour les garde-fous manquants sur schema_version et
  observation_version ».
- `confidence` `high` ; `central_files` : `core/daemon_v2/analysis/timeline.py`,
  `core/macos_observer/Sources/PulseApplicationObserver/WindowObserver.swift`,
  `core/daemon_v2/window_policy.py`, `core/daemon_v2/ingest.py`,
  `intelligence/pulse_intelligence/session_summary.py`.

**Hors compteur.** La relance du soir ne compte pas pour l'étape 4 : la
règle exige un lot launchd (v7, entrée schéma 3, Mac éveillé), c'était un
passage manuel. **Le compteur de l'étape 4 démarrera au lot du 2026-09-14
s'il produit un résumé.**

**Jugement (utilisateur).**

| Champ | Verdict |
| --- | --- |
| `doing` | **juste et utile** |
| `stopped_at` | **exact, sans valeur de reprise** : le dernier fait chronologique n'est pas le dernier fait significatif |
| `open` | **juste** : premier `recorded_statement` produit en production (le seul point `open` antérieur, v3 du 7, était un `requested`), et c'est la nature que le diagnostic `open` du jour désignait pour les restes hors vue |

**À creuser.**

- **`observation_version` 2 sous `schema_version` 3 : attendu.** Deux
  versions indépendantes : `schema_version` est celle du Context API
  (`SCHEMA_VERSION = 3`, `context_snapshot.py`), `observation_version` celle
  de la projection des faits (`OBSERVATION_VERSION = 2` depuis les faits
  `window`, Core 0.7.0.0, `work_observations.py`). La projection est calculée
  à la lecture par le code courant, pas stockée avec la session : les
  sessions du 11, du 12 et du 13 sont toutes servies en version 2 ce soir. Le
  lot du jour 8 lisait la version 1 parce que la prod tournait sur un code
  antérieur aux faits `window` (relancée le 12 à 15:02). Rien de propre à une
  session du 12.
- **`summarize` n'enregistre pas les tokens d'entrée, `eval` si.** Le
  provider les compte (`CompletionResult.prompt_tokens`), mais
  `Summarizer.summarize` ne rend que le texte : `ProviderSummarizer.summarize`
  jette le reste, alors qu'`eval` appelle `complete` et garde
  `prompt_tokens`. Seul un refus au plafond les écrit (dans son message
  d'échec). Aucun résumé émis ne dit donc à quelle distance du plafond il
  était.

**Limite de la CLI.** `summarize` exige l'identifiant complet de la session
(`find_session` compare l'égalité) ; `show` accepte un préfixe. Première
tentative du soir avec `0ababe11` : « session introuvable sur la période »,
sans appel au modèle ni changement d'état.

## Jour 10 — 2026-09-14

**Contexte.** Lot launchd 06:32:28 → 14:24:01, prompt v7,
`Qwen3.8-27B-4bit`, entrée schéma 3, reconstruction 4, `observation_version`
2, température absente (argmax du runtime ; #96 mergée le soir). 3
candidates, 3 créées, 0 échec, sur des sessions du 13. Mac en veille pendant
tout le lot (aucun réveil complet avant 19:43) : `generation_ms` non
significatif (182,6, 130,0 et 158,9 min).

**Compteur étape 4.** Il démarre à ce jour : la veille du Mac disqualifie la
mesure de durée, pas le jugement de reprise (décision du 2026-09-15,
`docs/decisions/2026-09-15-compteur-etape-4-veille-du-mac.md`).

**Verdicts (lecture humaine, 2026-09-15).**

| Session | Verdict | Détail |
| --- | --- | --- |
| work-4 `c50774a9` (13, 14:40–14:53) | **juste et utile** | `doing` juste et utile ; `stopped_at` exact ; `open` vide, correct. `central_files` pollué par `core/CHANGELOG.md`, `core/README.md` et `core/VERSION`, qui évincent `test_session_summaries.py` et la note de décision. |
| work-5 `455cb408` (13, 17:21–17:49) | **faux** | Le `doing` (« refonte du daemon v2 (timeline, traces, sessions) et la création d'audits de diagnostic dans le corpus ») décrit une refonte qui n'a pas eu lieu. Les 17 fichiers changés deux fois de 17:21:26 à 17:21:28 sont la rafale du checkout `core-html-resumes` → `main` (17:21:25) et du `pull --ff-only` qui suit (17:21:27), confirmée par le reflog ; les cinq `central_files` en viennent tous. Le travail réel : le diagnostic dans `corpus/` et cinq passes sur `docs/dogfooding.md`. `stopped_at` vise juste et contredit le `doing`. |
| work-8 `63c206ed` (13, 19:20–19:43) | **juste et utile**, le meilleur des six | Le `recorded_statement` sur o37 (commit `9fa4c8e`) fonctionne. Réserve : la citation embarque « observation_version 2 sous schéma 3 (attendu) », marqué attendu donc non ouvert ; le modèle a repris la phrase entière sans trancher dedans. |

**TODOS ouverts par ce jour** (sans traitement) : rafale de `git checkout`
enregistrée comme du travail (`core/TODOS.md`, cas `455cb408`).

## Jour 11 — 2026-09-15

**Contexte.** Lot launchd 06:30:25 → 09:48:12, prompt v7,
`Qwen3.8-27B-4bit`, entrée schéma 3, reconstruction 4, `observation_version`
2, premier lot à `temperature=0.0` (#96). 3 candidates, 3 créées, 0 échec ;
écartées comme trop courtes : work-3 `6f49ffb3` du 14 (0 min) et work-1
`98171820` du 15 (1 min). Mac en veille 3 h 15 sur 3 h 18, capot fermé :
`generation_ms` non significatif (190,1, 6,9 et 0,8 min). Le 14 n'a que trois
sessions, toutes après 22:31 : Mac en veille de 00:53 à 19:43, puis présence
seule (fenêtres, applications, verrouillage) de 19:57 à 22:28, que la
reconstruction classe en présence et non en session de travail.

**Verdicts (lecture humaine, 2026-09-15).**

| Session | Verdict | Détail |
| --- | --- | --- |
| work-1 `367ea441` (14, 22:31–22:42) | **juste et utile** | « issue #72 » figure dans l'entrée, dans le corps des commits o1 et o4 : aucune invention. |
| work-2 `00f91935` (14, 23:16–23:24) | **juste et utile** | Même pollution de `central_files` : deux README évincent la note de décision, modifiée quatre fois. |
| work-2 `84c6dd73` (15, 00:55–01:00) | **juste, inutile à la reprise** | `open` vide alors que le benchmark avait été interrompu en laissant quatre fichiers partiels. Défendable vu l'entrée : l'interruption ne laisse aucun fait qui la dise (`run.log` est modifié à 01:00:11 et les sorties s'arrêtent à la quatrième, mais le contenu n'est pas collecté). |

**Bilan des jours 10 et 11.** 5 justes sur 6, dont 4 utiles ; 1 faux
(`455cb408`). Compteur de l'étape 4 : 4 reprises justes et utiles sur 6
depuis son démarrage au jour 10.

**Motifs de la lecture des six résumés.**

- **`open` structurellement vide** : 5 résumés sur 6 à `[]` ; le sixième
  (`63c206ed`) cite un message de commit de l'utilisateur (`9fa4c8e`, co-écrit
  en session Claude Code).
- **`stopped_at` exact partout, utile presque nulle part.**
- **`central_files` colonisé par les fichiers d'accompagnement** : un README
  dans 4 résumés sur 6 (`c50774a9`, `63c206ed`, `00f91935`, `84c6dd73`),
  `CHANGELOG.md` et `VERSION` dans 1 (`c50774a9`), où ils évincent tests et
  note de décision. Les cinq de `455cb408` viennent de la rafale de checkout.

## Jour 12 — 2026-09-16

**Contexte.** Lot launchd 06:31:38 → 11:18:29, prompt v7,
`Qwen3.8-27B-4bit`, entrée schéma 3, reconstruction 4, `observation_version`
2, `temperature=0.0`. 6 candidates, 6 créées, 0 échec, toutes sur des
sessions du 15 ; écartées comme trop courtes : work-4 `fbf1ded6` (7 min,
14 activités), work-9 `dd06e6c8` (3 min, 20) et work-10 `8069a1f4` (0 min,
5). Mac en veille jusqu'à 11:12:10 (20 DarkWake de 2 à 10 s, toutes les 15 à
17 min, aucun réveil complet) : seule la première `generation_ms` porte la
veille (`ce2b5a40`, 281,2 min ; fin calculée 11:12:52, 42 s après l'ouverture
du capot). Les cinq autres ont tourné Mac éveillé : 91,3, 38,0, 136,1, 40,1
et 28,4 s, soit de 28 à 136 s, moyenne 66,8 s. Première mesure de durée
exploitable depuis le démarrage du compteur.

**Verdicts (lecture humaine, 2026-09-16, reconstruits avec Claude Code :
aucun souvenir spontané des sessions ; chaque verdict s'appuie sur les
commits, le reflog, `trace.db` et l'entrée rejouée depuis Core).**

| Session | Verdict | Détail |
| --- | --- | --- |
| work-3 `ce2b5a40` (15, 09:54–10:26) | **juste, peu utile** | Session intermédiaire du benchmark : aucun commit dans la fenêtre, les cinq `central_files` sous `corpus/`. `stopped_at` donné en secondes depuis le début (« à 1918s »), exact mais sans prise pour la reprise. |
| work-5 `a4109319` (15, 11:26–11:41) | **juste et utile** | `open` cite le corps de 2d506e4 (11:28:57) : les quatre points « qui disent plus que leur preuve » sont toujours en suspens, versés par a0a7880 à « Citation de `command_failure` non littérale » (`intelligence/TODOS.md`, P2). La mention de o7 (Ministral) est caduque depuis 86c0348 (15:03), postérieur à la session. |
| work-6 `d2500d2e` (15, 11:42–12:12) | **juste et utile** | `stopped_at` = 6ffb079, hash et heure exacts (12:12:29). Réserve : `open` vide ne dit pas que les quatre cas sont passés aux TODOS par a0a7880 (11:49:35), dans la fenêtre. |
| work-7 `21fdaaac` (15, 13:44–13:50) | **juste et utile** | `stopped_at` = 9f20f30, exact ; `open` (← o111) cite la limite du hook de pré-poussée, toujours ouverte (`docs/audits/README.md`). Réserve : « reconstruction de la documentation » pour 98a9a7a, qui est un `git mv` de 51 fichiers. |
| work-8 `e701281c` (15, 14:07–14:25) | **à moitié juste** | Le premier `open` (← o3, a786175 à 14:08:09) reprend la question des trailers, ouverte à 14:08 et tranchée à 14:12 par d8872b6, dans la même session ; l'entrée contenait les cinq commits. Le second (← o7, f2fd0cd) reste ouvert. `stopped_at` = 69deebf, exact. |
| work-11 `bdd27079` (15, 16:21–16:32) | **juste et utile** | « 7 branches » n'est écrit nulle part dans l'entrée (hash rejoué identique) : le nombre est compté depuis les sept noms de la commande o7 (`git branch -D …`, 16:32:00). `fetch --prune` (o8) et `git branch` (o10) exacts. |

**Bilan du jour 12.** 4 justes et utiles sur 6 ; 1 juste peu utile
(`ce2b5a40`), 1 à moitié juste (`e701281c`). Compteur de l'étape 4 : 8
reprises justes et utiles sur 12 depuis son démarrage au jour 10.

**Motifs de la lecture des six résumés.**

- **Question ouverte puis tranchée dans la même session, restée dans
  `open`** (`e701281c` : o3 à 14:08, d8872b6 à 14:12). Un `recorded_statement`
  cite un commit sans regarder si un commit suivant de la même session le
  ferme. Candidat pour le corpus.
- **Session écartée pour sa durée alors qu'elle porte un commit.** work-9
  `dd06e6c8` (14:59:51–15:03:37, 3 min, 20 activités) se termine sur 86c0348,
  le verdict du benchmark (Gemma et Ministral écartés) ; work-10 `8069a1f4`
  (15:04:14–15:04:49, 5 activités) porte 626bbad, la règle du compteur. Les
  deux décisions durables du 15 n'ont aucun résumé.
- **Pas de rafale de checkout ce jour-là** : le reflog du 15 ne contient que
  des commits ; les deux opérations de masse sont des commits (a0a7880, 52
  fichiers ; 98a9a7a, 51 renommages) et les `central_files` qui en viennent
  sont du travail.

**TODOS ouverts par ce jour** (sans traitement) : une session qui porte un
commit ne doit pas être écartée pour sa durée (`intelligence/TODOS.md`, cas
`dd06e6c8`). Traité le 16 par #98 (Intelligence) et #99 (Core).

**Relance manuelle de `dd06e6c8` (après #98, hors compteur).** dd06e6c8
résumée à la main après #98, hors compteur : juste, à moitié utile. La
décision est dans le commit mais absente du résumé (omission du modèle) :
le corps de 86c0348 dit « Gemma 4 26B-A4B et Ministral 3 14B écartés après
lecture, production inchangée » ; le résumé (v7, Qwen, 16 à 17:07) donne
`stopped_at` = 86c0348 « documentant la clôture du benchmark et le
déplacement des fichiers vers corpus/docs/audits-retired/ », `doing` =
rédaction des audits des jours 10-11 et archivage du benchmark, `open` vide,
sans nommer les modèles écartés ni le maintien de Qwen.

**Clôture du 15.** La relance de la production sur main 0.8.2.0 (#97, mergée
le 14 à 23:58) le 15 à 00:03, quatre services, `make status` sans STALE,
n'était consignée que dans les notes de session ; `core/CHANGELOG.md` porte
l'entrée 0.8.2.0 (« Déploiement : relancer le daemon Core »). Elle ne se
vérifie plus par `ps` : le Mac a redémarré le 16 vers 11:36 et launchd a
relancé les quatre services à 11:37:27, sur le même code (dernier commit
`core/` : 2e0f1bf, 14 à 23:58).

## Jour 13 — 2026-09-17

**Contexte.** Lot launchd 06:32:19 → 09:26:50, prompt v7,
`Qwen3.8-27B-4bit`. 3 candidates, 3 créées, 0 échec, toutes sur des sessions
du 16 ; écartée comme trop courte : work-3 `7499d425` (4 min, 11 activités,
sans commit). Premier lot avec #98 : work-4 `50316b4d` (1 min, 11 activités,
un commit) aurait été écartée avant. `run.log` n'écrit ni `prompt_version`,
ni modèle, ni sessions écartées : lus dans les trois événements Core et par
rejeu du classement à l'heure du lot. Dépôt sur
`exp/intelligence-compact-input` (398726e) pendant le lot, install
éditable : sans effet sur v7, rien sous `core/` dans le diff et les 3
`input_hash` recalculés à l'identique depuis le code de main. `caffeinate -i`
(#100) sans effet capot fermé sur batterie : Mac rendormi à 06:32:19,
DarkWake jusqu'à 09:14, capot ouvert à 09:23:49. `generation_ms` : la
première porte la veille et le chargement du modèle (`b6262f70`, 172,1 min) ;
2 mesures exploitables, Mac éveillé : 34,6 s (`50316b4d`) et 111,4 s
(`b21f932f`). Matière et preuves sous
`corpus/docs/audits/2026-09-17-jour-13/` (hors dépôt).

**Verdicts (validés par l'utilisateur, 2026-09-17 ; lecture à froid
impossible, voir les motifs).**

| Session | Verdict | Détail |
| --- | --- | --- |
| work-2 `b6262f70` (16, 15:27–16:06) | **juste et utile** | `stopped_at` = 7e6a6bf (o40), exact ; `open` (← o40) cite la règle de candidature en deux copies, Core et Intelligence. Texte et citation identiques : la même phrase affichée deux fois. |
| work-5 `b21f932f` (16, 21:53–23:40) | **juste, à moitié utile** | 131a6dd (o41, 22:39:47, clôture du 16) est dans l'entrée et absent du résumé. Le premier `open` (← o77, ca42b99 à 23:09:34, « La mesure avec le modèle n'a pas été lancée ») est fermé par o109 dans la même session ; le résumé le dit lui-même (« a été réalisée ensuite (o109) ») et garde le point. Le second (← o109, « Pas de verdict. ») reste ouvert. |
| work-4 `50316b4d` (16, 17:57–17:58) | **à moitié juste, inutile** | Candidate par #98 seulement. Le commit est une ligne de journal (203e318, « jour 12, dd06e6c8 résumée à la main après #98, hors compteur ») ; le résumé écrit « le commit dd06e6c8 » alors que dd06e6c8 est une session, et ne dit ni « hors compteur » ni « après #98 ». |

**Bilan du jour 13.** 1 juste et utile sur 3 ; 1 juste à moitié utile
(`b21f932f`), 1 à moitié juste et inutile (`50316b4d`). Compteur de
l'étape 4 : 9 reprises justes et utiles sur 15 depuis son démarrage au
jour 10.

**Motifs de la lecture des trois résumés.**

- **Commit de clôture absent du résumé** : 131a6dd (clôture du 16, 22:39)
  ne figure ni dans `doing`, ni dans `stopped_at`, ni dans `open` de
  `b21f932f`, qui ne retient que l'expérimentation v8.
- **Point `open` fermé par la session et gardé quand même** (`b21f932f`,
  o77 puis o109). Même motif qu'au jour 12 (`e701281c`), avec cette fois la
  fermeture écrite dans le texte du point.
- **#98 fait entrer un commit de journal sans valeur ajoutée** (`50316b4d`) :
  une session d'une minute dont le seul commit consigne un verdict dans
  `docs/dogfooding.md`. Le résumé prend dd06e6c8 pour un commit alors que
  c'est une session.
- **Texte et citation identiques affichés deux fois** (`b6262f70`) : quand le
  modèle reprend la phrase du commit mot pour mot, la reprise l'affiche une
  fois comme texte et une fois comme citation.
- **Lecture à froid impossible** : l'utilisateur ne se souvient pas de ses
  sessions ; `doing`, `stopped_at` et `open` lus seuls ne se jugent pas sans
  la reconstruction (commits, entrée rejouée), comme au jour 12.

**TODOS ouverts par ce jour** (sans traitement) : `run.log` n'écrit ni
`prompt_version`, ni modèle, ni sessions écartées (`intelligence/TODOS.md`,
P3) ; références oN cliquables dans la page HTML des résumés, passées en P1
le même jour et déplacées dans `core/TODOS.md` (rendu dans Core) : prochain
chantier.

## Jour 14 — 2026-09-18

**Contexte.** Lot planifié de 06:30 démarré à 06:36:11 (DarkWake, Mac en
veille sur batterie), **interrompu** à 06:47:52 : « Core injoignable »,
0 candidate — `/context/sessions?date=2026-09-17` (18 sessions, 702 Ko)
à cheval sur la veille, puis, Mac éveillé, en 4,9–9 s en production contre
le timeout de 5 s alors codé en dur. Au sens de la
[précision du 18](decisions/2026-09-15-compteur-etape-4-veille-du-mac.md) :
« interrompu, sessions rattrapées », **hors compteur**. Deux relances
manuelles, Mac éveillé sur secteur, hors compteur : 10:38 → 10:52 après #110
(timeout 60 s, retry GET), 16 créées, toutes du 17 ; 11:31 → 11:47 après
#112 (rattrapage depuis `last_complete_pass`, plafond 7 jours), 19 créées
(8 du 11, 2 du 12, 2 du 13, 3 du 15, 4 du 18), repère posé à
`2026-09-18T09:32:00Z`. Prompt v7, `Qwen3.8-27B-4bit`. Core 0.8.9.1 (#111,
`is_file_noise` sans pathlib) en production depuis 11:30.

**Verdicts (utilisateur, 2026-09-18) sur 6 résumés de la relance de 11:31 :
les 4 sessions du 18 et les 2 plus longues du 11.**

| Session | Verdict | Détail |
| --- | --- | --- |
| work-3 `bb6c96e0` (18, 10:31–10:40, Pulse + Holberton28) | `doing`/`stopped_at` justes ; `open` fausse alerte | `open` (← o28) : `docker build … && docker run …` en échec (code 1). Résolu plus tard, hors de cette session. |
| work-4 `f8a3ebc4` (18, 10:40–11:04, devops-formation + Holberton28 + Pulse) | `doing`/`stopped_at` justes ; `open` deux fausses alertes | `open` (← o26, o39) : deux échecs Docker (code 125). Résolus plus tard. Deux projets menés en parallèle dans la même session. |
| work-5 `0e1e3cab` (18, 11:04–11:12, Pulse) | `doing`/`stopped_at` justes ; `open` vide | Voir le motif ci-dessous : la poussée refusée par le hook tombe dans cette session et `open` ne l'a pas signalée. |
| work-6 `7fd70078` (18, 11:12–11:18, Pulse) | `doing`/`stopped_at` justes ; `open` vide | — |
| work-11 `efc91c08` (11, 21:13–21:52, Pulse + observer-log-timestamps) | ne permet pas de se rappeler la session | Lu à sept jours. |
| work-9 `cc4aa106` (11, 20:08–20:26, Pulse) | ne permet pas de se rappeler la session | Lu à sept jours. |

**Bilan du jour 14.** `doing` et `stopped_at` justes sur les 4 sessions du
18. `open` : 3 signalements, 3 fausses alertes — des échecs Docker résolus
plus tard, dans des sessions fragmentées (la journée du 18 est découpée en
sessions de 6 à 23 min) et avec deux projets en parallèle. Les 2 résumés du
11, lus à sept jours, n'ont pas permis à l'utilisateur de se rappeler la
session. Rien au compteur : 9 reprises justes et utiles sur 15, inchangé.

**Motifs.**

- **La poussée refusée par le hook n'est pas dans `open`** (work-5) : le
  commit `045852e` est à 11:10:21 (o à 365 s de la session), la poussée
  refusée par le hook de pré-poussée (exit 2, `env.kv` MEDIUM) dans la
  seconde qui suit, la session se ferme à 11:12:45 avec ce point non résolu
  (poussée acquittée à 11:24, dans work-7). `open` dit « Aucun point ouvert
  étayé par les faits de la session ». L'entrée de work-5 ne contient aucun
  fait de commande (les commandes de cette session ont été lancées par un
  agent, hors du terminal instrumenté) et `coverage.remote_push_state` vaut
  `not_collected` : l'échec n'était pas dans les faits lus par le modèle.
- **`open` signale des échecs de commande que la suite de la journée
  résout** (work-3, work-4) : les deux sessions se suivent (10:31–10:40,
  10:40–11:04) et la troisième occurrence du même `docker build` réussit
  plus tard ; à l'échelle d'une session de 8 min, le dernier fait observé
  est un échec.
- **Lecture à sept jours** (work-9, work-11) : `doing`, `stopped_at` et
  `open` ne suffisent pas à retrouver la session.

**Étape 2 du mode continu — « ce qui m'a manqué dans Session en cours »
(première ligne, utilisateur, 2026-09-18).** Ouvert : oui. Utile : le commit
et son message complet, qui racontent la session. Manqué : l'agent en cours
(seules ses sessions terminées apparaissent ; ses tests et ses échecs sont
invisibles, donc « aucun test » rassure à tort) ; les fichiers arrivés par
un merge masquent ceux réellement modifiés.
