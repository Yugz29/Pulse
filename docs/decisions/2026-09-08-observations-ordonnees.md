# Observations ordonnées entre Core et Intelligence

**Statut historique du deuxième chantier.** La projection Core reste en vigueur ;
le contrat Intelligence et la politique de reprise sont désormais décrits dans
[le troisième chantier](2026-09-08-reprise-fondee.md).

Date : 2026-09-08. Décision et implémentation du deuxième chantier autorisé sur
Core et Intelligence. Le gel fonctionnel est levé pour cette frontière précise.
**Statut : représentation implémentée et testée ; qualité de `open` non validée
pour activation en dogfooding.** Aucun service personnel n'a été modifié.
Le rejeu complet a été retiré du dépôt le 2026-09-09 (voir
[`docs/audits/README.md`](../audits/README.md) et l'historique Git).

## Problème constaté

La reconstruction unique fonctionnait déjà. Mais `_current_session_view`
transformait ses événements en listes indépendantes : premiers 20 fichiers
par catégorie, premiers 10 tests/erreurs distincts, 5 applications, commits
sans date au hash court et message réduit à sa première ligne. `session_input`
recopiait cette vue entière, UUID sources compris. Le modèle recevait les deux
résultats d'un test sans leur ordre, et des identifiants sans leur contenu.

La référence vérifiée est le commit `e00dd0e`. Les consommateurs trouvés dans
le dépôt sont Intelligence, les routes statut/accueil et les tests. Aucun
consommateur extérieur des anciennes listes n'a été identifié. Le statut ne
lit que durée, projets et ouverture ; le journal conserve son propre rendu.
Le schéma d'API change explicitement, au lieu de changer silencieusement le
sens des anciennes listes. Aucune requête réseau de découverte n'a été faite.

## Chaîne actuelle

```text
Événements canoniques append-only
  → reconstruction unique v3
  → session de travail (identité inchangée)
  → project_work_observations, version 1, sans I/O
      ├── observations chronologiques + dernières références observées
      │     → /context et /context/sessions, schéma 3
      │     → entrée Intelligence 2 → prompt v4 → interprétation
      └── sources compactes → événements exacts, hors du prompt
```

Une observation est un enregistrement factuel : commande et code de sortie,
notification de fichier, commit et son message, activation d'application.
Un message de commit est une déclaration enregistrée, pas une vérification de
son contenu. « Le problème est résolu » reste une interprétation du modèle.

## Contrat Core

`current_session` et chaque session de `/context/sessions` portent : identité,
label, sources exhaustives, version de reconstruction, bornes, durée, ouverture,
nombre d'activités, projets, workspace et `observations`.
Les anciennes clés de session `files`, `terminal`, `git`, `apps`, `signals`
sont remplacées. Les autres blocs de contexte restent présents. Le bloc Git
du workspace reste une vue d'affichage, distincte des observations datées.

`observations` contient :

- `version: 1`, `time_origin` UTC et `time_unit: seconds`. Les offsets conservent
  les microsecondes ; un démarrage de commande peut précéder l'origine.
- `timeline` : références `o1`, `o2`… ordonnées par date puis numéro de ligne
  enregistré. Les commandes et commits sont conservés, sans coupe arbitraire.
- Pour une commande : texte complet déjà masqué, cwd, début, code de sortie
  global, `exit_scope: whole_command`, reconnaissance prudente d'une commande
  de test simple, action Git simple éventuelle et snapshot Git persisté.
  Un code de sortie composé n'est jamais attribué à chaque sous-commande.
- Pour un fichier : chemin relatif au workspace connu, sinon absolu ; suites
  de transitions avec premier/dernier instant et nombre de notifications.
  Des notifications identiques sont fusionnées par fichier entre deux commandes
  ou commits. Une transition différente reste distincte. Deux fichiers peuvent
  avoir des intervalles qui se chevauchent : aucun ordre total n'est inventé.
- Pour un commit : hash et message complets, date, dépôt et branche observés.
- `applications` : nombres et intervalles d'activation, références `app:1`… ;
  aucun travail ou intention n'est déduit de l'application active.
- `last_observed.commands` : dernière référence par commande exacte et cwd.
  `files` : dernière série par chemin absolu. `git` : dernière référence de
  branche, de dirty et de commit, séparément par dépôt. Les valeurs et dates
  restent dans les observations citées. Aucun commit ne remet dirty à false.
- `coverage` : compte des événements omis et informations non collectées
  (sortie terminal, fichiers des commits, état distant du push).
- `sources` : référence vers la liste des event_id exacts qui l'étayent.

La politique de bruit fichiers est partagée avec le collecteur dans
`file_policy.py`. Elle ne change pas la collecte, mais écarte de la projection
les anciens fichiers d'index/cache qu'il ignore déjà aujourd'hui. Un chemin
historique extérieur au workspace déclaré garde une attribution inconnue ;
il n'est pas assimilé à du bruit. Aucun événement n'est supprimé.

Les compteurs de sessions récentes utilisent la même projection : nombre
d'exécutions en échec, dont commandes de test simples ; interruptions 130 et
résultats inconnus exclus. Des échecs répétés sont désormais comptés comme
des exécutions distinctes, et les fichiers techniques ignorés ne comptent plus.

## Workspace et annexes

La lecture du dernier agent sélectionne le plus récent compatible avec le
workspace résolu ou d'attribution inconnue. Un agent récent d'un autre projet
ne masque donc plus un agent compatible plus ancien. Intelligence vérifie à
nouveau le workspace de la session qu'elle résume et le chevauchement temporel.
L'annexe expose explicitement `same_workspace` ou `unknown`. Elle décrit une
demande initiale, pas un accomplissement ni un reste certain.

Le précédent résumé reste une interprétation, pas une observation. Sa
pertinence et la propagation de ses erreurs ne sont pas résolues par ce chantier.

## Intelligence et identité

Intelligence sélectionne les champs visibles ; elle ne reconstruit pas les
sessions ni leurs observations. La liste exhaustive de sources et les tables
de correspondance ne sont pas sérialisées dans l'entrée du modèle.
Le schéma de sortie `reprise`/`structured` et les trois natures de `open`
restent ceux de v3. Les preuves nouvelles sont `oN` et `app:N`.

Les deux filtres lexicaux D5/D6 sont supprimés. Leur hypothèse « sans commit
observé, fichier non commité » n'était pas justifiée ; ils pouvaient aussi
rejeter une affirmation étayée par un nouveau snapshot Git. Le validateur
contrôle forme, références et rôles des annexes, sans prétendre prouver une
interprétation par la présence d'une référence. Les erreurs sémantiques sont
mesurées dans le rejeu, pas rendues invisibles par un score de JSON valide.

L'identité de session et `reconstruction_version: 3` ne changent pas. Le prompt
v4 donne aux nouvelles générations une identité de résumé distincte des v1–v3,
sans écraser leurs événements. `input_hash` reste le hash de l'entrée exacte.
Toute future modification sémantique de projection devra versionner la
projection et l'identité de génération (nouveau prompt), pas réutiliser v4.

Les résumés nouveaux conservent `observation_version` et
`observation_sources` dans leurs détails : sources des faits et des annexes
connues réellement sélectionnées. Core valide les clés fermées, les types et
l'absence de texte sensible non masqué dans les identifiants, sans les réécrire.
Les UUID d'annexes exposés par Core restent eux aussi hors du modèle.

## Historique, livraison et adoption

Aucune base utilisateur ni archive de transcript n'est modifiée. Les anciennes
vues Core v2 sont lisibles via une compatibilité ciblée `legacy_aggregates`,
avec chronologie explicitement indisponible. Elles ne sont pas présentées
comme des faits ordonnés. Les résumés stockés et les payloads pending anciens
se relisent et se rejouent tels quels, sans modèle et sans adaptation destructive.

La collecte, l'outbox, les permissions et les règles de masquage restent
indépendantes d'Intelligence. La projection ne lit ni Git ni le disque et
n'envoie rien sur le réseau. Les évaluations ont utilisé MLX hors ligne.

L'adoption du nouveau contrat demande une mise à jour coordonnée de Core et
Intelligence. Une configuration qui épinglait v1–v3 doit choisir v4 pour
une génération nouvelle ; le provider refuse explicitement leur usage avec
l'entrée 2. La lecture et le rejeu des anciens résumés n'en dépendent pas.
Le défaut de code est v4 ; aucune configuration personnelle n'a été changée.
Compte tenu des régressions mesurées sur `open`, ne pas confondre ce défaut de
contrat avec une validation produit du prompt ou une activation du service.
