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

### Le corpus `eval/` ne porte aucune session à `previous_summary`

**What:** Aucune des dix sessions gelées de `intelligence/eval/corpus/` n'a d'annexe `previous_summary` : la consigne du prompt v2 sur la réévaluation de `open` (défaut D1, `docs/dogfooding.md`) n'est pas mesurable par `pulse-intel eval`, seulement à l'œil sur le dogfooding. Ajouter au corpus, **hors gel** (les dix d'origine restent la référence de l'étape 3), une session réelle portant `previous_summary`, avec son `context` tel que Core l'a servi.

**Session désignée (jour 2) :** `1e420dda8b6eee77` (work-26 du 2026-09-05, 88 min), le cas D1 du jour 1 — son résumé v1 recopiait le `open` de work-24. Second cas, plus net : `eef4956b36dd37ce` (work-3 du 2026-09-06), seule session du jour 2 résumée **avec** annexe, où la v2 recopie encore le `open` précédent.

**Piège de capture :** dès qu'une session a un résumé, `GET /context?at=<sa fin>` rend **ce résumé-là** en `last_session_summary` (même instant), et `previous_summary_annex` l'écarte (même id) sans repli sur le précédent : l'annexe est vide. Vérifié par `input_hash` : la régénération v2 de `1e420dda` a tourné sans annexe. Pour geler l'entrée, prendre le contexte à un instant **strictement antérieur** à `last_activity_at` (ou avant tout résumé de la session), et le noter dans `eval/README.md`.

**Déclencheur:** jour 2 du dogfooding (2026-09-06) — les deux sessions existent.

**Effort:** S
**Priority:** P2
**Depends on:** —

### Deux résumés d'une même session coexistent après un changement de `prompt_version`

**What:** `summary_event_id(session_id, prompt_version, model_id)` fait qu'un changement de prompt rend candidates à nouveau les sessions déjà résumées (jour 2 : six sessions du 2026-09-05 régénérées en v2, trace append-only, aucune collision). Deux événements `session_summary` valides décrivent alors la même session. Rien ne dit lequel **fait foi** : `show <id>` rend le dernier émis localement, Core sert le dernier en `last_session_summary`, l'annexe `previous_summary` d'une session suivante prend celui que Core sert. Conséquence déjà vue : une régénération ne reçoit pas d'annexe (son propre résumé antérieur masque le précédent, voir l'entrée ci-dessus) — elle n'est donc pas comparable à l'original, l'entrée diffère.

**À définir à l'étape 5 :** la règle de préséance (dernier émis ? version de prompt la plus haute ? celle de la config courante ?), et si l'annexe doit remonter au résumé d'une **autre** session plutôt qu'au dernier tout court — ce qui demande soit une règle côté Intelligence sur `recent_sessions`, soit une route Core, gelé.

**Déclencheur:** étape 5 (service résident), ou le premier `show` trompeur.

**Effort:** M
**Priority:** P2
**Depends on:** Service résident

## Completed

### CI rouge : cinq tests de CLI dépendaient de la date du jour

**What:** Les vues rejouées par le faux Core sont ancrées sur `REFERENCE = 2026-09-02 16:00 UTC` et la fenêtre de sélection vaut « aujourd'hui plus la veille » (`lookback_days = 1`). La CLI lisait l'heure réelle, donc la suite passait le jour où elle a été écrite puis échouait deux jours plus tard : le 2026-09-05, `list`, `summarize --dry-run`, `run --once`, `show <id>` et le test de permissions ne trouvaient plus aucune session close. Vert sur ce commit exact le 2026-09-03, rouge le 2026-09-05, sans qu'une ligne de code ait bougé.

**Résolution:** L'horloge est gelée, pas les fixtures — décaler les dates n'aurait reporté la panne que de quelques mois. La couture d'injection existait déjà sous la CLI (`lookback_days`, `classify_sessions`, `find_session`, et `run_pass` qui accepte `now` depuis toujours) ; seule `cli.py` lisait l'heure en quatre endroits, dont un qui ne la transmettait pas à `run_pass`. Tout passe désormais par `cli._now()`, et les tests le remplacent par une fixture autouse ancrée sur `at(120)`. Ni freezegun ni dépendance nouvelle. Suite Intelligence à 62.

**Completed:** 2026-09-05
