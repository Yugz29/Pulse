# Reprise fondée sur des observations, sans propagation automatique

Troisième chantier autorisé sur Core et Intelligence. Référence : état local
du deuxième chantier, entrée 2 / prompt v4, archivé dans l'audit des observations
ordonnées. Les événements et le corpus gelé ne sont pas modifiés.

## Diagnostic et décision

La relecture de 21 points dans 14 sorties v4 identifie trois sources majeures :
absence de collecte transformée en recommandation, état passé affirmé au présent,
interprétation précédente propagée sans preuve. Une sortie cite même dirty=false
pour affirmer dirty=true. La taxonomie détaillée (`taxonomy-v4.md`) est dans le
rapport d'audit retiré du dépôt le 2026-09-09 (voir `docs/audits/README.md`,
historique Git).

Le contrat précédent autorisait `carried_over` avec une simple raison rédigée
par le modèle et zéro observation. Nommer la propagation ne la rendait pas fondée.
La nouvelle écriture ne produit plus `carried_over` ni `requested` dans `open`.
Les demandes initiales et anciens résumés restent du contexte explicitement
attribué ; ils ne prouvent ni un accomplissement ni un reste.

## Sémantique minimale

- Observé : un événement enregistré ; un message de commit est une déclaration
  enregistrée, pas une preuve indépendante de ce qu'il affirme.
- Dernier observé : dernière observation du même sujet dans la session. Ce n'est
  pas une inspection actuelle.
- Résolution observée : pour une même commande exacte dans un cwd connu, un
  processus ultérieur commencé après la fin de l'échec et terminé avec code 0.
  Cette relation concerne le résultat global de cette commande, pas la santé
  du projet ou chaque sous-commande. Un échec ultérieur réouvre ce constat.
- Sans résolution observée : le dernier résultat de la commande est un échec
  connu. La qualification porte sur la fin de la session, jamais sur maintenant.
- Inconnu : résultat manquant/interrompu, identité ou ordre insuffisants ; et,
  dans tous les cas, état actuel non inspecté. Pas de seuil arbitraire de fraîcheur.
- `open` : sélection utile de constats positivement appuyés, bornés à la session,
  sans résolution correspondante observée. Un silence de collecte n'est pas un
  point ouvert et une suggestion de vérification appartient à une future couche
  d'action. La liste vide est une réponse normale, pas un échec du produit.

## Contrat et propriétaires

Core conserve observations v1, reconstruction v3 et API v3. L'annexe du dernier
résumé expose son origine et son workspace, sans interpréter son contenu.
Intelligence produit une entrée v3 : observations inchangées et relations de
résultats de commandes dans `resumption`, avec `as_of` et `current_state=unknown`.
La fonction pure `command_outcomes` en est le propriétaire unique. Aucun I/O.

Le prompt v5 demande deux types d'appui pour `open` :

- `command_failure` : exactement une référence au dernier échec admissible ;
- `recorded_statement` : exactement une référence de commit et une citation
  littérale d'une déclaration de problème/intention encore pertinente.

Le validateur vérifie types, références, résultat terminal et présence exacte
de la citation après normalisation des espaces et retours de ligne. Il ne sait pas si une citation signifie vraiment un reste,
si le texte libre explique correctement la cause, ni si ce point est utile.
Ces limites doivent être évaluées séparément de la validité du format.
Pas de regex sémantique, de graphe de croyances ou de recherche lexicale de TODO.

Le rendu situe chaque point dans les observations de fin de session ou dans
une déclaration attribuée. Le texte et la citation passent dans `reprise.open`,
champ masqué par Core. Les métadonnées ne contiennent que type, références et
scope fermé `session_end` ; aucune nouvelle copie libre hors masquage.

## Cycle de vie et compatibilité

Un ancien résumé antérieur à la session, de la même journée et sans workspace
connu contradictoire, reste une annexe `previous_model_interpretation`, avec sa
date et `evidence_eligible=false`. Ses points ne deviennent plus des références
de preuve individuelles. Toute reprise doit trouver un appui indépendant dans
les observations de la nouvelle session. La demande d'agent est une intention
initiale à accomplissement inconnu, pas une tâche automatiquement encore ouverte.

Les anciennes données, rendus, payloads pending et identités de génération
restent lisibles et rejouables sans modèle. Le parseur v3/v4 reste limité aux
entrées archivées ; l'entrée v3 sélectionne le nouveau validateur. La génération
v5 a une identité distincte : aucun ancien résumé n'est écrasé. Les anciennes
versions de prompt refusent explicitement la nouvelle entrée.

Les annotations humaines restent identiques. En particulier, `eef4956b` exige
historiquement un `carried_over` sans preuve indépendante : la nouvelle politique
ne peut satisfaire cette attente. L'écart doit rester visible, pas être corrigé
en retouchant l'annotation ou en masquant un échec.

## Évaluation et adoption

Les 14 entrées gelées ont été rejouées avec le même modèle local et les mêmes
paramètres, puis les huit scénarios contradictoires. Résultats : 14/14 sorties
acceptées, 8/8 cibles contradictoires vérifiées, mais 2/4 critères humains
satisfaits. Le rapport complet (retiré du dépôt le 2026-09-09, voir
[`docs/audits/README.md`](../audits/README.md) et l'historique Git)
distingue format, appui, résolution et utilité et conclut **non** à la fiabilité
quotidienne sans relecture.
Ne pas activer un service ou changer une configuration personnelle pendant ce
chantier. Le verdict d'usage quotidien appartient au rapport final d'évaluation.
