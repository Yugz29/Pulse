# C4-mini — Memory Candidates Skeleton

## Statut

C4-mini est une décision structurelle minimale.

Ce n'est pas R7. Ce n'est pas l'apprentissage. Ce n'est pas une mémoire intelligente. Ce n'est pas une mémoire stable. Ce n'est pas une injection LLM.

C4-mini est uniquement un squelette local review-only pour préparer une future surface de `memory_candidates`.

## Pourquoi ce document existe

C3 a défini les règles mémoire / apprentissage dans les contrats `docs/contract/MEMORY_LEARNING_CONTRACT.md`, `docs/contract/MEMORY_CANDIDATES_READINESS.md` et `docs/contract/MEMORY_CANDIDATES_MVP.md`.

Le readiness audit a conclu qu'il fallait isoler le store et les routes avant toute mécanique de candidates. Le patch prépare donc une structure minimale sans génération automatique.

Le but est d'éviter de mélanger les candidates avec `MemoryStore`, facts, DayDream, `/state`, debug memory ou le runtime live.

## Décision

`memory_candidates` devient une surface dédiée.

Elle est séparée du Core live et du Lab mémoire existant. Elle est locale, review-only et pending-oriented.

Une memory candidate ne doit pas être utilisée comme mémoire stable. Elle ne doit pas être injectée dans un LLM. Elle ne doit pas être alimentée automatiquement par les signaux live.

## Ce que le patch ajoute

- `MemoryCandidateStore`.
- SQLite local dédié.
- Routes review-only.
- Statut `pending` par défaut.
- Statuts de review : `accepted`, `edited`, `rejected`, `archived`.
- Types autorisés : `project_pattern`, `workflow_pattern`, `tool_usage`, `caution`.
- Types interdits sensibles : `medical`, `financial`, `identity`, `private_life`, `credential`, `psychological_profile`, `sensitive_preference`.
- Validation stricte de `sensitivity`.
- Validation basique de `evidence`.
- Trace de review humaine.
- Rejection policy explicite.
- Contradiction policy explicite.
- Réponses routes avec `canonical_memory_created=false` et `llm_injected=false`.

## Ce que le patch n'ajoute pas

- Pas de générateur automatique.
- Pas de scan de sessions.
- Pas de création depuis `/state`.
- Pas de création depuis `/debug/state`.
- Pas de création depuis `/insights`.
- Pas de création depuis `/feed`.
- Pas de création depuis LLM summary.
- Pas de création depuis facts Lab.
- Pas de création depuis DayDream.
- Pas de création depuis context probes.
- Pas de création depuis work intent.
- Pas de création depuis `user_presence`.
- Pas de branchement `RuntimeOrchestrator`.
- Pas de modification `RuntimeState`.
- Pas de modification `SignalScorer`.
- Pas de modification `SessionFSM`.
- Pas de `MemoryStore`.
- Pas de profile utilisateur ou projet.
- Pas de mémoire validée produit.
- Pas d'UI Swift.

## Frontières Core / Lab

La surface est dédiée et locale.

Elle n'est pas le Core live. Elle n'est pas la mémoire Lab historique. Elle n'est pas `MemoryStore`. Elle n'est pas facts / profile. Elle n'est pas DayDream. Elle n'est pas un contexte LLM.

Elle est une zone de review contrôlée pour hypothèses futures.

## Contrat API actuel

Routes exposées :

- `GET /memory/candidates`
- `GET /memory/candidates/<id>`
- `POST /memory/candidates/<id>/accept`
- `POST /memory/candidates/<id>/edit`
- `POST /memory/candidates/<id>/reject`
- `POST /memory/candidates/<id>/archive`
- `DELETE /memory/candidates/<id>`

Contraintes :

- Il n'existe pas de `POST /memory/candidates`.
- Il n'existe pas de route `generate`.
- `accept` ne crée pas de mémoire canonique.
- `accept` n'injecte rien dans LLM.
- `edit` conserve une trace humaine.
- `reject` conserve une trace et une policy.
- `delete` supprime la candidate.

## Règles de sécurité

- `pending` n'est pas une mémoire.
- `accepted` n'est pas encore une mémoire stable produit.
- `confidence` ne remplace pas validation humaine.
- Les données sensibles sont refusées par défaut.
- En cas de doute, refuser.
- Les sources debug / Lab ne doivent pas créer de candidate.
- `curl`, `/debug/state`, `/insights`, LLM summaries, DayDream, facts, work intent et context probes restent interdits comme sources directes.

## Garde-fous testés

Fichiers de tests :

- `tests/memory/test_candidates.py`
- `tests/test_memory_candidate_routes.py`
- `tests/test_main_runtime_state.py`

Garanties couvertes :

- Pas de dépendance runtime / Lab dans le module candidates.
- Routes sans `MemoryStore`, DayDream, facts ou LLM.
- Pas d'endpoints de génération.
- `/state`, `/debug/state` et `/insights` ne créent pas de candidates.
- Fallback sur `limit` invalide.
- JSON non-objet toléré côté routes.
- Fallback `human_rejected` si `reason` n'est pas une string non vide.
- `sensitivity` inconnue ou sensible refusée.
- Items `evidence` non-objets refusés.

## Risques acceptés

- `MemoryCandidateStore` est instancié au boot via `main.py`.
- Cette dette est acceptée temporairement car le store ne démarre aucun worker, ne scanne rien, ne génère rien et ne touche pas le runtime live.
- Pas encore de migration versionnée du schéma.
- Pas encore d'UI review.
- Pas encore d'endpoint de création manuelle.
- Pas encore de générateur offline dry-run.
- `accepted` reste un statut de review, pas une mémoire produit stable.

## Interdits après ce patch

- Ne pas brancher dans `RuntimeOrchestrator`.
- Ne pas ajouter un generator automatique.
- Ne pas scanner automatiquement les sessions.
- Ne pas créer depuis `/state`.
- Ne pas utiliser LLM, facts, DayDream, vector store ou embeddings.
- Ne pas injecter dans contexte LLM.
- Ne pas transformer `accepted` en mémoire stable sans contrat séparé.
- Ne pas ajouter d'UI qui présente une candidate comme vérité.

## Prochaines étapes possibles

- Continuer dogfooding / audit.
- Étudier plus tard une création manuelle explicite, sous tests, sans génération automatique.
- Étudier plus tard un générateur offline dry-run uniquement après décision séparée.
- Ne pas lancer de génération automatique maintenant.

## Décision finale

C4-mini est accepté comme squelette structurel.

Il autorise store dédié, routes review-only et tests de non-contamination.

Il n'autorise pas l'apprentissage, la génération, la promotion ou l'injection.
