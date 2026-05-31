# Today Value Loop Plan

## Statut

- Décision documentaire uniquement.
- Aucun code dans ce patch.
- Aucun test modifié.
- Aucune UI Swift modifiée.
- C4c.2+ est mis en pause temporairement pour valider la valeur utilisateur.

## Objectif

Valider la boucle de valeur minimale “Aujourd'hui” avant de poursuivre le cleanup architectural C4c.

Question produit à tester :

> Qu'est-ce que j'ai fait aujourd'hui, et est-ce que Pulse m'aide à reprendre le fil ?

## Surfaces existantes utilisées

La validation doit d'abord utiliser les surfaces déjà présentes :

- `GET /today_summary`
- `GET /feed`
- `TodaySummaryResponse`
- carte Swift existante “Aujourd'hui”

Ces surfaces existent déjà et suffisent pour un premier dogfooding sans nouvelle route.

## Décision

Ne pas créer de nouvelle route maintenant.

Ne pas créer `GET /today` dans cette étape. Dogfooder d'abord `/today_summary` et `/feed`, puis vérifier si la carte Swift “Aujourd'hui” permet déjà de répondre à la question produit.

## Interdits

Cette décision n'autorise pas :

- Lab ;
- DayDream ;
- facts / profile ;
- `VectorStore` ;
- LLM summaries ;
- memory candidates ;
- `MemoryStore` legacy comme nouvelle source produit ;
- nouvelle route `/today` immédiate ;
- apprentissage automatique ;
- génération automatique ;
- injection LLM ;
- nouvelle UI Swift dans ce patch documentaire.

## Dogfooding requis

Avant tout patch produit, effectuer au moins 5 sessions terrain.

Chaque session doit vérifier :

- `/today_summary` répond correctement ;
- `/feed` fournit les événements notables utiles ;
- la carte Swift “Aujourd'hui” est lisible ;
- le projet actif du jour est compréhensible ;
- les blocs de travail sont utiles ou non ;
- les commandes / commits visibles aident ou non à reprendre le fil ;
- aucune memory candidate spontanée n'est créée ;
- aucun contenu Lab n'est présenté comme Core stable.

Les observations doivent être ajoutées dans `docs/audits/CORE_DOGFOODING_NOTES.md`.

## Critères d'évaluation

La boucle est suffisante si, sur les sessions terrain :

- l'utilisateur comprend ce qui a été fait aujourd'hui ;
- le dernier bloc de travail aide à reprendre ;
- les totaux sont cohérents avec l'activité perçue ;
- les commandes notables de `/feed` apportent du contexte ;
- les projets du jour sont identifiables ;
- l'UI ne dépend pas de debug, Lab, facts, DayDream ou LLM ;
- les données affichées restent prudentes et déterministes.

La boucle est insuffisante si :

- les blocs sont trop vagues ;
- les fichiers importants manquent ;
- les commandes utiles ne sont pas visibles ;
- la reprise du fil nécessite encore d'ouvrir les vues debug ;
- la carte “Aujourd'hui” est noyée ou difficile à lire ;
- les données affichées semblent plus intelligentes ou plus certaines qu'elles ne le sont.

## Patch futur possible

Un patch produit futur est autorisé seulement si le manque est confirmé par dogfooding.

Options limitées :

- ajouter `top_files` dans `/today_summary` ;
- ajouter `notable_commands` dans `/today_summary` si `/feed` ne suffit pas ;
- simplifier ensuite l'UI “Aujourd'hui” pour mettre la reprise du fil au premier plan.

Toute évolution doit rester déterministe, locale, Core-only et sans LLM.

## Décision finale

Observer avant coder.

La boucle de valeur minimale “Aujourd'hui” doit d'abord être validée avec `/today_summary`, `/feed` et la carte Swift existante. C4c.2+ reste en pause temporaire pendant cette validation.
