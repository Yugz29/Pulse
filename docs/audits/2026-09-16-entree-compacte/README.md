# Entrée compacte (`input_version` 4) derrière le prompt v8 — mesure

**Date :** 2026-09-16
**Statut :** mesure complète, en attente du verdict de l'utilisateur.
L'étape 5 a été lancée le 16 à 23:21 sur secteur, après un premier soir sur
batterie. Rien en production : `Config.prompt_version` reste `v6`,
`~/.pulse_intelligence/config.toml` reste `v7`, le lot launchd n'est pas touché.
**Branche :** `exp/intelligence-compact-input` (PR en brouillon, pas de merge).
**Données de travail :** `corpus/docs/audits/2026-09-16-entree-compacte/`
(hors dépôt) : les 6 sessions du lot du 16 figées, `mesure_tokens.py`,
`tokens.json`, `tokens.md`, config et script de l'étape 5.

## Ce qui change, et où

- **Prompt v8** = v7 à l'identique, seules deux lignes changent : le titre
  « L'entrée v4 contient : » et le point `session.observations`, qui décrit
  la forme compacte. Vérifié par test (`test_v8_prompt_is_v7_plus_the_input_description_only`).
- **Entrée v4**, construite uniquement quand le prompt est v8
  (`uses_compact_input`), sur les observations déjà filtrées (faits `window`
  toujours absents) :
  - a. `workspace` retiré d'un fait quand il est celui de la session ;
  - b. dates arrondies à la seconde entière (`at`, `started_at`, intervalles
    des changements, `first_at`/`last_at` des applications) ;
  - c. hash de commit abrégé à 12 caractères ;
  - d. faits `file` sortis de `timeline` vers `observations.files`, un
    tableau : `columns` et `change_columns` déclarées une fois, une ligne par
    fait, dans l'ordre de la chronologie, `ref` d'origine conservée ; pas de
    tableau quand la session n'a aucun fait `file` (le prompt le dit).
  Messages de commit entiers ; aucun fait retiré, aucune `ref` renumérotée.
- **v7 octet pour octet** : les empreintes SHA-256 des 14 entrées v7 du corpus,
  relevées sur main au commit 131a6dd, sont figées dans
  `tests/test_compact_input.py` et revérifiées à chaque passage de la suite.
- **Validation** : sur chaque session du corpus, `input_references` rend les
  mêmes refs, les mêmes chemins, les mêmes relations de commandes et les
  mêmes faits énumérés en v7 et en v8 ; les 14 sorties Qwen v7 du benchmark
  du 15 (preuves versionnées avec la décision du 14) sont acceptées à
  l'identique sous les deux jeux de références ; un `stopped_at` qui cite le
  hash court est valide sous les deux.

## Rapport v7 contre v8 (Qwen3.8-27B-4bit)

La ligne v7 de référence est le passage Qwen du 2026-09-15 (prompt v7,
température 0.0, mlx-lm 0.31.3, mlx 0.32.2, transformers 5.16.1), comparable :
le code d'entrée n'a pas changé depuis (seul `selection.py` a bougé, hors
entrée) et la colonne v7 de la mesure de taille redonne ses 14 `prompt_tokens`.

| | v7 | v8 |
| --- | --- | --- |
| 1. Sorties acceptées sur 14 | 14/14 (le 15) | 14/14 |
| 2. Attentes `open` atteintes | 3/4, 3/3 atteignables (le 15) | 3/4, 3/3 atteignables (même manque : `eef4956b`, `carried_over` sans annexe) |
| 3. `prompt_tokens`, corpus 14 : total / médiane / maximum | 77 696 / 4 398,5 / 23 276 | 57 756 / 3 088,5 / 12 970 |
| 4. `prompt_tokens`, lot du 16 (6 sessions, observations v2) : total / médiane / maximum | 41 403 / 5 160,5 / 16 658 | 30 526 / 3 933,5 / 11 332 |
| 5. Durée de génération, totale / médiane | 739 s / 43,4 s (le 15) | 645 s / 41,9 s |
| 6. Sessions où v8 contredit une attente que v7 atteignait | — | aucune |
| 7. Verdict de qualité | aucun | aucun |
| 8. Conditions | secteur, aucun lot en cours (le 15) | secteur, aucun lot en cours, 23:21:48 → 23:32:41, `real` 650 s, pic 21,55 Go |

- **Tokens.** Comptés sans modèle, exactement comme `MLXProvider` les
  compte : gabarit de chat rendu par `_render_prompt`, tokenizer de production
  chargé par `mlx_lm.utils.load_tokenizer`, sans les poids. Corpus : −26 %
  au total, de −44 % (`eb652ce9`, 172 faits `file`) à +7 % (`8af930d9`, une
  commande, aucun fichier). Lot du 16 : −26 % au total ; toutes les six
  sessions baissent.
- **Le prompt v8 coûte 104 tokens de plus que v7** (1 214 contre 1 110) : la
  description du tableau. **Trois sessions du corpus montent** de 25 à
  100 tokens (`2ce34456`, `8af930d9`, `d9877899`) : sans fait `file`, leur
  entrée ne perd que 4 à 79 tokens (dates et hashes), moins que le surcoût
  du prompt. Première explication consignée le 16 au soir (« le tableau vide
  coûte plus qu'il n'épargne ») : fausse ; le tableau vide a été retiré à la
  demande de l'utilisateur, les trois sessions montent toujours.

- **Lignes 1, 2, 5, 6.** `meta.json` du passage v8 et `compare_run` contre
  `eval/expected/` (`rapport.py`, hors dépôt). Les `prompt_tokens` du
  `meta.json` v8 (57 756 / 3 088,5 / 12 970) sont ceux de la mesure sans
  modèle : la méthode est confirmée des deux côtés. Durées de génération de
  `meta.json`, Mac éveillé sous `caffeinate -i` ; `real` et pic mémoire par
  `/usr/bin/time -l`, comme le 15 (23,9 Go pour l'étalon v7 ce jour-là).
- **Ce qui diffère dans les sorties, sans verdict.** 13 sorties sur 14 ont une
  prose différente de v7 (`reprise`, `structured`) ; `071bbd62` est la seule
  inchangée. Les preuves citées dans `open` sont les mêmes sur 12 sessions ;
  `d047b37b` cite un échec de plus en v8 (o32, en plus de o33 et o34) et
  `eb652ce9` un point de moins (o195 seul, v7 citait o194 et o195). Aucune
  de ces deux sessions n'a d'attente annotée. Le total des tokens de sortie
  est le même dans les deux passages (4 066) par coïncidence : une seule
  session a le même compte dans les deux.
- **Pas de verdict de qualité ici** : la lecture des 14 sorties v8, côte à
  côte avec v7, revient à l'utilisateur. Sorties sous
  `corpus/docs/audits/2026-09-16-entree-compacte/out/v8/`, à comparer à
  `docs/decisions/2026-09-14-benchmark-modeles-en-local/out/qwen3.8-27b/`.

## Rejeu

- Taille : `cd intelligence && TZ=Europe/Paris HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python ../corpus/docs/audits/2026-09-16-entree-compacte/mesure_tokens.py`.
- Étape 5 : `corpus/docs/audits/2026-09-16-entree-compacte/run-v8.sh`
  sous `caffeinate -i` (refuse de partir sur batterie ou pendant un lot
  `pulse-intel`), config `config/v8.toml` = production avec
  `prompt_version = "v8"`, sorties sous `out/v8/`, journal `run.log`
  (commit f57a976, mlx-lm 0.31.3, mlx 0.32.2, transformers 5.16.1). Lignes
  1, 2, 5 et 6 : `rapport.py` au même endroit.
