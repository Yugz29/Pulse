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
