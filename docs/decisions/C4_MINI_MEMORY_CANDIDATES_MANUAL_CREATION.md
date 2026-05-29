# C4-mini.1 — Manual Memory Candidate Creation

## Statut

C4-mini.1 est une décision documentaire uniquement. Aucun code n'est autorisé dans ce patch.

Cette décision n'autorise pas de génération automatique, pas de scan de sessions, pas de mémoire stable et pas d'injection LLM.

Elle autorise seulement la conception d'une future création manuelle explicite de memory candidates.

## Pourquoi cette décision existe

Le squelette review-only `memory_candidates` existe déjà, mais aucune candidate ne peut encore entrer dans le store par une surface API dédiée.

Avant un générateur ou une UI, il faut tester le cycle review avec une candidate créée explicitement. La création manuelle sert à valider `list`, `read`, `edit`, `reject`, `archive` et `delete`.

Ce n'est pas de l'apprentissage.

## Décision

Une future route dédiée peut être conçue :

- `POST /memory/candidates/manual`

Cette route devra :

- créer une candidate `pending` ;
- être déclenchée explicitement par humain / dev ;
- exiger `claim` ;
- exiger `memory_type` ;
- exiger `evidence` ;
- exiger `sensitivity` ;
- refuser tout type sensible ou interdit ;
- refuser toute claim sensible ;
- refuser `evidence` vide ;
- refuser `sensitivity` absente, inconnue ou sensible ;
- retourner explicitement `canonical_memory_created=false` ;
- retourner explicitement `llm_injected=false`.

## Ce que cette décision n'autorise pas

- Pas de `POST /memory/candidates` générique si ambigu.
- Pas de route `generate`.
- Pas de generator automatique.
- Pas de scan de `SessionMemory`.
- Pas de création depuis `/state`.
- Pas de création depuis `/debug/state`.
- Pas de création depuis `/insights`.
- Pas de création depuis `/feed`.
- Pas de création depuis LLM summary.
- Pas de création depuis DayDream.
- Pas de création depuis facts Lab.
- Pas de création depuis context probes.
- Pas de création depuis work intent.
- Pas de création depuis `user_presence`.
- Pas de branchement dans `RuntimeOrchestrator`.
- Pas de modification `RuntimeState`.
- Pas de modification `SignalScorer`.
- Pas de modification `SessionFSM`.
- Pas de `MemoryStore`.
- Pas de profil utilisateur ou projet.
- Pas de mémoire validée produit.
- Pas d'UI Swift obligatoire dans cette étape.

## Contrat de payload minimal

Payload conceptuel :

```json
{
  "memory_type": "project_pattern",
  "claim": "Pulse est un projet de travail récurrent.",
  "evidence": [
    {
      "source_type": "human_manual",
      "summary": "Créé explicitement par l'utilisateur pour tester le cycle de review."
    }
  ],
  "sensitivity": {
    "level": "low",
    "reason": "non-sensitive project pattern"
  }
}
```

Règles :

- `claim` doit être courte, falsifiable et non sensible.
- `evidence` est obligatoire.
- `evidence` doit être une liste non vide.
- Chaque item `evidence` doit être un objet.
- `sensitivity` doit être explicite.
- Le store force `pending`.
- `MemoryCandidateStore` ne doit pas permettre de candidate manuelle valide sans preuve.

Cette règle renforce le contrat : une candidate n'est pas une mémoire, mais elle doit quand même être sourcée.

## Règles de validation

La route manuelle et `MemoryCandidateStore` doivent refuser :

- payload non-objet ;
- `claim` absente ou vide ;
- `claim` trop vague ou trop longue si une limite existe ;
- `memory_type` absent ou interdit ;
- `evidence` absente, vide ou non-list ;
- items `evidence` non-objets ;
- `sensitivity` absente ou non-objet ;
- `sensitivity.level` inconnu ;
- `sensitivity.level` sensible ;
- type médical, financier, identité, vie privée, credential, profil psychologique ou préférence sensible.

Erreurs attendues pour `evidence` :

- `evidence_required` si `evidence` est absente ou vide ;
- `invalid_evidence` si `evidence` n'est pas une liste ;
- `invalid_evidence_item` si un item `evidence` n'est pas un objet.

## Tests requis avant implémentation

Tests obligatoires :

- `POST /memory/candidates/manual` crée une candidate `pending` ;
- refuse `claim` absente ;
- refuse `evidence` absente ;
- refuse `evidence` vide ;
- `MemoryCandidateStore.create_manual_candidate()` refuse `evidence` absente ;
- `MemoryCandidateStore.create_manual_candidate()` refuse `evidence` vide ;
- refuse `sensitivity` absente ;
- refuse `sensitivity` inconnue ;
- refuse sensitive type ;
- refuse sensitive level ;
- retourne `canonical_memory_created=false` ;
- retourne `llm_injected=false` ;
- ne touche pas `/state` ;
- n'appelle pas LLM ;
- n'appelle pas `MemoryStore` ;
- n'appelle pas facts ;
- n'appelle pas DayDream ;
- n'appelle pas `RuntimeOrchestrator` ;
- pas de route `generate`.

## Dogfooding attendu

Après implémentation future :

- redémarrer daemon ;
- vérifier `/health/core` ;
- vérifier `/memory/candidates` vide avant création ;
- créer une candidate manuelle de test ;
- vérifier list / read ;
- tester edit / reject / delete ;
- vérifier `/state` inchangé ;
- documenter dans `docs/audits/CORE_DOGFOODING_NOTES.md`.

## Décision finale

C4-mini.1 autorise seulement la future création manuelle explicite de candidates `pending`.

Elle n'autorise pas génération, apprentissage, promotion, injection ou mémoire stable.
