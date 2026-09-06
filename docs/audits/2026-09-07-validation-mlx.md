# Validation locale MLX — 7 septembre 2026

Les 14 sessions du corpus passent la validation du contrat avec le modèle
local et le prompt v2. Des défauts de sens restent reproductibles dans `open` :
ce résultat ne constitue pas un score de justesse des résumés.

## Conditions du passage

- Base du dépôt : `6e93fd5`, avec les ajouts de tests locaux en cours.
- Mac Apple Silicon, Python 3.14.7 ; MLX 0.32.2, mlx-lm 0.31.3,
  transformers 5.16.1, tokenizers 0.23.2.
- Modèle : `mlx-community/Qwen3.8-27B-4bit`, chargé depuis le cache, hors ligne.
- Prompt v2 ; 2 048 tokens de sortie au maximum ; plafond d'entrée 30 000 ;
  température absente, argmax du runtime ; fuseau `Europe/Paris`.
- Un provider réutilisé sur les 14 entrées : dix sessions gelées et quatre
  extensions de dogfooding. Passage par `evaluate`, `build_model_input`,
  `ProviderSummarizer` et `parse_model_output`, comme pour l'évaluation CLI.
- Résultats écrits hors de l'arbre surveillé :
  `/private/tmp/pulse-mlx-validation-85bcqy98/` (artefacts temporaires).
  Ce dossier contient les sorties par session, `meta.json`, les versions du
  runtime, les mesures par appel et le résultat du refus de l'entrée de stress.

## Résultats du corpus

**14 valides, 0 rejet, 0 panne.** Aucune balise `<think>` dans les 14 sorties.
Le validateur vérifie notamment le JSON, les champs, les limites de longueur
et l'appartenance des chemins à l'entrée. Il ne vérifie pas la vérité des
phrases ni si un point est réellement encore ouvert.

| Session | Tokens d'entrée | Tokens de sortie | Génération (s) | Contrat |
| --- | ---: | ---: | ---: | --- |
| `071bbd62a95fb6cb` | 3859 | 160 | 40,7 | valide |
| `1e420dda8b6eee77` | 4861 | 208 | 54,3 | valide |
| `247f2062410ca5a9` | 12729 | 247 | 141,7 | valide |
| `2ce344566f7e85dc` | 1993 | 176 | 46,2 | valide |
| `3cabaefb759dae36` | 20901 | 247 | 221,5 | valide |
| `6a4166356dbab6ec` | 2484 | 157 | 29,4 | valide |
| `7bbaca7882c3d766` | 1918 | 169 | 26,7 | valide |
| `8af930d9ef437d2a` | 1482 | 145 | 25,3 | valide |
| `8faf4569fe2723b1` | 4811 | 226 | 61,0 | valide |
| `cda6ccce898d3e88` | 2982 | 265 | 47,4 | valide |
| `d047b37b4511d37c` | 6602 | 280 | 81,4 | valide |
| `d98778994319cd07` | 1692 | 206 | 31,6 | valide |
| `eb652ce9f04c4b37` | 10967 | 301 | 127,1 | valide |
| `eef4956b36dd37ce` | 4928 | 235 | 66,1 | valide |

Les appels totalisent environ **16 min 45 s**, chargement compris ; médiane
de génération **50,8 s**. Le pic cumulatif retourné par `mx.get_peak_memory()`
est **19,77 Gio** (21 232 532 534 octets), atteint sur la plus grosse session.
Il s'agit des allocations MLX, pas de toute la mémoire du Mac. Une seule
exécution a été mesurée ; ce n'est ni une distribution de latences ni une
garantie de stabilité sous d'autres charges.

## Refus d'une entrée trop longue

Le fichier alors nommé `synthetic-60k.json` (renommé `synthetic-114k.json` le
2026-09-07) compte en réalité **113 928 tokens**
avec le tokenizer du modèle et le prompt v2. Il est refusé au plafond de
30 000, avant le prefill, en environ **0,11 s** avec les poids déjà chargés.
Son nom historique et l'estimation caractères/4 ne sont pas une mesure MLX.

Cette vérification prouve le refus d'un dépassement large. Elle ne prouve pas
la tenue en mémoire de toutes les tailles comprises entre 20 901 et 30 000,
ni le comportement exact à 29 999, 30 000 et 30 001 tokens.

## Défauts de sens reproduits

- **D5 — observation absente transformée en fait négatif.** Sur `1e420dda`,
  la sortie affirme « Les commits ne sont pas poussés (push_observed: false) ».
  Sur `eef4956b`, elle affirme « Le push n'a pas été effectué ».
  L'absence d'observation ne permet pas cette conclusion. Le défaut passe le
  validateur et peut même accompagner une confiance `high`.
- **D1 — reprise du point ouvert précédent.** Sur `eef4956b`, la proposition
  « la configuration de llm_max_tokens et le passage de référence restent à
  valider » est reprise à l'identique de l'annexe `previous_summary`. La
  conformité du format ne garantit pas la réévaluation de ce point.
- **D3 — ancienne demande d'agent présentée comme état restant à traiter.**
  Sur `8af930d9`, `open` annonce que l'état de la PR #28 et la branche n'ont
  pas été confirmés ; ce sujet provient de la demande initiale conservée dans
  l'annexe d'agent. Le cas `d9877899` conserve également ce point ancien.

À l'inverse, les deux cas gelés sans fichiers (`2ce34456`, `6a416635`)
produisent bien `central_files: []`. Voir [le journal de dogfooding](../dogfooding.md)
pour les jugements et le contexte des défauts D1 à D5. Aucun score global de
justesse n'est déduit des seuls résultats de validation ci-dessus.

## Couverture conservée et limites

La suite `slow` couvre désormais les prompts v1 et v2, le refus de l'entrée
de stress avec le vrai tokenizer, ainsi qu'un parcours CLI → MLX → Core
temporaire → état local → `show`. Ce dernier vérifie aussi qu'une seconde
exécution ne recharge pas le modèle et ne crée pas de doublon.

Validation finale : **27 tests passent en 132,49 s** dans
`test_mlx_provider.py` et `test_real_core_integration.py`, marqueurs lents
inclus. Ils comprennent les **quatre tests utilisant réellement MLX**.

Les angles à traiter en priorité restent :

1. **Justesse de `open`** : des attentes annotées sur les sessions D1/D3/D5,
   puis une évaluation de toute modification de prompt avant activation.
2. **Durée et mémoire** : répétitions, contexte proche du plafond et charge
   concurrente. `generation_timeout_s` est transmis au provider HTTP ; il
   n'interrompt pas la génération locale MLX. Les appels de plus de 120 s de
   ce passage illustrent cette limite, pas un échec du contrat actuel de MLX.
3. **Conditions réelles prolongées** : veille/réveil et redémarrages de toute
   la chaîne d'observation, disque plein/coupure pendant une écriture,
   entrées contradictoires ou contenant des instructions trompeuses. Ce
   passage ne les a pas éprouvées avec le vrai modèle et les services réels.

## Reproduire

Depuis `intelligence/`, avec les poids présents en cache :

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest -m slow -v
TZ=Europe/Paris HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -m pulse_intelligence.cli eval --provider mlx \
  --out /private/tmp/pulse-eval-mlx-nouveau-passage
```

La commande `eval` utilise la configuration locale ; conserver les valeurs
indiquées plus haut pour une comparaison. Elle écrit les sorties et les
durées, mais pas le pic mémoire : ce dernier a été instrumenté séparément
autour de `MLXProvider.complete` lors du passage décrit ici.
