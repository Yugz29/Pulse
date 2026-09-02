# Prompts collés au shell — placeholder seul

**Date :** 2026-08-30
**Statut :** tranchée
**Source :** `core/TODOS.md`, section « Completed », « Politique de stockage
des prompts collés »

## Décision

Un collage en forme de prompt qui **échoue** au shell (`exit_code != 0`) est
remplacé avant persistance par `[prompt collé : N lignes, M caractères]`.
Aucun texte n'est conservé. Le remplacement se fait côté producteur (le texte
n'atteint jamais l'outbox) et à l'ingestion (défense en profondeur pour les
producteurs directs).

Une commande en forme de prompt qui **réussit** (heredoc légitime) garde son
texte intégral. Le placeholder reste exclu du rendu comme les prompts complets.

## Pourquoi

Un prompt collé par erreur est du texte destiné à une IA, pas une commande :
il peut contenir du contexte sensible et n'a aucune valeur pour le journal. Un
vrai collage raté échoue quasi toujours à l'invite, ce qui donne un critère
simple et sans faux négatif coûteux.

## Historique

Les lignes antérieures à la décision sont laissées telles quelles (store
append-only, cohérent avec la rétention infinie du brut).
