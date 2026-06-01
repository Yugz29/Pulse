# Route Surfaces Closure

Internal phase: C4a

## Statut

Cette décision est documentation-only.

Aucun code n'est autorisé dans ce patch.

C4a est clôturable. C4a n'a supprimé aucune route, n'a modifié aucun payload et n'a lancé aucun gating global.

## Ce que C4a a clarifié

C4a a clarifié les surfaces suivantes :

- Core minimal routes ;
- debug routes ;
- historical / minimal memory ;
- Lab / legacy memory ;
- MCP / proposals ;
- memory candidates ;
- assistant / LLM legacy ;
- context probes ;
- work intent ;
- lightweight LLM ;
- `/scoring/status` comme route transverse.

## Ce qui est verrouillé par tests

Les tests C4a verrouillent notamment :

- les routes principales restent présentes ;
- `memory_candidates` reste disjoint de Core, debug, Lab memory et MCP ;
- il n'existe pas de `/memory/candidates/generate` ;
- il n'existe pas de `POST /memory/candidates` générique ;
- `/state` n'expose pas `memory_candidates` ;
- `/memory/write` et `/memory/remove` sont bloquées en Core ;
- les mutations facts sont bloquées en Core ;
- `facts/profile` est neutralisé en Core ;
- `/health/core` reste indépendant des services Lab ;
- assistant, context probes et work intent restent enregistrés mais non-Core minimal ;
- les routes `/llm/lightweight/*` sont conditionnelles ;
- `/scoring/status` est une route transverse.

## Ce que C4a a révélé

C4a a révélé que beaucoup de routes non-Core sont encore consommées par Swift ou par le dogfooding local.

Les routes suivantes ne doivent pas être gatées brutalement :

- `/ask/stream` ;
- `/context` ;
- `/llm/model` et `/llm/models` ;
- `/context-probes/requests*` ;
- `/work-intent/candidates*` ;
- `/insights` ;
- `/llm/lightweight/*` ;
- `/scoring/status`.

Certaines routes plus faibles, comme `/context-probes/schema` ou `/context-probes/request-preview`, pourraient devenir candidates à un gating pilote, mais pas sans décision séparée.

## Décision

C4a est considéré clôturable.

Décision :

- les routes non-Core restent temporairement enregistrées pour compatibilité locale et dogfooding ;
- elles ne sont pas Core minimal ;
- elles ne doivent pas devenir dépendances de `/health/core`, `/state`, `/feed`, `memory_candidates` ou mémoire canonique ;
- aucun gating global n'est autorisé ;
- tout futur gating doit être décidé route par route ;
- toute migration Swift doit être documentée avant code.

## Ce que cette décision interdit

Cette décision interdit :

- suppression brutale de routes ;
- gating global assistant / context probes / work intent ;
- changement payload non documenté ;
- présentation de routes non-Core comme Core stable ;
- utilisation de ces routes pour `memory_candidates` ou mémoire canonique ;
- ajout UI produit sans décision séparée.

## Prochaine étape recommandée

La prochaine phase recommandée est C4b — `main.py` boot safety minimal.

Objectif C4b :

- réduire les effets de bord au boot ;
- séparer progressivement factory / import / entrypoint si possible ;
- éviter `runtime = create_runtime()` au module import si faisable ;
- préserver la compatibilité de lancement existante ;
- ne pas refactorer massivement.

## Décision finale

C4a est clôturable.

La prochaine phase recommandée est C4b.

Aucun gating ou UI n'est autorisé par cette clôture.
