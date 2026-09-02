# Cadrage V3 dégraissé et restructuration en repo unique

**Date :** 2026-09-02
**Statut :** tranchée
**Source :** cadrage V3 du 2026-08-31
([`../sources/2026-08-31-pulse-v3-cadrage.md`](../sources/2026-08-31-pulse-v3-cadrage.md))
et décisions prises depuis. Le document canonique est
[`../VISION.md`](../VISION.md).

## Décisions de direction

- **Roadmap réduite à trois pas** : (1) geler Core à 0.2 (la 0.2.0 est sortie le 2026-08-31, le gel est décidé aujourd'hui) ; (2) Context API,
  `GET /context` déterministe sans LLM ; (3) première boucle IA = résumé de
  session par un modèle local, stocké comme événement dérivé sur le patron de
  `agent_session`. Les phases benchmark et audit du cadrage sont supprimées.
  La proactivité vient après.
- **Un seul modèle local** pour commencer. Pas de Model Router à trois tiers
  tant qu'un problème réel ne l'exige pas.
- **Deux types de mémoire** : l'événementiel et les sessions (`trace.db`,
  existe) plus les résumés (à construire). Sémantique, épisodique et long
  terme viendront quand il y aura des résumés à indexer.
- **Runtime IA** : MLX sur Apple Silicon, sans Ollama. Pulse ne dépend d'aucun
  runtime spécifique.
- **Cortex, DevNote, Quest 3 hors périmètre** de la roadmap. Cortex et DevNote
  restent des sources d'enrichissement optionnelles, jamais structurantes :
  Pulse dégrade proprement si elles sont absentes.
- **Philosophie de construction** : composer avec des briques existantes
  (bibliothèques, inférence) mais construire soi-même le cœur — orchestration,
  mémoire, contexte.
- **Naming** : Pulse = le système entier. Pulse Core = la couche observation,
  garde son nom.

## Restructuration

- `~/Projets/Pulse/` devient le repo unique. Le repo `Pulse_Core` est promu à
  la racine, son contenu déplacé dans `core/` avec renommages git à 100 % :
  l'historique est conservé (`git log --follow`).
- Pulse Lab (SwiftUI + daemon Python, sqlite-vec, Ollama, MCP) est archivé
  intact dans `~/Projets/ARCHIVE/Pulse_Lab/`. Son repo imbriqué
  (`Pulse_Lab/Pulse`, remote `Pulse_V1`) porte le tag `archive/lab-2026-09`
  sur un dernier commit qui capture l'état de travail. Aucune suppression.
- Toute la documentation de Lab (docs v1/v2, contrats du Core Reset, audits,
  roadmaps de refacto, notes privées) est classée « ancienne direction » et
  archivée avec Lab. Rien n'en est extrait.
- L'outillage remonte à la racine : `.claude/`, `.gitnexus/`, `.gstack/`,
  `CLAUDE.md`, `AGENTS.md`. `CLAUDE.md` et `AGENTS.md` sont désormais suivis
  par git ; `.gitnexus/`, `.claude/` et `cortex-snapshot.json` restent
  ignorés.
- Aucun code de Core ne change. Les chemins absolus externes (LaunchAgents,
  hook SessionEnd, `.zshrc`, `watched_workspaces`, hook post-commit) ont été
  mis à jour à la main vers `~/Projets/Pulse/core`.

## Vérification

Suite Core lancée depuis `core/` après le déplacement : 432 tests passés.
