# Réouverture de Core pour un lot hardening 0.5.6

**Date :** 2026-09-05
**Statut :** tranchée — périmètre arrêté, implémentation à venir
**Source :** état des lieux au retour de migration (crash de l'observateur
d'applications relevé dans `~/.pulse_v2/logs/app_observer.log`, faux négatif de
`make status`) et cartographie des chemins menée pour
[la migration de la trace](2026-09-05-migration-trace-ancienne-machine.md).

## La décision

**Le gel de Core porte sur son périmètre fonctionnel, pas sur ses correctifs.**
C'est la lecture déjà appliquée en pratique : 0.5.1 (hardening), 0.5.2 (course
outbox), 0.5.4 (fermeture monotone), 0.5.5 (durcissement natif) sont toutes
sorties après le gel, sans ajouter de fonction. La 0.5.6 continue cette série.

Le gel reste entier sur ce qu'il visait : aucune nouvelle source d'observation,
aucun nouveau type d'événement, aucun changement du contrat `GET /context`.

## Périmètre du lot 0.5.6 — trois items, rien d'autre

1. **Crash de réentrance de `PulseApplicationObserver`.** `observe(_:)` est
   ré-entré pendant que `OutboxBridge` bloque la boucle principale dans
   `waitUntilExit`, ce qui viole l'accès exclusif à `recorder` et abat le
   processus (`Fatal access conflict detected`). 4 occurrences le 2026-09-05.
   `KeepAlive` relance, donc la perte est bornée — mais des activations
   disparaissent à chaque fois.
2. **Faux négatif de `scripts/status.sh`.** `--max-time 2` contre un `/status`
   qui répond en 2,04–2,11 s : `make status` annonce « daemon inaccessible »
   alors que le daemon tourne et répond 200.
3. **Résolution de casse là où l'échec est silencieux**, dans
   `daemon_v2/file_watcher.py` et `daemon_v2/private_files.py`. Une entrée de
   `watched_workspaces` dont la casse diverge donne un watcher qui démarre,
   journalise « Watching files in … », et n'émet plus rien : `should_ignore`
   retourne `True` sur `ValueError` de `relative_to`. Vérifié en conditions
   réelles — FSEvents remonte la casse canonique du disque, le watcher compare
   à la casse déclarée, tout est filtré sans un avertissement.

## Hors périmètre, explicitement

- Les 19 autres points de comparaison sensibles à la casse relevés par la
  cartographie (`analysis/projects.py`, `analysis/timeline.py`,
  `daily_trace.py`, `context_snapshot.py`, `event_logger.py`,
  `archive_transcripts.py`, `agent_sessions.py`). Ils dégradent l'affichage ou
  le regroupement, jamais en silence total, et n'ont pas de déclencheur observé.
- Le passage des chemins stockés à une forme relative à `$HOME` : changement de
  contrat d'événement, donc `schema_version` et migration. Reste une option
  ouverte, hors de ce lot.
- Toute uniformisation rétroactive des noms de projet en base (décidé le même
  jour dans la note de migration : les noms d'époque sont conservés).

## Analyse d'impact préalable

Menée sur l'index GitNexus reconstruit (2 299 nœuds, 6 418 arêtes) :

| Symbole | Impactés | Risque |
| --- | --- | --- |
| `ApplicationObserver.observe` | 12 | LOW |
| `OutboxBridge.run` | 8 | LOW |
| `should_ignore` | 8 | LOW |
| `should_ignore_directory` | 5 | LOW |
| `read_watched_workspaces` | 2 | LOW |
| **`is_private_path`** | **13** | **HIGH** |

`is_private_path` est le seul point à risque élevé : 4 processus en dépendent
(`archive_transcripts.main`, `agent_sessions.main`, `outbox_worker.main`,
`emit_agent_sessions`) et il commande le resserrement des permissions
`0700`/`0600` décidé en 0.5.1. Un faux positif y élargirait le champ des
dossiers dont Pulse modifie le mode — c'est la contrainte à respecter dans
toute correction : la comparaison peut devenir plus permissive **dans la
reconnaissance**, jamais dans le périmètre des racines corrigées.

`OutboxBridge.run` est appelé par les deux observateurs (`ApplicationObserver`
et `SystemObserver`) : une correction de la réentrance doit couvrir les deux
chemins, pas seulement les activations d'applications.
