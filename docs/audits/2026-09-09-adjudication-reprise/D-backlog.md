# Trous de collecte — registre agrégé des réponses D

**Décisions du 2026-09-11 (après lecture de `SYNTHESE.md`).** Trois entrées vont dans `core/TODOS.md` : pushs et merges (item `pre-push` élargi aux merges, P3 → P2), `pulse note` (nouveau, P2), PostToolUse (reste P3, avec ses fiches). Les 22 autres trous restent ici. Frontières confirmées : contenu des sessions d'agent (rétention inchangée ; PostToolUse donne les commandes sans le contenu), navigateur (pas d'URL). La CI distante n'est pas une frontière : elle reste en bas du registre.

Registre alimenté fiche par fiche pendant l'adjudication (commencée le
2026-09-10). Chaque réponse D d'une fiche est réduite à un ou plusieurs
trous nommés ; le compteur dit combien de fiches citent le trou. Règle
fixée par l'utilisateur à la fiche 13 : **ce qui revient souvent devient
prioritaire, ce qui revient une fois reste en note. Aucune implémentation
avant la fin des 18 fiches ; la liste consolidée décide de l'ordre.**

Une frontière n'est pas un trou : elle est listée pour mémoire et ne
reçoit pas de piste.

## Trous

| Trou | Fiches | Piste identifiée (à confronter aux autres fiches) |
| --- | --- | --- |
| Pushs et merges non observés (D5) | 13, 14, 04, 01, 02, 05, 08, 09, 10, 12, 16, 17, 18 | Hook pre-push → `git_push` (déjà P3 dans `core/TODOS.md`) ; observation locale des merges via le reflog ou les hooks post-merge / post-checkout. Pas d'appel à GitHub : on observe le moment où main avance sur la machine. |
| Déclarations et jugements faits en conversation, hors machine | 13, 14, 04, 08, 09, 16, 17 | Commande type `pulse note "…"` qui émet un `recorded_statement` horodaté, pour capter ce qui se décide hors Claude Code. |
| Contenu des commits non observé (seulement le titre) | 13, 01, 02 | `git_commit` porte la liste des fichiers du commit et le corps complet du message, sans lire le contenu des fichiers (`private_files` intact). |

| Résultats des commandes non observés (seulement la commande et son code) | 14, 03, 02, 06 | À confronter : chiffres d'eval, sorties de `show`. Aucune piste retenue encore. |
| Config hors workspace observé (`~/.pulse_intelligence/config.toml`) | 14, 18 | Aucune piste retenue encore. |
| Devenir des modifications après la fin de session (committées ou non) | 14 | Aucune piste retenue encore ; lié au trou « contenu des commits ». |

| Vérifications dans le navigateur sans trace exploitable | 03, 06, 07 | **Frontière confirmée le 2026-09-11** : pas d'URL. |
| Sessions d'agent antérieures au hook SessionEnd (fin août) | 03 | Limite historique du corpus, pas un trou actuel : ne pas compter dans la priorisation. |

| Bloc de commandes chaînées : un seul code global, sous-commande fautive inconnue | 04 | Aucune piste retenue encore. |
| Nature d'un chemin non connue (archive de départ dans Downloads) | 04 | Aucune piste retenue encore. |
| Dépôt hors périmètre du watcher : aucun événement de fichier | 04 | Trou de périmètre, pas de collecte : vérifié, 0 événement de fichier dans la capture du 22 août. |

| Commandes exécutées par l'agent (outil Bash de Claude Code) invisibles au hook shell | 06, 08, 09, 10, 15 | PostToolUse, déjà P3 dans `core/TODOS.md`. Fiche 06 : c'est presque sûrement là que la migration est passée. |
| Bascule de branche indistinguable d'une édition (rafale de fichiers au checkout) | 05, 10 | Déjà en `core/TODOS.md` : état net par chemin. |
| Session d'agent triviale (`/login`, `/model`) prise pour du travail | 05, 06, 11 | Aucune piste retenue encore ; lié à D3. |
| Intention non écrite, dans la tête de l'utilisateur | 01 | Pas un trou de collecte : rien à observer. Rejoint `pulse note` si l'utilisateur veut la déposer. |

| Rebase indistinguable de nouveaux commits (messages répétés sous des hashes différents) | 09, 17 | Reflog ; rejoint la piste « merges via reflog / hooks ». |
| Événements applicatifs d'une app à soi (DevNote : « une note a été écrite ») | 07 | Le chantier jetons API DevNote sert à ça ; Pulse comme outil optionnel de DevNote. |
| Lancement d'un processus hors shell (alias, GUI) | 07 | Aucune piste retenue encore. |

| Contenu de la session d'agent au-delà du premier prompt | 06, 11, 17 | **Frontière confirmée le 2026-09-11** : rétention inchangée, PostToolUse donnera les commandes sans le contenu. |
| Résultats de CI distants (GitHub Actions) | 12 | Pas une frontière (décision du 2026-09-11) ; reste en bas du registre, aucune piste. |
| Agent externe (Codex/Astral) non attribué comme acteur | 15, 18 | Lié à « acteur inversé » : le modèle écrit « l'agent » ou « l'utilisateur » sans base. |
| Fragmentation d'un chantier en tranches de session | 15 | Déjà P2 dans `core/TODOS.md`. Chaque tranche ressemble à « des fichiers modifiés ». |
| Déplacement (`git mv`) vu comme création + suppression | 16 | Lié à « état net par chemin ». |
| Troncature des listes de fichiers à 20, masquant les fichiers travaillés | 16, 17 | Les 20 fichiers déplacés remplissent la liste ; les 11 modifiés, dont AGENTS.md et VISION, passent derrière. |

| Contenu des fichiers non lu (note de décision, dogfooding.md) | 15, 18 | Frontière : Pulse ne lit pas les fichiers. Confirmée comme frontière en synthèse. |

## Frontières à garder

| Frontière | Fiches |
| --- | --- |
| Secret hors repo (`~/.config/pulse/llm.env`) | 13 |
| Cadre du projet hors machine (intranet, énoncé de tâches, contrainte « à trois ») | 03, 04 |

## Observations transversales

- Fiche 04 : **D3 sous sa forme pure.** Une session d'agent de 17 s en fin de session devient le cadre de 28 min de travail manuel : le `doing` inverse l'acteur (« l'agent a passé la session à… ») et efface un projet entier (DevNote). D3 ne contamine pas seulement `open`, il réécrit `doing` et `stopped_at`.
- Fiche 04 : la règle de résolution v5 fonctionne quand la commande est strictement identique (code 1 de 21:39 résolu par le 0 de 21:49) et rate quand elle est corrigée (fiche 03).
- Fiche 04 : une décision de bascule de projet prise en conversation dans l'heure rend faux un résumé pourtant parfait. L'argument le plus fort pour `pulse note`.

- Fiche 03 : **résolution par correction invisible à la règle v5.** Un code 0 ultérieur n'établit une résolution que pour la même commande exacte dans son cwd ; une commande relancée avec un chemin corrigé n'est jamais « la même ». Les deux `git add` en 128 restent donc en `open` alors qu'un add corrigé, un commit et un push suivent. Va revenir sur toutes les sessions où une faute de frappe est corrigée.
- Fiche 03 : quand aucune information observée ne manque, ce qui manque est de l'interprétation (`ls -R src` = ouverture de la Task 1). Sous v5 le modèle ne doit pas le deviner : trou de collecte, pas défaut du résumé.

- Fiche 14 : « non commises » dans `stopped_at` est une affirmation que la vue ne permet pas ; la formulation fondée serait « modifiées après le dernier commit ». Le modèle a eu raison de ne pas reporter le point hérité de `previous_summary` (résolu avant la session) : C4 jugé nuisible.
- Fiche 14 : le `doing` ne couvre que la dernière moitié de la session (prompt v2) et rate la clôture de l'étape 3 pourtant dans la vue (commits de 01:29 et 01:38).

- Fiche 13 : l'utilité d'un résumé dépend du délai et du nombre de
  bascules de projet, pas seulement de son contenu. Dès le lendemain il
  est utile ; dans la journée même, seulement après une bascule ou une
  longue inactivité.
- Fiche 01 : `stopped_at` invente « après l'activation de l'environnement virtuel », absent de la vue. Détail inventé, à compter comme tel.
- Fiche 02 : le code 130 d'un `npm run dev` est un arrêt normal au clavier, pas un échec. Une citation réécrite avec des `&&` absents n'est plus une citation.
- Fiche 05 : D3 en version légère. Une annexe agent réduite à `/login` devient « l'agent a finalisé » et « après avoir lancé l'agent Claude ».
- Fiche 06 : la base et les logs bougent après les échecs de migrate : le dernier fait n'est pas un échec terminal. `blockers` est probablement faux. Le modèle prend le dernier diagnostic terminal pour la dernière activité.
- Fiche 07 : **filtre de candidature.** 37 minutes, zéro commande de travail, quatre événements ; la session passe le seuil de 30 activités parce que les activations d'apps comptent. Le filtre devrait peut-être exiger au moins une commande ou un fichier de code. La bonne sortie ici est « rien à reprendre » ; les intents inventés (« consulter les journaux ») sont nuisibles et `confidence: medium` trop haut.
- Fiche 08 : sortie juste, aucune correction. Le `stopped_at` évite « non commises ». Ce qui manque est hors vue (regel de Core, merge) ou une lecture (VERSION touché = jalon).
- Fiche 09 : **deux fils, un seul résumé.** Le `doing` rate la spec v2 du pas 3 poussée sur main, qui n'est pas du hardening. Une décision de périmètre déclarée dans un commit (auth reportée) est exactement le `recorded_statement` visé par v5, et elle est absente.
- Fiche 10 : **quand le commit est riche, le résumé doit le suivre.** Aucune fausse affirmation, mais la condition de reproduction et la limite du correctif, présentes dans le message, sont jetées.
- Fiche 11 : **acteur inversé, troisième occurrence** (avec 04 et 05). Un `ls` passé par le shell de l'utilisateur devient « l'agent a effectué ». Le modèle attribue l'acteur sans base observée.
- Fiche 12 : D1 passe. « Non commises » de `previous_summary` n'est pas repris ; sortie juste, aucune correction.
- Fiche 15 : **D1 dans sa forme la plus grave sous v5** : tout le résumé est celui d'une autre session (901a5aaf), `central_files` vides avec 27 fichiers dans la vue. v6 corrige les deux. Ni v5 ni v6 ne voient la décision enregistrée (note créée) ni la frontière Core touchée sous gel.
- Fiche 16 : **le cas le plus net de `open` vide.** « 14 fiches à compléter » est un point ouvert déclaré dans le message du dernier commit, le `recorded_statement` parfait, et `open` est vide sous v5 comme sous v6. `central_files` rempli par des fichiers déplacés dans les deux versions.
- Fiche 17 : **le contenu du lot pris pour le travail de la session.** Sécurisation et découpage (snapshot WIP, rebase, PR par couche) rendus comme « refonte majeure » (v5) ou « développement » (v6). v5 fait du premier commit le point d'arrêt ; v6 cite l'avant-dernier. Huit doublons de rebase sur 21 commits, sans le dire.
- Fiche 18 : **deux fils, un seul résumé, troisième occurrence** (avec 04 et 09). Cinq fichiers Core modifiés sans commit, absents des deux versions. La seule information sauvée hors vue (v3 activé, config hors workspace) l'est par le message de commit.
