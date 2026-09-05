# TODOS — Intelligence

## Résumé de session

### `show <id>` lit l'état local avant Core

**What:** `show <id>` lit d'abord la copie locale de l'événement émis, puis Core en repli (`/context.last_session_summary` seulement, Core n'a pas de route par identifiant). À l'étape 5 (service résident), décider si l'API doit vérifier contre Core pour voir les résumés produits par d'autres processus.

**Déclencheur:** étape 5 du §12 de `docs/specs/2026-09-03-session-summary.md`.

**Effort:** S
**Priority:** P3
**Depends on:** Service résident

### `list` et `run` ne jugent pas « déjà résumée » avec le même modèle

**What:** `run_list` appelle `classify_sessions(model_id=config.model_id or "fake/summarizer")`, alors que `run_pass` utilise `summarizer.model_id`, c'est-à-dire le modèle réellement servi par le provider (PR 2 de l'étape 3). Les deux coïncident dès que `model_id` est renseigné dans `config.toml` — ce que `require_model()` encourage déjà. Ils divergent quand `PULSE_LLM_MODEL` surcharge un `model_id` différent : `list` peut alors annoncer candidate une session que `run` considère déjà résumée, et inversement. Affichage seulement : aucune émission, aucun état local n'en dépend.

**Pourquoi ce n'est pas corrigé :** aligner `list` sur le modèle réellement servi obligerait à construire le provider, donc à exiger les trois variables d'environnement pour une commande de lecture seule. Le repli `"fake/summarizer"` en dur dans `run_list` est le vrai reste à traiter.

**Déclencheur:** un `list` trompeur observé en usage réel, ou l'étape 5 (service résident) qui rendra la question structurante.

**Effort:** S
**Priority:** P3
**Depends on:** Cas réel observé

## Completed

### CI rouge : cinq tests de CLI dépendaient de la date du jour

**What:** Les vues rejouées par le faux Core sont ancrées sur `REFERENCE = 2026-09-02 16:00 UTC` et la fenêtre de sélection vaut « aujourd'hui plus la veille » (`lookback_days = 1`). La CLI lisait l'heure réelle, donc la suite passait le jour où elle a été écrite puis échouait deux jours plus tard : le 2026-09-05, `list`, `summarize --dry-run`, `run --once`, `show <id>` et le test de permissions ne trouvaient plus aucune session close. Vert sur ce commit exact le 2026-09-03, rouge le 2026-09-05, sans qu'une ligne de code ait bougé.

**Résolution:** L'horloge est gelée, pas les fixtures — décaler les dates n'aurait reporté la panne que de quelques mois. La couture d'injection existait déjà sous la CLI (`lookback_days`, `classify_sessions`, `find_session`, et `run_pass` qui accepte `now` depuis toujours) ; seule `cli.py` lisait l'heure en quatre endroits, dont un qui ne la transmettait pas à `run_pass`. Tout passe désormais par `cli._now()`, et les tests le remplacent par une fixture autouse ancrée sur `at(120)`. Ni freezegun ni dépendance nouvelle. Suite Intelligence à 62.

**Completed:** 2026-09-05
