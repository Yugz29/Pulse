# Migration de la trace de l'ancienne machine — normalisation puis fusion

**Date :** 2026-09-05
**Statut :** appliquée
**Source :** changement de machine (MacBook Pro M3 Max). `~/.pulse_v2` n'a pas
suivi la migration : la base active repartait de zéro le 2026-09-05 à 11:32 UTC,
tandis que l'ancienne base (9 737 événements depuis le 2025-10-08) et l'archive
de transcripts (215 Mo, 183 fichiers) dormaient dans `~/Desktop/Pulse/`.
**Outils :** `tools/normalize_legacy_trace.py`, `tools/merge_traces.py`,
`tools/rename_archive_tree.sh`.

## Contexte

Le dossier utilisateur a changé de casse entre les deux machines :
`/Users/yugz` est devenu `/Users/Yugz`. Deux propriétés se contredisent alors :

- APFS est **insensible** à la casse — `Path("/Users/yugz").exists()` vaut
  `True` ici, `os.path.samefile` confirme le même inode ;
- `PurePath` est **sensible** à la casse — `==` est faux, `relative_to` lève.

`realpath` / `.resolve()` **ne canonisent pas la casse** (vérifié :
`os.path.realpath("/Users/yugz/…")` rend le chemin inchangé). L'option
« normaliser à la comparaison avec realpath » était donc sans effet ; la
cartographie complète des points de comparaison est le préalable de la
réouverture décidée le même jour (voir
[`2026-09-05-reouverture-core-hardening.md`](2026-09-05-reouverture-core-hardening.md)).

La casse n'était pas la seule dérive : la restructuration en repo unique du
2026-09-02 avait déplacé Core, et deux projets sans rapport avaient changé de
nom. D'où une table de correspondance, pas une simple substitution.

## Table de correspondance

Ordre significatif, première règle qui matche, sur frontière de segment. Les
formes encodées (dossiers de projet Claude Code, où `/` et `_` deviennent `-`)
et les slugs d'archive (`parts` jointes par `-`) sont **dérivés
mécaniquement** de ces règles, jamais saisis à la main.

| Ancien préfixe | Nouveau | Motif | Occurrences |
| --- | --- | --- | --- |
| `/Users/yugz/Projets/Pulse/Pulse_Core` | `/Users/Yugz/Projets/Pulse/core` | Core avant le repo unique | 2 686 |
| `/Users/yugz/Projets/Pulse_V2` | `/Users/Yugz/Projets/Pulse/core` | premier nom de Core | 1 227 |
| `/Users/yugz/Projets/Pulse/Pulse` | `/Users/Yugz/Projets/Pulse` | imbrication transitoire d'avril | 18 |
| `/Users/yugz/Projets/portfolio` | `/Users/Yugz/Projets/Portfolio` | seconde dérive de casse, sans rapport avec `$HOME` | 33 |
| `/Users/yugz/Projets/Holberton C#28` | `/Users/Yugz/Projets/Holberton28` | renommé sur l'ancienne machine déjà | 34 |
| `/Users/yugz` | `/Users/Yugz` | repli : casse du dossier utilisateur | 10 444 |

Les 44 racines de l'ancienne base ont été confrontées une à une au disque
actuel par résolution **exacte en casse** (comparaison de noms segment par
segment, `exists()` seul mentant sur APFS). Tout le reste se résout sans
règle. Cinq racines n'ont plus de cible plausible sur la machine actuelle
— dossiers de travail sans rapport avec Pulse, sandbox et répertoires
temporaires disparus : aucune règle ne les concerne, elles sont laissées
telles quelles et seule la casse du dossier utilisateur leur est appliquée.

## Décisions

- **Les événements Core d'époque pointent vers `Pulse/core`, pas `Pulse`.**
  Ces événements portent des chemins de fichiers : mapper vers `Pulse` aurait
  fabriqué 1 445 chemins n'ayant jamais existé
  (`…/Pulse/daemon_v2/daily_trace.py`), là où `Pulse/core` désigne le fichier
  réel. Le résolveur les regroupe ensuite sous projet `Pulse`, module `core`
  (`core` est dans `GENERIC_MODULE_NAMES`) — vérifié au rendu du 2026-07-24.
- **`Pulse/Pulse` est mappé vers `Pulse`.** 6 événements d'avril 2026, dossier
  disparu, aucune cible mieux fondée.
- **Les noms d'époque sont conservés, aucune uniformisation.**
  `git_commit.repository` (42) et `workspace.project_name` (80) valant
  `Pulse_Core` restent tels quels : ce sont des noms, pas des chemins, et le
  dépôt s'appelait bien ainsi. Une session de juillet s'affiche donc
  « Projet : Pulse_Core » tout en étant rattachée au projet `Pulse`.
- **Chevauchement du 2026-09-05 : les événements de l'ancienne machine à partir
  de la première trace locale sont écartés.** Les deux machines ont enregistré
  simultanément ce jour-là. Seuil = `2026-09-05T11:32:30.274000+00:00`, la
  première trace du nouveau Mac. 47 événements écartés, **15 conservés**
  (10:37:42 → 11:18:53 UTC) : période sans recouvrement, close par un
  `system_sleep` 14 minutes avant le démarrage du nouveau Mac.

## Contraintes de la réécriture

- **Jamais en place.** `activities` est append-only par trigger : un `UPDATE`
  est refusé. Le script écrit une base neuve avec le DDL exact de la source.
- **`event_id` et `session_id` intacts** — ce sont les clés de fusion. Aucune
  collision entre les deux bases (0 sur 7 110 × 9 737).
- **`event_fingerprint` recalculé sous preuve.** L'empreinte est un sha256 des
  détails (`daemon_v2/models.py:71`) ; réécrire `details_json` la périme, et
  une ré-émission lèverait `EventConflictError` (`trace_store.py:214`). Le
  script ne recalcule une empreinte que s'il a d'abord su **reproduire celle
  qui était stockée**. L'auto-test a révélé **168 lignes dont l'empreinte
  n'est reproductible par aucune variante connue de l'algorithme** (2026-07-23
  → 08-25, 157 `app_activated` + 11 `terminal_finished`) : déjà périmées
  avant cette migration, laissées intactes. Le script abandonne si l'une
  d'elles est un `agent_session`, seul type à `event_id` déterministe donc
  ré-émissible ; aucune ne l'était.
- **Le texte libre n'est réécrit que sur chemins absolus.** Restent
  volontairement : `cd Projets/Pulse/Pulse_Core` (chemin relatif, 86),
  `rg "yugz|/Users/yugz|Projets"` (le motif fait partie de la commande, 1),
  les mentions dans les messages de commit et `first_prompt`.

## Résultat

```
Base    : 16 800 lignes fusionnées (9 690 + 7 110), integrity_check ok
          plage 2025-10-08 → 2026-09-05, 90 jours
Archive : 186 fichiers .zst, manifeste à 186 clés, bijection vérifiée
Agent   : manifeste à 185 entrées, 0 collision
```

Validation avant bascule par daemon jetable sur le port 8799 : `/status`,
`/context` (`schema_version: 2`), rendu markdown d'un jour de juillet,
`last_agent_session`. Passage d'archivage à blanc après bascule :
`Unchanged: 2`, aucun ré-archivage.

## Procédure de retour arrière

Sauvegardes datées dans `~/.pulse_v2/`, conservées :

```
trace.backup-20260905-201049.db                       5,9 Mo
agent_sessions_manifest.backup-20260905-201049.json
transcript_archive.backup-20260905-201049/            392 Ko
```

```sh
U=$(id -u)
for l in com.pulse.daemon com.pulse.outbox-worker com.pulse.file-watcher \
         com.pulse.app-observer com.pulse.agent-producers; do
  launchctl bootout gui/$U/$l
done
cd ~/.pulse_v2
rm -f trace.db trace.db-wal trace.db-shm
cp trace.backup-20260905-201049.db trace.db
cp agent_sessions_manifest.backup-20260905-201049.json agent_sessions_manifest.json
rm -rf transcript_archive && cp -Rp transcript_archive.backup-20260905-201049 transcript_archive
~/Projets/Pulse/core/scripts/fix_permissions.sh
for l in com.pulse.daemon com.pulse.outbox-worker com.pulse.file-watcher \
         com.pulse.app-observer com.pulse.agent-producers; do
  launchctl bootstrap gui/$U ~/Library/LaunchAgents/$l.plist
done
```

Les sources de `~/Desktop/Pulse/` n'ont jamais été ouvertes en écriture : elles
restent un troisième filet, indépendant des sauvegardes ci-dessus.

## Limite connue

`~/Desktop/Pulse/.pulse_v2` est une copie prise à chaud le 2026-09-05 à
18:16:50, alors que l'ancienne machine tournait encore (ses 62 derniers
événements décrivent la récupération elle-même). Le `-wal` n'a pas été copié.
`integrity_check` est `ok` et le dernier événement est cohérent avec le `mtime`
à une seconde près, mais si l'ancienne machine est encore accessible, une copie
à froid après arrêt du daemon reste préférable pour tout ce qui suivrait.
