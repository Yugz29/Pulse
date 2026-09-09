# Bonne reprise Pulse — évaluation et conception produit

9 septembre 2026. **Recommandation : non, il faut scinder `open`.** Séparer le rappel appuyé par les traces de la piste de reprise inférée ; garder les recommandations en dehors du contrat de reconstruction. Cela ne signifie ni quatre panneaux dans l’interface ni un nouveau moteur d’état.

C’est une recommandation de conception **à éprouver par votre adjudication**, pas un changement de production. Aucun code, prompt, configuration ou corpus existant n’est modifié. Aucun modèle n’est lancé. La mission prépare la vérité terrain ; elle ne peut pas inventer les réponses qui la constitueront.

**À utiliser maintenant : [les 18 fiches d’adjudication](FICHES.md).** Elles contiennent les faits courts, la sortie v5 complète, les annotations historiques, les intentions et inconnues, puis vos questions A–E. 67 rappels sont proposés sans sélection ; les 90 réponses A–E restent vierges. Les fiches 15 à 18, ajoutées le 2026-09-09 au soir, ne proposent aucun rappel. Commencer par list/run, le report de llm_max_tokens, les erreurs add et la session multi-projets.

Autres livrables : [omissions et responsabilités](OMISSIONS.md), [format d’annotation proposé](ANNOTATION-PROPOSEE.md), [KPI](KPI.md), [collecte](COLLECTE.md), [benchmark futur](BENCHMARK.md), [provenance et validations](VALIDATION.md). Aucun des tableaux de l’analyste ne vaut réponse de l’utilisateur.

## 1. Ce que `open` essaie actuellement de représenter

Le code courant prend les événements reconstruits par Core, les observations ordonnées et des annexes attribuées. `build_model_input()` construit une entrée v3 ; `command_outcomes()` qualifie des relations exactes entre résultats de commandes. Le prompt v5 sélectionne des points appuyés par un dernier échec admissible ou une déclaration citée dans un commit. Le validateur vérifie l’appui structurel, puis le rendu borne ou attribue le constat.

Le contrat tente donc de faire de `open` une **sélection utile de problèmes ou intentions encore pertinents en fin de session**. Il doit accomplir simultanément deux opérations très différentes : établir ce que les données autorisent à dire et choisir ce qui aidera cet utilisateur à reprendre.

La nouvelle mission intervient sur un dépôt propre à `0eb8667`, après les commits de clôture des chantiers précédents. L’analyse porte sur les 14 replays v5 archivés ; leurs entrées correspondent exactement au constructeur courant. « Modèle actuel » signifie ce dernier passage disponible, pas une nouvelle génération du 9 septembre.

## 2. Les concepts qu’il mélange réellement

L’hypothèse des quatre notions est confirmée par les cas :

| Notion | Exemple réel | Pourquoi son contrat diffère |
| --- | --- | --- |
| État factuellement sans résolution observée | `d047b37`, dernière commande migrate code 2 | Fait rétrospectif ; ne connaît ni cause ni état actuel |
| Intention explicitement inachevée | `1e420dda/o20`, list/run « Non corrigé » ; o21 prévoit un travail sur le rapport d’eval | Déclaration attribuée, dont la priorité n’est pas déductible |
| Reprise probable | `6a4166`, retour final vers React après des opérations Vue ; incidents add probablement dépassés | Inférence raisonnable à partir de la trajectoire, pas preuve d’une tâche actuelle |
| Recommandation | Vérifier le rendu gh-pages après déploiement | Action potentiellement utile, mais non demandée et sans problème observé |

Le corpus ajoute un cinquième ensemble que `open` représente mal : **ce qui est acquis et qu’il est utile de se rappeler**. Exemples : le déclencheur de la course WAL, la décision de reporter l’authentification, le tag exact du palier ou le changement de couverture du watcher. Leur utilité ne dépend pas d’un état ouvert.

## 3. Faux positifs observés

Dans les neuf points ouverts du replay v5, trois ajoutent une cause non collectée au code 127 ; un autre transforme des retours à la ligne shell en `&&`. Des échecs add restent sélectionnés malgré un chemin corrigé puis des commits/pushes réussis. Leur inutilité probable demande votre jugement, mais le progrès ultérieur est présent dans les traces.

L’examen de la fiche entière ajoute des problèmes : `2ce3445/doing` attribue à un agent tardif le travail antérieur de configuration ; ses blockers localisent un commit en échec depuis un code global de bloc. `eef4956/stopped_at` affirme un statut non commis que les notifications ne donnent pas. `071bbd6/intents` suppose la consultation des journaux sans l’observer.

Une correction de mon audit précédent est nécessaire : **`071bbd6` possède bien un dernier snapshot Git propre, à une seconde de sa borne finale**. Le rappeler comme observation datée est fondé. Ce cas ne doit pas être utilisé pour enseigner une abstention injustifiée. L’état au moment d’une reprise plusieurs jours plus tard reste inconnu.

## 4. Faux négatifs observés

Le faux négatif le plus solide reste **list/run dans `1e420dda`** : attendu par une ancienne annotation, déclaré explicitement dans le commit o20, absent de toute la fiche finale. Ce n’est pas une absence de collecte.

L’absence du report llm_max_tokens / passage de référence dans `eef4956` est un écart réel à l’ancienne annotation, mais **pas une preuve suffisante de perte d’utilité**. La session rapporte déjà des comparaisons dans o2 et o19, et modifie le périmètre du watcher. La configuration effective et l’identité du passage visé restent inconnues. Votre réponse doit déterminer si ce report était encore pertinent.

D’autres informations sont omises ou peu visibles : le travail DevNote au début de `2ce3445`, les succès Docker et lint/build, la consigne dropped_parameters, le tag du palier, les limites Swift/Agent et la correction du watcher. Elles sont proposées à l’adjudication, jamais comptées d’avance comme attentes humaines.

À l’inverse, dans `8af930d`, la demande d’état des lieux apparaît déjà dans intents. La considérer absente parce que open est vide fabriquerait un faux négatif. La question devient celle de son accessibilité et de son utilité dans la fiche.

## 5. Informations que Pulse ne pouvait pas connaître

La collecte disponible ne dit pas la cause exacte des échecs terminal, le résultat individuel de chaque sous-commande, l’état Git final de chaque fichier, les conclusions de PR #28, la configuration effective llm_max_tokens ou le contenu consulté dans Notes/Safari/Claude.

Elle ne révèle pas non plus votre priorité, une tâche abandonnée, une résolution faite hors traces ni la situation réelle au moment de revenir plusieurs jours plus tard. « Aucun modèle ne peut répondre honnêtement » concerne ces questions précises, pas la possibilité d’en décrire les limites.

Les transcripts complets n’ont pas été consultés. Leur présence dans des archives ne permet pas de prétendre que la réponse manquante s’y trouve, ni de justifier l’envoi de l’archive entière au modèle.

## 6. Informations disponibles mais mal utilisées

Les déclarations de commits, les commandes et leur ordre contiennent déjà de nombreuses informations de reprise : list/run, instruction future pour le rapport d’eval, succès suivant un chemin corrigé, décisions de périmètre, tag, dossier final et correction du watcher.

La plupart des pertes candidates se situent dans **la sélection et la compression du résumé**, pas dans la projection observée → entrée modèle. Les 14 entrées ont été comparées, sans différence. Cette vérification n’établit pas une exhaustivité de la collecte initiale.

Une limite de contrat est distincte : `central_files` ne peut utiliser que des observations de fichiers. Des chemins présents dans des commandes ou dans un message de commit restent donc exclus de ce champ. Dans les sessions anciennes sans watcher, cette règle peut retirer une ancre utile sans que le modèle soit fautif. Aucune modification n’est faite avant adjudication du besoin.

## 7. Limites attribuables au modèle

Un modèle disposant des mêmes entrées pourrait raisonnablement rappeler list/run, conserver le sens shell, respecter le code global d’un bloc, situer la demande tardive d’agent et ne pas inventer le statut Git des documents. Le prompt expose explicitement ces limites. Il n’est donc pas raisonnable d’attribuer automatiquement ces échecs à l’architecture.

Cela **ne prouve pas une incapacité intrinsèque de Qwen** : il n’y a pas de comparaison nouvelle ni d’étude de variance. Le diagnostic distingue : A, valeurs/ordre déterministes ; B, raisonnement accessible ; C, information absente ; D, jugement utilisateur. Chaque cas et chaque omission candidate sont classés dans [OMISSIONS.md](OMISSIONS.md).

Le même événement peut appeler plusieurs traitements : la cause de 127 relève de C, tandis que l’abstention de l’inventer relève de B. Savoir que des opérations suivantes réussissent ne suffit pas à prouver qu’un incident est résolu ; juger s’il mérite encore l’écran relève de D.

## 8. Proposition de vérité terrain

L’unité doit être **l’information qui permet de reprendre**, et non un objet open. Annoter séparément son contenu, sa source, sa borne temporelle, son statut de travail, son importance pour vous et sa disponibilité pour le modèle.

Le format proposé permet de distinguer explicitement ouvert, terminé, inconnu, reprise utile inférée, recommandation et information sans importance, sans les forcer dans une catégorie exclusive. Un fait terminé peut être essentiel ; un fait encore sans résolution peut être inutile.

Les 14 dossiers sont `awaiting_user`, avec réponses et éléments adjudiqués à `null`. Une liste vide ne sera une vérité terrain qu’après votre confirmation. Les connaissances nouvelles apportées dans vos réponses resteront des connaissances utilisateur, jamais des événements Core inventés rétroactivement. [Format et procédure](ANNOTATION-PROPOSEE.md).

## 9. Proposition de nouveau KPI

**Temps jusqu’à une reprise correcte**, accompagné du **taux de reprises correctes** et de l’**effort mental déclaré**. Une reprise correcte retrouve les informations essentielles adjudiquées sans affirmation trompeuse qui détournerait le travail. Elle n’impose pas une action si le travail était terminé.

Mesurer aussi les informations importantes retrouvées, les manquantes, les fausses affirmations par gravité, le bruit, les retours aux sources et la confiance avant/après vérification. Une fiche vide n’obtient pas un bon score parce qu’elle se lit vite ; une fiche exhaustive ne gagne pas si elle exige une reconstitution laborieuse.

Les 14 sessions constituent un pilote historique, avec souvenirs et apprentissage possibles. Les temps ne peuvent pas être reconstruits rétrospectivement. Le [protocole proposé](KPI.md) traite les échecs, l’ordre d’exposition et la séparation entre couverture de collecte et qualité du modèle. Aucun KPI nouveau n’est chiffré à ce stade.

## 10. Faut-il conserver `open` ?

**Non, il faut le scinder.** Un rappel factuel et une piste inférée peuvent partager une fiche, mais pas une promesse de certitude.

| Dimension | A — Conserver une liste unique | B — Séparer appuyé et inféré | C — Supprimer open, reconstruction seule |
| --- | --- | --- | --- |
| Valeur utilisateur | Simple à parcourir, mais risque de mélanger preuve, priorité et conseil | Peut restituer acquis et intentions, puis une piste utile sans la présenter comme fait | Bon socle de confiance ; laisse à l’utilisateur une part importante de la reconstitution |
| Fiabilité possible | Dilemme entre omissions par prudence et restes plausibles non fondés | Promesse explicite par nature d’information ; l’inférence doit rester évaluée | Élevée sur ce qui est bien observé, sans garantie que le résumé soit bien sélectionné |
| Coût cognitif | Faible visuellement, élevé si l’utilisateur doit deviner le statut de chaque point | Modéré si deux niveaux lisibles ; élevé si on expose une taxonomie technique | Faible nombre de rubriques, mais plus d’effort pour décider quoi reprendre |
| Complexité technique | Faible en apparence ; pression continue sur prompt/validateur | Modérée : sélection et attribution séparées, sans nouveau stockage nécessaire conceptuellement | Faible immédiatement ; la question de reprise revient dans une future couche |
| Dépendance au modèle | Forte pour concilier pertinence et certitude dans chaque point | Faible pour valeurs/ancres, forte mais visible pour la piste de reprise | Reste présente pour résumer et choisir les faits ; raisonnement reporté à plus tard |
| Risque d’invention | Élevé dès qu’on attend un « reste » de chaque session | Réduit par attribution, jamais supprimé ; danger d’un utilisateur lisant l’hypothèse comme certitude | Plus faible si le récit reste strict, mais omissions et inférences implicites possibles |

B est recommandé pour la valeur recherchée : diminuer le coût mental sans assimiler une inférence utile à une observation. L’adjudication peut montrer que les pistes apportent trop peu de valeur : C resterait alors une alternative plus simple. La décision ne repose pas sur le coût de compatibilité du code existant.

## 11. Architecture conceptuelle recommandée

```text
Événements → sessions → observations ordonnées
                              ↓
        Où j’en étais : réalisations, décisions, limites,
           intentions attribuées et ancres de navigation
                              ↓
        Pour reprendre : piste éventuelle, explicitement
           inférée, facultative et jugée par l’utilisateur

Recommandations nouvelles → autre contrat, hors reconstruction
```

La première partie décrit un contexte acquis, y compris des travaux terminés. La seconde répond à une question d’utilité sans prétendre prouver un état actuel. Elle peut être absente. Les libellés sont conceptuels : aucune API, enum, UI ou migration n’est décidée ici.

Les deux dimensions doivent aussi s’appliquer à doing, stopped_at, intents et blockers. Scinder uniquement le champ open tout en laissant des affirmations fausses dans les autres champs ne suffirait pas.

## 12. Données supplémentaires réellement justifiées

**Aucune extension de collecte n’est justifiée immédiatement par les faux négatifs confirmés.** List/run est déjà présent.

Deux sessions montrent un besoin possible de diagnostic terminal (`2ce3445`, `d047b37`) ; deux illustrent la portée inconnue d’un bloc (`2ce3445`, `8faf4569`). Cela justifie de vous demander si cette précision aurait aidé, pas de capturer toutes les sorties. Les fichiers de commits pourraient éclairer deux autres situations, mais ne prouveraient toujours pas un état Git actuel.

Les trois occurrences de la demande PR #28 ne sont pas trois besoins indépendants. Les neuf annexes d’agent, dont cinq opaques, n’établissent pas que l’évolution complète d’un transcript aurait été utile. Les [candidats de collecte](COLLECTE.md) indiquent les sessions exactes, coûts techniques et de stockage, confidentialité, alternatives et **zéro gain utilisateur mesuré**. Aucun réseau, contenu de fichier ou archive supplémentaire n’est collecté.

## 13. Benchmark futur pour modèles

Le [benchmark préparé](BENCHMARK.md) comprend **7 cas d’erreur**, **4 contrôles** et **3 sondes d’utilité en attente d’adjudication**. Le manifeste pointe vers les entrées complètes existantes, le prompt v5 et leurs empreintes. Le groupe des 14 sessions reste l’ensemble de régression.

Il permet d’examiner la sélection de list/run, la portée des commandes, les causes inventées, la fidélité du shell, l’attribution temporelle et le statut des fichiers. Il conserve aussi des contrôles qui empêchent de « gagner » en supprimant toute information : snapshot propre réellement observé, résolution exacte et intention déjà exprimée dans intents.

Un futur essai devra changer le modèle en gardant observations et prompt constants, conserver toutes les sorties, comparer la fiche entière et séparer critères objectifs et jugement d’utilité. Les réponses utilisateur et rubriques de notation n’entrent pas dans le prompt. Aucun nouveau modèle n’a été appelé ou téléchargé dans cette mission.

## 14. Prochaine mission technique

**Construire un évaluateur hors production de reprise, à partir des fiches adjudiquées et du format validé.** Il devra comparer la fiche entière aux informations essentielles, distinguer ce qui était accessible au modèle, conserver les erreurs de portée et mesurer la reprise correcte sans récompenser une sortie vide.

Prérequis : vos réponses et la confirmation des annotations proposées. Cette unique mission peut être menée sans modifier le contrat de génération. Elle doit précéder tout nouveau chantier sur le prompt, la collecte ou le modèle. Elle n’est pas implémentée ici.
