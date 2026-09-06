# Modèle local du résumé de session : Qwen3.8-27B-4bit pour le dogfooding

**Date :** 2026-09-06
**Statut :** tranchée
**Spec :** [`../specs/2026-09-05-llm-provider.md`](../specs/2026-09-05-llm-provider.md) (v2)
**Rapport :** passage `eval` sur les dix sessions gelées, comparé à une
référence distante ; spike B mémoire. Chiffres reproductibles via
`pulse-intel eval --provider mlx` et `eval/stress/synthetic-60k.json` (renommé
`synthetic-114k.json` le 2026-09-07 : 113 928 tokens réels).

## Décision

Le résumé de session tourne, pour le dogfooding (pas 3, étapes 4-5), sur
**`mlx-community/Qwen3.8-27B-4bit`** servi par `mlx-lm` sur Apple Silicon,
thinking désactivé. Le choix est réversible d'une ligne de config
(`llm_provider`, `model_id`) : c'est tout l'objet de la couche `LLMProvider`.

## Ce qui fonde la décision

### Comparaison Qwen local vs référence distante, sur les 10 du corpus

Modèle de référence : **`claude-sonnet-5`** (servi par un endpoint distant
compatible OpenAI). Nommé ici pour que le tableau soit reproductible sans
rouvrir le `meta.json` du passage.

```
                       référence   Qwen local
valides                   9/10         8/10
rejets (garde-fou)          1            2
confidence, succès partagés     coïncide partout (high/high, medium/medium)
durée par session         3,7–14,8 s   22–187 s   (5 à 30× plus lent)
```

- **Qualité** : là où les deux réussissent, Qwen tient. Les `confidence`
  coïncident sur chaque succès partagé ; sur la session Context API (`3cabaefb`,
  la plus grosse) les `central_files` de Qwen sont **identiques** à la
  référence ; les reprises sont justes et concises.
- **Le garde-fou anti-hallucination protège la trace quel que soit le modèle** :
  sur la session la plus ambiguë (`2ce34456`, 4 projets, 0 fichier), les deux
  modèles inventent un chemin et sont **rejetés** — rien n'est stocké.

### Spike B — mémoire (critère n°3 requalifié)

```
#1 réel (20 901 tokens)  pic  19,77 Go   OK    ← la plus grosse session réelle
synthétique 60k tokens   pic  27,98 Go   OOM   ← [METAL] Insufficient Memory
```

Le critère n°3 de la spec (« tenir avec une session de 60k tokens ») **n'est
pas tenu** par ce modèle sur 36 Go : une entrée de 60k tokens fait planter Metal
en OOM avant la fin du prefill. Il est **requalifié en plafond connu** : sur du
réel (≤ 20 901 tokens sur 90 jours de trace, `prompt_tokens` réel de `#1` —
les « 6 369 » des premiers passages étaient une estimation `len/4`, fausse
×3,3), Qwen tient ; au-delà de ~30k tokens d'entrée, `MLXProvider` **refuse
proprement** avant le prefill (`llm_max_input_tokens`, défaut 30 000), plutôt
que de laisser Metal planter. Le refus est bruyant : ligne `failed` en erreur
dans la sortie de `run` (donc dans `run.log` sous launchd).

La plus grosse session réelle est à 21k sur 30k : **1,4× de marge, pas dix**.
Le plafond reste à 30 000 jusqu'à un **spike B v2** (prompt v2, mesure du pic
entre 21k et 30k) ; la remesure du pic 27B en v2 a échoué deux fois le
2026-09-06 sur une erreur GPU Metal (`GPU Hang Error`, puis `victim of GPU
error/recovery`), sans OOM ni processus résiduel — **à remesurer**, sans plus.

## Les deux réserves écrites

1. **Hallucination sur les sessions sans fichier.** Là où la référence laisse
   `central_files: []` honnêtement, Qwen invente un chemin plausible (`#6`,
   holbertonschool, 0 fichier : `front_end-frameworks/react/vite.config.js`).
   Le garde-fou le rejette, donc rien de faux n'entre en base — mais une session
   sans fichier a plus de chances de ne produire **aucun** résumé avec le modèle
   local qu'avec la référence. Piste : une v2 du prompt durcissant la consigne
   « liste vide plutôt qu'inventé », mesurée sur le corpus — itération séparée,
   hors de ce lot.

2. **Plafond mémoire à ~30–40k tokens d'entrée.** Une session qui dépasserait
   ce seuil échouerait en local (refus explicite) là où la référence distante
   passerait. Non bloquant tant que le réel reste dix fois plus bas ; à
   rouvrir si une session longue réelle s'en approche.

## Plan B : `mlx-community/Qwen3.5-9B-4bit`

Mesuré le 2026-09-06 sur le corpus, prompt v2, contre le 27B :

```
                       27B            9B
valides                10/10          9/10   (#8 : chemin inventé, rejeté)
confidence = 27B         —            7/9 succès partagés
durée corpus           668 s          177 s  (×3,8 plus rapide)
pic mémoire, #1        19,77 Go       7,99 Go
poids                  14 Go          5,6 Go
```

Rapide et léger, il tient sur une machine à 16 Go. Mais sur les grosses
sessions ses `central_files` recoupent moins la référence (`eb652ce9` 1/5
contre 3/5 pour le 27B) et son `open` **invente des intentions** que l'entrée ne
porte pas (« la persistance des états des workspaces entre les redémarrages »
sur `247f2062`), là où le 27B reste factuel (« aucun push observé ; suite de
tests non exécutée »). **Le 27B reste le modèle du dogfooding** ; le 9B est le
repli si la mémoire ou la durée deviennent le problème — une ligne de config.

## Vérifié au premier chargement

`Qwen3.8-27B` est multimodal (`model_type: qwen3_5`) ; le point d'attention de
la spec est levé : `mlx-lm` 0.31.3 le charge **en texte seul**, sans processeur
de vision, et `enable_thinking=False` produit une sortie **sans aucun bloc de
réflexion** (vérifié en test `slow`). Chargement à froid ~6 s depuis le cache,
14 Go de poids.

## Ce qui suit

- **Étape 4 (dogfooding)** : `pulse-intel run` chaque soir sur les vraies
  sessions, `show latest` chaque matin, cinq jours.
- **Étape 5 (service résident)** : seulement si quatre reprises sur cinq sont
  jugées justes et utiles au terme des cinq jours (critère du §12 de la spec du
  2026-09-03). Sinon on itère prompt/modèle sur `eval`, et le service attend.
