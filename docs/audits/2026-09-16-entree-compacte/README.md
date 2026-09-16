# Entrée compacte (`input_version` 4) derrière le prompt v8 — mesure

**Date :** 2026-09-16
**Statut :** en attente ; la mesure avec le modèle (étape 5) n'a pas été
lancée, le Mac était sur batterie pendant tout le chantier (50 % → 47 %,
en décharge). Rien en production : `Config.prompt_version` reste `v6`,
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
    fait, dans l'ordre de la chronologie, `ref` d'origine conservée.
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

Les lignes 1, 2, 5 et 7 attendent l'étape 5 : « en attente », pas mesurées.
La ligne v7 de référence est le passage Qwen du 2026-09-15 (prompt v7,
température 0.0, mlx-lm 0.31.3, mlx 0.32.2, transformers 5.16.1), comparable :
le code d'entrée n'a pas changé depuis (seul `selection.py` a bougé, hors
entrée) et la colonne v7 de la mesure de taille redonne ses 14 `prompt_tokens`.

| | v7 | v8 |
| --- | --- | --- |
| 1. Sorties acceptées sur 14 | 14/14 (le 15) | en attente |
| 2. Attentes `open` atteintes | 3/4, 3/3 atteignables (le 15) | en attente |
| 3. `prompt_tokens`, corpus 14 : total / médiane / maximum | 77 696 / 4 398,5 / 23 276 | 57 653 / 3 083 / 12 958 |
| 4. `prompt_tokens`, lot du 16 (6 sessions, observations v2) : total / médiane / maximum | 41 403 / 5 160,5 / 16 658 | 30 454 / 3 921,5 / 11 320 |
| 5. Durée de génération, totale / médiane | 739 s / 43,4 s (le 15) | en attente |
| 6. Sessions où v8 contredit une attente que v7 atteignait | — | en attente |
| 7. Verdict de qualité | aucun | aucun |
| 8. Conditions | secteur, aucun lot en cours (le 15) | Mac sur batterie : non lancé |

- **Tokens.** Comptés sans modèle, exactement comme `MLXProvider` les
  compte : gabarit de chat rendu par `_render_prompt`, tokenizer de production
  chargé par `mlx_lm.utils.load_tokenizer`, sans les poids. Corpus : −26 %
  au total, de −44 % (`eb652ce9`, 172 faits `file`) à +7 % (`8af930d9`, une
  commande, aucun fichier : le tableau vide coûte plus qu'il n'épargne). Lot
  du 16 : −26 % au total ; toutes les six sessions baissent.
- **Trois sessions du corpus montent** de 26 à 101 tokens (`2ce34456`,
  `8af930d9`, `d9877899`) : sans fait `file`, l'entrée paie la déclaration du
  tableau vide et ne gagne que sur les dates et les hashes.

## Rejeu

- Taille : `cd intelligence && TZ=Europe/Paris HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python ../corpus/docs/audits/2026-09-16-entree-compacte/mesure_tokens.py`.
- Étape 5, préparée, non lancée : `corpus/docs/audits/2026-09-16-entree-compacte/run-v8.sh`
  (refuse de partir sur batterie ou pendant un lot `pulse-intel`), config
  `config/v8.toml` = production avec `prompt_version = "v8"`, sorties sous
  `out/v8/`. Puis la ligne 6 se lit par `compare_run` contre les attentes
  d'`eval/expected/` et les sorties du 15 sous
  `docs/decisions/2026-09-14-benchmark-modeles-en-local/out/qwen3.8-27b/`.
