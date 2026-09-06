# Dogfooding — résumé de session (pas 3)

Journal du dogfooding du modèle local (`Qwen3.8-27B-4bit`, décision
[2026-09-06](decisions/2026-09-06-modele-local-qwen.md)). Un jour par entrée :
les reprises lues et jugées, les défauts trouvés. Critère de sortie (spec du
2026-09-03, §12) : au terme de cinq jours, **quatre reprises sur cinq jugées
justes et utiles** → service résident (étape 5) ; sinon on itère le prompt ou le
modèle sur le corpus `eval/`, et le service attend.

## Reprise

**Où on en est (soir du jour 2, 2026-09-06).**

- Jours 1 et 2 faits : 7/7 puis 8/8 résumés créés sur la trace réelle.
- Config de dogfooding : `llm_provider = "mlx"`, `Qwen3.8-27B-4bit`,
  `prompt_version = "v2"` (défaut du code aussi, PR #49).
- `run --once` planifié par launchd **chaque jour à 06:30**
  (`com.pulse.intelligence-run`, PR #50, journal
  `~/.pulse_intelligence/logs/run.log`) — premier passage automatique le
  2026-09-07 au matin.
- Plan B consigné : `Qwen3.5-9B-4bit` (×3,8 plus rapide, 8 Go, mais invente des
  intentions dans `open` sur les grosses sessions) — note de décision.
- Comptes de tokens corrigés partout : `#1` = 20 901 `prompt_tokens` réels, pas
  « ~6 500 » ; plafond 30 000 inchangé, marge 1,4×.

**Ce qui attend au jour 3.**

- Le jugement des huit reprises v2 du jour 2 (colonne « à juger »).
- D1 / D3 sur les enchaînements du 2026-09-07 (toutes les sessions auront une
  annexe, aucune n'ayant de résumé antérieur) → v3 du prompt seulement si le
  jour 3 confirme.
- Spike B v2 : pic mémoire du 27B avec le prompt v2 sur `#1`, puis entre 21k et
  30k tokens ; la remesure du 2026-09-06 a échoué deux fois sur une erreur GPU
  Metal, à refaire.
- Corpus : geler `1e420dda` et `eef4956b` avec annexe (`intelligence/TODOS.md`,
  piège de capture).

**Décisions en attente de moi.**

- Merger la PR du refus bruyant + affichage des `prompt_tokens` réels dans
  `eval` (branche `ship/intelligence-tokens`).
- Relever ou non `llm_max_input_tokens` après le spike B v2.
- `eval/out` hors de la vue du watcher : ajouter `out` au filtre de Core
  (correctif) ou faire écrire `eval` hors de l'arbre observé.
- Étape 5 : règle de préséance entre deux résumés d'une même session
  (`intelligence/TODOS.md`).

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

### Suite

Jour 3 : `run --once` sur les sessions du jour ; D1 à confirmer sur les
enchaînements de la journée (toutes auront une annexe, aucune n'ayant de résumé
antérieur) ; jugements de la colonne « à juger » ci-dessus. Corpus : geler
`1e420dda` et `eef4956b` avec annexe (`intelligence/TODOS.md`, piège de capture).
