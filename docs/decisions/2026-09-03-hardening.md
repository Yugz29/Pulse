# Hardening de Core 0.5.1 — permissions, versions de schéma, courses

**Date :** 2026-09-03
**Statut :** tranchée
**Source :** relecture externe de Core après 0.5.0 ; chantier `ship/hardening`

## Décisions

- **Permissions `0700` / `0600` comme politique.** `~/.pulse_v2/` (trace,
  journaux, archives de transcripts, manifestes) et `~/.pulse_core/`
  (outbox durable) contiennent des commandes, des messages de commit et des
  transcripts. Chaque point d'entrée Python pose `umask 077` avant sa
  première création ; les dossiers sont créés en `0700` et resserrés s'ils
  existaient plus larges, mais seulement sous ces deux racines ; les bases
  SQLite sont ramenées à `0600`. `scripts/fix_permissions.sh` migre
  l'existant, idempotent, appelé par les installateurs launchd.
- **Versions de schéma explicites.** `SUPPORTED_SCHEMA_VERSIONS = {1}` :
  un `schema_version` inconnu est refusé à l'ingestion (400,
  `field: schema_version`) au lieu d'être lu avec les règles de la
  version 1. Le chemin legacy sans version ne change pas.
- **Rédaction complète des `session_summary`.** Les listes de `structured`
  (`intents`, `blockers`, `central_files`) suivent la même règle que la
  reprise : texte libre d'un modèle, rédigé élément par élément.
- **Un seul passage écrit à la fois.** Archivage des transcripts et
  émission des `agent_session` prennent chacun un verrou `flock` (60 s puis
  abandon propre, exit 2), et n'écrivent plus que par temporaire unique
  puis `os.replace`. Le verrou est par phase, dans le script Python ; le
  hook et le wrapper shell ne changent pas.
- **Dépendances épinglées et CI.** `core/requirements.txt` et
  `requirements-dev.txt` aux versions de la venv ; workflow GitHub
  `core.yml` sur `macos-latest`, Python 3.14, sans le build Swift.

## Reporté

- **Authentification des producteurs locaux** : le daemon accepte tout
  `POST /activities` sur `127.0.0.1` sans authentification. Reportée,
  déclencheur = première action de la couche Agent (un composant qui agit
  doit prouver d'où viennent ses entrées). Même ligne dans « Plus tard » de
  la Vision.
