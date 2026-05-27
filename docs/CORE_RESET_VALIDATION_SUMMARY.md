# Synthèse de validation — Pulse Core Reset R1-R6

État courant : R1 à R6 sont validés côté Python. La suite complète récente `./scripts/test_all.sh` passe avec 1216 tests OK.

Ce document ne démarre pas R7. Il ne propose pas d'apprentissage, de facts / profile, de DayDream, de vector store, de résumés LLM, de dashboard avancé ni de nouvelle feature.

## Verdict Core Reset

Pulse Core a maintenant une baseline Python crédible de runtime local de diagnostic. Pulse n'est pas un agent intelligent, pas une mémoire intelligente et pas un système adaptatif.

Le reset a surtout réussi à séparer les couches Core des surfaces Lab les plus risquées. Le résultat n'est pas "Pulse comprend l'utilisateur", mais "Pulse possède un socle observable, testable et moins menteur".

R1 à R6 valident :

- le runtime minimal ;
- l'observation ;
- l'interprétation prudente ;
- les sessions ;
- la mémoire minimale ;
- les propositions contrôlées.

## Ce qui est maintenant garanti

Pulse Core garantit raisonnablement :

- un mode runtime `core` par défaut ;
- `/ping`, `/state`, `/feed`, `/debug/state` et `/health/core` utilisables sans services Lab ;
- une ingestion `/event` vers `EventBus` avec filtrage de bruit, normalisation terminal et actor classification testés ;
- des fixtures d'observation portables, sans dépendance à `/Users/yugz` ;
- un feed lisible sur un bus réaliste ;
- un `SignalScorer` verrouillé par scénarios golden, sans prétendre être plus explicable qu'il ne l'est ;
- des tests anti-overclaim sur signaux faibles ;
- des sessions runtime via `SessionFSM` avec états réels `idle`, `active`, `locked` ;
- une intégration session dans `RuntimeOrchestrator`, `RuntimeState`, `/state` et `/debug/state` ;
- une persistance minimale via `SessionMemory` SQLite et snapshots ;
- une baseline de restart repair distincte du commit recovery ;
- une mémoire minimale avec hidden payload et `truth_layers` ;
- des routes mémoire Core/Lab testées : lecture historique acceptable, write/remove bloqués en Core ;
- un flux MCP de propositions contrôlées où l'autorisation passe seulement par `accepted`.

## Ce qui n'est pas garanti

Pulse Core ne garantit pas :

- une compréhension profonde de l'utilisateur ;
- l'apprentissage d'habitudes ;
- un profil utilisateur ou projet fiable ;
- une mémoire sémantique ;
- une recherche vectorielle produit ;
- des résumés LLM fiables ;
- des propositions intelligentes ;
- des actions autonomes ;
- de l'adaptation ;
- une preuve canonique détaillée des poids internes du `SignalScorer` ;
- une séparation parfaite produit/debug dans tous les payloads ;
- que le dashboard Swift reflète parfaitement toutes les frontières Core/Lab ;
- une robustesse terrain macOS prolongée au-delà des tests Python.

Les tests prouvent une baseline. Ils ne prouvent pas encore que Pulse est stable après plusieurs jours d'usage réel.

## Ce qui reste Lab / expérimental

Restent Lab ou hors Core :

- DayDream ;
- facts / profile ;
- `MemoryStore` comme mémoire durable produit ;
- vector store ;
- embeddings ;
- résumés LLM ;
- lightweight LLM queue en produit Core ;
- context probes ;
- work intent candidates ;
- resume cards intelligentes ;
- context injection Lab/dev auto-`executed` ;
- commit episode linking ;
- work episodes riches ;
- dashboard avancé ;
- apprentissage utilisateur / projet ;
- adaptation ;
- propositions générées par LLM ;
- corrections autonomes.

## Fragilités acceptées

Fragilités documentées et acceptées pour l'instant :

- `SignalScorer` ne retourne pas encore une trace canonique des poids / preuves internes.
- `/state.present` peut paraître plus affirmatif que les signaux réels, notamment parce que `task_confidence` n'est pas dans `PresentState`.
- `WorkContextCard` reconstruit une explication après coup ; ce n'est pas la preuve source du scorer.
- `SessionFSM.session_started_at` peut exister avant une vraie activité si ce champ est lu naïvement.
- `paused`, `closed` et `resumed` ne sont pas des états FSM.
- `/memory/sessions` Markdown reste une lecture historique, pas une source canonique.
- `extractor.py` reste mixte.
- `update_memories_from_session()` n'est pas Core-safe comme fonction isolée.
- `/memory/sessions?include_hidden=true` expose encore le payload brut explicitement.
- `ProposalStore` permet techniquement `pending -> executed`.
- `Proposal` n'a pas `decided_by`, `decision_source` ou `human_approved`.
- `/mcp/decision` peut publier un événement même si la décision échoue.

## Ce qui peut être testé en usage réel

Assez solide pour usage réel prudent :

- démarrage daemon en mode Core ;
- santé `/health/core` ;
- `/ping`, `/state`, `/debug/state`, `/feed` ;
- ingestion d'événements app / file / terminal / lock / idle ;
- lisibilité du feed ;
- observation du bruit filtré ;
- scoring courant comme hypothèse, pas vérité ;
- sessions lock / unlock / idle / restart ;
- snapshots session SQLite ;
- lecture historique mémoire minimale ;
- flux MCP approval / deny / timeout.

Le test terrain doit vérifier la stabilité et la qualité des signaux. Il ne doit pas chercher à activer l'intelligence.

## Ce qu'il ne faut pas toucher maintenant

Ne pas toucher maintenant :

- DayDream ;
- facts / profile ;
- vector store ;
- embeddings ;
- résumés LLM ;
- apprentissage / adaptation ;
- propositions intelligentes ;
- context probes automatiques ;
- work intent intelligent ;
- dashboard avancé ;
- refactor massif de `RuntimeOrchestrator` ;
- refonte mémoire ;
- optimisation LLM ;
- nouvelles catégories de scoring.

Le risque principal serait de casser les frontières Core/Lab fraîchement stabilisées.

## Risques si on repart trop vite dans les features

Repartir trop vite dans les features avancées risque de :

- réintroduire des effets de bord Lab dans le boot Core ;
- transformer des signaux faibles en affirmations produit ;
- promouvoir du Markdown ou du narratif en vérité canonique ;
- faire passer `executed` pour une validation humaine ;
- rendre `/state` dépendant de LLM, facts ou vector store ;
- masquer des bugs de session derrière des résumés intelligents ;
- rendre les tests verts mais le comportement terrain illisible ;
- perdre la séparation observation / interprétation / session / mémoire / proposition.

Ce serait recréer le problème que le Core Reset vient de réduire.

## Prochaine étape recommandée

Prochaine étape saine : validation terrain Core, sans nouvelle feature.

Plan court :

- lancer Pulse en `PULSE_MODE=core` sur une vraie session de travail ;
- observer les logs daemon : erreurs, bruit, events ignorés, lock / unlock, restart repair ;
- vérifier `/health/core`, `/state`, `/debug/state` et `/feed` pendant l'usage ;
- comparer ce que Pulse affiche avec ce qui s'est réellement passé ;
- vérifier que le dashboard reste diagnostic et ne vend pas de Lab comme stable ;
- relancer les smoke tests daemon et `./scripts/test_all.sh` après les observations ;
- nettoyer README / docs uniquement si elles prétendent encore que Pulse fait plus que le Core validé.
