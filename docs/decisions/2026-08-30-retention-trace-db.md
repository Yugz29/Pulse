# Rétention de trace.db — conservation infinie du brut

**Date :** 2026-08-30
**Statut :** tranchée (porte à sens unique)
**Source :** `core/TODOS.md`, section « Completed », et item sentinelle P4
« Réexamen rétention trace.db »

## Décision

- Le brut de `~/.pulse_v2/trace.db` est conservé indéfiniment. Aucune purge,
  aucun résumé de substitution.
- Les transcripts d'agents (Claude Code, Codex) n'entrent jamais en brut dans
  `trace.db` : un événement dérivé `agent_session` par session, plus une
  archive zstd séparée dans `~/.pulse_v2/transcript_archive`.

## Pourquoi

- Mesures réelles : `trace.db` pesait 3,1 Mo, ~45 Ko par jour actif. Le
  problème de rétention n'existe pas dans les données actuelles ; la colonne
  `occurred_at_utc` et le cache par jour de `/days` ont réglé les coûts de
  lecture.
- Le brut est la valeur du produit : une mémoire fidèle. Un résumé n'est pas
  temporellement stable, et « purger une fois le résumé fiable » a un critère
  de sortie invérifiable.
- Les transcripts d'agents (50 à 85 Mo par jour chargé) sont la seule source
  qui changerait l'ordre de grandeur ; d'où le dérivé plus l'archive.

## Réexamen

Uniquement si un seuil falsifiable est franchi : `trace.db` > 500 Mo, rendu
d'une page > 1 s malgré le cache, audit `audit_secrets.py` > 60 s, ou archive
de transcripts > 2 Go. Premier levier le cas échéant : compaction des
micro-événements `app_activated`, jamais les résumés.
