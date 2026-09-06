# Corpus d'évaluation — `intelligence/eval/`

Dix sessions **réelles gelées**, tirées des 90 jours de trace, pour comparer un
modèle à une référence sur les mêmes entrées. Le corpus est figé : on ne le
retouche pas d'un passage à l'autre, sinon la comparaison ne veut plus rien
dire (règle du pas 3, spec `docs/specs/2026-09-03-session-summary.md` §11).

## `corpus/` — les dix sessions, plus l'extension

Chaque fichier `<session_id>.json` fige, pour une session :

- `session_raw` — la vue de session rendue par Core, intacte ;
- `context` — le `GET /context` à l'instant de fin de la session ;
- `why` — pourquoi elle est au corpus ;
- `added` — date d'ajout, **seulement** pour une entrée hors gel.

Les dix d'origine (sans `added`) sont la référence de l'étape 3 et ne bougent
pas. **Extension du 2026-09-06**, hors gel, quatre sessions du dogfooding
(`docs/dogfooding.md`) : `1e420dda8b6eee77` (work-26 du 05) et
`eef4956b36dd37ce` (work-3 du 06), les deux cas D1 — les seules entrées à
annexe `previous_summary` ; `8af930d9ef437d2a` (work-2 du 05) et
`d98778994319cd07` (work-24 du 05), deux des quatre cas D3 — leur annexe
`agent_session` porte la demande initiale « vérifier l'état de la PR #28… »
que le résumé v2 recopiait en point ouvert. Sans elles, ni D1 ni D3 ne sont
mesurables par `eval`.

Piège de capture pour une session déjà résumée : `GET /context?at=<fin>` rend
en `last_session_summary` le résumé de la session *elle-même*, que
`previous_summary_annex` écarte sans repli — l'annexe serait vide. Le
contexte de l'extension est donc pris à **fin − 1 s**. Pour `eef4956b`,
l'entrée ainsi reconstruite reproduit exactement l'`input_hash` du résumé v2
émis au jour 2 ; pour `1e420dda`, elle diffère des deux résumés émis (le v1
avait reçu la v1 de work-24, Core sert aujourd'hui sa v2 ; le v2 n'avait
reçu aucune annexe).

`eval` reconstruit l'entrée exacte du modèle par le même code que la production
(`build_model_input`, `serialize_input`, `input_paths`) : aucune trace ni
daemon nécessaire, la reproduction est hors ligne.

La diversité visée : trois projets au moins (Pulse, core, Cortex, DevNote,
holbertonschool…), étalement de juillet à septembre, une longue et une courte,
au moins une avec `agent_session`, une avec `git_commit`, une « bruyante »
(beaucoup d'apps, peu de fichiers) et une volontairement ambiguë (quatre
projets, zéro fichier).

## `expected/` — les attentes annotées

Un fichier par session cible du schéma `open` v3 (`1e420dda`, `eef4956b`,
`8af930d9`, `d9877899`) : le `open` attendu, chaque point avec sa nature, ses
preuves et un `why` ; `optional` pour les points acceptables sans être exigés ;
`must_not` pour les motifs interdits (`kind`, `carried_from`, `text_matches`),
justifiés. Un test rapide vérifie que chaque attente est elle-même une sortie
v3 valide pour son entrée. La comparaison (`compare_open`) retrouve un point
par sa nature et ses preuves, jamais par sa prose ; `eval` l'imprime après un
passage v3.

## `stress/` — l'entrée synthétique

`synthetic-114k.json` (ex-`synthetic-60k.json`, renommé le 2026-09-07 d'après
sa taille réelle : 113 928 tokens avec le tokenizer Qwen et le prompt v2)
**n'est pas une vraie session** et n'entre jamais dans le corpus. Le réel plafonne à 20 901 tokens (`prompt_tokens` de `meta.json`, `3cabaefb`) ; le critère n°3 de la spec (« tenir
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
