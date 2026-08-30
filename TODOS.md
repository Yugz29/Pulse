# TODOS

## Daemon V2

### Exécution récurrente des producteurs agent (launchd/cron)

**What:** Brancher l'exécution récurrente de `archive_transcripts` PUIS `agent_sessions`, dans cet ordre (l'archive d'abord, le pointeur ensuite). Le backfill initial est fait (2026-08-30) : 152 sessions sur 74 jours livrées, 0 dead-letter.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Réexamen rétention trace.db — déclencheurs falsifiables

**What:** La rétention infinie du brut (décision du 2026-08-30) se rouvre UNIQUEMENT si un de ces seuils mesurables est franchi : `trace.db` > 500 Mo ; ou latence de rendu d'une page > 1 s malgré le cache /days ; ou l'audit `scripts/audit_secrets.py` > 60 s. Premier levier si ça arrive : compaction des micro-événements `app_activated` (68 % des lignes, 20 octets pièce) — pas les résumés.

**Effort:** —
**Priority:** P4 (veille)
**Depends on:** Aucun — item sentinelle, ne pas implémenter

### Remplacer le polling du file watcher par watchdog/FSEvents

**What:** Migrer `file_watcher.py` du re-scan complet par seconde (`os.walk` + `stat`) vers la bibliothèque `watchdog` (FSEvents natif macOS).

**Why:** Le scan par seconde coûte CPU/batterie en continu sur un gros workspace ; FSEvents est le mécanisme éprouvé [Layer 1] exact pour ce besoin, avec un coût quasi nul au repos et sans la fenêtre d'1 s où création+suppression rapide passe inaperçue.

**Context:** Introduit une dépendance externe (le projet n'en a que Flask) et watchdog a ses propres pièges (événements groupés, renames). À faire APRÈS le chantier outbox du file watcher (décision 2A-révisée) — ne jamais mélanger changement de transport et changement de mécanisme de détection dans le même diff (règle de Beck : structurel et comportemental séparés).

**Effort:** M
**Priority:** P4
**Depends on:** Chantier 2A-révisée (file_watcher via outbox) — livré le 2026-08-30, débloqué

## Completed

### Ingestion des sessions agent (Claude Code / Codex) en événements dérivés

**What:** Nouvelle source pour le journal : un événement `agent_session` par session terminée, sans que le brut des transcripts n'entre jamais dans `trace.db`.

**Résolution:** Producteur `daemon_v2/agent_sessions.py` — parseurs déterministes des deux formats (Claude Code : lignes typées user/assistant ; Codex : enveloppe timestamp/type/payload), résumé versionné `summary_version: 1` calculé UNE fois (une session qui regrossit après émission est signalée, jamais ré-émise), premier prompt rédigé par `redact_command` (producteur ET ingestion, défense en profondeur), `event_id` uuid5 déterministe (ré-émission = duplicate), fenêtre de silence 60 min avant émission, manifeste producteur, payload canonique via `enqueue_json_input` (chemin de l'observateur Swift, validation incluse). Côté daemon : type `agent_session` supporté, branche `normalize_activity` (validation stricte), `workspace` lu par le résolveur 5A, et activité « forte » dans la timeline (preuve = transcript réel sur disque) — les sessions agent forment de vraies sessions de travail attribuées au projet, changement additif (aucune donnée historique de ce type). Dry-run réel : 173 sessions émissibles, 1 active retenue par la fenêtre. 15 tests, suite à 397.

**Completed:** 2026-08-30

### Archivage compressé des transcripts agent

**What:** Copie zstd des `.jsonl` de sessions vers un dossier d'archive avant leur purge par les outils sources — préalable à l'ingestion `agent_session`.

**Résolution:** `scripts/archive_transcripts.py` — `compression.zstd` stdlib (Python 3.14, zéro dépendance), lecture seule sur les sources, écritures atomiques, reruns idempotents via manifeste (taille + mtime_ns), garde anti-troncature (une source rétrécie n'écrase jamais une archive plus complète — un transcript est append-only par nature), manifeste corrompu = erreur d'infrastructure exit 2 (convention audit_secrets). Archive : `~/.pulse_v2/transcript_archive` (`PULSE_TRANSCRIPT_ARCHIVE_PATH`). Premier archivage réel : 174 fichiers, 839 Mo → 220 Mo (26 %) en 8,6 s ; idempotence vérifiée sur données réelles. 8 tests. Reste à planifier l'exécution récurrente (cron/launchd) — trivial, à brancher avec l'ingestion `agent_session`.

**Completed:** 2026-08-30

### Politique de rétention / purge de trace.db — tranchée

**What:** Décision produit sur la rétention de `trace.db` (porte à sens unique), à trancher avant l'ingestion des transcripts agent.

**Résolution (décision du 2026-08-30, sur mesures réelles) :** `trace.db` = 3,1 Mo, ~45 Ko/jour actif (~1,5 Mo/mois) — le problème de rétention n'existe pas dans les données actuelles, et 10A/11A ont réglé les coûts de lecture. Politique : **rétention infinie du brut, aucune purge, aucun résumé** (le brut est la valeur du produit — mémoire fidèle ; un résumé n'est pas temporellement stable et « purger une fois le résumé fiable » a un critère de sortie invérifiable). Les transcripts agent (50–85 Mo/jour chargé) n'entrent jamais en brut : événement `agent_session` dérivé + archivage fichier zstd (voir items actifs). Réexamen uniquement sur seuils falsifiables (item sentinelle P4). Note de décision complète : artifact « Rétention trace.db » du 2026-08-30.

**Completed:** 2026-08-30

### file_watcher via l'outbox + suppression d'app_watcher (2A-révisée)

**What:** Le watcher fichiers POSTait en HTTP direct (timeout 0,5 s — événement perdu si daemon indisponible) ; `app_watcher.py` déprécié doublonnait l'observateur Swift.

**Résolution:** Changement de transport uniquement (détection par polling inchangée — FSEvents séparé, règle de Beck). `build_file_event_payload`/`enqueue_file_event` dans `producer_outbox` (producteur `pulse-file-watcher`, événement canonique `file_changed`), `record_file_event` remplace `post_file_event` — un daemon arrêté ne perd plus d'événements, le worker livre au retour ; une erreur de stockage ne crashe jamais la boucle. `app_watcher.py` + son test supprimés (0 appelant, doublon de `PulseApplicationObserver`) ; le préfixe de label `python -m daemon_v2.app_watcher` reste dans `analysis/terminal.py` pour l'étiquetage des traces historiques. README mis à jour. 374 tests.

**Completed:** 2026-08-30

### Cache par jour de /days (11A)

**What:** `/days` reconstruisait la trace complète de chaque jour de l'historique à chaque requête — O(historique).

**Résolution:** Cache par jour dans `build_available_days` (corps extrait en `_build_day_entry`). Le store étant append-only, un jour passé ne change que si une ligne datée de ce jour arrive après coup : le watermark `MAX(id)` (`TraceStore.latest_activity_id`) détecte les nouvelles lignes (`occurred_at_since`) et évince exactement les jours touchés (livraison en retard, dead-letter rejouée). Le jour courant n'est jamais mis en cache (rendu dépendant de l'horloge — session en cours). Paramètre `now=` injectable pour les tests (ancrage midi). Avec 10A, le chantier rétention est techniquement débloqué. 373 tests.

**Completed:** 2026-08-30

### Colonne occurred_at_utc normalisée + requêtes lexicales (10A)

**What:** Remplacer les requêtes `julianday(occurred_at)` de `trace_store.py` (expression → scan complet, index `occurred_at` inutilisé) par une colonne canonique indexée.

**Résolution:** Colonne `occurred_at_utc` — UTC à largeur fixe (`isoformat(timespec="microseconds")`, helper `utc_lexical`) : l'ordre lexical EST l'ordre chronologique, les comparaisons de chaînes utilisent `idx_activities_occurred_at_utc`. Écrite à l'insert, backfillée dans la migration transactionnelle existante (triggers append-only levés puis recréés), `idx_activities_occurred_at` (mort) supprimé. `occurred_at` brut conservé avec son offset d'origine pour les lecteurs. Test de régression offsets mélangés (un `14:00+02:00` comparé brut à une borne `13:00+00:00` serait exclu à tort) + assertions de migration étendues. Débloque la moitié 10A du chantier rétention. 371 tests.

**Completed:** 2026-08-30

### Divergence de qualification projet entre live et archive

**What:** Trancher la divergence de `build_daily_summary` : en live un workspace à observation unique était retenu si `(workspace/.git)` existait sur disque au rendu, règle absente en archive.

**Résolution (option « résorber », 2026-08-30) :** la preuve git vient désormais exclusivement des détails d'événement persistés, lus par le résolveur 5A (`persisted_workspace_identity(...).method == "git"` → `details.workspace.resolution_method`, `details.git.git_root` ou `details.git_root` historique). Règle unique dans les deux modes : fichier explicite OU ≥2 signaux OU preuve git persistée. Le paramètre `project_mode`/`ProjectQualificationMode` est supprimé (plus de mode), le `stat()` disque par workspace au rendu disparaît, et l'état actuel du disque ne peut plus réécrire le rendu d'un jour passé (stabilité temporelle étendue au live). Test de contrat réécrit (`test_project_qualification_ignores_current_disk_state_in_every_mode`) + test de qualification par preuve persistée dans les deux modes. 370 tests.

**Completed:** 2026-08-30

### Résolveur workspace unique + parseur porcelain unique (5A)

**What:** Résorber les 3 implémentations parallèles de résolution workspace et le double parseur `git status` (T14 de la revue eng du 2026-08-29).

**Résolution:** Refactor structurel pur, comportement inchangé. `WorkspaceIdentity`, `persisted_workspace_identity` et `is_generic_workspace_path` promus dans `analysis/projects.py` (résolveur unique) ; `timeline.py` délègue via alias. `git_context.py` gagne `PorcelainStatus`/`parse_status_output`, seul parseur d'en-tête/codes `git status --branch` ; `_parse_branch`/`_parse_status_counts` et `_git_local_snapshot` (daily_trace) en dérivent leurs propres comptages, sorties identiques. Nouveau `tests_v2/test_projects.py` + tests du parseur. C'est le véhicule prévu pour persister la preuve `.git` à l'ingestion (chantier divergence live/archive, maintenant débloqué). 369 tests.

**Completed:** 2026-08-30

### Commande replay-dead-letter

**What:** Ajouter `python -m daemon_v2.producer_outbox replay-dead-letter [--event-id X | --http-status N | --all]` pour re-enfiler des dead-letters dans la file pending.

**Résolution:** `ProducerOutbox.replay_dead_letters(event_id=, http_status=)` — transaction unique (`BEGIN IMMEDIATE`), `INSERT OR IGNORE` vers `events` (attempts remis à 0, `created_at` = maintenant : le rejeu rejoint la queue FIFO sans doubler les événements déjà en attente), suppression des lignes `dead_letters` sélectionnées. Un événement déjà pending garde sa ligne, sa dead-letter obsolète est purgée. Sélection explicite obligatoire côté CLI (`--event-id` | `--http-status` | `--all`, groupe mutuellement exclusif comme `clear-dead-letter`). Cycle replay → re-échec → replay testé. 8 tests ajoutés.

**Completed:** 2026-08-30

### Politique de stockage des prompts collés

**What:** Appliquer une politique de stockage aux « prompts collés » détectés par `is_pasted_prompt_command` — jusqu'ici exclus du rendu mais persistés intégralement en clair.

**Résolution (décision du 2026-08-30) :** placeholder seul — aucun texte conservé. Un collage en forme de prompt qui **échoue** (`exit_code != 0`, un vrai collage raté à l'invite échoue quasi toujours) est remplacé par `[prompt collé : N lignes, M caractères]` avant persistance, côté producteur (`build_terminal_payload`, le texte n'atteint jamais `outbox.db`) et à l'ingestion (`normalize_activity`, défense en profondeur pour les producteurs directs). Une commande en forme de prompt qui **réussit** (heredoc légitime) garde son texte intégral. Le placeholder est reconnu par `is_pasted_prompt_command` et reste exclu du rendu comme les prompts complets. Historique : laissé tel quel (append-only) — sera traité par le chantier rétention/purge. Tests : 349.

**Completed:** 2026-08-30

### Nettoyage des 5 lignes historiques à motif secret

**What:** Traiter les lignes suspectes détectées par l'audit élargi : 3 dans `trace.db`, 2 en attente dans l'outbox.

**Résolution:** Faux positifs à 100 % — vérifié ligne par ligne (daemon arrêté, sauvegardes `*-20260829-145832` faites) : les 5 textes ne différaient de leur forme rédigée que par le repli des continuations `\`+retour-ligne (normalisation du fix C4), aucun secret. Aucune donnée réécrite. Le prédicat de l'audit est corrigé (`command_has_secret` dans `daemon_v2/ingest.py` ignore le repli), avec tests de régression. Audit final : 0 suspecte sur trace.db (5 641 lignes) et outbox (70 événements), exit 0.

**Completed:** 2026-08-29
