# TODOS — Intelligence

## Résumé de session

### `show <id>` lit l'état local avant Core

**What:** `show <id>` lit d'abord la copie locale de l'événement émis, puis Core en repli (`/context.last_session_summary` seulement, Core n'a pas de route par identifiant). À l'étape 5 (service résident), décider si l'API doit vérifier contre Core pour voir les résumés produits par d'autres processus.

**Déclencheur:** étape 5 du §12 de `docs/specs/2026-09-03-session-summary.md`.

**Effort:** S
**Priority:** P3
**Depends on:** Service résident

## Completed

### CI rouge : cinq tests de CLI dépendaient de la date du jour

**What:** Les vues rejouées par le faux Core sont ancrées sur `REFERENCE = 2026-09-02 16:00 UTC` et la fenêtre de sélection vaut « aujourd'hui plus la veille » (`lookback_days = 1`). La CLI lisait l'heure réelle, donc la suite passait le jour où elle a été écrite puis échouait deux jours plus tard : le 2026-09-05, `list`, `summarize --dry-run`, `run --once`, `show <id>` et le test de permissions ne trouvaient plus aucune session close. Vert sur ce commit exact le 2026-09-03, rouge le 2026-09-05, sans qu'une ligne de code ait bougé.

**Résolution:** L'horloge est gelée, pas les fixtures — décaler les dates n'aurait reporté la panne que de quelques mois. La couture d'injection existait déjà sous la CLI (`lookback_days`, `classify_sessions`, `find_session`, et `run_pass` qui accepte `now` depuis toujours) ; seule `cli.py` lisait l'heure en quatre endroits, dont un qui ne la transmettait pas à `run_pass`. Tout passe désormais par `cli._now()`, et les tests le remplacent par une fixture autouse ancrée sur `at(120)`. Ni freezegun ni dépendance nouvelle. Suite Intelligence à 62.

**Completed:** 2026-09-05
