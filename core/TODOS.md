# TODOS

## Hardening 0.5.6

Lot ouvert le 2026-09-05, note de décision
`docs/decisions/2026-09-05-reouverture-core-hardening.md`. Le gel de Core porte
sur son périmètre fonctionnel, pas sur ses correctifs.

### Réentrance fatale de PulseApplicationObserver

**What:** `ApplicationObserver.observe(_:)` est ré-entré pendant que
`OutboxBridge.run(command:input:)` bloque la boucle principale dans
`waitUntilExit` — `NSConcreteTask` fait tourner la run loop, qui redélivre
`didActivateApplicationNotification` sur `.main`. L'accès exclusif à `recorder`
(`var`, ligne 10) est violé : `Fatal access conflict detected`, SIGABRT.
Trace complète dans `~/.pulse_v2/logs/app_observer.log`, 4 occurrences le
2026-09-05. `KeepAlive` relance, donc la perte est bornée aux activations de
l'intervalle — mais elle est silencieuse côté base. `SystemObserver.observe`
emprunte le même pont et doit être couvert par la correction.

**Impact (GitNexus):** `ApplicationObserver.observe` 12 impactés / LOW ;
`OutboxBridge.run` 8 impactés / LOW, appelé par les deux observateurs.

**Effort:** M
**Priority:** P1
**Depends on:** Xcode installé sur la machine (`swift test` échoue aujourd'hui
sur `no such module 'Testing'`, seuls les Command Line Tools sont présents)

### status.sh annonce le daemon inaccessible alors qu'il répond

**What:** `scripts/status.sh:22` impose `curl --max-time 2` ; `GET /status`
répond en 2,04–2,11 s (mesuré, code 200), donc `make status` sort en erreur
avec « daemon inaccessible » pendant que les cinq services tournent. Le coût
est dominé par la journée courante, pas par la taille de l'historique — la
fusion de 16 800 événements ne l'a pas aggravé. À traiter par le délai, et à
décider séparément si `/status` doit devenir moins cher.

**Effort:** S
**Priority:** P2
**Depends on:** Aucun

### Résolution de casse là où l'échec est silencieux

**What:** APFS est insensible à la casse, `PurePath` y est sensible, et
`realpath`/`.resolve()` ne canonisent pas la casse (vérifié). Deux points où
l'écart ne produit ni erreur ni avertissement :
`file_watcher.should_ignore` / `should_ignore_directory` retournent `True` sur
le `ValueError` de `relative_to`, donc un workspace déclaré à une casse
différente de celle du disque filtre **tout** — le watcher démarre, journalise
« Watching files in … » et n'émet plus rien (reproduit en conditions réelles :
FSEvents remonte la casse canonique) ; `read_watched_workspaces` déduplique sur
`set[Path]`, donc deux graphies du même dossier passent pour deux workspaces.
`private_files.is_private_path` compare par `relative_to(root.resolve())` : un
chemin sous une racine Pulse mal casée n'est pas reconnu comme privé et n'est
pas resserré en `0700`/`0600`.

**Contrainte:** `is_private_path` est le seul symbole du lot à risque HIGH
(13 impactés, 4 processus). Toute correction peut élargir la **reconnaissance**
d'un chemin comme privé, jamais le périmètre des racines dont Pulse modifie le
mode.

**Hors périmètre:** les 19 autres points sensibles à la casse relevés par la
cartographie du 2026-09-05 (`analysis/projects.py`, `analysis/timeline.py`,
`daily_trace.py`, `context_snapshot.py`, `event_logger.py`,
`archive_transcripts.py`, `agent_sessions.py`) : ils dégradent l'affichage ou
le regroupement, jamais en silence total.

**Impact (GitNexus):** `should_ignore` 8 / LOW, `should_ignore_directory`
5 / LOW, `read_watched_workspaces` 2 / LOW, `is_private_path` 13 / **HIGH**.

**Effort:** M
**Priority:** P2
**Depends on:** Aucun

## Hygiène du dépôt

### Chemins `/Users/<user>` en dur dans un dépôt public

**What:** Le dépôt est public et `main` porte 41 occurrences de chemins absolus
sous le dossier utilisateur — `core/README.md`, sept fichiers de
`core/tests_v2/`, `docs/specs/2026-09-02-context-api.md`, trois fichiers de
`intelligence/tests/`. Le scan `gstack-redact` les classe LOW
(`internal.user_path`), non bloquants. Les remplacer par un placeholder ou une
fixture (`tmp_path`, `/Users/dev` déjà utilisé ailleurs dans les tests) rend le
dépôt indépendant de la machine qui l'a produit.

**Pas de réécriture d'historique :** le nom d'utilisateur est public depuis les
premiers commits, une réécriture coûterait plus qu'elle ne masquerait. Le
chantier porte sur l'état courant seulement.

**Note pour une prochaine machine :** `tools/normalize_legacy_trace.py` porte sa
table de correspondance en dur dans `PATH_RULES` — c'est la configuration d'une
migration ponctuelle, assumée telle quelle. Si le cas se représente, la sortir
dans un fichier de config ou un argument CLI rendrait l'outil réutilisable et
retirerait les derniers chemins personnels du dépôt.

**Déclencheur:** aucun — item d'hygiène, à traiter quand le dépôt est au calme.

**Effort:** S
**Priority:** P4
**Depends on:** Aucun

## Daemon V2

### Coût de reconstruction de TraceStore à grande échelle

`TraceStore.append_event` recharge toute la table à chaque écriture (coût
mesuré : ~50ms à 50k lignes, ~14 mois au rythme actuel). Déclencheur :
surveiller à l'approche de 50k événements, envisager un index ou une stratégie
incrémentale vers 100k.

### TraceStore._connect : même ordre pragma-puis-busy_timeout que l'outbox avant correctif

**What:** `TraceStore._connect` exécute `PRAGMA journal_mode=WAL` avant `PRAGMA busy_timeout`, exactement l'ordre que `ProducerOutbox._connect` avait avant le correctif 0.5.2 (course au passage en WAL d'une base neuve, « database is locked »). Non corrigé : un seul processus crée `trace.db` en pratique. Le jour venu, reprendre le même patron (busy_timeout d'abord, retry borné sur « locked », constantes de module, test à plusieurs créateurs bouclé).

**Déclencheur:** si un jour deux daemons démarrent sur une base `trace.db` neuve, ou si la stratégie de connexion change. Ne pas implémenter avant.

**Effort:** S
**Priority:** P4
**Depends on:** Cas réel observé

### Segments de reprise pour agent_session

**What:** Émettre la continuation d'une session reprise après émission comme un **segment** supplémentaire (nouvel événement borné, même `session_id`, `segment: 2`), au lieu du statu quo « résumé figé, reprise invisible » (`grown_after_emit`). Conséquence assumée de la décision (a) du 2026-08-31 : l'émission immédiate à SessionEnd fige le résumé à la première fin de session.

**Déclencheur:** quand `grown_after_emit` devient récurrent dans `agent_producers.log` / le log du hook (la reprise rapide sur un même transcript devient un vrai usage), ou quand une continuation substantielle manque visiblement au journal. Ne pas implémenter avant.

**Effort:** M
**Priority:** P3
**Depends on:** Cas réel observé

### Hook PostToolUse Claude Code (second étage)

**What:** Second étage du chantier hooks (le premier, SessionEnd, est livré) : un hook `PostToolUse` pour donner à Pulse un signal d'activité agent en quasi-temps réel pendant la session — aujourd'hui le journal ne voit une session qu'à sa fin. À cadrer avant d'implémenter : quel événement dérivé (heartbeat de session active ? activité outil agrégée ?), quel débit acceptable (un hook par appel d'outil est fréquent — il faudra agréger côté hook), et ce que le rendu en ferait.

**Effort:** M
**Priority:** P3
**Depends on:** Retour d'usage du hook SessionEnd

### Kind `renamed` sémantique pour le watcher fichiers

**What:** Émettre un vrai signal de renommage au lieu de la paire `deleted(src)` + `created(dest)`. C'est un changement de vocabulaire d'événement : ingestion + aval (timeline, renderers) n'ont aucun concept de rename aujourd'hui. watchdog fournit src+dest via `on_moved` — l'information que le poller n'a jamais eue, donc le chantier est devenu possible depuis la migration FSEvents (PR #23).

**Déclencheur:** quand les paires delete+create rendent la reprise trompeuse — typiquement un refactor Claude Code avec renommages en masse.

**Effort:** M
**Priority:** P4
**Depends on:** Cas réel observé (ne pas implémenter avant)

### Enqueue outbox par lot pour le watcher fichiers

**What:** Une transaction SQLite par fenêtre de coalescence au lieu d'une par événement (~3 ms/événement mesuré en run vivant, PR #23). Changement de transport pur — à ne jamais mélanger avec un changement de détection (règle de Beck).

**Déclencheur:** rafale réelle non bornée par les ignore, ou latence d'enqueue mesurable dans le journal. Non-sujet tant que `node_modules`/`.venv`/`dist`/`build` restent exclus.

**Effort:** S
**Priority:** P4
**Depends on:** Cas réel observé (ne pas implémenter avant)

### Limite connue : le raisonnement des conversations Claude.ai n'est pas capturable

**What:** Le raisonnement le plus dense d'une journée peut vivre dans une conversation Claude.ai (web), hors de portée du pipeline local (`~/.claude/projects/` ne contient que les sessions Claude Code). Aucun correctif local ne peut combler ce trou — à décider consciemment plus tard si/comment le combler (export manuel périodique ? autre source ?).

**Effort:** —
**Priority:** P4 (veille — item sentinelle, ne pas implémenter sans décision)
**Depends on:** Décision produit

### Réexamen rétention trace.db — déclencheurs falsifiables

**What:** La rétention infinie du brut (décision du 2026-08-30) se rouvre UNIQUEMENT si un de ces seuils mesurables est franchi : `trace.db` > 500 Mo ; ou latence de rendu d'une page > 1 s malgré le cache /days ; ou l'audit `scripts/audit_secrets.py` > 60 s ; ou `~/.pulse_v2/transcript_archive` > 2 Go (croissance monotone, ~220 Mo au 2026-08-31). Premier levier si ça arrive : compaction des micro-événements `app_activated` (68 % des lignes, 20 octets pièce) — pas les résumés.

**Effort:** —
**Priority:** P4 (veille)
**Depends on:** Aucun — item sentinelle, ne pas implémenter

## Hors gel

Observations du dogfooding (`docs/dogfooding.md`) qui touchent la
reconstruction des sessions, donc le périmètre fonctionnel gelé (0.5.6). Parquées
ici, par ordre de priorité, pas de correctif sans décision.

### Fragmentation des sessions : `core/` détecté comme projet distinct de Pulse

**What:** Dans le repo unique, `core/` est qualifié comme un projet à part
(`core`) et non comme `Pulse` ; chaque bascule entre les deux coupe la session
en cours. Le 2026-09-05 : 26 sessions reconstruites, 20 jugées « trop
courtes ». Effet sur Intelligence : des sessions de 3 à 13 minutes qui ne
racontent qu'un fragment du travail, et une annexe `previous_summary` qui
remonte à un fragment plutôt qu'à la session précédente.

**Effort:** M
**Priority:** P2
**Depends on:** Décision sur le gel (changement de la qualification projet)

### Une session ouverte par un commit ne voit pas ses fichiers

**What:** Cas `eadb7573` (work-13 du 2026-09-05) : `core/CHANGELOG.md` et
`core/VERSION` sont écrits à 21:02:04 et 21:02:14, rattachés à work-12 ; le
commit 5d1f349 qui les contient tombe à 21:02:39 et **ouvre** work-13. La vue
de work-13 porte le commit (hash + message) mais `files.modified = []`, donc
le résumé rend `central_files: []`. L'événement `git_commit` porte
`files_changed`, `insertions`, `deletions` dans `details_json`, mais pas les
chemins.

**Deux remèdes à peser :** enrichir l'événement à la source (le hook git émet
la liste des chemins — donnée nouvelle dans un type existant, à confronter au
gel) ; ou ne pas couper une session entre une rafale de `file_changed` et un
`git_commit` qui la suit à moins d'une minute (reconstruction seulement, rien
de nouveau dans la trace).

**Effort:** M
**Priority:** P3
**Depends on:** Décision sur le gel

## Completed

### CI rouge : le test du verrou terminal assertait la vitesse du runner

**What:** `test_terminal_hook_reports_sqlite_lock_timeout` bornait la durée du hook par le haut (`assert 4.5 <= elapsed < 8`, `subprocess.run(timeout=8)`). Le hook attend le `busy_timeout` de l'outbox (5 s) puis renonce ; sur `macos-latest`, ces 5 s plus deux démarrages de processus dépassaient 8 s et la CI tombait sur une machine lente, pas sur une régression. Vert sur `main` le 2026-09-03, rouge le 2026-09-05 sans qu'une ligne de code ait bougé.

**Résolution:** Une machine lente ne peut qu'allonger `elapsed`, jamais le raccourcir : la borne basse porte tout le contrat (« il a bien attendu le verrou ») et reste vraie partout. Elle est désormais dérivée de `_BUSY_TIMEOUT_MS` au lieu d'être recopiée, avec 10 % de marge — SQLite ne rend pas la main à la milliseconde près. La borne haute est supprimée ; le `timeout=` du sous-processus, porté à 60 s, ne sert plus qu'à attraper un blocage franc. Aucun code de production touché : le défaut était l'assertion, pas l'attente. Mesuré à 5,35 s en local, suite Core à 550.

**Completed:** 2026-09-05

### Couverture d'observation en mode service (watcher fichiers + observateur d'apps sous launchd)

**What:** Le watcher fichiers et `PulseApplicationObserver` ne tournaient que sous `make dev` ; en mode service (launchd), le journal était aveugle aux fichiers et aux apps — le 2026-08-31 : `files_changed` 0, `applications` [] sur les deux sessions de la journée.

**Résolution:** Deux LaunchAgents `KeepAlive` supplémentaires (`scripts/install_observers_launchd.sh`, même patron managé : marqueur, refus d'écraser un plist étranger, `plutil -lint`, `--uninstall`). `com.pulse.file-watcher` : `daemon_v2.file_watcher --config ~/.pulse_v2/watched_workspaces` — le watcher passe au multi-workspaces (un collecteur + snapshot par workspace, un seul observer FSEvents, une seule boucle), liste **déclarée** (un chemin par ligne, entrée disparue ignorée avec avertissement — n'aveugle pas les autres, fichier absent = erreur, lue au démarrage → `launchctl kickstart -k` après édition). `com.pulse.app-observer` : binaire release copié dans `~/.pulse_v2/bin` (hors `.build`), `PULSE_CORE_REPO_ROOT` au plist. Les deux écrivent dans l'outbox durable (le pont Swift passe par `enqueue-json`) — daemon éteint, rien de perdu. Coexistence : `pulse_mode.sh` décharge les deux agents en mode dev (dev.sh lance ses propres watcher/observateur — sinon doublons, les event_id fichiers sont des uuid4) et les recharge en sortie s'ils sont installés ; `status.sh` affiche les 5 labels. Conséquence assumée : le watcher résident voit les écritures des agents (Claude Code compris) comme n'importe quel `file_changed`. Vérifié en réel : services running sous launchd, créé/supprimé dans Pulse_Core arrivés en base en ~6 s, second workspace ajouté à la liste + kickstart → événement attribué au bon workspace, `Activated Claude` émis par l'observateur résident. 3 tests (`read_watched_workspaces`), suite à 428.

**Completed:** 2026-08-31

### Hook SessionEnd Claude Code → émission agent_session immédiate

**What:** Brancher un hook `SessionEnd` de Claude Code (`~/.claude/settings.json`) qui, à la fin d'une session, archive SON transcript puis émet SON événement `agent_session` en ciblé — au lieu d'attendre le passage horaire launchd + la fenêtre de silence de 60 min.

**Résolution (décision (a) — émission immédiate, résumé figé à la première fin assumé ; item « Segments de reprise » porte le réexamen) :** mode ciblé dans le producteur (`emit_agent_sessions(transcript=...)` / CLI `--transcript` : seul CE fichier est traité, fenêtre de silence contournée, toutes les autres règles inchangées — déjà émis, sidechain, doublon, résumé figé ; transcript hors sources ou absent = erreur d'infrastructure). `scripts/pulse_session_end_hook.sh` : garde-fou 1 — exit 0 inconditionnel, tout va au log `~/.pulse_v2/logs/session_end_hook.log`, jamais d'échec visible pour Claude Code ; garde-fou 2 — archive zstd AVANT le pointeur, archivage en échec = émission annulée (le passage horaire launchd rattrape, il reste aussi le filet pour Codex, sans hooks). Course hook/passage horaire bénigne (event_id déterministe → duplicate inoffensif). Hook installé (`SessionEnd`, timeout 30 s, marqueur `_pulse_source`). **Mesuré sur la plus grosse session réelle Claude Code (50 Mo)** : 0,73 s à froid (archive+parse+émission), 0,16 s en rerun idempotent, scan réel des 177 fichiers sources 0,08 s — synchrone sans risque. 8 tests (5 mode ciblé, 3 script), suite à 425.

**Completed:** 2026-08-31

### Remplacer le polling du file watcher par watchdog/FSEvents

**What:** Migrer `file_watcher.py` du re-scan complet par seconde (`os.walk` + `stat`) vers la bibliothèque `watchdog` (FSEvents natif macOS).

**Why:** Le scan par seconde coûte CPU/batterie en continu sur un gros workspace ; FSEvents est le mécanisme éprouvé [Layer 1] exact pour ce besoin, avec un coût quasi nul au repos et sans la fenêtre d'1 s où création+suppression rapide passe inaperçue.

**Résolution:** Changement de détection uniquement (transport outbox intact — symétrique de 2A-révisée). Les pièges watchdog (coalescence FSEvents, types d'événements devinés, renames) sont neutralisés par design : watchdog (6.0.0, backend FSEvents vérifié) n'est qu'un notificateur de chemins sales (`DirtyPathCollector`, filtrage à la source), la vérité `created`/`modified`/`deleted` vient du snapshot (`resolve_dirty_paths` — stat des seuls chemins signalés, signature `(mtime_ns, taille)` inchangée → aucun événement, un save atomique reste `modified`, jamais `created`). Un événement répertoire coalescé s'étend aux enfants connus du snapshot + re-scan borné du répertoire s'il existe (mv d'arbres entiers couvert). `--interval` devient la fenêtre de coalescence ; observer mort = sortie bruyante pour dev.sh, après livraison des derniers événements. `compare_snapshots` supprimé (remplacé). Vérifié en réel sur FSEvents : créé/modifié/supprimé/save atomique/bruit `.git` — sémantique identique à l'ancien poller. 10 tests ajoutés, suite à 416.

**Completed:** 2026-08-31

### Ne plus promouvoir un événement fort isolé en session pleine

**What:** La reconstruction ouvre un bloc « Session » pour tout signal fort à >30 min du précédent, même seul — le 2026-08-30 affiche 6 sessions dont deux de 0 min (un `cd` nu, un commit isolé). Une session pleine devrait exiger ≥2 signaux forts ou une durée >0 ; l'événement isolé devient une « activité isolée » en une ligne, hors compteur de sessions.

**Context:** Cohérent avec la qualification projet du jour (fichier explicite OU ≥2 signaux OU preuve git). Zone CRITICAL (reconstruction + renderers + tests de contrat à faire évoluer explicitement). Le gap de 30 min lui-même est sain — ne pas l'élargir.

**Résolution:** Rétrogradation à la clôture de session (`reconstruct_session_views.close_current`) : <2 signaux forts ET durée 0 ET raison ≠ « open » (une session qui vient de commencer n'est jamais rétrogradée) → `activity_kind: "isolated"`. `_displayed_sessions` filtre, nouveau `isolated_sessions`, section « Activités isolées » (une ligne : heure · description · projet) dans les deux renderers, gardes « Aucune activité » ajustées, `work_session_count`/`session_count` ne comptent que les vraies sessions. La reconstruction elle-même est inchangée (les compteurs RAW du store restent identiques). 14 tests de contrat mis à jour (fixtures enrichies quand le sujet était autre, 3 réécrits vers le nouveau contrat). Vérifié en réel : la journée du 2026-08-30 passe de 6 sessions (dont 2×0 min) à 4 + 2 activités isolées. Suite à 405.

**Completed:** 2026-08-30

### Filtrer les transcripts de sous-agents (sidechains) du producteur agent_session

**What:** Le seul `agent_session` du 2026-08-30 est le prompt d'un sous-agent de revue de code : les transcripts sidechain (`isSidechain: true`) vivent dans les mêmes dossiers que les sessions principales et `parse_claude_session` ne les distingue pas. Les exclure (ou les marquer `sidechain: true` sans les émettre) pour que le signal reflète les vraies sessions.

**Context:** `summary_version` passe à 2 pour les nouvelles émissions (résumés déjà émis figés, décision rétention). Les sessions déjà émises en v1 restent telles quelles.

**Résolution:** `parse_claude_session` marque `sidechain=True` quand toutes les lignes user/assistant portent `isSidechain` (un transcript mixte reste mainline, conservateur) ; `emit_agent_sessions` les trace au manifeste sans émettre (`sidechain_skipped`), reconnus au re-run sans re-parsing. `SUMMARY_VERSION` → 2 pour les nouvelles émissions ; les résumés v1 déjà en base restent figés (décision rétention) — y compris la session sidechain du 2026-08-30 18:10, assumée. 2 tests. Suite à 405.

**Completed:** 2026-08-30

### Exclure les interruptions volontaires (exit 130) du signal d'erreur

**What:** `build_resume` traite tout `exit_code != 0` comme « Erreur terminal récente » et le label « erreur » compte pareil — or 5/8 commandes du 2026-08-30 étaient des Ctrl-C volontaires sur `make dev` (exit 130 = 128+SIGINT), qui écrasent les vrais signaux de reprise.

**Context:** Prédicat partagé `is_interrupted_exit` (130 seul ; 143/SIGTERM à n'ajouter que sur données observées), exclu du candidat erreur-récente (`daily_trace.py:469-477`) ET du label « erreur » (`analysis/terminal.py:187-189`). Ne pas toucher au statut des tests interrompus (« Échec (130) » reste juste pour un test non terminé).

**Résolution:** Prédicat `is_interrupted_exit` (130 seul) dans `analysis/terminal.py`, exclu de 4 points : label « erreur » (`terminal_labels`), candidat « Erreur terminal récente » (`build_resume`), compteur du résumé compact (`_build_compact_activity_summary`) et faits « Erreurs terminal » par session (`build_session_summary`). Les tests interrompus restent « Échec (130) » (un test coupé n'est pas vert). 2 tests. Suite à 403.

**Completed:** 2026-08-30

### Services daemon + worker en continu (launchd)

**What:** Faire tourner le daemon et le worker outbox en continu, même patron que le LaunchAgent des producteurs, pour que le journal se remplisse sans lancer `dev.sh`.

**Résolution:** `scripts/install_daemon_launchd.sh` — deux LaunchAgents `KeepAlive` (`com.pulse.daemon`, `com.pulse.outbox-worker`), un par service longue durée (vs `StartInterval` pour les passages ponctuels des producteurs), RunAtLoad, logs séparés, marqueur « managed », `--uninstall`. Coexistence dev.sh : verrou `flock` déjà présent côté worker ; conflit de port documenté côté daemon. Installé et vérifié en réel le 2026-08-30 : les deux services actifs, outbox à 0/0, et contrat KeepAlive prouvé (daemon tué → relancé par launchd, nouveau pid, /status répond).

**Completed:** 2026-08-30

### Exécution récurrente des producteurs agent (launchd)

**What:** Brancher l'exécution horaire de `archive_transcripts` PUIS `agent_sessions` (l'archive d'abord, le pointeur ensuite).

**Résolution:** `scripts/pulse_agent_producers.sh` (wrapper séquentiel — émission ANNULÉE si l'archivage échoue, exit 2 ; sources surchargeables par env pour les tests) + `scripts/install_agent_producers_launchd.sh` (génère et charge `com.pulse.agent-producers.plist` : StartInterval 3600, RunAtLoad, logs `~/.pulse_v2/logs/agent_producers.log`, `plutil -lint`, marqueur « managed », refus d'écraser un plist étranger, `--uninstall`). Installé et vérifié en réel le 2026-08-30 : premier passage exit 0. Le daemon peut être éteint : l'outbox durable porte les événements jusqu'à la prochaine livraison. 2 tests wrapper (ordre + annulation), suite à 401.

**Completed:** 2026-08-30

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
