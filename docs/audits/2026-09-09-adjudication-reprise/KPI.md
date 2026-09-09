# Mesurer la reprise correcte avec moins d’effort

Proposition de protocole, **aucune mesure utilisateur effectuée**. Le score historique 2/4 ne mesure ni temps de reprise ni utilité globale : seulement quelques attentes de open, et certaines clauses datent d’un autre contrat de collecte.

## KPI principal : temps jusqu’à une reprise correcte

Mesurer les secondes entre l’ouverture de la fiche et le moment où l’utilisateur peut formuler un plan de reprise cohérent avec ses informations essentielles adjudiquées : où il en était, ce qu’il veut faire ou ne pas faire ensuite, et l’ancre nécessaire pour y retourner.

Une « reprise correcte » doit satisfaire **tous les éléments classés essentiels pour cette situation**, sans fausse affirmation susceptible de détourner le travail. Cela peut être « ce travail était terminé » ou « je n’ai pas assez d’information pour décider ». Ne pas imposer une prochaine action si aucune n’est pertinente.

Rapporter ensemble :

- médiane du temps pour les reprises correctes ;
- nombre de reprises correctes / nombre de sessions effectivement adjudiquées et testées ;
- échecs ou abandons au plafond d’observation défini avant le test, séparés des temps réussis.

Une fiche vide ne gagne pas parce qu’elle se lit vite : si elle ne retrouve pas un élément essentiel, la reprise n’est pas réussie. Une fiche très longue ne gagne pas parce qu’elle contient tout : le temps, l’effort et le bruit la pénalisent. Ne pas masquer les échecs en ne publiant que la médiane des réussites.

## Mesures de diagnostic

| Mesure | Définition | Pourquoi |
| --- | --- | --- |
| Information importante retrouvée | Éléments essentiels et utiles reconnus dans **toute la fiche**, rapportés séparément ; comparaison sémantique validée humainement | Capture les omissions, sans favoriser le nom d’un champ |
| Couverture observable | Parmi les éléments souhaités, combien étaient présents dans l’entrée / seulement ailleurs / inconnus | Sépare collecte et modèle |
| Fausses informations présentées | Nombre par fiche et gravité : cosmétique, trompeuse, susceptible de détourner l’action | Pas de compensation d’une erreur grave par plusieurs faits anodins |
| Statut épistémique correct | Fait daté, déclaration attribuée, inférence ou inconnu présentés avec la bonne portée | Une bonne hypothèse présentée comme certitude reste un défaut |
| Informations inutiles | Éléments jugés inutiles ou nuisibles, doublons compris | Mesure le coût de distraction |
| Effort mental | Note utilisateur 1–5 après reprise, avec ancres « immédiat » → « reconstitution laborieuse » | Mesure directement l’objectif produit |
| Confiance calibrée | Confiance 1–5 avant vérification, puis erreurs constatées | Une confiance élevée dans une fiche fausse n’est pas une réussite |
| Retours aux sources | Temps et nombre de consultations nécessaires pour comprendre ou vérifier | Montre si Pulse facilite réellement la reprise |
| Préférence | Choix comparatif et raison entre deux présentations | Permet de juger le coût cognitif de la séparation factuel/inféré |

Pas de score composite optimisé immédiatement. « Confiance × utilité » est un principe : mesurer les deux et le coût, conserver un garde-fou sur les erreurs graves. Si un score agrégé est nécessaire plus tard, publier aussi ses composantes et figer ses poids avant les comparaisons.

## Expérience du pilote

Après adjudication, comparer trois supports conceptuels à contenu contrôlé : reconstruction factuelle seule, liste open unique, reconstruction plus piste de reprise explicitement inférée. Aucune nouvelle interface n’est construite ici. Les fiches peuvent suffire pour le pilote.

Ne pas montrer successivement trois versions de la même session puis comparer naïvement leurs temps : la première lecture améliore les suivantes. Alterner l’ordre entre sessions, équilibrer les types de cas (terminé, incident, intention, pauvre en traces, multi-projets), puis réserver un autre ensemble pour un test ultérieur. Avec un seul utilisateur et 14 sessions historiques, annoncer les résultats comme exploratoires ; pas de significativité ou de généralisation inventée.

Noter l’horizon de reprise, la connaissance antérieure de la session, l’assurance du souvenir, la version du support et l’ordre d’exposition. L’adjudication rétrospective actuelle identifie des attentes ; elle ne mesure pas rétroactivement le temps réellement gagné en juillet ou août.

Le premier résultat attendu n’est pas « plus de open corrects », mais **davantage de reprises correctes avec moins d’effort, sans hausse des affirmations trompeuses**.
