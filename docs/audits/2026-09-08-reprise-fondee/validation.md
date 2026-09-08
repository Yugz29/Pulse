# Validations du troisième chantier

## Résultats exécutés

| Validation | Résultat exact |
| --- | --- |
| Core, suite régulière `tests_v2` | **598 passed in 16.76s** |
| Intelligence, suite régulière | **261 passed, 8 deselected in 56.88s** |
| Intelligence, suite MLX `-m slow` | **7 passed, 1 skipped, 261 deselected in 259.23s** |
| Replay final des 14 sessions réelles | **14/14 générations et sorties acceptées** |
| Scénarios contradictoires avec vrai modèle | **8/8 sorties acceptées et cibles open satisfaites** |
| Annotations humaines gelées | **2/4**, contre **1/4** avant |
| Entrées des 14 générations finales comparées au constructeur courant | **14 identiques** |
| Empreintes SHA-256 des 14 sessions et 4 annotations | **18 inchangées** |
| Prompt final comparé au prompt utilisé par le replay | **Identique** |

Les suites régulières du début de ce chantier comptaient 597 tests Core et
247 tests Intelligence (7 tests lents exclus). Les résultats ci-dessus sont
ceux de la version finale. Le passage lent a été exécuté après correction d’une
assertion de test qui attendait encore v2 alors que sa configuration avait été
adaptée à v5.

Le test lent ignoré attend `PULSE_EVAL_RUN` et ne dispose pas d’un passage désigné.
L’écart aux annotations n’est pas ignoré : le replay complet est comparé
séparément, archivé et rapporté comme 2/4. Les sept tests lents exécutés couvrent
les prompts historiques v1/v2/v3, le prompt courant v5, le vrai tokenizer et ses
plafonds, et le parcours CLI → MLX → Core → état → affichage avec idempotence.

Les validations de panne et de confidentialité utilisent un Core temporaire :
reprise des livraisons, payload accepté, absence de seconde génération,
masquage du texte et de la citation, métadonnées fermées, provenance conservée.
Aucune base personnelle n’a été modifiée. MLX utilise uniquement ses poids en
cache, avec `HF_HUB_OFFLINE=1` et `TRANSFORMERS_OFFLINE=1`.

## Mesures et limites

Les fichiers `before/` et `after/` donnent les sorties brutes et leurs mesures.
`trial-v5/` conserve le premier essai non retenu. Ses refus restent ceux du
validateur utilisé à cet instant ; ne pas les recalculer silencieusement avec
le traitement typographique final des citations. Un format valide ne signifie
pas un texte fondé. La revue humaine des neuf points finaux reste indépendante.

Les scénarios synthétiques passent la projection Core et la construction
Intelligence réelles, puis le vrai modèle. Leurs résultats ne sont pas inclus
dans le score des quatre annotations humaines. Ils ne constituent pas une
preuve de qualité générale de `doing`, `stopped_at` ou `blockers`.

## Analyse d’impact et état Git

Les analyses GitNexus ont précédé les modifications de fonctions. L’impact
élevé de l’exposition du dernier résumé par Core a été signalé ; ses appelants
incluent `/context`, l’accueil et le statut. Les fonctions de tests que le
graphe ne relie pas sont découvertes par pytest ; les résultats UNKNOWN ont
été confirmés par recherche et inspection des tests, jamais interprétés comme
une absence d’usage. Les deux renommages de tests ont utilisé le renommage
GitNexus.

La comparaison globale au HEAD inclut aussi le deuxième chantier non committé.
Les nombres de lignes propres au troisième proviennent d’une copie de référence
prise au début de celui-ci, pas du diff global. Les nouveaux fichiers sont
signalés à Git par intention d’ajout pour l’analyse ; aucun contenu n’est stagé,
aucun commit ni push n’a été effectué.

Le contrôle final du graphe et de la forme du diff est consigné ci-dessous.

Contrôle final : index actualisé, **3 616 nœuds, 9 624 arêtes et 287 parcours**.
Le détecteur compare **156 fichiers, 260 symboles et 45 parcours affectés** au
HEAD, avec un risque global **critical**. La liste des 260 symboles est entière ;
le résultat de détection ne porte pas `partial` ni `truncated`. Ce risque global
inclut les deux chantiers non committés et ne signifie pas 156 fichiers de code
modifiés pour la seule reprise.

L’indexeur signale néanmoins des limites de découverte des parcours :
65 candidats écartés, 56 points d’entrée non explorés, 27 parcours coupés par
budget et 368 appels non suivis. Une nouvelle indexation et une nouvelle
détection ont été effectuées ; les plafonds du moteur restent présents. Ce
contrôle n’est donc **pas une preuve exhaustive d’absence d’impact**. La revue
des appels et les suites Core/Intelligence complètent cette vue, sans annuler
cette limite. Aucun outil ou plafond GitNexus n’a été modifié pour masquer
l’avertissement.

`git diff --check` ne signale aucune erreur. `git diff --cached --stat` est
vide : aucun contenu préparé pour commit. Les contrôles ont bien été exécutés
sur `/Users/Yugz/Projets/Pulse`, branche `main`.
