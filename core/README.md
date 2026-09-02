# Pulse Core

> **Core est gelé** (version 0.3.0, après le pas 2 « Context API ») — aucune
> autre évolution fonctionnelle n'est prévue dans cette couche. La direction du projet, les couches à construire et la roadmap
> sont dans [`../docs/VISION.md`](../docs/VISION.md).

Pulse V2 observe l’activité locale de développement, conserve une trace locale en append-only, regroupe les événements en sessions et reconstruit une vue lisible de la journée en cours.

L’historique des versions vit dans [CHANGELOG.md](CHANGELOG.md) ; le travail
restant et les décisions différées dans [TODOS.md](TODOS.md).

## Contrat d’événement et compatibilité temporaire

`POST /activities` accepte un contrat canonique versionné contenant
`event_id`, `schema_version`, `type`, `producer`, `occurred_at` et `details`.
`occurred_at` vient du producteur et conserve son fuseau ; `recorded_at` est
créé en UTC par Core lors de la première insertion durable.

Les producteurs historiques qui envoient encore un payload plat passent par
un adaptateur explicite `pulse-legacy`. Core leur attribue un nouvel
`event_id` à chaque requête. Ce chemin garantit leur compatibilité, mais **ne
fournit aucune idempotence entre deux requêtes legacy identiques**. Il est
destiné à être supprimé après migration des producteurs.

La version actuelle prend en charge cinq signaux d’activité :

- `terminal_finished` depuis le watcher Zsh du terminal ;
- `file_changed` depuis le watcher de fichiers du workspace ;
- `app_activated` depuis le watcher macOS de l’application active ;
- `git_commit` depuis un hook `post-commit` local (voir « Hook Git » plus bas),
  déclenché quel que soit le client à l’origine du commit (terminal, VS Code,
  ou tout autre outil Git), avec le hash, la branche, le message complet et
  les statistiques de fichiers du commit réellement créé ;
- `agent_session` depuis le producteur horaire des sessions d’agents
  (voir « Sessions d’agents » plus bas) : un événement dérivé par session
  Claude Code / Codex terminée, jamais le transcript brut.

Pulse complète ces signaux avec une lecture Git passive au rendu pour enrichir
la reprise du projet courant, sans écrire ces informations dans SQLite.

Pulse V2 expose une page HTML locale, une trace JSON et une trace Markdown via une API Flask liée à `127.0.0.1`.

## État actuel

Le projet fonctionne comme un prototype produit local :

- le daemon Python reçoit et normalise les activités ;
- SQLite conserve les événements en append-only dans
  `~/.pulse_v2/trace.db` ;
- les événements sont regroupés en sessions de travail ;
- une vue HTML vivante, des archives HTML et des représentations JSON et
  Markdown sont produites depuis la même trace quotidienne ;
- les watchers terminal, fichiers et application — comme le hook Git et les
  producteurs de sessions d’agents — écrivent dans l’outbox durable ; le
  worker livre ensuite au daemon, y compris après une indisponibilité
  momentanée.


## Palier 1 — Journal passif et reprise factuelle

Le premier palier de Pulse V2 est stabilisé : le projet fournit un journal local
passif capable de reconstruire une journée de travail à partir de signaux
observés localement.

Ce palier couvre :

- l’observation des commandes terminal, fichiers modifiés et applications
  actives ;
- le stockage local append-only dans SQLite ;
- la reconstruction de la journée en cours avec `Maintenant`, `Reprise`,
  `Aujourd’hui` et la timeline brute ;
- les archives multi-jours via `/days` et `/day/YYYY-MM-DD` ;
- les résumés compacts par projet dans l’index des journées ;
- la distinction entre timeline brute et signaux utiles.

Pulse conserve les événements observés dans la timeline, mais filtre certains
bruits dans les résumés : commandes d’inspection de Pulse, prompts collés
accidentellement dans le terminal et workspaces génériques comme le dossier
personnel utilisateur.

À ce stade, Pulse reste factuel. Il ne produit pas encore de synthèse
intelligente et ne cherche pas à deviner l’intention du travail. Le bloc
`Reprise` expose uniquement des signaux observés ou déduits prudemment à partir
de l’activité locale, comme le dernier test local observé, les derniers fichiers
observés et un contexte Git local lu passivement au rendu.

- Les prochaines limites connues de ce palier sont :
  - les commandes Git restent aussi observées via le terminal (labellisées
    `git` dans les résumés), mais le contexte Git affiché dans `Reprise` vient
    de l’état réel du dépôt lu passivement ;
  - un commit fait via un client sans hook installé (autre machine, dépôt non
    équipé) reste invisible comme événement dédié tant que le hook n’y est
    pas installé ;
- le projet courant repose encore sur des heuristiques de workspace ;
- Pulse ne produit pas encore de synthèse assistée par IA.

## Installation

```bash
cd ~/Projets/Pulse/core
python3 -m venv .venv
.venv/bin/pip install Flask pytest watchdog
```

## Tests

```bash
.venv/bin/python -m pytest tests_v2
```

## Développement local

Le port local dédié est `8765`. Il peut être remplacé pour toute la pile avec
une seule variable, par exemple `PULSE_CORE_PORT=9876 make dev`. Le superviseur
transmet toujours le même endpoint à Pulse Core, au worker et au watcher
fichiers.

Le hook terminal doit rester chargé dans chaque Zsh interactive, car `preexec`
et `precmd` ne peuvent pas fonctionner dans un processus de fond. Dans
`~/.zshrc`, supprimer l’ancienne ligne :

```zsh
source /Users/yugz/Projets/Pulse_V2/scripts/pulse_terminal_watcher.zsh
```

et la remplacer par :

```zsh
source /Users/yugz/Projets/Pulse/Pulse_Core/scripts/pulse_terminal_watcher.zsh
```

Le hook construit et écrit les événements terminal dans l’outbox. Il ne lance
plus son propre worker : `make dev` supervise l’unique worker. Après avoir
modifié `~/.zshrc`, ouvrir un nouveau terminal ou sourcer manuellement la
nouvelle ligne.

Depuis la racine du dépôt :

```bash
make dev
```

Si les services launchd sont installés, le daemon `com.pulse.daemon` occupe
déjà le port : utiliser `make mode-dev` plutôt que `make dev` (voir
« Bascule service ↔ dev »).

Cette commande effectue les préflight, démarre Pulse Core, attend que
`GET /status` identifie réellement Pulse, puis lance le worker outbox, le
watcher fichiers et l’observateur macOS Swift. Le watcher fichiers observe le
dossier depuis lequel `make dev` est lancé. `Ctrl-C` arrête les quatre
processus dans l’ordre inverse.

Commandes de diagnostic :

```bash
.venv/bin/python -m daemon_v2.producer_outbox status
.venv/bin/python -m daemon_v2.producer_outbox \
  inspect-dead-letter --limit 10
.venv/bin/python -m daemon_v2.producer_outbox \
  clear-dead-letter --http-status 403
.venv/bin/python -m daemon_v2.producer_outbox \
  replay-dead-letter --http-status 500
```

`clear-dead-letter` supprime uniquement les dead-letters ciblées ;
`replay-dead-letter` les re-enfile dans la file de livraison (sélection
explicite obligatoire : `--event-id`, `--http-status` ou `--all`). Aucune des
deux ne touche aux événements pending. Aucune dead-letter n’est supprimée ou
rejouée automatiquement.

Sémantique de livraison : les erreurs de connexion (daemon arrêté, machine
hors ligne) sont réessayées indéfiniment — l’outbox survit à l’indisponibilité
du daemon. Seuls les échecs HTTP répétés (le serveur répond mais échoue)
finissent en dead-letter, après ~1 h de tentatives. Une réponse 204
(commande volontairement filtrée) supprime l’événement sans dead-letter.

Test manuel :

1. lancer `make dev` et attendre les quatre messages `started` ;
2. changer d’application, exécuter une commande terminal et modifier un fichier ;
3. vérifier les lignes événementielles lisibles et le statut de l’outbox ;
4. faire `Ctrl-C` ;
5. vérifier avec `ps` qu’aucun processus Pulse Core, outbox worker, watcher
   fichiers ou `PulseApplicationObserver` ne subsiste.

L’observateur natif écoute
`NSWorkspace.didActivateApplicationNotification`, produit un état initial et
écrit dans l’outbox avant tout envoi. Il ne collecte ni titre de fenêtre,
document, URL ou contenu d’écran.

Le même processus écoute aussi les transitions publiques macOS de veille,
réveil et les notifications distribuées système de verrouillage. Les
identifiants `com.apple.screenIsLocked` et `com.apple.screenIsUnlocked` ne sont
pas exposés comme constantes AppKit fortement typées ; Pulse les observe via
`DistributedNotificationCenter`. Test manuel :

1. lancer `make dev-reload` ;
2. verrouiller la session avec `Ctrl-Cmd-Q`, puis la déverrouiller ;
3. mettre le Mac en veille, puis le réveiller ;
4. vérifier quatre lignes `screen_locked`, `screen_unlocked`, `system_sleep`
   et `system_wake`, chacune suivie d’un `POST /activities` en HTTP 201.

Pendant le diagnostic lock/unlock, la réception brute est aussi visible sur
stderr sous la forme `[macos-observer] received screen lock notification` ou
`received screen unlock notification`. Un doublon reçu est journalisé mais
n’est pas publié une seconde fois.

Ces événements ont un objet `details` vide. L’observateur ne fait aucun appel
HTTP : il remet leur JSON canonique à la même outbox durable que les événements
d’application.

## Commandes utiles

```bash
make dev
make dev-reload
make mode-dev
make mode-service
make test
make status
make logs
make reset
make help
```

`make dev-reload` est réservé au développement. Il surveille les sources du
dépôt par polling et redémarre Pulse après un court debounce, sans utiliser les
événements `file_changed` ni écrire directement dans SQLite.

- `make dev` : lance Pulse localement ;
- `make dev-reload` : lance Pulse et le redémarre lorsque les sources changent ;
- `make mode-dev` : décharge les services launchd et lance le hot reload,
  avec retour automatique au mode service en sortie ;
- `make mode-service` : recharge les services launchd (daemon + worker) ;
- `make test` : lance les tests ;
- `make status` : affiche l’état local (daemon, launchd, outbox) ;
- `make logs` : suit les journaux des services launchd et du passage horaire
  des producteurs (`agent_producers.log`) ;
- `make reset` : réinitialise la trace de développement ;
- `make help` : affiche les commandes disponibles.

Pour lancer uniquement le daemon :

```bash
.venv/bin/python -m daemon_v2.main
```

La base SQLite V2 est créée dans `~/.pulse_v2/trace.db`. Elle n’est ni migrée depuis Pulse V1, ni partagée avec les anciennes bases situées dans `~/.pulse`. Le chemin peut être surchargé avec `PULSE_V2_DB_PATH=/chemin/vers/trace.db`.

Les bases (`trace.db` et l’outbox) fonctionnent en mode WAL : les écritures
concurrentes (producteurs, worker, daemon) ne se bloquent plus entre elles.
Conséquence pour les sauvegardes : copier uniquement le fichier `.db` peut
perdre les dernières écritures — copier aussi les fichiers `-wal` et `-shm`,
ou passer par `sqlite3 trace.db ".backup"` qui les intègre. Les archives de
transcripts (`~/.pulse_v2/transcript_archive`) font aussi partie des données
à sauvegarder : les événements `agent_session` pointent vers elles.

Ouvrir la page locale de l’activité du jour :

```text
http://127.0.0.1:8765/
```

La page locale affiche les blocs `Maintenant`, `Reprise`, `Aujourd’hui` et
`État système`, puis une timeline navigable. Elle regroupe les changements de
fichiers par vague de modification, résume les sessions, marque les changements
de projet et synthétise les applications actives. Un événement fort isolé
(un `cd` nu, un commit seul) apparaît en une ligne dans la section
« Activités isolées » au lieu d’ouvrir une session de 0 minute. Côté JSON,
ces activités restent dans `work_sessions` avec `activity_kind: "isolated"` ;
`work_session_count` ne compte que les vraies sessions — ne pas compter
`len(work_sessions)`. Le bloc `Reprise` complète la
trace enregistrée avec un contexte Git local lu passivement : état du dépôt,
branche et commits du jour. Cette lecture Git est best-effort, limitée par un
timeout court, et n’est pas écrite dans SQLite.

Vérifier l’état local sans démarrer de processus :

```bash
./scripts/status.sh
```

Le même état est disponible en JSON sur `http://127.0.0.1:8765/status`.

Réinitialiser explicitement la trace de développement, après avoir arrêté
Pulse :

```bash
./scripts/reset-dev.sh
```

Le script cible `~/.pulse_v2/trace.db`, respecte `PULSE_V2_DB_PATH`, demande
confirmation et refuse tout chemin situé sous `~/.pulse`. En mode service
(`KeepAlive`), le daemon relancé répond en permanence et le reset est
refusé : décharger d’abord les services
(`./scripts/install_daemon_launchd.sh --uninstall` ou `launchctl bootout`).

## Envoyer une activité

```bash
curl -X POST http://127.0.0.1:8765/activities \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "terminal_finished",
    "occurred_at": "2026-07-03T19:30:00+02:00",
    "command": "pytest tests_v2",
    "exit_code": 0,
    "cwd": "/Users/yugz/Projets/Pulse/Pulse_Core"
  }'
```

Exemple d’activité fichier :

```bash
curl -X POST http://127.0.0.1:8765/activities \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "file_changed",
    "path": "/Users/yugz/Projets/Pulse/Pulse_Core/daemon_v2/daily_trace.py",
    "event": "modified",
    "workspace": "/Users/yugz/Projets/Pulse/Pulse_Core"
  }'
```

## Routes principales

| Route | Format | Rôle |
| --- | --- | --- |
| `/` | HTML | Vue vivante de la journée en cours |
| `/status` | JSON | État local du daemon et de la trace du jour |
| `/context` | JSON | Context API : le présent, déterministe et sans modèle |
| `/activities` | JSON | Ingestion d’une activité par `POST` |
| `/trace/today` | JSON | Trace structurée de la journée en cours |
| `/trace/today.md` | Markdown | Trace lisible de la journée en cours |
| `/days` | HTML | Liste des jours disponibles |
| `/trace/days` | JSON | Liste structurée des jours disponibles |
| `/day/YYYY-MM-DD` | HTML | Archive d’une journée |
| `/trace/YYYY-MM-DD` | JSON | Trace structurée d’une journée |
| `/trace/YYYY-MM-DD.md` | Markdown | Trace lisible d’une journée |

Lire la trace JSON du jour :

```bash
curl http://127.0.0.1:8765/trace/today
```

Pour une trace Markdown lisible, regroupée par session :

```bash
curl http://127.0.0.1:8765/trace/today.md
```

### Context API (`/context`)

`GET /context` répond à « que se passe-t-il en ce moment ? » à partir de
`trace.db` uniquement : aucun modèle, aucune lecture du disque ni de Git au
rendu. La réponse (`schema_version: 1`) contient le workspace résolu et ses
faits git persistés, la session courante (durée, projets, apps, fichiers,
commits, tests, erreurs, signaux), les sessions récentes fermées, les signaux
isolés et le dernier `agent_session`. C'est le contrat stable que la couche
Intelligence consomme (voir `../docs/specs/2026-09-02-context-api.md`).

```bash
curl -s http://127.0.0.1:8765/context | jq .current_session.projects
curl -s 'http://127.0.0.1:8765/context?window=30&at=2026-09-02T14:00:00Z'
```

`window` (minutes, défaut 120, de 5 à 1440) et `at` (instant de référence
ISO 8601 avec fuseau, défaut maintenant) invalides renvoient 400. Même base,
même `at`, même `window` → même JSON, `generated_at` excepté.

### Vue vivante et vue archive

La route `/` représente l’état courant. Elle affiche :

- `Maintenant` ;
- `Reprise` ;
- `Aujourd’hui` ;
- `État système` ;
- la timeline, ses résumés de session et ses séparateurs de projet ;
- un lien `Direct` en fin de navigation.

La route `/day/YYYY-MM-DD` représente une archive stable d’une journée. Elle
affiche `Journal du YYYY-MM-DD`, le résumé du jour et la timeline. Elle
n’affiche pas `Maintenant`, `Reprise` ni `État système`, et sa navigation se
termine par `Fin du jour`.

Les vues datées HTML et Markdown sont temporellement stables : elles n’affichent
pas `Maintenant` ni `Reprise`, et ne consultent pas l’état Git courant. La
qualification des projets suit la même règle dans les deux modes : fichier
explicite, au moins deux signaux, ou preuve git persistée dans les détails
d’événement. L’état actuel du disque n’est jamais consulté au rendu — un dépôt
déplacé ne réécrit donc pas les journées passées.

## Structure du code

```text
daemon_v2/
  analysis/
    projects.py
    terminal.py
    timeline.py
  renderers/
    html.py
    markdown.py
  agent_sessions.py
  daily_trace.py
  dev_environment.py
  event_logger.py
  file_watcher.py
  git_context.py
  ingest.py
  main.py
  models.py
  outbox_worker.py
  producer_outbox.py
  routes.py
  runtime_config.py
  session_tracker.py
  trace_store.py
  workspace_context.py
```

- `agent_sessions.py` parse les transcripts Claude Code / Codex terminés et
  émet les événements dérivés `agent_session` via l’outbox durable.
- `producer_outbox.py` est l’outbox SQLite durable des producteurs locaux
  (file pending, dead-letters, CLI de diagnostic et de rejeu).
- `outbox_worker.py` est le worker de livraison FIFO synchrone de l’outbox
  vers le daemon.
- `git_context.py` lit le contexte Git en tolérance de panne et porte
  l’unique parseur `git status --branch` (`PorcelainStatus`).
- `runtime_config.py` centralise l’endpoint local et les chemins de stockage
  partagés (sans dépendance Flask).
- `workspace_context.py` résout le workspace côté producteur pour enrichir
  les événements.
- `event_logger.py` fournit la journalisation console opt-in des événements
  acceptés.
- `dev_environment.py` regroupe les préflights et healthchecks testables de
  `scripts/dev.sh`.
- `main.py` crée l’application Flask et initialise le stockage.
- `routes.py` expose l’ingestion, les vues et les traces.
- `ingest.py` valide, normalise et masque les données sensibles des activités
  entrantes.
- `trace_store.py` encapsule le stockage SQLite append-only.
- `session_tracker.py` affecte les activités aux sessions.
- `daily_trace.py` construit la trace quotidienne, calcule les synthèses et
  conserve les façades publiques de rendu.
- `analysis/terminal.py` contient la classification des commandes terminal et
  le parsing des commandes Git observées.
- `analysis/projects.py` contient les helpers purs liés aux workspaces et aux
  notions de projet observé ou explicite.
- `analysis/timeline.py` contient les regroupements et sélections purs utilisés
  pour préparer les timelines.
- `renderers/html.py` et `renderers/markdown.py` produisent les représentations
  finales sans template engine.
- `file_watcher.py` collecte les changements de fichiers et les enfile
  dans l'outbox durable ; le watcher terminal reste un script Zsh externe.

## Watcher terminal

Sourcer le watcher depuis chaque session Zsh interactive :

```bash
source /Users/yugz/Projets/Pulse/Pulse_Core/scripts/pulse_terminal_watcher.zsh
```

Pour le charger dans les futures sessions Zsh, ajouter soi-même cette ligne dans `~/.zshrc` :

```zsh
source /Users/yugz/Projets/Pulse/Pulse_Core/scripts/pulse_terminal_watcher.zsh
```

Le watcher enregistre la commande, le dossier courant, les heures de début et
de fin ainsi que le code de sortie. Il écrit immédiatement dans l’outbox, même
si Core est indisponible. Il doit être sourcé depuis Zsh ; `make dev` lance le
worker qui livre ensuite ces événements.

## Watcher de fichiers

Lancer manuellement le watcher avec un workspace explicite, ou avec la
liste déclarée du mode résident :

```bash
.venv/bin/python -m daemon_v2.file_watcher /Users/yugz/Projets/Pulse/Pulse_Core
.venv/bin/python -m daemon_v2.file_watcher --config ~/.pulse_v2/watched_workspaces
```

La détection s’appuie sur `watchdog` (FSEvents natif sur macOS) : coût quasi
nul au repos, plus de re-scan complet par seconde. FSEvents coalesce et
qualifie mal ses événements, donc watchdog ne sert que de notificateur de
chemins touchés — les types `created`/`modified`/`deleted` sont établis en
comparant chaque chemin signalé au snapshot interne, et `--interval`
(1 s par défaut) devient la fenêtre de coalescence entre deux purges.

Il enfile les fichiers créés, modifiés et supprimés dans l’outbox durable
(décision 2A-révisée) ; le worker les livre ensuite au daemon, donc un daemon
momentanément indisponible ne perd plus d’événements. Les chemins techniques
comme `.git`, `.venv`, les caches, `*.pyc`, `*.db` et `.DS_Store` sont
ignorés. L’arrêter avec `Ctrl-C`.

## Archivage des transcripts d'agents

Copie compressée (zstd, stdlib Python 3.14) des sessions Claude Code et
Codex avant leur purge par les outils sources — préalable à l'ingestion
`agent_session` (décision de rétention du 2026-08-30) :

```bash
.venv/bin/python -m scripts.archive_transcripts [--dry-run]
```

Lecture seule sur les sources, reruns idempotents (seuls les fichiers
nouveaux ou qui ont grossi sont réarchivés), une source rétrécie n'écrase
jamais une archive plus complète. Archive dans
`~/.pulse_v2/transcript_archive` (surcharge : `PULSE_TRANSCRIPT_ARCHIVE_PATH`).
Codes de sortie : 0 = terminé, 2 = erreur d'infrastructure. Options :
`--source` (répétable), `--archive-root`, `--level`.

## Sessions d'agents (agent_session)

Un événement dérivé par session Claude Code / Codex terminée — le brut des
transcripts n'entre jamais dans `trace.db` (décision de rétention du
2026-08-30). Résumé déterministe calculé une seule fois (versionné
`summary_version`), métadonnées (bornes, compteurs de messages, workspace,
branche), premier prompt rédigé, pointeur vers le fichier source :

```bash
.venv/bin/python -m daemon_v2.agent_sessions [--dry-run] [--quiet-minutes N]
```

Une session n'est émise que stable (silence d'une heure par défaut). Une
session déjà émise qui regrossit est signalée mais jamais ré-émise ;
`event_id` déterministe : une ré-émission accidentelle est un duplicate.
Passe par l'outbox durable, comme tous les producteurs. Codes de sortie :
0 = terminé, 2 = erreur d'infrastructure. Options supplémentaires :
`--claude-dir`, `--codex-dir`, `--outbox-database`, `--manifest` (surcharge
d'environnement : `PULSE_AGENT_SESSIONS_MANIFEST_PATH`), `--transcript`
(mode ciblé : seul ce transcript est traité, fenêtre de silence contournée).

### Hook SessionEnd Claude Code

`scripts/pulse_session_end_hook.sh`, branché sur l'événement `SessionEnd`
dans `~/.claude/settings.json`, émet la session **immédiatement** à sa fin
(archive zstd d'abord, puis émission ciblée `--transcript`) au lieu
d'attendre le passage horaire launchd + la fenêtre de silence. Le hook ne
fait jamais échouer la fermeture d'une session (exit 0 inconditionnel,
journal : `~/.pulse_v2/logs/session_end_hook.log`) et annule l'émission si
l'archivage échoue — le passage horaire launchd rattrape, et reste le
chemin d'émission pour Codex (pas de hooks). Décision (a) du 2026-08-31 :
une reprise sur le même transcript après émission laisse le résumé figé
(`grown_after_emit`). Mesuré sur la plus grosse session réelle (50 Mo) :
0,73 s à froid, 0,16 s en rerun.

Contrat `POST /activities` du type `agent_session` (champs de `details`) :
requis `source_tool`, `session_id`, `transcript_path`, `summary_version`
(entier ≥ 1) ; optionnels `started_at`/`ended_at`,
`user_messages`/`assistant_messages`, `archive_hint`, `git_branch`,
`tool_version` et `first_prompt` (re-rédigé à l'ingestion, défense en
profondeur).

## Services daemon + worker (launchd)

Deux LaunchAgents `KeepAlive` font tourner Pulse en continu — relancés au
login et après un crash :

```bash
./scripts/install_daemon_launchd.sh              # com.pulse.daemon + com.pulse.outbox-worker
./scripts/install_daemon_launchd.sh --uninstall
```

Journaux : `~/.pulse_v2/logs/daemon.log` et `~/.pulse_v2/logs/outbox_worker.log`.
Coexistence avec `scripts/dev.sh` : le worker porte un verrou (`flock`), une
seconde instance s'éteint d'elle-même ; le daemon, lui, entrerait en conflit
de port — désinstaller (ou `launchctl bootout`) avant de lancer `dev.sh`.

## Observateurs résidents (launchd)

Sans eux, le journal est aveugle aux fichiers et aux applications dès que
`make dev` ne tourne pas. Deux LaunchAgents `KeepAlive` supplémentaires :

```bash
./scripts/install_observers_launchd.sh           # com.pulse.file-watcher + com.pulse.app-observer
./scripts/install_observers_launchd.sh --uninstall
```

- `com.pulse.file-watcher` lance `daemon_v2.file_watcher --config
  ~/.pulse_v2/watched_workspaces` : la liste des workspaces observés est
  **déclarée** (un chemin par ligne, `~` accepté, `#` commentaires) au lieu
  d'hériter du dossier de lancement de `make dev`. La liste est lue au
  démarrage — après édition : `launchctl kickstart -k
  gui/$(id -u)/com.pulse.file-watcher`. Une entrée disparue est ignorée
  avec un avertissement, elle n'aveugle pas les autres workspaces.
- `com.pulse.app-observer` fait tourner `PulseApplicationObserver` (build
  release copié dans `~/.pulse_v2/bin`, hors de `.build`).

Les deux écrivent dans l'outbox durable : un daemon éteint ne perd rien.
Conséquence assumée : le watcher résident voit les écritures des agents
(Claude Code compris) comme n'importe quel `file_changed`. Journaux :
`~/.pulse_v2/logs/file_watcher.log` et `~/.pulse_v2/logs/app_observer.log`.
Coexistence : `make mode-dev` décharge ces agents (dev.sh lance ses propres
watcher et observateur — sinon événements en double) et les recharge en
sortie s'ils sont installés.

## Bascule service ↔ dev

`scripts/pulse_mode.sh` bascule proprement entre les deux modes :

```bash
make mode-dev       # décharge les services launchd, lance le hot reload
make mode-service   # recharge les services (daemon + worker, KeepAlive)
./scripts/pulse_mode.sh status
```

En mode dev, la sortie du hot reload (Ctrl-C compris) **recharge
automatiquement les services** — impossible d'oublier de réinstaller. Le
LaunchAgent horaire des producteurs n'est jamais touché : l'outbox durable
vaut dans les deux modes. Visibilité : `make logs` (journaux des services)
et `make status` (daemon, launchd, outbox).

## Exécution récurrente des producteurs agents

Un LaunchAgent utilisateur exécute toutes les heures (et au chargement de la
session) `scripts/pulse_agent_producers.sh` : l'archivage zstd D'ABORD, puis
l'émission `agent_session` — un pointeur n'est jamais émis si l'archivage a
échoué. Installation (idempotente, refuse d'écraser un plist non géré) :

```bash
./scripts/install_agent_producers_launchd.sh            # installe + charge
./scripts/install_agent_producers_launchd.sh --uninstall
```

Journal : `~/.pulse_v2/logs/agent_producers.log`. Le daemon n'a pas besoin de
tourner : les événements patientent dans l'outbox durable jusqu'à la
prochaine livraison par le worker. Surcharges de test :
`PULSE_AGENT_CLAUDE_DIR` / `PULSE_AGENT_CODEX_DIR` (répercutées à la fois sur
l'archivage et sur l'émission).

## Hook Git

Installer le hook `post-commit` sur un dépôt suivi (idempotent, refuse
d’écraser un hook existant qu’il n’a pas lui-même posé) :

```bash
./scripts/install_git_hook.sh /chemin/vers/le/depot
```

Le hook gagne sa fiabilité en s’appuyant sur l’objet commit lui-même plutôt
que sur une commande shell observée : il lit `commit_hash`, `branch`, le
message complet et les statistiques `--shortstat` directement depuis Git une
fois le commit créé, donc il capte un commit fait depuis le terminal, VS Code
ou tout autre client. Il envoie l’événement via l’outbox durable existante
(`daemon_v2.producer_outbox enqueue-git-commit`), donc un daemon
momentanément indisponible ne perd pas l’événement. Toute erreur reste
best-effort : le hook ne bloque et ne fait jamais échouer un commit.

## Observateur d’application

L’ancien observateur Python par polling (`daemon_v2.app_watcher`) est
supprimé : il envoyait des payloads legacy directement à Core et doublonnait
les activations produites par l’observateur Swift. `make dev` lance uniquement
`PulseApplicationObserver`.

Le watcher fichiers exclut les répertoires techniques `.build`, `.git`,
`.gitnexus`, `.venv`, `__pycache__`, `.pytest_cache`, `node_modules`, `dist`
et `build`.
Ils ne produisent donc pas d’événements `file_changed`.

La reconstruction considère les verrouillages et mises en veille comme des
interruptions candidates. Une reprise dans le même workspace conserve la
session lorsque l’interruption ne dépasse pas cinq minutes. Ce seuil peut être
adapté avec `PULSE_SESSION_INTERRUPTION_MINUTES`.

Les activations d’application représentent une présence utilisateur, pas une
preuve de projet. Celles qui ne sont pas confirmées par une activité de travail
ultérieure sont exposées dans `unresolved_sessions`, sans workspace. Une
activité forte ultérieure dans la même session peut les y rattacher
rétroactivement ; une activation isolée ne prolonge jamais `ended_at`.
L’ancien champ JSON `passive_sessions` est conservé temporairement comme alias
déprécié de `unresolved_sessions` pour les clients existants.

Sur macOS, `make dev` lance `PulseApplicationObserver`, fondé sur
`NSWorkspace`. L’ancien watcher Python n’est plus lancé par le superviseur.

## Limites actuelles

- Les entrées sont acceptées via l’API HTTP locale, les watchers optionnels
  terminal, fichiers et application, le hook Git `post-commit` et le
  producteur horaire de sessions d’agents.
- Les sessions utilisent une coupure fixe après 30 minutes d’inactivité.
- Les commandes Git restent observées via le terminal ; un commit crée un
  événement `git_commit` dédié partout où le hook `post-commit` est installé,
  et reste sinon visible via la lecture Git passive.
- Le projet courant repose encore sur des heuristiques de workspace ; les notions
  de workspace observé, workspace explicite et projet qualifié sont séparées
  dans le code, mais pas encore remplacées par une identité projet durable.
- Les commandes reçoivent un masquage basique des secrets, sans parsing shell
  avancé.
- Les watchers restent best-effort côté observation, mais la livraison passe
  par l’outbox durable : un daemon momentanément indisponible retarde la
  livraison sans perdre l’événement.
- SQLite est local et mono-machine ; la politique de rétention est tranchée
  (conservation infinie du brut, réexamen sur seuils mesurables, voir
  [TODOS.md](TODOS.md)) et le schéma évolue par migrations transactionnelles.
- Les lectures d’historique s’appuient sur la colonne indexée
  `occurred_at_utc` et le cache par jour de `/days` ; le coût des autres
  agrégations reste à surveiller lorsque l’historique grandira.
- Les archives datées évitent les lectures live de Git et de `Reprise`, mais les
  règles de résumé restent des projections déterministes de la trace, pas des
  faits métier persistés.
- Pulse ne produit pas encore de synthèse intelligente : les résumés restent
  factuels et issus des signaux observés.
- Le daemon n’a pas d’authentification, car il écoute uniquement sur `127.0.0.1`.
