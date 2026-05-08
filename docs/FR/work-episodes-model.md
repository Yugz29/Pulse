# Pulse — Modèle des épisodes de travail

## Statut

Ce document décrit le modèle cible de la Phase 2a.

Les `work blocks` existent déjà partiellement via `daemon/memory/work_heartbeat.py` et `today_summary`.

Les épisodes de travail ne sont pas encore implémentés comme unité canonique.

## Objectif

Pulse doit distinguer clairement plusieurs concepts proches mais différents :

- session système
- work block
- épisode de travail
- livraison de commit
- entrée de journal

Cette distinction évite de confondre un ordinateur allumé, une session runtime longue, une livraison Git tardive ou une simple présence utilisateur avec du temps de travail réel.

## Définitions

### Session système

La session système décrit l'état large du runtime : `awake`, `active`, `idle`, `locked`, ainsi que la durée live affichée par Pulse.

Elle peut être plus large que le travail réel. Par exemple, une machine peut rester active pendant une lecture passive, une pause, une vidéo ou un contexte non professionnel.

La session système ne doit jamais être utilisée seule comme durée travaillée.

### Heartbeat de travail

Un heartbeat de travail est un signal qualifié par `daemon/memory/work_heartbeat.py`.

Il existe trois niveaux :

- `strong`
- `weak`
- `none`

Un heartbeat `strong` peut ouvrir ou prolonger un bloc de travail.

Un heartbeat `weak` peut seulement soutenir ou prolonger un bloc récent déjà corroboré par un signal `strong`.

Un heartbeat `none` ne doit jamais créer ni prolonger du travail.

### Work block

Un work block est un cluster court de heartbeats qualifiés.

Il représente une activité de travail observée, déjà utilisée par `today_summary`.

Sa durée vient des heartbeats et de leur clustering. Elle ne doit pas dépendre de la durée wall-clock brute de la session système.

### Épisode de travail

Un épisode de travail est la future unité canonique de la Phase 2a.

Il regroupe un ou plusieurs work blocks cohérents autour d'une même intention ou tâche. Il peut survivre à de courts gaps si les signaux restent compatibles.

Il doit se terminer sur une vraie rupture : long idle, non-work dominant, screen lock, nuit, restart repair, ou autre frontière qui rend la continuité incertaine.

### Livraison de commit

La livraison de commit est le moment où un commit est livré.

Ce n'est pas forcément le moment où le travail a été fait. Un commit peut être créé ou poussé après coup, parfois le lendemain.

Ce moment doit être représenté par `delivered_at`.

### Entrée de journal

Une entrée de journal est un rendu mémoire humain.

Elle peut fusionner plusieurs commits ou plusieurs blocs lorsque cela améliore la lecture.

Elle ne doit pas inventer de durée travaillée si les preuves sont faibles.

## Invariants

- La présence utilisateur seule ne peut jamais ouvrir un épisode.
- Une app faible seule ne peut jamais ouvrir un épisode.
- Les apps IA/dev sont des signaux `weak` sauf corroboration.
- Les commandes git read-only comme `status`, `log`, `show` et `diff` ne sont pas des preuves fortes.
- Les titres non-work type YouTube/Netflix doivent empêcher ou couper la prolongation.
- Un commit livré tard ne rallonge jamais la durée travaillée.
- `delivered_at` est distinct de `worked_at`.
- La durée d'un épisode vient des heartbeats/work blocks, pas de `session_duration_min`.
- Une session `restart_repair` longue doit être considérée incertaine tant qu'elle n'est pas corroborée.

## Règles de rattachement d'un commit

La règle cible est de rattacher un commit à un épisode compatible, sans gonfler artificiellement la durée.

Pulse doit chercher un épisode récent compatible avec le commit.

La compatibilité doit utiliser la cohérence des fichiers, le scope du diff, le projet actif et les signaux de travail observés.

Si le commit est livré beaucoup plus tard, `worked_at` reste sur l'épisode réel et `delivered_at` porte l'heure du commit.

Si aucun épisode compatible n'existe, Pulse doit créer une entrée commit-only courte ou incertaine plutôt que gonfler la durée depuis la session système.

## Exemples

### Travail normal

Code + terminal + commit immédiat.

Pulse crée un épisode court à partir des work blocks observés. Le commit est livré dans l'épisode, donc `worked_at` et `delivered_at` restent proches.

### Livraison tardive

Travail de 23:00 à 00:30, puis YouTube/nuit, puis commit à 10:00.

Pulse conserve `worked_at` sur 23:00-00:30. Le commit porte `delivered_at` à 10:00. La durée de travail n'est pas rallongée jusqu'à 10:00.

### Présence sans travail

YouTube + souris + Chrome.

Pulse ne crée aucun épisode. La présence utilisateur et l'app active ne suffisent pas.

### App IA pendant le travail

Code + ChatGPT + terminal.

ChatGPT soutient l'épisode parce qu'il apparaît dans un contexte déjà corroboré par du code ou du terminal. ChatGPT seul ne doit pas ouvrir l'épisode.

## Implications pour Phase 2a

La Phase 2a doit construire la chaîne suivante :

```text
events → heartbeats → work blocks → episodes → journal entries
```

La Phase 2a ne doit pas :

- utiliser `session_duration_min` comme source de vérité
- assimiler `commit_time` à `start_time`
- assimiler app active à travail
- réintroduire un cap arbitraire de durée

## Non-objectifs

- Pas de fine-tuning.
- Pas d'apprentissage adaptatif maintenant.
- Pas de refactor global.
- Pas de surveillance intrusive écran/contenu.
- Pas de résumé LLM pour décider de la durée travaillée.
