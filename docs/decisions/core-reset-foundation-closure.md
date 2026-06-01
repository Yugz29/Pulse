# Core Reset Foundation Closure

Internal phase: C2

## Statut

C2 est clôturable.

La phase a transformé les constats de C1 et du dogfooding en garde-fous concrets, sans démarrer R7 et sans ajouter de mémoire intelligente.

C2 est considérée terminée après :

- C2.1 — Santé Core Swift ;
- C2.2 — Clarification textes Lab UI ;
- C2.3 — Tests de garde routes / state / UI ;
- C2.4 — Observation terrain post-hardening ;
- C2.5 — Contrat `/feed` + observation app Swift.

Le résultat n'est pas un Pulse plus intelligent. Le résultat est un Core plus honnête, plus lisible et moins facile à faire régresser.

## Ce qui a été corrigé pendant C2

Corrections et garde-fous actés :

- la santé Core Swift est séparée de la disponibilité LLM ;
- un LLM indisponible ne doit plus faire apparaître le Core comme dégradé si `/health/core.status == "ok"` ;
- les textes Lab UI ont été clarifiés, notamment Mémoire, DayDream et `context_injection` ;
- l'UI ne doit plus présenter DayDream, facts / profile, mémoire avancée ou injection LLM comme requis par le Core ;
- `/state.present` est protégé par test contre les champs bruts sensibles ;
- l'inventaire des routes Core / debug / Lab est documenté par test ;
- `/feed` est verrouillé comme sélection notable, pas comme journal brut complet ;
- `close_reason` est persisté et visible dans `recent_sessions.boundary_reason` ;
- les raisons observées ou attendues incluent notamment `stale_repair`, `idle_timeout` et le fallback `session_end` ;
- `user_presence` est masqué par défaut dans l'onglet Événements, tout en restant inspectable explicitement ;
- l'observation `active_app = null` a été réinterprétée : elle est liée à une app Swift / SystemObserver non lancée ou incomplète pendant l'observation, pas à un bug Core confirmé.

## Ce qui est accepté temporairement

Ces dettes restent acceptées pendant le dogfooding Core. Elles ne doivent pas être confondues avec un feu vert pour construire l'apprentissage.

- `RuntimeOrchestrator` reste large et concentre encore orchestration Core, gates Lab, sessions, mémoire minimale et propositions.
- `main.py` reste à la fois composition root, entrypoint exécutable, route hub et glue legacy.
- `/state` reste large pour compatibilité Swift et debug.
- `/state.signals` reste large et peut contenir des détails proches du debug.
- les routes Lab restent enregistrées, mais doivent rester gatées, neutralisées ou clairement marquées en Core.
- le Dashboard reste un cockpit interne de dogfooding, pas une UI produit finale.
- `/insights` reste une surface locale raw-ish.
- le periodic sync worker peut encore exister en Core tant que son chemin avancé reste no-op.
- `FactEngine` et `MemoryStore` peuvent encore être instanciés tant qu'ils ne participent pas au flux Core.

Accepté ne veut pas dire sain. Cela veut dire : pas prioritaire avant le contrat mémoire / apprentissage.

## Ce qui doit être fixé avant une première mémoire candidate

Avant toute mémoire candidate, il faut définir un contrat strict. Pas de code d'apprentissage avant ce contrat.

Pré-requis minimum :

- définir précisément `observation`, `signal`, `hypothèse`, `mémoire candidate` et `mémoire validée` ;
- interdire toute promotion automatique depuis `/state` seul ;
- exiger des preuves multi-sources ou multi-sessions avant de créer une mémoire candidate ;
- rendre la validation humaine obligatoire pour toute mémoire stable ;
- prévoir un mécanisme explicite de refus, correction et oubli ;
- marquer chaque mémoire avec source, preuve, confiance et date ;
- ne jamais apprendre depuis des commandes de diagnostic seules ;
- ne jamais apprendre depuis des surfaces Lab non validées ;
- ne jamais apprendre depuis un résumé LLM seul ;
- distinguer une mémoire utile de reprise d'une préférence utilisateur durable ;
- conserver la séparation observed / derived / inferred / narrative.

La première mémoire candidate devra être traitée comme une hypothèse contrôlée, pas comme un fait utilisateur.

## Ce qui est reporté à C4 Architecture Cleanup

C4 devra traiter l'architecture, mais pas avant que C3 ait fixé les contrats mémoire / apprentissage.

Sujets reportés :

- séparer entrypoint exécutable et factory importable dans `main.py` ;
- éviter `runtime = create_runtime()` au module import ;
- rendre l'ordre de boot plus sûr ;
- extraire progressivement des responsabilités de `RuntimeOrchestrator` ;
- isoler route registration Core / debug / Lab ;
- remplacer progressivement `/insights` côté UI par une surface bornée ;
- rendre le periodic sync worker non démarré en Core ;
- rendre `FactEngine` lazy ou Lab-only ;
- clarifier `StateStore` legacy ;
- centraliser les constantes de types d'événements.

Ces changements sont utiles, mais ils sont structurels. Les faire maintenant risquerait de mélanger hardening, refactor et design mémoire.

## Ce qu'il ne faut pas faire maintenant

Interdits temporaires :

- ne pas coder l'apprentissage ;
- ne pas coder facts / profile produit ;
- ne pas brancher vector store ou embeddings ;
- ne pas réactiver DayDream ;
- ne pas faire de propositions intelligentes ;
- ne pas faire de context probes automatiques ;
- ne pas ajouter de work intent intelligent ;
- ne pas ajouter de LLM summaries au chemin Core ;
- ne pas refactorer massivement `RuntimeOrchestrator` ou `main.py` ;
- ne pas désenregistrer brutalement les routes Lab ;
- ne pas casser `/state.signals` ou `/insights` avant migration Swift.

Le risque principal est de recréer le problème initial : des surfaces avancées branchées avant que les fondations ne prouvent leur stabilité terrain.

## Décision finale

C2 peut être clôturé.

Pulse Core est prêt pour dogfooding contrôlé : observer, filtrer, interpréter prudemment, suivre des sessions, conserver une mémoire minimale et contrôler le flux MCP.

Pulse n'est pas prêt pour apprentissage automatique, mémoire intelligente, profil utilisateur / projet ou adaptation.

La suite historique de C2 était C3 — Memory / Learning Contract, documentation only.

C3 devait définir les règles avant tout code. C4 — Architecture Cleanup venait ensuite, guidé par les contrats C3.
