# Resume Card

Resume Card est la première boucle proactive de Pulse.

Objectif utilisateur :

```text
Me remettre dans le contexte en moins de 10 secondes quand je reviens après une pause.
```

## Déclencheur MVP

- `screen_unlocked` après un verrouillage d'au moins 20 minutes.

## Sources autorisées

- `PresentState`
- dernier payload mémoire/session
- dernier work window si disponible dans le payload
- épisode courant ou épisodes clos exposés par le payload
- fichiers récents ou fichiers de commit
- `diff_summary` si disponible

Le LLM peut enrichir la formulation, mais il ne décide pas si la carte doit exister.
Il résume uniquement des sources locales déjà collectées par Pulse.

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
- pas plus de 5 lignes côté UI ;
- fallback déterministe obligatoire si le LLM est indisponible ou invalide ;
- la carte doit rester explicable via `source_refs`.

## Surface UI

La carte est affichée brièvement dans l'encoche.
La hauteur est bornée par trois formats :

- `compact`
- `standard`
- `expanded`

Pulse adapte la taille au contenu, mais ne transforme pas l'encoche en dashboard.
