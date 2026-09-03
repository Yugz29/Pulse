# Changelog

Toutes les modifications notables de Pulse Core sont consignées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/) ;
versionnage 4 chiffres `MAJOR.MINOR.PATCH.MICRO`.

## [0.3.1.0] - 2026-09-03

### Corrigé
- Le watcher fichiers exclut `.gitnexus/` : l'index GitNexus (base et CSV
  régénérés à chaque analyse) produisait des rafales de `file_changed` qui
  remplissaient `/context` jusqu'à la troncature des listes de fichiers.

## [0.3.0.0] - 2026-09-02

Pas 2 de la roadmap V3 : le Context API. Seul changement prévu dans Core
depuis le gel ; Core est de nouveau gelé après cette version.

### Ajouté
- Route `GET /context` : réponse JSON déterministe, sans modèle, à « que se
  passe-t-il en ce moment ? » — workspace (résolveur unique, git persisté
  uniquement), session courante bornée (apps, fichiers, commits, tests,
  erreurs, signaux), sessions récentes, signaux isolés, dernier
  `agent_session` sans limite de fenêtre. Paramètres `window` (5–1440 min,
  défaut 120) et `at` (instant de référence, défaut maintenant). Même base +
  même `at` + même `window` → même JSON, `generated_at` excepté. Contrat
  `schema_version: 1`, spec dans `docs/specs/2026-09-02-context-api.md`.
- Module pur `daemon_v2/context_snapshot.py` : ne connaît ni Flask ni le
  rendu, réutilise la reconstruction des sessions et les helpers d'analyse.
- Lecture `TraceStore.latest_activity_of_type`, bornée par un instant.
- `/status` expose un bloc `context` compact et `scripts/status.sh` affiche
  une ligne « Contexte : session en cours depuis … · projet » lue sur
  `/context` : premier consommateur du contrat.

Suite portée à 462 tests. `daily_trace.py`, `trace_store.py` (hors lecture
ajoutée), `session_tracker.py`, `models.py` et les renderers sont inchangés.

## [0.2.0.0] - 2026-08-31

Le journal s'étend aux sessions d'agents IA et devient un service autonome.
Politique de rétention tranchée : conservation infinie du brut de `trace.db`,
les transcripts d'agents n'y entrent jamais en brut (dérivés + archives zstd).

### Ajouté
- Événements `agent_session` : une entrée par session Claude Code / Codex
  terminée — résumé déterministe versionné, bornes, compteurs de messages,
  premier prompt (rédigé), pointeur vers le transcript. Backfill initial :
  152 sessions uniques sur 74 jours (173 transcripts traités, doublons de
  reprise absorbés), réparties dans les journées passées.
- Archivage compressé des transcripts d'agents (`scripts/archive_transcripts.py`,
  zstd de la stdlib) : copie pérenne avant la purge des outils sources
  (839 Mo → 220 Mo), idempotent, garde anti-troncature.
- Fonctionnement en continu : LaunchAgents `KeepAlive` pour le daemon et le
  worker, passage horaire des producteurs (archive puis émission), bascule
  `make mode-dev` / `make mode-service` avec retour au mode service garanti
  à la sortie du hot reload.
- Visibilité services : `make logs`, `make status` enrichi (état launchd,
  compteurs outbox), livraisons du worker horodatées dans le journal.
- Section « Activités isolées » : un `cd` nu ou un commit isolé apparaît en
  une ligne au lieu d'ouvrir une fausse session de 0 minute.
- Commande `replay-dead-letter` : re-enfile les événements en échec définitif
  dans la file de livraison (par événement, par statut HTTP, ou tous).
- Colonne `occurred_at_utc` canonique indexée et cache par jour de `/days` :
  les pages d'historique ne reparcourent plus toute la base.

### Modifié
- Qualification des projets du jour identique en vue live et archive : la
  preuve git vient des détails persistés, plus jamais de l'état du disque au
  rendu — un dépôt déplacé ne réécrit plus les journées passées.
- Résolveur de workspace unique et parseur `git status` unique, partagés par
  tout le pipeline (décision 5A).
- Le watcher de fichiers passe par l'outbox durable : un daemon arrêté ne
  perd plus d'événements.
- Prompts collés par erreur au shell : stockés en placeholder
  (`[prompt collé : N lignes, M caractères]`), jamais en clair.

### Corrigé
- Fuite d'un descripteur de fichier par opération SQLite : le worker en
  service launchd saturait ses 256 descripteurs en ~10 minutes (panne
  silencieuse) — fermeture déterministe partout, tests de régression.
- Un Ctrl-C (exit 130) n'est plus compté comme erreur : ni badge, ni
  « Erreur terminal récente » dans la reprise.
- Les transcripts de sous-agents (sidechains) n'émettent plus de fausse
  session d'agent (les émissions antérieures au filtre restent en base,
  figées — conforme à la politique de rétention).
- Deux transcripts partageant un même identifiant de session (reprise/fork)
  n'écrasent plus l'émission : la première gagne, le doublon est tracé.

### Supprimé
- `app_watcher.py` (déprécié, doublon de l'observateur Swift) et le
  paramètre `project_mode` des rendus (plus de divergence à piloter).

Suite portée à 407 tests.

## [0.1.0.0] - 2026-08-30

Premier jalon versionné de Pulse V2 : durcissement de la rédaction des secrets,
robustesse de l'outbox, et déterminisme des tests.

### Sécurité
- Rédaction des secrets élargie dans `redact_command` : jetons connus
  (`sk-`, `ghp_`, `AKIA`, `xox…`, `glpat-`), identifiants dans les URLs,
  en-têtes `Authorization`/`X-Api-Key`, `curl -u user:pass`, `mysql -p`,
  `sshpass -p`, `aws configure set`, variables d'environnement et options
  `--password`/`--token`/`--passphrase`.
- Captures conscientes des guillemets (un secret entre guillemets avec espaces
  est masqué en entier) et repli des continuations de ligne `\`+retour-ligne
  avant rédaction, pour empêcher les contournements.
- Motifs ancrés au contexte pour éviter la corruption de commandes légitimes :
  `Authorization:` pour bearer/basic, commandes à credentials pour `-u`,
  famille mysql pour `-p` (sensible à la casse : `-P3306` reste le port).
- Rédaction des messages de commit git, à l'ingestion et côté producteur.
- Nouvel outil `scripts/audit_secrets.py` (lecture seule, suit
  `PULSE_V2_DB_PATH`/`PULSE_CORE_OUTBOX_PATH`, code de sortie 2 distinct pour
  les erreurs d'infrastructure) et prédicat `command_has_secret`.

### Robustesse
- Sémantique de livraison de l'outbox clarifiée : les erreurs de connexion
  (daemon indisponible) sont réessayées indéfiniment ; seuls les échecs HTTP
  répétés partent en dead-letter (après ~1 h, `MAX_DELIVERY_ATTEMPTS=20`) ;
  une réponse 204 supprime l'événement sans dead-letter.
- `run_forever` résiste aux erreurs de stockage (plus de crash-loop du worker).
- `move_to_dead_letter` en `INSERT OR REPLACE` (rejeu sûr), `response_body`
  borné à 4096 caractères.
- `producer_instance_id` : lecture sans verrou sur le chemin chaud.
- Mode WAL + `busy_timeout` sur les deux bases SQLite (écritures concurrentes
  sans blocage). Voir la note de sauvegarde `-wal`/`-shm` du README.

### Tests
- Filtres d'inspection restreints aux ports Pulse (configuré, 8765, 5000
  historique) et au chemin `/activities` exact : les commandes de dev locales
  (`curl localhost:3000/…`) ne sont plus supprimées de la trace.
- Tests temporels ancrés sur un horodatage fixe via l'injection `now=` dans
  `build_daily_trace` ; nouveaux tests de frontière de jour aux changements
  d'heure (DST). Fin des échecs intermittents entre 00h et 03h.
- Suite portée à 340 tests.

### Interne
- `select_database_path` déplacée dans `runtime_config` (sans Flask) pour que
  les outils CLI n'importent plus Flask.
