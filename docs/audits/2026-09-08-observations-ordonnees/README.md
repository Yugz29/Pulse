# Pulse — observations ordonnées : rapport du chantier

2026-09-08. Référence avant : `e00dd0e`, reconstruction unique déjà intégrée.
**La nouvelle représentation est implémentée. Le gain de fiabilité du modèle
n'est pas validé sur le corpus réel : `open` régresse sur certaines sessions.**
Aucun service, modèle ou réglage personnel n'a été activé par ce chantier.

## 1. Diagnostic de l'entrée précédente

Core reconstruisait déjà correctement les sessions, puis perdait de
l'information dans leur projection : premières occurrences de fichiers,
listes séparées de tests réussis/échoués et d'erreurs, commits sans date et
réduits au hash court et à la première ligne du message. Intelligence recopiait
cette projection, y compris ses identifiants sources exhaustifs, dans le prompt.

Sur les 14 sessions : **102 692 caractères de JSON, dont 73 056 pour les
listes de sources (71,1 %)**. La session `3cabaefb` occupait 25 503 caractères,
dont 21 919 de sources (85,9 %). Le modèle ne recevait pas le contenu de ces
UUID. Le prompt système v3 ajoutait 10 717 caractères par session.

Les anciennes catégories de chemins occupaient 8 412 caractères. Les champs
descriptifs de session (chemins, commandes classées, messages) en occupaient
12 706. Ces deux mesures se chevauchent ; ce ne sont ni des tokens ni une
mesure objective de quantité d'information sémantique.

## 2. Informations perdues avant le modèle

L'ordre d'un échec et d'un succès, les répétitions de cycles, la date des
modifications par rapport aux commits, les commandes ordinaires et leur cwd,
les snapshots de branche/dirty et le corps des messages n'atteignaient pas
la vue de session du modèle. Les vingt premiers chemins pouvaient masquer
les suivants, notamment après du bruit d'index GitNexus historique.

Le code attribuait le résultat global d'une commande à plusieurs lignes
filtrées. Une même commande pouvait apparaître dans les trois listes
réussite/échec/erreur, sans dernier résultat. L'annexe d'agent vérifiait le
chevauchement temporel mais pas le workspace.

Conséquences observées : erreurs anciennes présentées comme ouvertes,
fichiers déclarés non commités sans connaître les fichiers d'un commit,
mission initiale d'un agent confondue avec l'activité ou son état final.

## 3. Nouveau modèle de représentation

Un fait est une **observation enregistrée**, pas une conclusion : une commande
avec son code global, une transition de fichier, un commit avec son message,
une activation d'application. La projection est pure, déterministe et versionnée.

Les commandes et commits gardent leur ordre. Les fichiers gardent leurs suites
de transitions et leurs intervalles ; seules les notifications identiques
sont regroupées entre deux commandes/commits. Les applications restent des
comptages avec premier/dernier instant. Des références désignent les derniers
résultats réellement observés, séparément par commande/cwd, fichier et dépôt.
Un commit ne transforme jamais un ancien dirty en false et ne démontre pas
la publication distante.

Sur le corpus : **2 030 événements sources retrouvés sur 2 030**, projetés en
500 observations de travail, plus les agrégats d'applications. Les bruits
historiques écartés sont comptés ; leurs événements restent dans la source.

## 4. Architecture avant / après

Avant :

```text
événements → session reconstruite → listes indépendantes /context
                                  → copie avec UUID → prompt v3 → modèle
```

Après :

```text
événements → même session → observations ordonnées v1
                              ├→ contexte v3 → entrée 2 → prompt v4 → modèle
                              └→ références → événements sources (hors prompt)
```

Les compteurs récents utilisent aussi cette projection. Le rendu du journal
reste une présentation de la reconstruction commune ; il ne devient pas une
entrée de modèle ni un second moteur de faits.

## 5. Responsabilité de Core

Core collecte et stocke sans Intelligence, reconstruit les sessions et prépare
les observations sans accès au disque, à Git ou au réseau. Il expose les faits,
les dernières références observées et les limites de collecte. Les dates sont
des offsets en secondes depuis une origine UTC, avec les microsecondes conservées.

La politique de bruit fichiers existante est partagée avec le collecteur.
Les anciennes coupes 20 fichiers / 10 commandes / 5 applications disparaissent
de la session détaillée. Les compteurs récents comptent désormais les exécutions
en échec, dont tests simples, et les fichiers utiles de la projection : une
répétition d'échec n'est plus une seule chaîne dédupliquée.

Core sélectionne le dernier agent compatible avec le workspace résolu, ou
d'attribution inconnue. Il conserve les identifiants des annexes pour l'audit.

## 6. Responsabilité d'Intelligence

Intelligence choisit les champs visibles, sépare les annexes et interprète les
observations. Elle ne réordonne pas les événements et ne réinvente pas leurs
résultats. L'entrée ne contient plus les sources exhaustives.

La sortie `session_summary` conserve `doing`, `stopped_at`, `open` et les
champs structurés. La forme et les références restent validées. Deux filtres
lexicaux D5/D6 ont été retirés : ils ne savaient pas établir la vérité et leur
hypothèse « aucun commit observé ⇒ fichier non commité » était incorrecte.
Aucune nouvelle regex sémantique ne les remplace. Les références valides ne
sont pas un certificat de vérité : les erreurs du modèle sont visibles ci-dessous.

## 7. Provenance

L'identité de session et la reconstruction v3 sont conservées. Chaque `oN`
ou `app:N` renvoie aux event_id exacts de ses observations dans
`observations.sources`. Les sources exhaustives restent sur la session.
Les nouveaux résumés portent `observation_version` et `observation_sources`,
avec les sources connues des annexes effectivement sélectionnées. Cette table
est validée par Core et conservée dans l'événement, hors du prompt.

Le hash d'entrée désigne le JSON réellement envoyé. La génération v4 possède
une identité distincte des v1–v3. Les résumés historiques, sources, archives et
payloads pending ne sont ni réécrits ni supprimés. Les anciennes vues restent
lisibles comme agrégats dont la chronologie est explicitement indisponible.
Les prompts historiques refusent explicitement la nouvelle entrée.

## 8. Cas contradictoires

Les tests de projection couvrent les six familles, les commandes composées,
les cwd différents, les répétitions de fichiers, les dates identiques, la
provenance, le bruit historique et les workspaces incohérents. Le modèle local
a aussi été exécuté sur les six cas minimaux ; entrées et sorties dans
[`scenarios/`](scenarios/).

| Cas | Projection déterministe | Sortie du modèle local |
| --- | --- | --- |
| Échec → modification → succès → commit | Ordre conservé, dernier résultat 0, commit ensuite | Succès puis commit dans `stopped_at`, `open: []` |
| Échec → modification | Dernier code 1, aucun succès inventé | Échec maintenu ouvert ; aucune résolution inventée |
| Échec/succès/échec/succès | Quatre résultats, dernier code 0 | Dernier succès reconnu, `open: []` |
| Modification → commit → push code 128 | Commande et code 128, état distant non collecté | Échec du push reconnu ; suggestion réseau/auth non démontrée par les données |
| Deux workspaces d'agents | L'agent étranger est exclu ; agent compatible retrouvé en Core | Pas de contamination par la mission étrangère ; invente néanmoins « fichier non commité » |
| Terminal seul | Aucun test ni état Git inventé | Incertitude conservée, confiance basse, `open: []` |

Le critère central échec/correction/succès/commit fonctionne sans règle
lexicale dédiée. Cela ne prouve pas la justesse sur toutes les sessions réelles.

**Validation de code finale : 597 tests Core réussis en 16,86 s ; 247 tests
Intelligence réussis en 56,08 s, 7 tests slow exclus de la suite standard.** Les 28 générations réelles
avant/après et les 6 cas minimaux ont été lancés séparément. Les tests de
récupération réelle après arrêt de processus, de pending, de conflit après
restauration, de masquage et de permissions restent dans les suites réussies.

## 9. Corpus réel

Deux passages complets, mêmes 14 identités et mêmes annexes gelées : ancien
code et prompt v3, puis nouvelle projection et prompt v4. Le modèle est
Qwen3.8-27B-4bit en MLX local, hors ligne, température 0, plafond de sortie 2 048
tokens. Les fichiers [`before/`](before/) et [`after/`](after/) conservent les
textes complets, tokens, durées et validations, y compris les sorties rejetées.

**12/14 sorties valides avant, 14/14 après. Ce n'est pas un gain de justesse.**
Les mêmes quatre annotations humaines passent de **2/4 à 1/4**. Les deux
points obligatoires auparavant manquants sont désormais retrouvés (divergence
list/run et validation de llm_max_tokens), mais restent accompagnés de points
interdits. Les annotations n'ont pas été modifiées : seule l'écriture des
références de commit est rapprochée de leur hash. `compare_open.ok` ne pénalise
pas les points supplémentaires ; ceux-ci ont donc aussi été relus.

Comparaison qualitative par champ, sans inventer de notes humaines nouvelles :

| Session | `doing` / `stopped_at` | `open` et limites de l'après |
| --- | --- | --- |
| `071bbd62` | Ajout de navigation et du snapshot Git ; attribuer le travail aux apps reste fragile | Supprime le reste « db/logs non commités », mais présente le snapshot comme état actuel |
| `1e420dda` | Sujet LLMProvider conservé, branche et détail des commits accessibles | Retrouve la divergence, mais conserve la PR/migration indue et transforme dirty ancien en reste |
| `247f2062` | Commandes ultérieures au commit enfin visibles | Remplace l'ancien D6 par une branche déclarée non fusionnée sans preuve |
| `2ce34456` | Installation et commande de commit en échec deviennent identifiables | Échec réel retrouvé ; la demande .gitignore reste traitée abusivement comme non réalisée |
| `3cabaefb` | Sujet Context API conservé, modifications postérieures visibles | Régresse de liste vide à fichiers prétendument non commités |
| `6a416635` | Commandes Vue/React enfin disponibles ; annexe étrangère exclue | Invente une vérification de déploiement à faire |
| `7bbaca78` | Décrit les commandes de stabilisation au-delà du seul README | Ajoute un contrôle distant parce que l'état distant manque |
| `8af930d9` | L'exploration `ls -R` remplace une pure reprise de demande | Rappel de demande autorisé par l'annotation, sans observation de son accomplissement |
| `8faf4569` | Dernière commande interrompue et fichier churn visibles | Meilleure prudence sur l'échec composé, mais localisation commit/push toujours incertaine |
| `cda6ccce` | Sujet et deux commits conservés | Régresse de liste vide à vérification de push sans problème observé |
| `d047b37b` | Cwd et commandes de migration visibles | Le modèle affirme une cause à partir du cwd et du code, sans stderr collecté |
| `d9877899` | Sujet CI précisé par le corps des commits | Invente dépôt propre/branche à jour et reprend la PR #28 ; annotation auparavant satisfaite perdue |
| `eb652ce9` | Détails du hardening et nombreuses transitions conservés | Dirty ancien et absence supposée de merge/push deviennent des restes |
| `eef4956b` | Détails de documentation retrouvés | Validation llm_max_tokens conservée, mais propagation du push manquant, d'un message ancien et de D6 |

Ces écarts ne sont pas corrigés par une nouvelle interdiction de formulation.
Pour chaque famille :

- **Collecte absente** : pas de stderr, fichiers d'un commit, état des PR ou
  du distant. Le modèle ne peut pas confirmer ces états.
- **Projection antérieure déficiente** : ordre et commandes perdus ; désormais
  présents et vérifiés par les cas minimaux.
- **Interprétation erronée malgré l'entrée** : commit ⇒ propre, branche ⇒ non
  fusionnée, absence de collecte ⇒ tâche ouverte, notification ⇒ non commité.
  Les dates, références et mentions d'incertitude sont présentes ; le modèle
  les dépasse encore. Plus de contenu ne suffit pas à mieux interpréter.

Les anciens jugements de dogfooding sur 13 autres fiches ne sont pas
réutilisés comme notes des 14 sessions ici. Ils éclairent les mêmes familles
D1/D3/D5/D6 ; seuls les quatre fichiers d'attentes correspondent directement.

## 10. Taille et performance

Totaux sur les 14 sessions, détail et méthode dans
[`measurements.json`](measurements.json). Caractères Unicode du JSON compact ;
tokens mesurés par le tokenizer du modèle **sur son prompt final avec template**.
Les durées du provider excluent le chargement des poids ; un seul passage par
condition, sans prétention de benchmark statistique ou de causalité isolée.

| Mesure | Avant | Après |
| --- | ---: | ---: |
| JSON, caractères | 102 692 | 167 454 (+63,1 %) |
| Listes de sources dans le prompt, caractères | 73 056 | 0 |
| Champs de chemins, caractères | 8 412 | 30 487 |
| Champs descriptifs de session, caractères | 12 706 | 45 171 |
| Système + JSON, caractères, hors template | 252 730 | 244 664 (−3,2 %) |
| Prompt final, tokens mesurés | 111 897 | 80 858 (−27,7 %) |
| Tokens d'entrée médians | 6 443,5 | 4 572 |
| Tokens de sortie | 3 630 | 5 140 |
| Durée de génération cumulée | 1 352,6 s | 1 053,1 s (−22,1 %) |
| Durée médiane | 79,4 s | 57,9 s |

La plus grosse entrée initiale `3cabaefb` passe de 23 013 à 4 255 tokens
(et de 248,0 à 54,6 s). À l'inverse, `eb652ce9`, riche en commits et fichiers,
passe de 13 072 à **23 386 tokens** (142,8 à 272,0 s) : la chronologie complète
coûte davantage. Aucun dépassement du plafond de 30 000 n'a eu lieu ici.
Les JSON grandissent souvent ; ce chantier n'est pas une optimisation de taille
au prix de la perte de faits. Les changements simultanés de projection,
annexe, bruit historique et prompt empêchent d'attribuer le gain à un seul facteur.

## 11. Code supprimé ou simplifié

Suppression de `_terminal_facts`, `_file_facts`, `_bounded`, des limites
historiques de la vue détaillée, de ses listes contradictoires, de la copie
intacte avec UUID, et des deux oracles lexicaux D5/D6 et leurs tests dédiés.
La politique fichiers a été extraite du collecteur pour être partagée sans
charger le watcher dans l'API. Les tests protègent désormais l'ordre, les
résultats observés, l'incertitude et les liens de provenance.

Le nombre d'étapes de projection reste comparable ; leur contrat devient
explicite et conserve l'information. Un propriétaire prépare les observations.
Pas de nouveau manager, cache, base ou moteur de règles. `append_event()` ne
change pas et ne reconstruit toujours aucune session à l'écriture.

Sur les 14 fichiers Python d'exécution concernés : 4 908 lignes avant,
4 965 après (**+57**), hors tests et documentation. Ce n'est donc
pas une réduction nette de lignes : l'ordre, les intervalles, la provenance
et leur validation remplacent des suppressions d'information implicites.

## 12. Limites restantes

La projection ne connaît pas le contenu des fichiers, la sortie des commandes,
les fichiers inclus dans un commit, la réussite distante du push, les merges
ou l'avancement réel d'un agent. Une demande initiale peut être vieille et
un précédent résumé peut déjà être faux. Les horloges observées et l'ordre
local enregistré ne deviennent pas une preuve d'ordre causal global.

Le modèle reste trop affirmatif, notamment sur `open`. **Le résultat ne justifie
pas une activation automatique du prompt v4 en dogfooding.** La configuration
personnelle n'a pas été touchée. Les lecteurs v2 restent compatibles ; toute
adoption du nouveau contrat nécessite les composants cohérents et le prompt v4.

GitNexus a servi à l'analyse d'impact avant les modifications. La surface
contexte/ingestion est à risque élevé/critique, annoncée avant intervention.
Le contrôle final couvre 89 fichiers modifiés, 141 symboles et 45 processus
affectés, avec un risque critique. Ses processus sont bornés et l'index
signale des flux non explorés ; les
recherches de consommateurs et tests complètent le graphe, sans faire passer
une absence de lien pour une preuve d'absence d'impact. Aucun commit ni push
n'a été effectué.

## 13. Prochaine frontière

Fiabiliser **l'interprétation de reprise** : distinguer dernière observation,
état actuel et information non collectée ; mesurer la pertinence de chaque
point ouvert et empêcher la propagation d'interprétations anciennes. Les
contre-exemples sont désormais archivés avec leurs observations. Ce chantier
suivant n'a pas été implémenté ici ; ni mémoire sémantique, ni agent, ni collecte
supplémentaire n'ont été ajoutés.
