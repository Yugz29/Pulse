# Validation locale du champ `open` v3 — 7 septembre 2026

Le champ `open` de Pulse Intelligence devient vérifiable : chaque point
déclare sa nature (`observed`, `carried_over`, `requested`) et ses preuves, et
le validateur rejette ce qu'hier il laissait passer. Ce rapport dit ce que le
contrat prouve désormais, ce que le passage MLX avec le prompt v3 a produit
sur les 14 sessions, et ce qui reste un défaut de sens que le contrat ne
peut pas attraper.

## Ce qui a changé depuis le rapport du matin

- **Entrée référencée** (`session_input`) : chaque fait de la vue est
  désignable par `<type>:<clé>` (`path:`, `commit:`, `event:`, `app:`,
  `test_passed:`, `test_failed:`, `error:`, `signal:`, `agent_request:0`,
  `previous_summary:<i>`). La vue Core n'est pas réécrite ; seules les
  annexes gagnent `open_items` et `ref`, et seulement pour un prompt au
  schéma v3. L'entrée des prompts v1 et v2 est octet pour octet celle
  d'avant (`input_hash` inchangé) ; aucun changement de l'export de Core
  n'a été nécessaire.
- **Schéma `open` v3 et règles** (`session_summary`) : liste de points
  `{text, kind, evidence, carried_from, reason_kept}` ; rejet si `kind`
  inconnu, `observed` sans preuve, preuve absente de l'entrée ou tirée
  d'une annexe, `carried_over` sans point réel ni `reason_kept`,
  `requested` citant autre chose que l'annexe d'agent, texte recopié de
  `previous_summary` sans `carried_over` (D1), ou point `observed` qui
  affirme qu'un push n'a pas été effectué (D5, règle lexicale sur le push
  seulement). Core ne change pas : `reprise.open` reste une chaîne (rendu
  une phrase par point), `details.open_items` porte nature, preuves et
  origine, jamais de texte libre hors des champs rédigés. Les résumés v1/v2
  en base se lisent et s'affichent comme avant.
- **Attentes annotées** (`eval/expected/`) pour `1e420dda`, `eef4956b`,
  `8af930d9`, `d9877899`, chaque point et chaque interdit justifiés ;
  comparaison sur nature et preuves, jamais sur la prose ; écart imprimé
  par `eval`.
- **Prompt v3** : v2 intacte (empreinte épinglée par un test) et toujours
  sélectionnable ; le défaut de `Config` reste `v2`, rien n'est activé.

## Conditions du passage

- Base du dépôt : `6e93fd5` plus les commits de la journée (état à la
  génération : `9df8416`, prompt v3 et validateur v3 inclus ; l'avertissement de version de reconstruction est arrivé après, `meta.json` de ce passage ne le porte pas).
- Mac Apple Silicon, Python 3.14.7 ; MLX 0.32.2, mlx-lm 0.31.3,
  transformers 5.16.1, tokenizers 0.23.2 (`environment.json`).
- Modèle : `mlx-community/Qwen3.8-27B-4bit`, cache local, hors ligne.
- Prompt v3 ; 2 048 tokens de sortie au maximum ; plafond d'entrée 30 000 ;
  température absente (argmax) ; `TZ=Europe/Paris`.
- Même chemin que la production et que le passage du matin : `evaluate`,
  `build_model_input(references=True)`, `ProviderSummarizer`,
  `parse_model_output(references=…)`. Un provider réutilisé sur les 14
  entrées ; pic mémoire lu par `mx.get_peak_memory()` après chaque appel.
- Artefacts sous [`2026-09-07-validation-open-v3/`](2026-09-07-validation-open-v3/) :
  `outputs/` (sorties par session et `meta.json`), `measurements.json`,
  `environment.json`, `run.log`. Ceux du passage v2 du matin sont sous
  [`2026-09-07-validation-mlx/`](2026-09-07-validation-mlx/).

## Résultats du corpus

**14 valides, 0 rejet, 0 panne, une génération par session.** Aucune balise
`<think>`. Le validateur v3 a accepté chaque sortie du premier coup : toutes
les références citées existent dans l'entrée, aucun point `observed` sans
preuve, aucune recopie de `previous_summary` non déclarée, aucun push
« non effectué ». Ce résultat prouve que le modèle sait produire le schéma ;
il ne prouve pas que chaque point est juste (voir plus bas).

| Session | Tokens d'entrée v2 → v3 | Sortie v3 | Génération v3 (s) | `open` v3 |
| --- | ---: | ---: | ---: | --- |
| `071bbd62a95fb6cb` | 3859 → 5795 | 240 | 50,8 | 1 observed |
| `1e420dda8b6eee77` | 4861 → 6848 | 285 | 62,6 | 1 carried_over (**écart**) |
| `247f2062410ca5a9` | 12729 → 14672 | 367 | 131,2 | 1 observed |
| `2ce344566f7e85dc` | 1993 → 3936 | 354 | 71,6 | 1 observed, 1 requested |
| `3cabaefb759dae36` | 20901 → 22844 | 315 | 244,0 | 1 observed |
| `6a4166356dbab6ec` | 2484 → 4427 | 215 | 48,2 | 1 requested |
| `7bbaca7882c3d766` | 1918 → 3861 | 200 | 41,3 | 1 observed |
| `8af930d9ef437d2a` | 1482 → 3425 | 213 | 38,6 | 1 requested (conforme) |
| `8faf4569fe2723b1` | 4811 → 6754 | 364 | 80,5 | 2 observed |
| `cda6ccce898d3e88` | 2982 → 4918 | 361 | 65,3 | 1 observed |
| `d047b37b4511d37c` | 6602 → 8545 | 341 | 92,5 | 2 observed |
| `d98778994319cd07` | 1692 → 3690 | 144 | 37,4 | `[]` (conforme) |
| `eb652ce9f04c4b37` | 10967 → 12903 | 590 | 163,8 | 5 observed |
| `eef4956b36dd37ce` | 4928 → 6913 | 434 | 110,9 | 1 observed, 1 carried_over (conforme) |

Le prompt v3 coûte **+1 936 à +1 943 tokens d'entrée** par session (le
texte du prompt ; les références n'ajoutent que 7 à 62 tokens, mesurés avec
le vrai tokenizer sans les poids) ; la plus grosse session passe de 20 901 à
22 844 tokens, marge 1,31× sous le plafond de 30 000. Les appels totalisent
**20 min 43 s** chargement compris (16 min 45 s en v2), médiane de
génération **68,5 s** (50,8 s), complétion médiane **328 tokens** (217 :
le JSON des points est plus long). Pic `mx.get_peak_memory()` **20,09 Gio**
(21 568 076 854 octets, contre 19,77 Gio). Une seule exécution, pas une
distribution.

## Ce que le contrat prouve désormais, et ce qu'il ne prouve pas

**Prouvé par les tests unitaires** (`test_open_v3_contract.py`, 25 tests) :
chaque règle de rejet a un test, et les trois sorties réelles du matin
(D1 `eef4956b`, D3 `8af930d9` et `d9877899`, D5 `1e420dda` et `eef4956b`),
transcrites au schéma v3 dans leur forme la plus favorable au modèle, sont
rejetées — pour la raison de leur défaut, pas par accident de forme. La
seule forme acceptée du cas D3 déclare le point `requested`. Un test contre
le vrai Core prouve qu'un résumé v3 est accepté, `reprise.open` rédigé,
`details.open_items` conservé, et que `GET /context` le sert comme avant.

**Prouvé par les attentes** (`test_expectations.py`) : chaque attente est
elle-même une sortie v3 valide pour son entrée (le validateur ne demande
rien d'impossible), et la comparaison ignore la prose : elle retrouve un
point par sa nature et ses preuves. **Non prouvé** : que les attentes soient
les bonnes — elles sont mon jugement des quatre sessions, justifié point par
point, pas une vérité mesurée.

**Ce que le contrat ne vérifie pas** :

- la **pertinence** d'une preuve. `observed` + `path:x` est accepté dès que
  `x` est dans la vue ; rien ne dit que la phrase parle de `x`. Un point
  faux sur un fichier réel passe.
- la **raison** d'une reprise. `carried_over` + `reason_kept` non vide est
  accepté ; « aucun événement ne mentionne la PR #28 » est une raison
  valide au sens du schéma, même quand le point repris est une demande
  d'agent et non un reste de travail (`1e420dda`, ci-dessous).
- D5 hors du push. La règle lexicale ne vise que le push ; « les tests
  n'ont pas été exécutés » sur une session sans `terminal.tests_*` passerait
  s'il cite un chemin. Aucune sortie de ce passage ne le fait.
- les faux `error:`. `2ce34456` cite six références `error:` ; elles
  existent dans la vue, mais le validateur ne vérifie pas que « git add et
  git commit ont échoué » résume bien ces lignes.

## D1, D3, D5 après le prompt v3

- **D5 : plus aucune occurrence.** Aucun `open` ne parle de push comme d'un
  fait non accompli (6 sur 14 en v2 le matin, 9 sur 9 en réel au jour 2).
  `8faf4569` écrit « La commande git push a échoué » avec `error:git push` :
  c'est une observation réelle du terminal, pas D5.
- **D1 : réglé dans sa forme, pas jugé.** `eef4956b` ne recopie plus
  « la configuration de llm_max_tokens … » comme une observation : elle le
  déclare `carried_over` depuis `previous_summary:1` avec la raison
  « aucun événement sur la configuration ou le passage de référence dans la
  vue » — exactement l'attente. La fiche `show` le rendra comme repris,
  avec sa raison. Ce qui reste : rien ne garantit que la raison est vraie.
- **D3 : deux cas sur trois réglés, un déplacé.** `8af930d9` et
  `6a416635` rappellent la demande de l'agent comme `requested`,
  `d9877899` rend `[]` (ses deux commits traitent le point reçu, la
  demande d'agent n'est plus présentée comme état). Mais **`1e420dda`
  reprend le point PR #28 / migration en `carried_over`** depuis
  `previous_summary:0` — la demande d'agent, passée par le résumé de
  work-24, revient sous une nature légale. Le contrat l'accepte : il impose
  la déclaration, pas le jugement. L'attente le refuse (interdit
  `carried_over` et `PR #28`), et le point attendu (la divergence list/run,
  commit `f30781f`) manque. **D3 reste observable en forme déclarée sur ce
  cas ; il est visible dans la fiche, plus caché dans une phrase.**

Attentes annotées : **3 sur 4 conformes** (`eef4956b`, `8af930d9`,
`d9877899`), écart sur `1e420dda`. Le test `slow`
`test_an_eval_run_is_compared_to_the_annotated_expectations`, pointé sur ce
passage par `PULSE_EVAL_RUN`, échoue sur cette session : c'est le résultat
attendu, pas une régression du test.

Autres mouvements v2 → v3, à lire avec le corpus : `confidence` baisse d'un
cran sur quatre sessions (`247f2062`, `cda6ccce`, `eb652ce9`, `eef4956b`,
high → medium), `central_files` change d'un à deux chemins sur trois
sessions, toujours pris dans la vue ; `eb652ce9` produit cinq points
`observed` de forme identique (un par fichier) — valides, verbeux ;
`2ce34456` passe de « la création du .gitignore n'apparaît pas » (demande
lue comme état) à un point `requested` plus un point `observed` sur les
erreurs du terminal.

## Couverture conservée et limites

La suite rapide passe à **239 tests** (194 ce matin). La suite `slow`
couvre v1, v2 et v3 avec le vrai modèle, le refus de l'entrée de stress
(renommée `synthetic-114k.json`), le parcours CLI → MLX → Core, le tokenizer
réel sur les quatre sessions cibles et la comparaison d'un passage.
Validation finale : **6 tests `slow` passent en 187 s** (le septième, la comparaison d'un passage, est sauté sans `PULSE_EVAL_RUN`, et échoue comme attendu sur `1e420dda` quand il pointe sur ce passage), dont les **cinq tests utilisant réellement MLX**.

Non éprouvé par ce passage : la répétabilité (une génération par session,
argmax ; un second passage peut différer sur la prose et sur les preuves
citées), le comportement en réel avec des annexes `previous_summary` v3
(rendu « (repris : …) » redécoupé le lendemain), et l'activation : le
défaut de `Config` reste `v2`. Activer `v3` en dogfooding rendrait les
sessions déjà résumées candidates à nouveau (troisième résumé par session,
`intelligence/TODOS.md`).

## Reproduire

Depuis `intelligence/`, avec les poids en cache :

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TZ=Europe/Paris .venv/bin/python -m pytest -m slow -v
printf 'llm_provider = "mlx"\nmodel_id = "mlx-community/Qwen3.8-27B-4bit"\nprompt_version = "v3"\n' > /private/tmp/pulse-v3.toml
TZ=Europe/Paris HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -m pulse_intelligence.cli --config /private/tmp/pulse-v3.toml \
  eval --provider mlx --out /private/tmp/pulse-eval-v3-nouveau-passage
PULSE_EVAL_RUN=/private/tmp/pulse-eval-v3-nouveau-passage/mlx-mlx-community-Qwen3.8-27B-4bit \
  .venv/bin/python -m pytest -m slow tests/test_expectations.py -k compared
```

`eval` imprime l'écart aux attentes après le passage ; il n'écrit pas le pic
mémoire, mesuré ici autour de `MLXProvider.complete` (`run.log`,
`measurements.json`).
