# Modèle local du résumé de session : Qwen3.8-27B-4bit pour le dogfooding

**Date :** 2026-09-06
**Statut :** tranchée
**Spec :** [`../specs/2026-09-05-llm-provider.md`](../specs/2026-09-05-llm-provider.md) (v2)
**Rapport :** passage `eval` sur les dix sessions gelées, comparé à une
référence distante ; spike B mémoire. Chiffres reproductibles via
`pulse-intel eval --provider mlx` et `eval/stress/synthetic-60k.json`.

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
#1 réel (6 369 tokens)   pic  19,77 Go   OK    ← la plus grosse session réelle
synthétique 60k tokens   pic  27,98 Go   OOM   ← [METAL] Insufficient Memory
```

Le critère n°3 de la spec (« tenir avec une session de 60k tokens ») **n'est
pas tenu** par ce modèle sur 36 Go : une entrée de 60k tokens fait planter Metal
en OOM avant la fin du prefill. Il est **requalifié en plafond connu** : sur du
réel (≤ ~6 500 tokens sur 90 jours de trace), Qwen tient largement ; au-delà de
~30k tokens d'entrée, `MLXProvider` **refuse proprement** avant le prefill
(`llm_max_input_tokens`, défaut 30 000), plutôt que de laisser Metal planter.

Le corpus réel plafonnant dix fois sous ce seuil, la limite est théorique en
pratique — mais écrite, pas découverte un soir de dogfooding.

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
