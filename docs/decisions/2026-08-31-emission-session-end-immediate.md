# Hook SessionEnd Claude Code — émission immédiate, résumé figé

**Date :** 2026-08-31
**Statut :** tranchée (décision « a »), réexamen porté par l'item
« Segments de reprise pour agent_session » de `core/TODOS.md`
**Source :** `core/TODOS.md`, section « Completed », « Hook SessionEnd Claude
Code → émission agent_session immédiate »

## Décision

À la fin d'une session Claude Code, un hook `SessionEnd` archive le transcript
de cette session (zstd) puis émet son événement `agent_session` en mode ciblé,
sans attendre le passage horaire launchd ni la fenêtre de silence de 60 min.

Conséquence assumée : le résumé est figé à la première fin de session. Une
session reprise ensuite sur le même transcript est signalée
(`grown_after_emit`) mais jamais ré-émise.

## Garde-fous

- Le hook sort toujours en 0 ; tout va au log
  `~/.pulse_v2/logs/session_end_hook.log`. Jamais d'échec visible pour Claude
  Code.
- Archive avant pointeur : un archivage en échec annule l'émission. Le passage
  horaire launchd rattrape, et reste le filet pour Codex, sans hooks.
- Course hook / passage horaire bénigne : `event_id` déterministe, le doublon
  est un duplicate inoffensif.

## Pourquoi

Le journal voyait une session d'agent avec jusqu'à une heure de retard. Mesuré
sur la plus grosse session réelle (50 Mo) : 0,73 s à froid, 0,16 s en rerun.
Synchrone sans risque.

## Réexamen

Passer aux segments de reprise (nouvel événement borné, même `session_id`,
`segment: 2`) uniquement quand `grown_after_emit` devient récurrent dans les
logs. Ne pas implémenter avant.
