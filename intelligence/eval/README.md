# Corpus d'évaluation — `intelligence/eval/`

Dix sessions **réelles gelées**, tirées des 90 jours de trace, pour comparer un
modèle à une référence sur les mêmes entrées. Le corpus est figé : on ne le
retouche pas d'un passage à l'autre, sinon la comparaison ne veut plus rien
dire (règle du pas 3, spec `docs/specs/2026-09-03-session-summary.md` §11).

## `corpus/` — les dix sessions

Chaque fichier `<session_id>.json` fige, pour une session :

- `session_raw` — la vue de session rendue par Core, intacte ;
- `context` — le `GET /context` à l'instant de fin de la session ;
- `why` — pourquoi elle est au corpus.

`eval` reconstruit l'entrée exacte du modèle par le même code que la production
(`build_model_input`, `serialize_input`, `input_paths`) : aucune trace ni
daemon nécessaire, la reproduction est hors ligne.

La diversité visée : trois projets au moins (Pulse, core, Cortex, DevNote,
holbertonschool…), étalement de juillet à septembre, une longue et une courte,
au moins une avec `agent_session`, une avec `git_commit`, une « bruyante »
(beaucoup d'apps, peu de fichiers) et une volontairement ambiguë (quatre
projets, zéro fichier).

## `stress/` — l'entrée synthétique

`synthetic-60k.json` **n'est pas une vraie session** et n'entre jamais dans le
corpus. Le réel plafonne à 20 901 tokens (`prompt_tokens` de `meta.json`, `3cabaefb`) ; le critère n°3 de la spec (« tenir
avec une session de 60k tokens ») ne s'éprouve donc que sur cette entrée
fabriquée, réservée au spike B (mesure mémoire du `MLXProvider`). Elle porte des
marqueurs `_synthetic` pour qu'on ne la confonde jamais avec du réel, et ne sert
jamais à juger la qualité d'un résumé.

## `out/` — les sorties (non versionnées)

`pulse-intel eval --provider …` écrit sous `out/<provider>-<model>/` un résultat
par session plus un `meta.json` de passage (durées, tokens, `dropped_parameters`).
Ce dossier est ignoré par git : c'est un artefact de passage, régénérable.

## Lancer

```sh
pulse-intel --config … eval --provider openai-compatible
```

Pas de score automatique : `eval` produit les fichiers, la comparaison
local ↔ référence se fait à l'œil. Le rapport d'un passage est joint à la PR
qui change le prompt ou le modèle.
