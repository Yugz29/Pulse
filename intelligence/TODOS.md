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

### L'annexe `previous_summary` dépend du fuseau de la machine

**What:** `previous_summary_annex` ne garde le résumé précédent que s'il s'est terminé le même jour **local** que la session (`ended.astimezone().date() == session.day`), et le jour local vient du fuseau du processus. La même vue Core donne donc une entrée différente — et un autre `input_hash` — selon le fuseau : sur la PR #53, le test de l'extension du corpus était vert à Paris et rouge sur le runner en UTC (`a0aacd1f` finit le 05 à 22:39 UTC, le 06 à Paris). En production le fuseau est celui du poste, stable ; c'est la reproductibilité de `eval` hors du poste qui est en cause. Contournement : le test rejoue le corpus dans son fuseau de capture (`TZ=Europe/Paris`). À trancher : fixer le fuseau de la règle (celui du `context.timezone` servi par Core, plutôt que celui du processus).

**Déclencheur:** `eval` lancé hors du poste (CI, autre machine), ou tout changement de `previous_summary_annex`.

**Effort:** S
**Priority:** P3
**Depends on:** —

### Deux résumés d'une même session coexistent après un changement de `prompt_version`

**What:** `summary_event_id(session_id, prompt_version, model_id)` fait qu'un changement de prompt rend candidates à nouveau les sessions déjà résumées (jour 2 : six sessions du 2026-09-05 régénérées en v2, trace append-only, aucune collision). Deux événements `session_summary` valides décrivent alors la même session. Rien ne dit lequel **fait foi** : `show <id>` rend le dernier émis localement, Core sert le dernier en `last_session_summary`, l'annexe `previous_summary` d'une session suivante prend celui que Core sert. Conséquence déjà vue : une régénération ne reçoit pas d'annexe (son propre résumé antérieur masque le précédent, voir l'entrée ci-dessus) — elle n'est donc pas comparable à l'original, l'entrée diffère.

**À définir à l'étape 5 :** la règle de préséance (dernier émis ? version de prompt la plus haute ? celle de la config courante ?), et si l'annexe doit remonter au résumé d'une **autre** session plutôt qu'au dernier tout court — ce qui demande soit une règle côté Intelligence sur `recent_sessions`, soit une route Core, gelé.

**Déclencheur:** étape 5 (service résident), ou le premier `show` trompeur.

**Effort:** M
**Priority:** P2
**Depends on:** Service résident

### `details.workspace` peut désigner la session suivante (`1f931a43`, 2026-09-06)

**What:** Le résumé v2 de `1f931a43c3b7149f` (work-4 du 2026-09-06, 07:44–08:47 UTC) porte `structured.project: "Pulse"` — juste, la vue dit `projects: ["Pulse"]` et les fichiers sont sous `intelligence/` — mais `details.workspace: /Users/Yugz/Projets/Cortex`. Diagnostic (trace relue en lecture seule le 2026-09-07) : `last_activity_at` de la session vaut `08:47:25.998428`, qui est l'horodatage d'un `file_changed` **dans Cortex** (`electron.vite.config.…`, premier événement du travail suivant) que la reconstruction du jour a absorbé dans work-4 par la règle de proximité temporelle. `summarize_session` lit `GET /context?at=<last_activity_at>` ; à cet instant précis, `_select_current_session` de Core rend une session **ouverte** dans Cortex (work-5, `projects: ["Cortex"]`) et `workspace.resolution: "session"` suit cette session — alors qu'à `at − 1 s`, la session courante est bien work-4 et le workspace Pulse. `details.workspace` vient de ce `context.workspace.path` ; `structured.project` vient du modèle, qui lit la vue. Les deux routes de Core ne s'accordent donc pas sur l'appartenance de l'événement frontière (même famille que le défaut 1 de l'audit 2026-09-06 : `is_open` selon la route lue), et Intelligence prend le workspace de l'instant sans vérifier qu'il est celui de la session résumée. Aucune donnée n'a été modifiée : le résumé émis reste tel quel, `input_hash` compris.

**Correction proposée (Intelligence, sans toucher Core) :** dans `summarize_session`, ne retenir `context.workspace.path` que si `context.current_session.id == session.id` (ou si `workspace.resolution` n'est pas `"session"`) ; sinon omettre `details.workspace` (champ optionnel) et l'écrire sur stderr. Variante : lire le contexte à `last_activity_at − 1 µs`, comme la capture du corpus le fait à fin − 1 s — mais cela change l'`input_hash` de tous les résumés à venir pour un cas frontière. Côté Core (gelé, correctif possible) : à `at == last_activity_at` d'une session close, `_select_current_session` devrait rendre cette session, cohérente avec `/context/sessions`. Le résumé de `1f931a43` n'est pas à réécrire : une régénération sous la même identité serait refusée (409), et le champ n'entre pas dans la reprise.

**Déclencheur:** validation de la correction par l'utilisateur ; ou un second cas de workspace incohérent.

**Effort:** S
**Priority:** P2
**Depends on:** —

## Completed

### Le corpus `eval/` ne porte aucune session à `previous_summary`

**What:** Aucune des dix sessions gelées n'avait d'annexe `previous_summary` : la consigne du prompt v2 sur la réévaluation de `open` (défaut D1) n'était mesurable qu'à l'œil sur le dogfooding.

**Résolution:** Deux sessions réelles ajoutées à `eval/corpus/`, hors gel (champ `added = "2026-09-06"`, les dix d'origine restent la référence) : `1e420dda8b6eee77` (cas D1 du jour 1) et `eef4956b36dd37ce` (cas D1 du jour 2). Contexte pris à fin − 1 s pour contourner le piège de capture (le résumé de la session elle-même masque le précédent) ; règle notée dans `eval/README.md`. L'entrée de `eef4956b` reproduit l'`input_hash` du résumé v2 émis.

**Completed:** 2026-09-06

### CI rouge : cinq tests de CLI dépendaient de la date du jour

**What:** Les vues rejouées par le faux Core sont ancrées sur `REFERENCE = 2026-09-02 16:00 UTC` et la fenêtre de sélection vaut « aujourd'hui plus la veille » (`lookback_days = 1`). La CLI lisait l'heure réelle, donc la suite passait le jour où elle a été écrite puis échouait deux jours plus tard : le 2026-09-05, `list`, `summarize --dry-run`, `run --once`, `show <id>` et le test de permissions ne trouvaient plus aucune session close. Vert sur ce commit exact le 2026-09-03, rouge le 2026-09-05, sans qu'une ligne de code ait bougé.

**Résolution:** L'horloge est gelée, pas les fixtures — décaler les dates n'aurait reporté la panne que de quelques mois. La couture d'injection existait déjà sous la CLI (`lookback_days`, `classify_sessions`, `find_session`, et `run_pass` qui accepte `now` depuis toujours) ; seule `cli.py` lisait l'heure en quatre endroits, dont un qui ne la transmettait pas à `run_pass`. Tout passe désormais par `cli._now()`, et les tests le remplacent par une fixture autouse ancrée sur `at(120)`. Ni freezegun ni dépendance nouvelle. Suite Intelligence à 62.

**Completed:** 2026-09-05
