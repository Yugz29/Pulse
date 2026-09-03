# `agent_session` hors identité des sessions

**Date :** 2026-09-03
**Statut :** tranchée, réexamen sur déclencheur (voir plus bas)
**Source :** audit externe du pas 3 (résumé de session), correction 1 ;
branche `ship/session-identity-agent-fix`

## Décision

L'événement dérivé `agent_session` ne participe plus au regroupement des
sessions de travail dans `core/daemon_v2/analysis/timeline.py` : il n'est
plus un signal fort, ne fait jamais partie des `event_id` qui composent
l'identité d'une session (`source_event_ids`, hash `id`) et n'influence plus
ses bornes `started_at` / `ended_at`. Il n'est pas non plus rendu comme
activité isolée ou non attribuée : la trace journalière (HTML et Markdown)
le liste dans une catégorie d'affichage à part, « Sessions d'agent », avec
ses bornes et le résumé figé de l'événement — affichage seulement, sans
recalcul, indépendant de la session de travail dont il est proche.

Il reste accessible exactement comme prévu par la spec du résumé de session :

- `GET /context` → `last_agent_session`, déjà sans fenêtre ;
- annexé à l'entrée du modèle dans `intelligence/` (spec §7, clé
  `agent_session`).

## Pourquoi

Un `agent_session` est émis après coup — hook `SessionEnd`, ou passage
horaire launchd pour Codex — avec un `occurred_at` qui tombe au milieu d'une
session déjà reconstruite. L'identité d'une session est le hash de ses
sources (Core 0.5.0) : l'arrivée tardive changeait donc l'`id` et les bornes
d'une session que la couche Intelligence avait peut-être déjà résumée, et
le résumé désignait alors un ensemble d'événements qui n'existait plus dans
`/context/sessions`. L'audit a reproduit le cas ; le test
`test_late_agent_session_inside_a_session_never_moves_its_identity` le gèle.

## Effet de bord accepté

Comme signal fort, un `agent_session` pouvait faire pont entre deux grappes
de travail distantes de moins de 30 minutes de lui et les fusionner en une
seule session. Ce n'est plus le cas : deux grappes séparées de plus de
30 minutes restent deux sessions, quoi qu'un agent ait fait entre les deux.
Documenté par `test_agent_session_no_longer_bridges_two_clusters_within_the_gap`.

Conséquence visible : la ligne « Agent session (claude-code) » quitte les
blocs Session et « Activités isolées » pour la section « Sessions d'agent ».
Le nombre d'événements du jour la compte toujours.

## Réexamen

Revoir ce choix (par exemple avec un mécanisme générique de tolérance aux
arrivées tardives, plutôt qu'une exclusion par type) **si un type d'événement
autre qu'`agent_session` montre le même pattern d'arrivée tardive** : un
`occurred_at` antérieur à l'ingestion de plus que la fenêtre de session, qui
modifie l'identité d'une session déjà résumée.
