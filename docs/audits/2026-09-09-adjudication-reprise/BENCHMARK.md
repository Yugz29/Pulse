# Benchmark futur — même information, modèle différent

**Préparé, non exécuté. Aucun nouveau modèle appelé ou téléchargé.** Les cas partent des sorties finales v5, pas d’une nouvelle génération. Le manifeste donne le fichier exact, son empreinte, le pointeur vers l’entrée complète et les références d’examen. Les traces existantes se trouvent dans `corpus/`, exclu de Git ; ne pas envoyer automatiquement ce dossier ailleurs.

## Cas limitants et contrôles

| Cas | Session | Type | Question à vérifier |
| --- | --- | --- | --- |
| M01 | `1e420dda` | omission_documented | Déclaration list/run non corrigée omise de toute la fiche. |
| M02 | `2ce34456` | scope_error | Le résultat global d’un bloc devient un échec précis de commit. |
| M03 | `2ce34456` | invented_cause | Le modèle ajoute commande introuvable au code 127. |
| M04 | `d047b37b` | invented_cause | Le modèle ajoute commande non trouvée à manage.py migrate. |
| M05 | `8faf4569` | changed_command_semantics | La citation remplace des retours de ligne shell par &&. |
| M06 | `eef4956b` | unsupported_git_state | Notifications de fichiers transformées en modifications non commises. |
| M07 | `2ce34456` | actor_chronology | doing attribue la configuration antérieure à l’agent dont la demande visible arrive en fin de session. |
| T01 | `2ce34456` | control | Résolution exacte présente dans le corpus. |
| T02 | `071bbd62` | control | Dernier snapshot Git propre : ne pas pénaliser une rétrospection fondée. |
| T03 | `8af930d9` | control | La demande de PR n’a pas de réponse observée. |
| T04 | `d9877899` | control | Ancienne interprétation sur PR #28 à ne pas transformer en reste. |
| P01 | `6a416635` | user_judgment_pending | Utilité de conserver les erreurs add après correction de chemin et progrès. |
| P02 | `eef4956b` | user_judgment_pending | Report llm_max_tokens / référence ambigu face à des évaluations déclarées. |
| P03 | `d047b37b` | user_judgment_pending | Dernier diagnostic pertinent versus dernières écritures SQLite/logs. |

Sept cas M examinent des erreurs avec des faits suffisants pour répondre prudemment. Quatre contrôles T empêchent de gagner par abstention ou par surcorrection. Trois sondes P restent sans réponse idéale tant que vous n’avez pas adjudiqué leur utilité. Tous ces cas sont connus : ce benchmark est un diagnostic, pas une mesure aveugle de généralisation.

## Conditions du futur essai

1. Garder les 14 sessions comme ensemble de régression ; ne pas évaluer seulement les sept cas où Qwen échoue.
2. Pour isoler le modèle, lui donner l’objet `/input` entier et le prompt v5 inchangé, avec les mêmes paramètres. Ne pas lui fournir les réponses utilisateur, les critères, la sortie Qwen, la taxonomie ou les titres des cas. Les références sélectionnées servent aux évaluateurs, pas à raccourcir son entrée.
3. Conserver la même sérialisation JSON compacte, le même rendu de conversation lorsque comparable, la limite de sortie et le budget d’entrée. Enregistrer modèle, révision, quantification, runtime, template, paramètres réellement acceptés, tokens, troncatures et durées. Une différence de template/tokenizer empêche de prétendre à une comparaison parfaite du seul poids du modèle.
4. Séparer refus techniques, sortie invalide, omission, attribution incorrecte, cause inventée et utilité humaine. Appliquer le parseur existant sans le modifier pour faire passer un nouveau modèle ; examiner également le texte brut rejeté.
5. Noter toute la fiche en lecture aveugle quant à l’identité du modèle et dans un ordre varié. Les rubriques M/T proposées évaluent la fidélité de l’information ; leur réussite ne démontre pas une utilité quotidienne. P01–P03 ne doivent pas entrer dans un taux de réussite avant adjudication.
6. Publier les régressions aussi bien que les corrections, avec les mêmes critères historiques en parallèle. Ne pas choisir après coup la meilleure génération de chaque modèle. Si plusieurs essais sont faits, annoncer leur nombre avant le passage et conserver tous les résultats.
7. Comparer le temps et le coût local seulement comme mesures secondaires à la reprise correcte. Aucun téléchargement ni changement de configuration n’est autorisé par le simple fait que ce protocole existe.

Une comparaison ultérieure de nouvelles représentations produit relève d’un **autre essai** : changer à la fois le prompt, le contrat et le modèle ne permettrait plus d’attribuer un gain au modèle. La mission présente prépare le diagnostic sans réintroduire des adaptations lexicales en production.
