# Fermeture de session monotone

**Date :** 2026-09-03
**Statut :** tranchée
**Source :** audit externe du pas 3 (bloqueur P0), vérifié dans le code ;
branche `ship/session-closure-monotonic`

## Décision

Dans `core/daemon_v2/analysis/timeline.py`, `screen_locked` et
`system_sleep` sont des frontières dures et immédiates : dès que l'un
survient et qu'une session de travail est ouverte, elle se ferme
sur-le-champ avec ce motif (`end_reason`), bornée sur son dernier travail
observé. Une fermeture ne se défait jamais. `screen_unlocked` et
`system_wake` ne rouvrent rien : ils prouvent seulement que l'utilisateur
est de retour, et l'activité forte suivante démarre une nouvelle session.

Entre un verrouillage et la reprise **du bon type** (`screen_unlocked` pour
`screen_locked`, `system_wake` pour `system_sleep` ; verrouillage puis
veille exigent les deux reprises), aucune activité forte ne démarre ni ne
fait grandir une session de travail. Ce qu'on observe alors, ce sont des
faits — un agent qui tourne seul, un build qui finit — pas une reprise
humaine. Une reprise orpheline ou du mauvais type est ignorée en silence,
comme avant.

`RECONSTRUCTION_VERSION` passe à 2. Le seuil de fusion
`PULSE_SESSION_INTERRUPTION_MINUTES` (`configured_interruption_threshold`,
`DEFAULT_INTERRUPTION_THRESHOLD`) n'a plus d'appelant et disparaît. Les
champs `interruptions` et `active_duration_seconds` restent dans la forme
JSON des sessions, toujours vide et égal à `duration_seconds`.

## Pourquoi

Un verrouillage ouvrait une interruption « en attente » sans rien fermer.
Le résultat dépendait des données disponibles au moment du calcul : la
même session sortait fermée (`end_reason: screen_locked`, artefact de fin
de boucle) si le flux s'arrêtait là, puis rouverte par fusion si une
reprise et un travail suivaient dans les cinq minutes. Pire, une activité
forte sans déverrouillage vu passait pour la fin de l'interruption, écran
encore verrouillé : 123 signaux forts observés sur la base réelle pendant
des fenêtres de verrouillage, vraisemblablement des agents.

C'est incompatible avec le contrat `is_open: false` que le pas 3 (résumé
de session, `docs/specs/2026-09-03-session-summary.md`) utilise pour
choisir quoi résumer : Intelligence aurait pu résumer une session que Core
rouvrait deux minutes plus tard, sous un autre id.

## Bornes d'une session fermée par verrouillage

`ended_at` = dernier travail observé, pas l'instant du verrouillage : le
verrouillage est le motif, les minutes d'inactivité qui le précèdent ne
sont pas du travail, exactement comme pour `inactivity`. Un seul signal
fort avant le verrouillage reste une activité isolée (règle du
2026-08-30).

## La catégorie d'arrière-plan

Vue `activity_kind: "background"` dans `work_sessions`, une par fenêtre de
verrouillage : `id` (hash de ses propres sources), `label` `background-N`,
`source_event_ids`, `lock_type`, `locked_at`, `resumed_at` (ou `null`),
`end_reason` `resumed` / `still_locked`, bornes = première et dernière
activité, comptes habituels (`files_changed`, `commands_executed`…).
Elle ne compose ni l'identité ni les bornes d'aucune session de travail,
n'est pas comptée dans `work_session_count` ni dans le résumé du jour,
et n'atteint pas `/context` (`current_session`, `recent_sessions`,
`isolated_signals`, `/context/sessions` filtrent sur `work` / `isolated`).

Rendu (HTML et Markdown) : section « Activité en arrière-plan (écran
verrouillé) », hors Session et hors « Activité non attribuée » qui reste
vide, une ligne par fenêtre : `09:12–09:20 · 2 fichiers modifiés, 1 commit
(Pulse) — écran verrouillé à 09:10, reprise à 09:41` (ou « sans reprise
vue »). Même patron que « Sessions d'agent »
(`2026-09-03-agent-session-hors-identite.md`), section **distincte** : un
agent qui tourne pendant un verrouillage produit les deux — la ligne
d'agent dit ce qui lui a été demandé (résumé figé de l'événement dérivé),
la ligne d'arrière-plan dit ce qui s'est passé sur le disque (faits bruts).
Les fusionner ferait perdre l'une des deux informations.

## Limites connues

- La reconstruction est journalière : un verrouillage de la veille sans
  déverrouillage vu le jour même n'est pas connu du jour suivant. Le
  premier travail de la journée démarre une session.
- Les événements de verrouillage et de reprise ne sont plus rendus comme
  lignes d'activité dans un bloc Session (ils n'appartiennent à aucune
  session) ; la ligne « Fin : écran verrouillé » du bloc porte le motif.
- Une activité d'application pendant un verrouillage, sans session
  ouverte, tombe dans « Activité non attribuée » comme toute activation
  hors session.

## Réexamen

Exposer l'arrière-plan dans `/context` (par exemple pour qu'Intelligence
sache qu'un agent a travaillé pendant le verrouillage) uniquement quand un
consommateur le demande. Pas avant.
