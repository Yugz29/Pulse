# Memory Candidates Readiness Audit

## Verdict

Ne pas implémenter directement `memory_candidates` dans les surfaces existantes.

Le MVP est faisable sans gros refactor, mais seulement après un mini C4 cleanup ciblé : store dédié, routes dédiées, registration explicite et tests de non-promotion.

Le chemin le moins risqué est :

- ne pas brancher dans `RuntimeOrchestrator` au départ ;
- ne pas utiliser `MemoryStore` ;
- ne pas étendre `/state` ;
- ne pas utiliser facts, DayDream, LLM summaries, vector store ou context probes ;
- créer plus tard un module `memory_candidates` séparé, local-only, pending-only ;
- exposer une surface de review dédiée, pas une surface Lab.

Pulse n'est pas prêt à apprendre automatiquement. Il peut seulement préparer une mécanique de candidates contrôlées.

## Résumé décisionnel

- Stockage recommandé : store local dédié, probablement SQLite dédié ou table dédiée, séparé de `MemoryStore` et des journaux Markdown.
- Routes recommandées : fichier séparé `daemon/routes/memory_candidates.py`, enregistré explicitement, sans passer par facts / DayDream / MemoryStore.
- À ne pas brancher : `RuntimeOrchestrator._process_signals()`, `_sync_memory_background()`, `/state`, `/debug/state`, `/insights`, facts routes, DayDream routes.
- À tester avant code : pending-only, preuves multiples, aucune candidate depuis `/state` seul, `curl`, `/debug/state`, `/insights`, LLM summary, DayDream ou facts Lab.
- Niveau de risque : moyen si store/routes sont séparés ; élevé si intégré aux chemins mémoire existants.

## C4-mini decision

C4-mini ne doit pas implémenter `memory_candidates`.

La décision de préparation est limitée à des garde-fous :

- les routes candidates ne sont pas enregistrées tant que le store dédié et les tests de non-promotion n'existent pas ;
- `/state.present` ne doit pas exposer `memory_candidate` ou `memory_candidates` ;
- `/feed` doit rester une sélection notable et ne doit pas devenir une surface de candidates ;
- le futur patch produit devra créer store dédié + routes dédiées + tests avant toute génération ;
- le futur patch produit ne devra pas toucher `RuntimeOrchestrator` au départ.

Donc le prochain patch produit autorisable n'est pas "générer des candidates". C'est un squelette test-first, pending-only, local-only, sans LLM et sans Lab.

## Stockage

### Option `SessionMemory`

`SessionMemory` est la source persistée Core la plus utile aujourd'hui : sessions SQLite, events, snapshots, `recent_sessions`, `search_events()`, `export_session_data()` et `export_memory_payload()`.

Avantages :

- déjà local ;
- déjà SQLite ;
- déjà relié aux sessions et events observés ;
- source acceptable pour construire des preuves plus tard.

Limites :

- c'est la vérité historique session, pas un store de décisions utilisateur ;
- mélanger candidates avec events / sessions rendrait la frontière moins lisible ;
- ajouter du lifecycle de review dans `SessionMemory` augmenterait son rôle au-delà de la persistance session Core ;
- risque de confusion entre session observée, pattern candidat et mémoire candidate.

Verdict : utiliser `SessionMemory` comme source de preuves, pas comme store principal des candidates.

### Option `MemoryStore`

`MemoryStore` est à éviter pour le MVP.

Raisons :

- historiquement lié à mémoire durable / tiers / rendu ;
- classé Lab / legacy pendant le Core Reset ;
- encore proche de `/memory/write`, `/memory/remove`, freeze memory et surfaces Lab ;
- risque de faire passer une candidate `pending` pour une mémoire déjà écrite.

Verdict : ne pas utiliser `MemoryStore` pour `memory_candidates`.

### Option fichiers Markdown

Les journaux Markdown restent utiles comme lecture historique, mais ils ne sont pas un bon stockage de candidates.

Risques :

- confusion avec `/memory/sessions` ;
- hidden payload déjà sensible ;
- difficile de gérer statuts, refus, expiration, contradiction et audit propre ;
- risque de promouvoir le narratif visible en vérité.

Verdict : ne pas stocker les candidates dans Markdown.

### Option store local dédié

Recommandation : nouveau store local dédié.

Deux formes acceptables plus tard :

- SQLite dédié, par exemple `~/.pulse/memory/candidates.sqlite` ;
- table dédiée dans une base séparée du store session, si le chemin de migration est clair.

Propriétés requises :

- statuts explicites ;
- evidence structurée ;
- human review structurée ;
- rejection / contradiction policy ;
- timestamps ;
- sensitivity ;
- aucune dépendance LLM ;
- aucune dépendance facts / DayDream / vector store.

Verdict : store dédié obligatoire pour un MVP propre.

## Routes

### Routes existantes

`daemon/routes/memory.py` mélange déjà :

- `/memory` vers `MemoryStore` Lab / legacy ;
- `/memory/write` et `/memory/remove`, désactivés en Core ;
- `/memory/sessions`, lecture historique Markdown ;
- `/search`, recherche events SQLite via `SessionMemory`.

Ce fichier est trop mélangé pour accueillir des candidates sans brouiller Core / Lab.

`daemon/routes/facts.py` est hors périmètre : facts / profile restent Lab.

`daemon/routes/runtime_status_routes.py` ne doit pas être étendu : `/state` est déjà large et doit éviter toute mémoire candidate.

`daemon/routes/runtime_debug_routes.py` et `/insights` sont des surfaces debug/raw, pas des surfaces de review mémoire.

### Recommandation

Créer plus tard un fichier séparé :

```text
daemon/routes/memory_candidates.py
```

Routes conceptuelles acceptables plus tard :

- `GET /memory/candidates`
- `GET /memory/candidates/<id>`
- `POST /memory/candidates/<id>/accept`
- `POST /memory/candidates/<id>/edit`
- `POST /memory/candidates/<id>/reject`
- `POST /memory/candidates/<id>/archive`
- `DELETE /memory/candidates/<id>`

Contraintes :

- ne pas créer ces routes maintenant ;
- ne pas appeler LLM ;
- ne pas appeler DayDream ;
- ne pas appeler vector store / embeddings ;
- ne pas appeler facts Lab ;
- ne pas écrire dans `MemoryStore` ;
- ne pas modifier `/state` ;
- ne pas faire de promotion automatique après `accept` sans décision séparée.

## Runtime integration

Ne pas brancher candidate generation dans `RuntimeOrchestrator` au départ.

Raisons :

- `RuntimeOrchestrator` concentre déjà ingestion, sessions, state, memory sync Lab, DayDream Lab, propositions et workers ;
- `_process_signals()` est le chemin live le plus risqué : y ajouter candidates transformerait des signaux temporaires en quasi-mémoire ;
- `_sync_memory_background()` est explicitement Lab / advanced memory et no-op en Core ; y brancher candidates recréerait la contamination que R1-R6 ont neutralisée ;
- le periodic sync worker peut encore tourner en Core comme no-op ; il ne doit pas devenir un générateur de mémoire.

Mécanisme recommandé plus tard :

- générateur explicite, manuel ou offline ;
- déclenché par une route de dry-run ou un job local explicitement demandé ;
- lit des sources persistées et bornées ;
- produit seulement des candidates `pending` ;
- ne modifie ni `RuntimeState`, ni `PresentState`, ni `SignalScorer`.

Le runtime live doit rester observateur / interprète prudent, pas producteur d'apprentissage.

## Evidence sources

### Sources utilisables plus tard

Sources Core acceptables pour construire des preuves, avec prudence :

- `SessionMemory` events ;
- `SessionMemory` snapshots ;
- `recent_sessions` ;
- `/feed` terminal notable comme signal secondaire ;
- commandes git / test / build répétées ;
- fichiers modifiés significatifs ;
- app / fichier / projet cohérents ;
- commits ou contexte Git confirmé ;
- action explicite utilisateur dans une future UI de review.

Ces sources doivent être combinées. Aucune ne suffit seule.

### Sources interdites

Sources à ne pas utiliser pour créer ou promouvoir directement :

- `/state` seul ;
- `/state.present` seul ;
- `probable_task` seul ;
- `active_project` seul ;
- `/debug/state` brut ;
- `/insights` brut ;
- commandes `curl` diagnostic ;
- DayDream ;
- facts Lab ;
- LLM summaries ;
- context probes non validés ;
- work intent expérimental ;
- session `stale_repair` seule ;
- `user_presence` seul ;
- window title seul ;
- clipboard metadata seul.

## UI readiness

Le Dashboard actuel est un cockpit de dogfooding. Il mélange encore Core, debug et Lab, même si les labels C2 ont réduit les ambiguïtés.

Ne pas intégrer `memory_candidates` dans l'onglet `Mémoire (Lab)`.

Raisons :

- l'onglet actuel affiche facts, profile Lab, MemoryStore et journaux ;
- y placer des candidates Core-safe ferait croire qu'elles appartiennent au Lab mémoire existant ou à une mémoire déjà stable ;
- pending pourrait être confondu avec validé.

Recommandation UI plus tard :

- section explicite `Memory Candidates` ou `Candidats mémoire` ;
- statut visible `pending`, `accepted`, `edited`, `rejected`, `expired`, `contradicted`, `archived` ;
- claim affichée comme hypothèse ;
- preuves lisibles ;
- confidence et sensitivity visibles ;
- actions review explicites ;
- rejet aussi simple que acceptation ;
- aucune injection ou activation implicite après accept.

Modèles Swift nécessaires plus tard :

- `MemoryCandidateResponse` ;
- `MemoryCandidateRecord` ;
- `MemoryCandidateEvidence` ;
- `MemoryCandidateHumanReview` ;
- payloads d'action accept / edit / reject / archive / delete.

Risque principal UI : faire croire que `pending` est une vérité. La UI doit combattre cette interprétation.

## Mini C4 requis avant implémentation

Prérequis strictement nécessaires, sans gros refactor :

- créer un module conceptuel séparé `daemon/memory/candidates.py` ou équivalent ;
- créer un store dédié, hors `MemoryStore` ;
- créer une route registration séparée `daemon/routes/memory_candidates.py` ;
- enregistrer ces routes explicitement sans les mélanger à facts / DayDream / debug memory ;
- définir un générateur explicitement appelé, pas branché au flux runtime live ;
- écrire les tests de non-promotion avant toute logique de génération ;
- garantir que `accept` n'injecte rien automatiquement ;
- garantir que `pending` est le statut par défaut ;
- garantir que Lab ne promeut pas vers Core.

Ce mini C4 ne doit pas extraire tout `RuntimeOrchestrator` ni refondre `main.py`.

## Ce qui peut attendre C4 plus large

À reporter :

- refactor global de `main.py` ;
- séparation complète entrypoint exécutable / factory importable ;
- extraction large de `RuntimeOrchestrator` ;
- migration ou réduction de `/state` ;
- remplacement de `/insights` côté UI ;
- lazy facts engine ;
- cleanup periodic sync worker ;
- centralisation globale des event type constants ;
- séparation complète route Core / debug / Lab.

Ces travaux sont utiles, mais non bloquants pour un MVP candidates si le store et les routes sont isolés.

## Tests requis avant premier patch

Tests obligatoires avant implémentation :

- pas de candidate depuis `/state` seul ;
- pas de candidate depuis `curl` ;
- pas de candidate depuis `/debug/state` ou `/insights` ;
- pas de candidate depuis LLM summary seul ;
- pas de candidate depuis DayDream ;
- pas de candidate depuis facts Lab ;
- pas de candidate depuis `user_presence` seul ;
- pas de candidate depuis `stale_repair` seul ;
- candidate exige preuves multiples ;
- candidate démarre `pending` ;
- `accept` n'injecte rien automatiquement ;
- `accept` ne crée pas de mémoire validée produit sans décision séparée ;
- `reject` empêche reproposition immédiate ;
- `delete` supprime ;
- `edit` conserve trace humaine ;
- sensitive candidate refusée ;
- Lab ne promeut pas vers Core.

Tests d'intégration à prévoir ensuite :

- routes candidates n'appellent pas LLM / DayDream / vector store / facts Lab ;
- routes candidates ne modifient pas `/state` ;
- routes candidates ne touchent pas `MemoryStore`;
- UI affiche `pending` comme hypothèse, pas vérité.

## Décision finale

Pas de code mémoire avant ce readiness.

Si implémentation plus tard, le MVP doit être :

- store dédié ;
- routes dédiées ;
- pending-only ;
- review humaine ;
- test-first ;
- local-only ;
- sans LLM ;
- sans facts / DayDream / vector store ;
- sans branchement initial dans `RuntimeOrchestrator`.

Ne pas brancher dans `RuntimeOrchestrator` au départ si évitable.

Le premier patch produit acceptable serait un squelette store + routes + tests de non-promotion, sans génération automatique.
