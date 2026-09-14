# Benchmark de modèles : le verdict se prend en local

**Date :** 2026-09-14
**Statut :** tranchée ; benchmark pas encore lancé
**Voir :** [modèle local du 2026-09-06](2026-09-06-modele-local-qwen.md),
[température explicite](2026-09-14-temperature-explicite.md)

## Décision

Le modèle du résumé de session se départage en local, en MLX 4-bit, sur le
corpus `intelligence/eval/` (`observed/`, 14 sessions). Deux candidats et un
étalon :

- **`gemma-4-26b-a4b-it`** (`mlx-community/gemma-4-26b-a4b-it-4bit`,
  15,4 Go) : 3,8 Md de paramètres actifs, réflexion sur demande.
- **`Ministral-3-14B-Instruct-2512`**
  (`mlx-community/Ministral-3-14B-Instruct-2512-4bit`, 8,5 Go) : dense.
- **Étalon** : le modèle de production, `mlx-community/Qwen3.8-27B-4bit`,
  rejoué sur le même corpus.

## Pourquoi pas de dépistage à distance

Le dépistage devait d'abord passer par le routeur distant. Sur les cinq
candidats initiaux, trois ne sont plus servis en serverless : Llama 3.1 8B,
Mistral Nemo et Gemma 3 27B. Deux d'entre eux, dont Gemma 3 27B, sont routés
en silence vers un autre modèle : on mesurerait Gemma 4 en croyant mesurer
Gemma 3. Le passage ne le montrerait pas, car le `meta.json` d'`eval` inscrit
l'identifiant demandé, pas le modèle servi.

## Candidat écarté après chiffrage

`qwen3.6-35b-a3b` : pic estimé à 23-25 Go, contre 21,6 Go mesurés le
2026-09-14 pour le modèle de production. Il demanderait donc plus de mémoire
qu'aujourd'hui. Sa réflexion est active par défaut, et sa fiche le destine à
l'agent et au code.

## Avertissement `fix_mistral_regex` sur Ministral : faux positif

- **Faux positif.** transformers 5.16.1 annonce une tokenisation fausse en ne
  lisant que `config.json` : `transformers_version` y vaut `5.0.0.dev0`,
  antérieur à `5.0.0` selon PEP 440. La regex de `tokenizer.json` est déjà le
  `pattern` de `tekken.json`, celle que le drapeau substituerait. Le drapeau
  n'est passé nulle part : sur une copie de Gemma 4 ou de Qwen privée de
  `transformers_version`, il change la tokenisation (16 et 7 textes sur 16).
- **Mesure du 2026-09-15.** Avec et sans `fix_mistral_regex=True`, même
  tokenizer sérialisé et mêmes identifiants de tokens pour Ministral, Gemma 4
  et le Qwen de production, sur les 14 sessions d'`eval/observed`, le prompt
  v7 et une ligne d'essai (environ 300 000 tokens par modèle).
- **Rejeu.** transformers 5.16.1, tokenizers 0.23.2, mlx-lm 0.31.3, hors
  ligne : `corpus/docs/audits/2026-09-15-benchmark-modeles/regex_flag.py`
  charge chaque tokenizer par `mlx_lm.utils.load_tokenizer`, avec et sans le
  drapeau, et compare `backend_tokenizer.to_str()` et les identifiants.
- **Limite.** Aucune comparaison avec `mistral-common`, non installé : la
  concordance avec le tokenizer de référence de Mistral repose sur l'identité
  des regex, pas sur une tokenisation mesurée contre lui.
