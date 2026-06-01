# Today Value Loop

Internal context: product dogfooding

## Statut

- Décision documentaire uniquement.
- Aucun code dans ce patch.
- Aucun test modifié.
- Aucune UI Swift modifiée.
- La parenthèse produit “Aujourd'hui” a été faite, puis C4c a repris et est maintenant clôturé.
- Cette décision reste utile pour cadrer l'observation / stabilisation Core-Produit.

## Objectif

Valider la boucle de valeur minimale “Aujourd'hui” et cadrer son usage pendant la phase observation / stabilisation Core-Produit.

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

## État après sessions terrain #1/#2

Les premières sessions terrain ont confirmé que `/today_summary` est la bonne surface de départ.

Un premier patch minimal a été appliqué après la session #1 :

- `top_files` est maintenant exposé dans `/today_summary.work_blocks[]` ;
- la carte Swift “Aujourd'hui” affiche les derniers blocs avec heures courtes, tâche / projet, signal récent et fichiers principaux ;
- aucune nouvelle route n'a été créée ;
- aucune surface Lab, LLM ou mémoire avancée n'a été utilisée.

La session #2 a confirmé que le couple `/today_summary` + `/feed` reste cohérent : `/today_summary` donne la structure et les fichiers quand ils existent, tandis que `/feed` expose les commandes terminal notables comme `pytest`.

Cette validation ne justifie pas encore d'ajouter `notable_commands` dans `/today_summary`.

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

Avant tout nouvel enrichissement produit, continuer le dogfooding jusqu'à au moins 5 sessions terrain.

Chaque session doit vérifier :

- `/today_summary` répond correctement ;
- `/feed` fournit les événements notables utiles ;
- la carte Swift “Aujourd'hui” est lisible ;
- le projet actif du jour est compréhensible ;
- les blocs de travail sont utiles ou non ;
- les commandes / commits visibles aident ou non à reprendre le fil ;
- aucune memory candidate spontanée n'est créée ;
- aucun contenu Lab n'est présenté comme Core stable.

Les observations terrain peuvent être gardées localement dans `docs/private/dogfooding/` ou synthétisées dans une décision publique si elles deviennent structurantes.

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

- ajuster la lisibilité de la carte “Aujourd'hui” si les derniers blocs restent trop denses ;
- ajouter `notable_commands` dans `/today_summary` seulement si `/feed` ne suffit pas sur plusieurs sessions ;
- envisager une synthèse documentaire publique dédiée si les notes locales deviennent structurantes.

Toute évolution doit rester déterministe, locale, Core-only et sans LLM.

## Décision finale

Observer avant tout nouvel enrichissement.

La boucle de valeur minimale “Aujourd'hui” a été validée initialement avec `/today_summary`, `/feed` et la carte Swift existante. Elle reste le cadre Produit minimal pendant l'observation / stabilisation.
