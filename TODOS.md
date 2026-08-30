# TODOS

## Daemon V2

### Politique de rétention / purge de trace.db

**What:** Définir une rétention pour `trace.db` (archivage ou purge des jours anciens) — la base croît indéfiniment.

**Why:** Sans élagage, chaque mois ajoute du poids ; certaines opérations (audits, migrations) parcourent toute la base même une fois les lectures indexées.

**Context:** `trace_store.py` interdit UPDATE/DELETE par triggers (append-only). Une purge passerait par export vers archive + reconstruction, ou par partitionnement par fichier/période. Décision produit avant tout : combien d'historique Pulse promet-il de garder ? Porte à sens unique — supprimer de l'historique est irréversible. Les caches décidés en revue (10A/11A) réduisent la pression court terme.

**Effort:** M
**Priority:** P3
**Depends on:** 10A (colonne occurred_at_utc) et 11A (cache /days) livrés

### Divergence de qualification projet entre live et archive

**What:** Trancher la divergence de `build_daily_summary` (`daily_trace.py:626-635`) : en mode live un workspace est retenu si `(workspace/.git)` existe sur disque, règle absente en mode archive — le même jour peut afficher des projets différents selon le mode.

**Why:** La vue archive est la mémoire fidèle de la journée ; une divergence live/archive mine la confiance dans l'outil. Le check live fait aussi un `stat()` filesystem par workspace à chaque rendu.

**Context:** Les commits « archives temporellement stables » (cbc5913, f6f...) ont délibérément figé l'archive : la divergence est en partie un choix. Options : l'assumer et la documenter, ou la résorber en persistant la preuve `.git` dans les détails d'événement à l'ingestion (bon véhicule : le chantier résolveur unique, décision 5A). 

**Effort:** S
**Priority:** P3
**Depends on:** Chantier résolveur unique (5A)

### Remplacer le polling du file watcher par watchdog/FSEvents

**What:** Migrer `file_watcher.py` du re-scan complet par seconde (`os.walk` + `stat`) vers la bibliothèque `watchdog` (FSEvents natif macOS).

**Why:** Le scan par seconde coûte CPU/batterie en continu sur un gros workspace ; FSEvents est le mécanisme éprouvé [Layer 1] exact pour ce besoin, avec un coût quasi nul au repos et sans la fenêtre d'1 s où création+suppression rapide passe inaperçue.

**Context:** Introduit une dépendance externe (le projet n'en a que Flask) et watchdog a ses propres pièges (événements groupés, renames). À faire APRÈS le chantier outbox du file watcher (décision 2A-révisée) — ne jamais mélanger changement de transport et changement de mécanisme de détection dans le même diff (règle de Beck : structurel et comportemental séparés).

**Effort:** M
**Priority:** P4
**Depends on:** Chantier 2A-révisée (file_watcher via outbox) terminé

## Completed

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
