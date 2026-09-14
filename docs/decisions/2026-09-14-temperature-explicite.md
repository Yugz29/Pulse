# Température explicite : 0.0 par défaut pour tous les providers

**Date :** 2026-09-14
**Statut :** tranchée, appliquée au merge de `fix/intelligence-comparabilite-modeles`
**Remplace :** le défaut « `llm_temperature` absente = non envoyée » de la spec
[`2026-09-05-llm-provider`](../specs/2026-09-05-llm-provider.md) (§5 et §9)
**Ferme :** issue #72

## Décision

`llm_temperature` vaut `0.0` par défaut dans `Config`. Une configuration
sans la clé, comme celle de production, envoie donc `0.0` à tous les
providers. Une valeur écrite dans `config.toml` reste prise telle quelle.

## Pourquoi

Absente, la température n'avait pas le même sens selon le provider : MLX
restait en argmax, sans sampler, et l'endpoint distant appliquait son propre
défaut, souvent 1.0. Deux modèles mesurés ainsi, l'un local et l'autre
distant, n'étaient pas comparables.

## Ce que chaque provider en fait

- **MLX** : `make_sampler(temp=0.0)`, qui rend l'argmax dans `mlx-lm` 0.31.3,
  épinglé dans la même PR. C'est le décodage d'avant : les résumés locaux ne
  changent pas, seule la ligne stderr passe de `temperature=absente` à
  `temperature=0.0 (sampler)`.
- **Endpoint compatible OpenAI** : `temperature: 0.0` part dans la requête ;
  ce que le serveur en fait dépend de son implémentation. S'il la refuse par
  un 400 qui la nomme, le provider la retire une fois et l'inscrit dans
  `dropped_parameters`, reporté par session dans le `meta.json` d'`eval`.
- **Faux provider** : reçoit la valeur et l'enregistre, sans effet.

## Conséquences

- L'absence d'envoi ne se configure plus, TOML n'ayant pas de valeur nulle.
  `CompletionRequest(temperature=None)` reste possible pour un appel direct.
- L'autre piste de l'issue, tracer « défaut du provider » dans stderr et
  `meta.json`, devient sans objet.
- `0.0` réduit l'aléa sans garantir la reproductibilité : prompt, modèle,
  poids, runtime et serveur comptent aussi.
