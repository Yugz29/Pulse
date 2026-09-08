# Troisième chantier — Ce que Pulse peut affirmer lors d’une reprise

8 septembre 2026. Travail local sur `main`, après l’unification des sessions et la projection en observations ordonnées. **Verdict : non, `open` n’est pas encore suffisamment fiable pour un usage quotidien sans relecture.** La distinction entre observation et interprétation est maintenant explicite et contrôlée sur des cas précis ; elle ne garantit pas la pertinence ni la fidélité du texte généré.

La référence « avant » est l’état local du **deuxième chantier** (entrée 2 / prompt v4), et non le HEAD Git `e00dd0e`, qui précède ces changements non committés. Les chiffres de ce rapport isolent le troisième chantier. Aucun commit, push, changement de configuration personnelle, démarrage de service permanent ni réécriture de base utilisateur n’a été effectué.

Pièces consultables : [décision](../../decisions/2026-09-08-reprise-fondee.md), [taxonomie des 21 points v4](taxonomy-v4.md), [revue des neuf points v5](review-v5.md), [mesures](measurements.json), [empreintes du corpus inchangé](unchanged-inputs.json). Les dossiers `before/`, `trial-v5/`, `after/` et `scenarios/` conservent les entrées, sorties brutes, paramètres, mesures et résultats du parseur. Chaque prompt est archivé à côté. Les fichiers JSON d’audit sont des traces d’évaluation, pas un nouveau stockage produit.

## 1. Taxonomie des erreurs `open`

Les **14 sessions** ont été relues, y compris celle dont `open` était vide. Les **21 points v4** sont classés individuellement dans la taxonomie : observations disponibles, texte généré, justification insuffisante et information nécessaire. Les catégories viennent des cas observés ; elles ne deviennent pas des règles du logiciel.

| Catégorie observée | Nombre |
| --- | ---: |
| Ancienne observation transformée en état courant | 2 |
| Déclaration explicite appuyée par un commit | 1 |
| Interprétation précédente propagée | 3 |
| Référence réelle mais preuve insuffisante | 4 |
| Échec réel, portée exagérée | 2 |
| Demande initiale transformée en reste | 1 |
| Recommandation issue d’un manque d’information | 3 |
| Demande seulement contextuelle | 1 |
| Échec réel, cause inventée | 1 |
| Affirmation contredite par l’observation citée | 1 |
| Report attendu par l’annotation mais non vérifiable | 1 |
| Intention enregistrée, pertinence encore incertaine | 1 |

Exemples déterminants : `eb652ce9` cite `o23`, dont `dirty=false`, pour affirmer `dirty=true` ; `247f2062` déduit une branche non fusionnée d’un snapshot de branche ; `2ce3445` transforme le code global d’un bloc shell en échec d’un commit précis ; `d047b37b` explique une migration échouée sans disposer de stderr. `1e420dda/o20` contient au contraire une déclaration explicite « Non corrigé » : c’est une information positive que la version finale omet.

## 2. Cause principale

Le défaut architectural principal était **un contrat trop permissif sur la nature de la preuve**. Des références vérifiaient l’existence d’un élément sans établir que cet élément appuyait un reste. `carried_over` pouvait être accepté sans observation, avec une raison écrite par le même modèle. Une absence de confirmation entretenait alors une affirmation antérieure.

Les données ont aussi des limites réelles : pas de sortie terminal, de liste des fichiers d’un commit, de vérité sur les PR ou d’inspection du dépôt au moment où l’utilisateur lit la fiche. Les observations ordonnées du deuxième chantier rendent ces limites visibles, mais ne les comblent pas.

Enfin, le modèle reste une cause indépendante : il omet un problème explicitement déclaré, extrapole des causes malgré un prompt clair et transforme des séparateurs shell. Toute erreur restante ne justifie donc pas une nouvelle couche architecturale.

## 3. Sémantique retenue

| Notion | Affirmation autorisée |
| --- | --- |
| Observation | Un événement a été enregistré. Un message de commit est une déclaration de son auteur. |
| Dernière observation | Dernier fait enregistré sur un sujet dans la session, avec sa date. |
| Résolution observée | Une exécution ultérieure de la même commande exacte, dans le même cwd connu, commence après l’échec et réussit. |
| Sans résolution observée | Le dernier résultat de cette commande est un échec connu ; aucun résultat correspondant ne le remplace. |
| Inconnu | L’ordre, l’identité ou le résultat ne permettent pas de conclure. L’état actuel reste toujours inconnu sans nouvelle inspection. |
| `open` | Sélection utile de problèmes ou intentions positivement appuyés, encore pertinents à la fin de la session et sans résolution correspondante observée. |

La relation déterministe porte sur le **processus complet**, pas chaque test ou sous-commande. Un code 0 n’établit pas la santé du projet. Un résultat manquant ou une interruption 130 n’est pas une preuve de résolution. Un succès qui chevauche l’exécution échouée ne la résout pas. Deux cwd inconnus ne sont pas considérés identiques.

Pour Git, la dernière valeur reste un snapshot daté. Pour les fichiers, une notification ne révèle ni contenu ni statut de commit. Pour les commits, l’absence des chemins empêche de conclure qu’un fichier précis a été inclus. Pour l’agent, la demande initiale ne révèle pas son accomplissement. Aucun seuil arbitraire de fraîcheur ni règle lexicale FAILED/PASSED n’a été ajouté.

La recommandation « tu devrais vérifier/pousser/committer » reste en dehors de cette reconstruction. Une liste vide est une sortie normale. Le périmètre d’appui courant est volontairement conservateur : échec de commande ou déclaration de commit ; une intention exprimée ailleurs ne devient pas automatiquement un `open`.

## 4. Ancien résumé

Le parcours réel était : `session N → génération → événement session_summary → Core /context.last_session_summary → previous_summary_annex → modèle N+1`. L’annexe contenait `doing`, `stopped_at`, `open` et, dans l’entrée référencée, chaque fragment de `open` recevait un identifiant `previous_summary:i`. Le validateur admettait ensuite un `carried_over` sans preuve indépendante.

Le corpus conserve une chaîne concrète : `58874e67 → d9877899 → 1e420dda`. Une interrogation sur PR #28 puis la migration apparaît comme contexte précédent et se propage. Ces captures prouvent le mécanisme et les textes transmis ; elles ne constituent pas une reconstitution de tous les appels successifs du modèle en production.

Désormais :

- l’origine est explicitement `previous_model_interpretation`, avec date, `current_state=unknown` et `evidence_eligible=false` ;
- une seule référence identifie l’annexe pour auditer le contexte reçu ; aucun ancien point n’est une preuve de la session courante ;
- les résumés de la session elle-même, futurs, d’une autre journée locale ou d’un workspace connu différent sont exclus ;
- un ancien workspace absent reste inconnu, pour préserver la lecture des captures historiques ;
- la demande d’agent porte `initial_agent_request`, un accomplissement inconnu et le même refus d’éligibilité comme preuve.

Le texte ancien peut encore influencer la formulation : l’attribution et le validateur ferment un canal d’appui, ils n’effacent pas les biais possibles du modèle. Le cas synthétique d’ancien résumé faux produit toutefois `open: []`.

## 5. Architecture avant / après

### Avant ce chantier

```text
Core : événements → reconstruction unique → observations ordonnées
                                               ↓
ancien résumé → découpage des anciens open → entrée v2 / prompt v4
                                               ↓
                  observed / requested / carried_over
                                               ↓
                     validation des références → fiche
```

### Après ce chantier

```text
Core : événements → reconstruction unique → observations ordonnées
                                               ↓
Intelligence : relations déterministes de résultats de commandes
              + borne de session + état actuel inconnu
                                               ↓
ancien résumé / demande agent ── contexte attribué, non probant
                                               ↓
                                entrée v3 / prompt v5
                                               ↓
                        sélection de constats par le modèle
                                               ↓
             validation des appuis + rendu daté ou attribué
                                               ↓
                  session_summary → Core masquage → fiche
```

`command_outcomes()` est une fonction pure de 40 lignes, sans accès au stockage ni réseau. Core reste factuel. Son seul changement d’exécution propre à ce troisième chantier est l’ajout de l’origine et du workspace normalisé du résumé précédent. Reconstruction v3, observations v1 et Context API v3 restent inchangés.

## 6. Changements du prompt

Le prompt v5 expose quelques principes communs : rétrospection, preuve positive, attribution des déclarations, portée du résultat d’une commande, séparation avec les recommandations et possibilité de `[]`. Ils s’appliquent aussi à `stopped_at` et `blockers`.

Deux formes d’appui remplacent les catégories de propagation : `command_failure` avec une référence admissible, ou `recorded_statement` avec une référence de commit et une citation continue. Les anciennes instructions permettant d’entretenir un point par absence de preuve de résolution disparaissent du chemin courant.

Un premier essai v5 est conservé dans `trial-v5/` : 14 formats conformes, mais 10 sorties acceptées. Trois sorties proposaient des chemins trouvés dans des commandes, à cause de ma formulation trop large de `central_files` ; la quatrième échouait sur une citation dont les retours à la ligne avaient changé. Le prompt final rétablit précisément la règle des chemins issus des observations de fichiers. Le validateur tolère le reformatage des espaces d’une citation, en conservant mots, casse et ponctuation. **Le replay complet a été refait** ; les résultats du premier essai ne sont pas présentés comme ceux de la version finale.

## 7. Validations déterministes

Le validateur courant garantit : structure, bornes, types, références existantes, exactement un appui, absence d’appui dupliqué, dernier échec admissible pour `command_failure`, citation effectivement présente dans le message pour `recorded_statement` après normalisation des espaces.

Il refuse donc un échec ancien remplacé par un succès correspondant, une référence Git/fichier comme preuve de reste, un ancien résumé comme preuve, ou une citation absente. **Il ne garantit ni la vérité du texte libre, ni sa causalité, ni son utilité.** Un test montre volontairement qu’une citation réelle peut accompagner un texte injustifié et passer ces contrôles. Ce n’est pas un moteur d’inférence en langage naturel.

Le rendu borne les échecs à la fin de session et attribue les déclarations au commit. Texte et citation voyagent dans `reprise.open`, masqué par Core. Les métadonnées ne transportent que type, références et `scope=session_end`, sans seconde copie libre non masquée.

## 8. Cas contradictoires

Huit scénarios construits avec le vrai projecteur Core et le vrai constructeur d’entrée Intelligence ont été exécutés avec le même modèle local. Les huit sorties passent le parseur courant.

| Scénario | Résultat réel de `open` | Cible vérifiée |
| --- | --- | --- |
| pytest échoue, fichier modifié, pytest réussit | `[]` | Échec remplacé par succès |
| pytest échoue, fichier modifié, fin | 1 constat d’échec sans résolution observée | Pas d’affirmation absolue sur maintenant |
| échec / succès / échec / succès | `[]` | Dernier résultat et cycles |
| ancien Git dirty, activité ultérieure | `[]` | Pas de tâche commit inventée |
| git push code 128 | 1 constat du code 128, aucune cause ajoutée | Portée globale et cause inconnue |
| demande initiale « Implémente X » | `[]` | Pas d’intention automatiquement transformée en reste |
| ancien résumé faux sur PR et migration | `[]` | Pas de propagation du faux point |
| Terminal seul, aucune preuve suffisante | `[]` | Inconnu acceptable |

**8/8 sur la cible `open`**, pas 8/8 sur toute la fiche : `stalegit` ignore une activation Terminal ultérieure dans sa description de la dernière activité, et `intention` décrit trop largement une absence de toute activité. Les tests unitaires couvrent en plus chevauchements, cwd différents ou absents, résultats inconnus, rejet des preuves périmées et normalisation typographique des citations.

## 9. Corpus réel

Les 14 fichiers `eval/observed` et les quatre annotations `eval/expected` sont inchangés, vérifiés par SHA-256. Même modèle, température 0, plafond de sortie 2048, plafond d’entrée 30000, pensée désactivée, fonctionnement hors ligne. La comparaison adapte seulement les noms des catégories d’appui au type historique `observed` et les références de commit à leur ancienne notation. Elle ne change ni le texte, ni les règles requises/interdites, ni les sorties archivées.

| Mesure | Avant v4 | Après v5 final |
| --- | ---: | ---: |
| Sessions | 14 | 14 |
| Formats conformes | 14/14 | 14/14 |
| Sorties acceptées par le contrat correspondant | 14/14 | 14/14 |
| Points `open` produits | 21 | 9 |
| Sessions avec `open: []` | 1 | 9 |
| Sessions satisfaisant les critères humains | 1/4 | 2/4 |
| Tokens d’entrée, total | 80 858 | 80 238 |
| Tokens de sortie, total | 5 140 | 4 074 |
| Entrées JSON compactes, caractères | 167 454 | 170 617 |
| Durée cumulée, millisecondes | 1 053 144 | 962 214 |

Les entrées augmentent de 3 163 caractères à cause de la sémantique explicite ; le prompt compense ce coût en tokens. Un seul passage par version, sur la même machine : ces durées ne prouvent pas une amélioration reproductible des performances.

### Appui, résolution et utilité, séparément

- **Appui** : les neuf points v5 ont tous un ancrage admissible. La relecture n’en trouve que **cinq sans affirmation supplémentaire non étayée** dans leur texte : quatre constats de commande et une déclaration attribuable au commit. Trois autres ajoutent « commande introuvable/non trouvée » au code 127 ; le dernier transforme des retours à la ligne shell en `&&`. Même les cinq constats littéraux ne sont pas automatiquement utiles. La taxonomie avant et la revue après sont des jugements d’audit explicites, pas un nouveau score humain rétroactif.
- **Résolution** : le corpus contient une relation exacte résolue (`2ce3445`, o8 → o11), écartée des points finaux, et dix relations exactes sans résolution observée. Les huit points de type commande retenus appartiennent à ces dernières. En revanche `6a4166/o22` est suivi d’un add avec chemin corrigé, puis commit et push réussis : le modèle garde cet échec intermédiaire. `8faf4569` conserve aussi un bloc échoué malgré plusieurs blocs ultérieurs réussis. La relation exacte est correcte dans son périmètre et insuffisante pour décider de la pertinence de ces restes.
- **Utilité** : les annotations humaines restent le critère, et le résultat demeure faible. La liste plus courte supprime des inventions, mais perd aussi un problème explicitement déclaré.

| Session annotée | v4 | v5 final | Explication finale |
| --- | --- | --- | --- |
| `1e420dda8b6eee77` | Échec | Échec | Omission de la divergence list/run explicitement consignée au commit o20 |
| `8af930d9ef437d2a` | Réussite | Réussite | Le rappel requested facultatif de v4 disparaît ; `open: []` satisfait aussi le critère |
| `d98778994319cd07` | Échec | Réussite | `open: []` supprime la propagation interdite de PR #28 |
| `eef4956b36dd37ce` | Échec | Échec | Le report historique requis sur llm_max_tokens/passage de référence est absent |

L’attente `carried_over` de `eef4956b` entre en tension avec la politique nouvellement demandée : le report attendu ne dispose pas d’une preuve indépendante dans cette session. Cette contradiction reste visible. Elle n’explique pas l’omission injustifiée de `1e420dda` et ne permet pas de qualifier 2/4 de bon résultat.

Les dix autres sessions sans annotation exploitable ne sont pas assimilées à des réussites humaines parce que leur JSON passe. Toutes les 14 fiches et leurs points sont revus dans `review-v5.json` ; les défauts de `stopped_at` et `blockers` restent documentés.

## 10. Comparaison de modèles

Modèle réellement utilisé : `mlx-community/Qwen3.8-27B-4bit`, snapshot `3e6447f082e89cc7f0bc6e5441afd38dfce760ff`. Seul autre modèle local trouvé : Qwen3.5 9B quantifié, plus petit. Aucun modèle local plus capable disponible pour une comparaison utile ; aucun téléchargement ni appel distant effectué.

On ne peut donc pas prouver qu’un autre modèle corrigerait les erreurs. On peut constater que celui-ci échoue encore avec les faits et les restrictions déjà fournis. L’hypothèse d’une fiabilité insuffisante du modèle doit rester ouverte, sans la confondre avec les lacunes de collecte.

## 11. Code simplifié ou supprimé

Le chemin courant supprime le découpage des anciens `open` en preuves autonomes, la production `carried_over`/`requested`, et l’acceptation d’un report uniquement justifié par une raison du modèle. Il n’existe plus de second classement heuristique des textes ni de propagation assimilée à un fait Core.

Sont conservés : lecture des anciens rendus et payloads pending, validation des entrées archivées pour les tests historiques, ancienne notation des preuves pour l’évaluation gelée. Les prompts v1–v4 restent archivés. Une configuration les épinglant reçoit un refus explicite pour la nouvelle entrée et doit choisir v5 ; la configuration personnelle n’a pas été modifiée.

Le troisième chantier modifie **8 fichiers Python d’exécution, dont un nouveau** : 150 lignes ajoutées, 24 retirées, net +126, hors prompt, tests et documentation. C’est une clarification de contrat, pas une réduction nette du code. Le seul nouveau calcul est linéaire sur les observations déjà projetées. Aucun mécanisme de collecte, de reconstruction ou de stockage supplémentaire n’a été créé.

Les événements historiques et identités de sessions sont préservés. La version de prompt distingue les nouvelles générations ; aucun ancien résumé n’est écrasé. Une livraison pending reste rejouable sans charger le modèle. La provenance des événements et du contexte demeure distincte de l’entrée LLM. La citation passe par les protections de masquage existantes.

## 12. Limites persistantes

Pulse ne connaît pas l’état actuel à partir d’une ancienne session. Il ne connaît pas une résolution effectuée hors collecte, les fichiers exacts d’un commit, la cause d’un code de sortie ou l’état distant non enregistré. L’équivalence entre deux commandes différentes reste indécidable dans le petit modèle temporel retenu. Le périmètre de `recorded_statement` exclut des intentions légitimes exprimées ailleurs qu’en commit ; c’est un compromis conservateur explicite.

Le modèle peut encore mal lire une preuve, inventer une cause, omettre une déclaration utile ou garder un incident devenu peu pertinent. Le validateur n’interprète pas son texte. Les préfixes rétrospectifs réduisent une ambiguïté, mais ne rendent pas le contenu vrai. Des erreurs similaires persistent dans `stopped_at` et `blockers`.

Validation logicielle et limites de contrôle détaillées dans [validation.md](validation.md). La suite régulière couvre le contrat et les invariants ; le score humain mesure un autre problème. Le graphe GitNexus porte aussi sur les changements non committés du deuxième chantier et comporte des limites de parcours explicites : il ne prouve pas une absence exhaustive de régression.

## 13. Verdict

**Non.** `open` est plus prudent, ses appuis sont mieux définis, et les cas contradictoires ciblés passent. Mais seuls 2 critères humains sur 4 passent ; quatre textes sur neuf ajoutent une affirmation non appuyée ou modifient la commande ; plusieurs échecs intermédiaires restent peu utiles ; un problème explicite est omis. Ces défauts empêchent de traiter la fiche comme une reprise quotidienne fiable sans vérification.

La séparation observation/interprétation est livrée. La promesse de fiabilité du texte produit reste non atteinte. Le défaut de code passe à v5 pour employer le nouveau contrat, sans activation d’un service personnel ni déclaration d’aptitude quotidienne.

## 14. Prochaine frontière

Évaluer la **sélection utile et la fidélité des constats**, avec une adjudication humaine explicite des intentions reportables et des incidents réellement dépassés, puis comparer les mêmes cas difficiles à un modèle local plus capable lorsqu’il sera disponible. Garder les critères historiques en parallèle pour ne pas masquer les changements de politique. Ne pas ajouter d’abord des regex, une mémoire sémantique ou un moteur générique de croyances. Ce chantier suivant n’est pas implémenté ici.
