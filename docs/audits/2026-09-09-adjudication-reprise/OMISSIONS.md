# Omissions, erreurs et responsabilités — lecture avant adjudication

**Aucune nouvelle réponse utilisateur reçue.** « Omission candidate » signifie qu’une information manque ou est peu visible, pas que vous auriez nécessairement voulu la retrouver. Le seul faux négatif actuel appuyé à la fois par une ancienne exigence explicite et par la collecte de la session est list/run. L’écart sur le report de `eef4956b` est un échec au test historique, mais sa valeur de reprise reste contestable.

La fiche entière est examinée : une information dans `intents` ou `stopped_at` ne compte pas comme absente parce qu’elle manque à `open`. Les références `oN` désignent les entrées exactes de la session dans les replays sous `corpus/docs/audits/2026-09-08-reprise-fondee/after/`.

## Omissions à faire juger

| Cas / session | Information et constat sur la fiche entière | Statut avant vos réponses | Cause possible parmi les six familles demandées | Même entrée suffisante ? |
| --- | --- | --- | --- | --- |
| O01 — `1e420dda`, o20 | Divergence list/run « Non corrigé », absente de tous les champs | Faux négatif documenté par l’annotation historique | Information disponible mais mal interprétée/sélectionnée ; capacité insuffisante du modèle reste une hypothèse, pas une cause prouvée | **B** : oui, rappeler la déclaration et son périmètre sans affirmer un état actuel |
| O02 — `1e420dda`, o21 | Le rapport d’eval devra exposer les paramètres retirés ; absent | Intention explicite omise, utilité à confirmer | Information collectée mais perdue à la sélection du résumé | **B + D** : oui pour la restitution, vous pour la priorité |
| O03 — `2ce3445`, o2–o3 | Partie DevNote sur la recherche/les chemins de documents absente ; doing réduit la session à DevOps | Omission de couverture, valeur à confirmer | Information collectée mais perdue dans la sélection d’un seul sujet | **B + D** : tous les événements et cwd sont déjà présents ; aucun nouveau découpage de session demandé ici |
| O04 — `2ce3445`, o11–o12 | Succès du script et de hello-world, absents comme résultats ; les échecs dominent | Omission candidate de progrès | Information disponible mais mal interprétée/sélectionnée | **A/B + D** : codes exacts déterministes, importance et histoire d’ensemble à juger |
| O05 — `6a4166`, o8/o11/o14 | Lint/build/deploy code 0 absents comme résultats, sujet de déploiement présent | Omission candidate de validation bornée | Information collectée mais perdue à la sélection | **A + D** pour rappeler les codes ; **C** pour conclure au bon rendu distant |
| O06 — `6a4166`, o23–o25/o32 | Dernier dossier React présent dans stopped_at ; central_files vide malgré les chemins des commandes | **Pas** une omission totale ; visibilité des ancres à juger | Restriction de représentation de sortie : les chemins autorisés viennent des observations fichier ; ne pas blâmer le modèle pour respecter ce contrat | **A + D** : chemin disponible, règle produit à réexaminer seulement après réponse |
| O07 — `7bbaca7`, o5 | Identifiant exact du tag absent, mais palier 2 présent | Omission candidate d’une ancre de navigation | Information collectée mais perdue à la compression | **A/B + D** : l’identité est donnée, son importance n’est pas universelle |
| O08 — `cda6ccc`, o34 | Déclencheur « outbox neuve / premiers connecteurs » et limites de correction absents ; course WAL présente | Omission candidate d’une explication utile, pas d’un reste | Information collectée mais perdue à la compression | **B + D** : oui, comme déclaration du commit |
| O09 — `d987789`, o1–o2 | Raisons détaillées des correctifs largement comprimées ; leurs sujets présents | Pas de faux négatif certain ; niveau de détail à choisir | Ambiguïté intrinsèque de la saillance | **D**, avec **B** pour la restitution si souhaitée |
| O10 — `eb652ce`, o65/o67 | Build Swift exclu de CI et authentification reportée à l’action Agent, tous deux absents | Décisions de périmètre omises, pertinence à confirmer | Information collectée mais perdue à la sélection | **B + D** : oui ; les présenter comme dettes urgentes serait une autre erreur |
| O11 — `eef4956`, o8/o13 | Changement de couverture du watcher et correction déclarée de D2, absents | Omission candidate d’état acquis | Information collectée mais perdue à la sélection | **B + D** : commande exacte et confirmation déclarée sont disponibles |
| O12 — `eef4956`, o13 | Limite du filtre d’ignore pour eval/out, absente | Limite explicite omise, importance à confirmer | Information collectée mais perdue à la sélection | **B + D** : oui, sans transformer la limite en mission impérative |
| O13 — `eef4956`, previous_summary / o2/o19 | Report llm_max_tokens / passage de référence absent ; des évaluations sont pourtant déclarées dans la session | Écart à l’ancienne annotation ; **pas un faux négatif utilisateur établi** | Ambiguïté intrinsèque + information jamais observée sur la configuration effective/l’identité du passage ; la source originale de l’intention n’est pas vérifiée | **C + D** pour sa persistance réelle ; **B** pour rappeler prudemment l’ancienne déclaration et la contradiction |
| O14 — `8af930d`, agent_request / o1 | Objectif d’état des lieux déjà présent dans intents ; réponses de l’agent absentes | Pas d’omission d’intention ; résultat inconnu | Information présente uniquement dans une conversation d’agent : **hypothèse non vérifiée**, faute de lecture du transcript complet | **C + D** pour les conclusions ; aucun modèle ne peut les inventer à partir de ls -R |
| O15 — `d047b37`, o32–o37 | Cause précise et statut final de migration non connus ; composants et échecs présents | Lacune de diagnostic, utilité à confirmer | Information jamais observée dans l’entrée ; ne pas confondre absence et insuffisance du modèle | **C** pour la cause réelle, **D** pour la priorité ; **B** pour dire honnêtement « inconnu » |
| O16 — `071bbd6`, applications / o1–o4 | Objectif réel dans Notes/Safari/Claude inconnu | Besoin éventuel inconnu ; ce n’est pas un faux négatif démontré | Information jamais observée + jugement utilisateur | **C + D** ; aucune collecte de titres/contenus justifiée à ce stade |
| O17 — `247f206`, o3 ; `3cabaef`, o7/o10/o14 | Protocoles de validation et invariants plus détaillés que la fiche | Choix de profondeur, pas d’omission demandée établie | Ambiguïté intrinsèque de l’utilité | **D**, puis **B** si l’utilisateur souhaite ces détails |
| O18 — `8faf456`, o53 | GraphView.tsx absent des cinq chemins, bien que l’optimisation du graphe soit mentionnée | Omission candidate d’une ancre, pas du sujet | Information collectée mais perdue à la sélection sous limite de cinq chemins | **B + D** : aucun fichier supplémentaire à collecter |

« Information collectée mais perdue » désigne ici **la compression en sortie**, sauf mention contraire. La comparaison des 14 entrées montre que le constructeur courant fournit bien les mêmes observations que le replay v5. Elle ne prouve pas que la collecte initiale était exhaustive. Aucune suppression de fait pertinent entre ce corpus projeté et l’entrée finale n’est démontrée dans cette mission.

Les six familles ne sont pas des diagnostics obligatoires à distribuer : aucun transcript complet n’a été lu, donc aucun cas « uniquement dans une conversation » n’est confirmé ; aucune comparaison de modèle n’a été faite, donc « capacité insuffisante » demeure une hypothèse pour les échecs avec données suffisantes.

## Erreurs persistantes et classe de traitement

**A — Déterministe** : conserver des valeurs/identités/ordres exacts. **B — Raisonnement accessible** : un modèle pourrait restituer ou rapprocher honnêtement les données. **C — Information absente** : impossible de répondre affirmativement avec cette entrée. **D — Jugement utilisateur** : utilité sans vérité universelle. Un cas peut avoir plusieurs responsabilités ; elles concernent des questions différentes.

| Cas | Défaut observé / limite | Classe et conséquence |
| --- | --- | --- |
| E01 — `2ce3445`, open o7/o10 | « commande introuvable » ajouté au code 127 | **C** pour connaître la cause ; **B** pour s’abstenir de l’inventer avec le prompt actuel |
| E02 — `d047b37`, open o33 | Même extrapolation sur manage.py | **C/B**, même distinction |
| E03 — `2ce3445`, stopped_at et blockers o14 | Le modèle transforme un échec de bloc en échec certain de commit | **C** pour localiser la sous-commande ; **B** pour respecter explicitement la portée globale |
| E04 — `8faf456`, open o41 | Des retours à la ligne deviennent `&&` | **A** pour préserver le texte exact ; **B** pour ne pas réécrire sa sémantique dans la narration |
| E05 — `6a4166`, open o20/o22 | Échecs intermédiaires sélectionnés malgré add corrigé, commits/pushes suivants | **B** pour rapprocher les opérations avec incertitude ; **D** pour décider de les rappeler ; pas de preuve de résolution certaine du but général |
| E06 — `8faf456`, open o41 | Incident conservé après cinq blocs Git réussis | **B + D** ; les textes diffèrent, donc pas de règle déterministe générale de résolution |
| E07 — `eef4956`, stopped_at | Documents dits non commis sur la base de notifications | **C** pour connaître leur statut Git final ; **B** pour restituer les transitions sans ce statut |
| E08 — `2ce3445`, doing | L’agent est présenté comme configurant Docker durant la session, alors que sa demande visible arrive après ces commandes | **B** : chronologie et bornes agent suffisantes pour éviter cette attribution ; **C** pour connaître l’auteur réel de toutes les commandes |
| E09 — `071bbd6`, intents | Consultation des journaux et vérification Git supposées, alors qu’on observe navigation et écritures | **C** pour connaître le but réel ; **B** pour qualifier l’inférence ; **D** pour son utilité |
| E10 — `d047b37`, stopped_at | Les tentatives de migration sont présentées comme arrêt, malgré des écritures ultérieures de base et logs | **A** pour l’ordre, **B** pour distinguer dernière commande pertinente et dernière activité ; ces écritures ne prouvent pas une migration réussie |
| E11 — `247f206`, doing | Accomplissement « finalisé » attribué à l’agent depuis une déclaration de commit | **B** pour l’attribution au message ; **C** pour vérifier l’état vivant des services |
| O01 — `1e420dda` | Déclaration list/run explicite ignorée | **B**, données et contrat suffisants ; aucun correctif de collecte préalable nécessaire |

## Révision explicite d’un jugement précédent

Le troisième audit traitait `071bbd6/stopped_at` comme un état Git ancien abusivement propagé. La relecture complète montre `o4`, dernier snapshot, `dirty=false`, une seconde avant la fin de session. **« Le dernier snapshot indique un dépôt propre » est appuyé.** Le problème robuste est l’objectif de consultation supposé dans intents, et la distinction avec l’état au moment d’une reprise ultérieure. L’ancien rapport reste inchangé ; la correction est documentée ici et ce cas clean n’est pas un échec imposé au futur benchmark.

L’annotation `eef4956` dit aussi que eval/out reste hors de l’arbre observé, alors que o8 élargit le watcher et o13 note précisément cet angle mort du filtre sous la nouvelle racine. Ce changement ne prouve pas la validation de llm_max_tokens, mais interdit de traiter toute la justification historique comme intemporelle.
