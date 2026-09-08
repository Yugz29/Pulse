# Taxonomie des sorties v4

Relecture des 14 sorties du deuxième chantier, chaque point conservé sans modification. Les catégories sont des jugements d’audit, pas des règles du produit. `071bbd62` contient `open: []`.

## 1e420dda8b6eee77 / point 1 — past_as_current

**Observations disponibles** : o19 (command, +4581.0 s), o21 (commit, +5296.0 s)

**Sortie du modèle** : Le dépôt est en état dirty sur la branche ship/intelligence-param-negotiation, avec des modifications non commitées.

**Analyse** : Un snapshot dirty antérieur à deux commits ne décrit pas le dépôt actuel ni les fichiers non commités.

**Information nécessaire** : Un statut daté après les opérations pertinentes, et les chemins de ce statut.

## 1e420dda8b6eee77 / point 2 — supported_declaration

**Observations disponibles** : o20 (commit, +4744.0 s)

**Sortie du modèle** : La divergence entre run_list et run_pass sur l'identification du modèle est consignée mais non corrigée (repli en dur).

**Analyse** : Le message o20 consigne explicitement « Non corrigé » ; la formulation devrait rester attribuée au message et bornée à la session.

**Information nécessaire** : Aucune pour rappeler la déclaration ; une vérification du code serait nécessaire pour affirmer son état actuel.

## 1e420dda8b6eee77 / point 3 — propagated_interpretation

**Observations disponibles** :  ; annexe de modèle antérieur

**Sortie du modèle** : La PR #28 et la migration du nouveau MacBook Pro M3 Max n'ont pas été confirmées dans cette session.

**Analyse** : La seule justification est une absence de confirmation. La migration est même dite terminée dans la demande initiale.

**Information nécessaire** : Une observation ou une intention pertinente renouvelée dans cette session.

## 247f2062410ca5a9 / point 1 — insufficient_evidence

**Observations disponibles** : o18 (command, +574.39508 s), o20 (command, +1783.39508 s)

**Sortie du modèle** : La branche ship/launchd-observers n'a pas été fusionnée dans main ; le dépôt est actuellement sur main.

**Analyse** : Les snapshots montrent main ; ils ne donnent aucun graphe de merge. La référence existe mais ne prouve pas la non-fusion.

**Information nécessaire** : Un état de merge ou de PR explicitement observé.

## 2ce344566f7e85dc / point 1 — supported_failure_overstated_scope

**Observations disponibles** : o14 (command, +1655.0 s)

**Sortie du modèle** : La commande de commit dans devops_culture_git a échoué (exit_code 1) et n'a pas été réessayée avec succès.

**Analyse** : Le code 1 concerne un bloc de quatre commandes ; il ne localise pas le commit en échec et ne prouve pas un état actuel.

**Information nécessaire** : Le résultat individuel de chaque sous-commande pour préciser laquelle échoue.

## 2ce344566f7e85dc / point 2 — initial_intention_as_remaining

**Observations disponibles** :  ; demande initiale d’agent

**Sortie du modèle** : La demande de l'agent de créer un fichier .gitignore n'a pas été observée dans la session.

**Analyse** : La demande de créer un gitignore ne prouve ni son absence ni un besoin actuel de reprise.

**Information nécessaire** : Une intention de reprise renouvelée ou une observation positive de blocage.

## 3cabaefb759dae36 / point 1 — insufficient_evidence

**Observations disponibles** : o15 (file, +802.322968 s), o16 (file, +802.331077 s), o17 (file, +802.336439 s), o18 (file, +802.340472 s), o19 (file, +802.344679 s), o20 (file, +802.348936 s), o21 (file, +802.352668 s)

**Sortie du modèle** : Modifications non commitées dans les fichiers de documentation et de version (AGENTS.md, CLAUDE.md, README.md, CHANGELOG, VERSION, VISION.md).

**Analyse** : Les notifications postérieures au commit n’indiquent pas le statut Git des chemins.

**Information nécessaire** : Un statut Git explicite de ces fichiers, et une raison positive de les reprendre.

## 6a4166356dbab6ec / point 1 — recommendation_from_unknown

**Observations disponibles** : o24 (command, +4162.0 s), o25 (command, +4169.0 s)

**Sortie du modèle** : Vérifier que le déploiement gh-pages fonctionne correctement pour les sous-dossiers React et Vue.

**Analyse** : Commit et push code 0 ne signalent pas un problème de déploiement ; le modèle propose une vérification.

**Information nécessaire** : Un échec observé du déploiement ou une demande explicite de validation à reprendre.

## 7bbaca7882c3d766 / point 1 — recommendation_from_unknown

**Observations disponibles** : o5 (command, +1120.0 s)

**Sortie du modèle** : Vérifier l'état distant du push du tag palier-2-project-context-stabilized, car l'état distant n'est pas collecté.

**Analyse** : L’absence de collecte distante devient une tâche, sans problème observé.

**Information nécessaire** : Un échec de publication ou une intention explicite pertinente.

## 8af930d9ef437d2a / point 1 — contextual_request_only

**Observations disponibles** :  ; demande initiale d’agent

**Sortie du modèle** : Vérifier l'état de la PR #28 (exclusion .gitnexus/ du watcher, Core 0.3.1) et la présence de branches en attente, comme demandé à l'agent.

**Analyse** : Le rappel requested est autorisé comme option par l’annotation ancienne ; il ne prouve aucun reste et sera conservé en contexte.

**Information nécessaire** : Une indication de pertinence actuelle pour le promouvoir en point à reprendre.

## 8faf4569fe2723b1 / point 1 — supported_failure_overstated_scope

**Observations disponibles** : o41 (command, +4318.260941 s)

**Sortie du modèle** : Le commit `fix: serialize project scans` a un exit_code 128, indiquant un échec Git (probablement push ou commit), bien que les fichiers aient été modifiés.

**Analyse** : Le bloc add/commit/push a un résultat global 128. Attribuer ce code au commit puis spéculer sur la sous-commande excède la collecte.

**Information nécessaire** : Des résultats individuels et la sortie de commande pour localiser la panne.

## cda6ccce898d3e88 / point 1 — recommendation_from_unknown

**Observations disponibles** : o34 (commit, +502.659611 s), o35 (commit, +503.659611 s)

**Sortie du modèle** : Vérifier que la branche ship/outbox-race a bien été poussée sur le distant, l'état du push n'ayant pas été collecté.

**Analyse** : Une branche et deux commits ne constituent pas une publication manquante à reprendre.

**Information nécessaire** : Une publication échouée ou une demande explicite encore pertinente.

## d047b37b4511d37c / point 1 — supported_failure_invented_cause

**Observations disponibles** : o28 (command, +3843.0 s), o32 (command, +3896.0 s), o33 (command, +3901.0 s), o34 (command, +3918.0 s)

**Sortie du modèle** : La migration Django n'a pas abouti : les dernières commandes `manage.py migrate` ont échoué (exit 127/2) car exécutées depuis la racine du dépôt au lieu du dossier `backend/`.

**Analyse** : Des commandes migrate ont échoué ; le cwd enregistré et le code ne suffisent pas à déterminer la cause, notamment dans un bloc contenant cd.

**Information nécessaire** : La sortie stderr ou les résultats individuels pour expliquer la cause.

## d047b37b4511d37c / point 2 — past_as_current

**Observations disponibles** : o34 (command, +3918.0 s)

**Sortie du modèle** : Le dépôt Git est en état dirty sur la branche main, avec des modifications non commitées sur les fichiers du backend et du frontend.

**Analyse** : Le snapshot dirty ne désigne pas les fichiers cités et ne prouve pas un reste utile à traiter.

**Information nécessaire** : Un statut par chemin et un problème ou une intention de reprise explicite.

## d98778994319cd07 / point 1 — propagated_interpretation

**Observations disponibles** :  ; annexe de modèle antérieur

**Sortie du modèle** : L'état de la PR #28 et la branche courante n'ont pas été vérifiés.

**Analyse** : La PR provient d’une ancienne demande propagée par un résumé ; les deux commits de cette session ne la concernent pas.

**Information nécessaire** : Une preuve indépendante du modèle ou une intention renouvelée pertinente.

## eb652ce9f04c4b37 / point 1 — contradicted_by_observation

**Observations disponibles** : o23 (command, +405.611247 s)

**Sortie du modèle** : Le dépôt est en état dirty lors de la dernière observation, avec des modifications non commitées.

**Analyse** : La référence o23 citée porte dirty=false : la sortie contredit directement sa preuve, en plus de présumer des fichiers non commités.

**Information nécessaire** : Aucune donnée supplémentaire pour détecter cette erreur ; lire la valeur citée suffit.

## eb652ce9f04c4b37 / point 2 — insufficient_evidence

**Observations disponibles** : o202 (commit, +2139.611247 s)

**Sortie du modèle** : La branche ship/hardening contient les correctifs mais n'a pas été fusionnée sur main ; le push de la branche n'est pas observé.

**Analyse** : Le commit sur ship/hardening ne prouve ni absence de merge ni publication manquante.

**Information nécessaire** : Un état de merge/publication observé et une raison de reprise.

## eef4956b36dd37ce / point 1 — propagated_interpretation

**Observations disponibles** :  ; annexe de modèle antérieur

**Sortie du modèle** : Le push n'a pas été observé pour les commits de la session.

**Analyse** : Le silence sur le push dans l’ancienne synthèse est de nouveau transformé en reste.

**Information nécessaire** : Un problème de publication observé ou une intention pertinente.

## eef4956b36dd37ce / point 2 — legacy_expected_but_unverified

**Observations disponibles** :  ; annexe de modèle antérieur

**Sortie du modèle** : La configuration de llm_max_tokens et le passage de référence restent à valider.

**Analyse** : L’annotation historique exige ce report. La collecte de cette session ne permet pourtant ni de confirmer la tâche ni sa non-réalisation hors arbre observé.

**Information nécessaire** : L’intention d’origine vérifiable ou une confirmation de reprise ; contradiction de politique conservée dans l’évaluation.

## eef4956b36dd37ce / point 3 — recorded_intention_uncertain_relevance

**Observations disponibles** : o19 (commit, +3204.0 s)

**Sortie du modèle** : Le défaut D1 (open recopié du previous_summary) n'est pas mesurable sur le corpus gelé ; à juger au jour 2 du dogfooding.

**Analyse** : Le commit o19 signale explicitement un jugement à faire au jour 2. C’est une déclaration réelle, mais son actualité à la fin de la session reste à évaluer.

**Information nécessaire** : Une confirmation de réalisation ou de report ; pas une preuve par absence.

## eef4956b36dd37ce / point 4 — insufficient_evidence

**Observations disponibles** : o20 (file, +3270.581488 s), o21 (file, +3270.587474 s), o22 (file, +3270.593141 s)

**Sortie du modèle** : Des modifications non commitées subsistent dans docs/dogfooding.md, docs/specs/2026-09-05-llm-provider.md et intelligence/TODOS.md.

**Analyse** : Les notifications de fichiers n’indiquent pas les chemins présents dans les commits ni leur statut Git final.

**Information nécessaire** : Un statut explicite des chemins et un besoin de reprise.

Les observations complètes citées et les annexes utilisées sont conservées dans `taxonomy-v4.json`. Le contexte entier, y compris les observations non citées, reste dans le corpus `intelligence/eval/observed`.
