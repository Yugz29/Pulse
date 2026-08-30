# Changelog

Toutes les modifications notables de Pulse Core sont consignées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/) ;
versionnage 4 chiffres `MAJOR.MINOR.PATCH.MICRO`.

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
