# Resume Card

Resume Card est la première boucle proactive de Pulse.

Objectif utilisateur :

```text
Me remettre dans le contexte en moins de 10 secondes quand je reviens après une pause.
```

## Déclencheurs

Chemin principal :
- `screen_locked` prépare une Resume Card à chaud quand le contexte est encore frais ;
- la carte préparée est stockée temporairement en mémoire ;
- `screen_unlocked` consomme immédiatement la carte préparée si elle est encore valide.

Fallback :
- si aucune carte préparée valide n'existe, `screen_unlocked` peut générer une Resume Card à la demande après une pause suffisante.

## Sources autorisées

- `PresentState`
- `current_context` quand disponible
- dernier payload mémoire/session
- `work_blocks` / `work_block_*`
- `recent_sessions`
- entrées récentes du journal local
- fichiers récents ou fichiers de commit
- fenêtre de commit dérivée de `commit_activity_started_at` / `commit_activity_ended_at`
- `diff_summary` si disponible

Les anciens champs `work_window_*` et `closed_episodes` peuvent être lus en fallback de compatibilité, mais ils ne doivent pas guider les nouvelles features.

Le LLM peut enrichir la formulation, mais il ne décide pas si la carte doit exister.
Il résume uniquement des sources locales déjà collectées par Pulse.
La Resume Card est une projection de reprise, pas une source de vérité du travail.

## Contrat de sortie

```text
ResumeCard
- id
- project
- title
- summary
- last_objective
- next_action
- confidence
- source_refs
- generated_by
- display_size
- created_at
```

## Règles produit

- maximum une carte toutes les 2 heures ;
- pas de carte si le projet est inconnu ;
- pas de carte si la pause est courte ;
- fallback déterministe obligatoire si le LLM est indisponible ou invalide ;
- le LLM peut raisonner, mais seule une réponse finale exploitable est acceptée ;
- en cas de `reasoning_without_final`, le provider peut relancer une fois en mode final-only ;
- la carte doit rester explicable via `source_refs` ;
- la carte préparée est consommable une seule fois et expire après un délai borné.

## Chemins de génération

### Déterministe

Le chemin déterministe produit une carte sans LLM.
Il sert de fallback obligatoire et de base de test rapide.

Route debug :

```text
/debug/resume-card
```

### LLM

Le chemin LLM utilise le même contexte local, mais améliore la formulation.
Il doit retourner une réponse finale structurée.
Si la réponse LLM est vide, invalide ou seulement composée de raisonnement, Pulse retombe sur le déterministe.

Route debug :

```text
/debug/resume-card/llm
```

Cette route expose un diagnostic de génération :
- `llm_called`
- `fallback_reason`
- `raw_preview`
- `error`
- `generated_by`

### Préparée

La Resume Card préparée est générée au `screen_locked`, pendant que le contexte est encore chaud.
Elle est stockée temporairement en mémoire puis publiée immédiatement au prochain `screen_unlocked` si elle est encore valide.

Limites V1 :
- stockage mémoire uniquement ;
- perte si le daemon redémarre ;
- pas encore de route debug dédiée au cycle `prepare` / `peek` / `consume` / `expire`.

## Surface UI

La carte est affichée brièvement dans l'encoche.
Elle est structurée autour de trois blocs :
- résumé ;
- objectif probable ;
- prochaine action.

La taille est bornée par trois formats :
- `compact`
- `standard`
- `expanded`

Le format `expanded` peut augmenter la largeur et la hauteur de l'encoche.
La hauteur reste semi-dynamique selon le contenu, avec un `ScrollView` de sécurité.

Pulse adapte la taille au contenu, mais ne transforme pas l'encoche en dashboard.
