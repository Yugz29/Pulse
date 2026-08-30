# TODOS

## Daemon V2

### Politique de rétention / purge de trace.db

**What:** Définir une rétention pour `trace.db` (archivage ou purge des jours anciens) — la base croît indéfiniment.

**Why:** Sans élagage, chaque mois ajoute du poids ; certaines opérations (audits, migrations) parcourent toute la base même une fois les lectures indexées.

**Context:** `trace_store.py` interdit UPDATE/DELETE par triggers (append-only). Une purge passerait par export vers archive + reconstruction, ou par partitionnement par fichier/période. Décision produit avant tout : combien d'historique Pulse promet-il de garder ? Porte à sens unique — supprimer de l'historique est irréversible. Les caches décidés en revue (10A/11A) réduisent la pression court terme.

**Effort:** M
**Priority:** P3
**Depends on:** 10A et 11A livrés le 2026-08-30 — chantier débloqué ; reste la décision produit (combien d'historique garder ? porte à sens unique)

### Remplacer le polling du file watcher par watchdog/FSEvents

**What:** Migrer `file_watcher.py` du re-scan complet par seconde (`os.walk` + `stat`) vers la bibliothèque `watchdog` (FSEvents natif macOS).

**Why:** Le scan par seconde coûte CPU/batterie en continu sur un gros workspace ; FSEvents est le mécanisme éprouvé [Layer 1] exact pour ce besoin, avec un coût quasi nul au repos et sans la fenêtre d'1 s où création+suppression rapide passe inaperçue.

**Context:** Introduit une dépendance externe (le projet n'en a que Flask) et watchdog a ses propres pièges (événements groupés, renames). À faire APRÈS le chantier outbox du file watcher (décision 2A-révisée) — ne jamais mélanger changement de transport et changement de mécanisme de détection dans le même diff (règle de Beck : structurel et comportemental séparés).

**Effort:** M
**Priority:** P4
**Depends on:** Chantier 2A-révisée (file_watcher via outbox) — livré le 2026-08-30, débloqué

## Completed

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
