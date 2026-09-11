# Synthèse de l'adjudication — 18 fiches répondues le 2026-09-10

Rédigée le 2026-09-11 à la demande de l'utilisateur, après ses réponses
aux 18 fiches. **Rien n'est implémenté, activé ni commité.** Trois
parties : le registre D consolidé, les observations transversales hors
collecte, le verdict v5 contre v6 avec la question de `open` vide.

Provenance des réponses : aucune des 18 sessions n'a été répondue de
souvenir spontané. Quatorze le sont depuis une reconstruction externe
(chats avec Fable, notes de l'époque, TODOS), quatre (01, 02, 07, 10 pour
partie) depuis la seule lecture de la vue. L'aveugle A/B a été abandonné
après les quatre premières fiches pour cette raison (note de protocole
dans `FICHES.md` et le JSON). La « vérité terrain » produite ici est donc
une vérité reconstruite, à ne pas confondre avec un souvenir.

## 1. Registre D consolidé : trous de collecte par fréquence

Source : [`D-backlog.md`](D-backlog.md), rempli fiche par fiche. Le
compteur est le nombre de fiches qui citent le trou. Statut : **TODO
Core** si un item de `core/TODOS.md` le couvre déjà, **nouveau** sinon,
**frontière** si l'utilisateur a dit de ne pas le combler. Règle fixée à
la fiche 13 : ce qui revient souvent devient prioritaire, ce qui revient
une fois reste en note ; l'ordre est décidé par cette liste, après
lecture, pas avant.

| # | Trou | Fiches | Statut | Piste notée pendant l'adjudication |
| --- | --- | --- | --- | --- |
| 13 | Pushs et merges non observés (D5) | 13, 14, 04, 01, 02, 05, 08, 09, 10, 12, 16, 17, 18 | **TODO Core** P3 pour le push (hook `pre-push` → `git_push`) ; **nouveau** pour les merges | Observation locale des merges via le reflog ou les hooks post-merge / post-checkout. Pas d'appel à GitHub : on observe le moment où main avance sur la machine. |
| 7 | Déclarations et jugements faits en conversation, hors machine | 13, 14, 04, 08, 09, 16, 17 | **nouveau** | `pulse note "…"` qui émet un `recorded_statement` horodaté. Cas le plus fort : fiche 04, bascule de projet décidée dans l'heure, qui rend faux un résumé pourtant parfait. |
| 5 | Commandes de l'agent (outil Bash de Claude Code) invisibles au hook shell | 06, 08, 09, 10, 15 | **TODO Core** P3 (hook PostToolUse) | Fiche 06 : c'est presque sûrement là que la migration est passée. Tests de l'agent invisibles dans 08, 09, 10, 15. |
| 4 | Résultats des commandes non observés (commande et code seulement) | 14, 03, 02, 06 | **nouveau** | Chiffres d'eval, sortie de `show`, sortie de `ls -R`, cause d'un code 2. Aucune piste retenue. Le hook `PostToolUse` couvrirait la part agent, pas le shell de l'utilisateur. |
| 3 | Contenu des commits non observé (titre seulement) | 13, 01, 02 | **nouveau** | `git_commit` porte la liste des fichiers du commit et le corps complet du message, sans lire le contenu des fichiers. Rejoint « devenir des modifications après la session » (14). |
| 3 | Vérifications dans le navigateur sans trace exploitable | 03, 06, 07 | **nouveau**, frontière probable | URL de Safari, test d'UI. Aucune piste ; à trancher comme frontière ou non. |
| 3 | Session d'agent triviale (`/login`, `/model`) prise pour du travail | 05, 06, 11 | **nouveau**, côté entrée Intelligence | Lié à D3. Une annexe de 17 secondes ou un slash-command devient l'acteur ou le cadre de la session. v6 retire l'annexe, ce qui règle le symptôme sans qualifier la session d'agent. |
| 3 | Contenu de la session d'agent au-delà du premier prompt | 06, 11, 17 | **frontière** (rétention voulue) | Le transcript archivé n'est pas ingéré, seul le premier prompt l'est. À confirmer comme frontière ; le TODO Core P3 « segments de reprise pour agent_session » est la version bornée. |
| 2 | Config hors workspace (`~/.pulse_intelligence/config.toml`) | 14, 18 | **nouveau** | `prompt_version` invisible. Fiche 18 : sauvé cette fois par le message de commit. |
| 2 | Bascule de branche indistinguable d'une édition | 05, 10 | **TODO Core** P3 (état net par chemin) | Rafale de fichiers au checkout comptée comme des modifications. |
| 2 | Rebase indistinguable de nouveaux commits | 09, 17 | **nouveau** | 21 commits dont 8 doublons (17). Reflog ; rejoint la piste merges. |
| 2 | Troncature des listes de fichiers à 20 | 16, 17 | **nouveau**, côté Core `/context` | Les 20 fichiers déplacés remplissent la liste, les fichiers travaillés passent derrière (17 : aucun fichier Intelligence visible alors que six commits les concernent). |
| 2 | Agent externe (Codex / Astral) non attribué comme acteur | 15, 18 | **nouveau** | Lié à « acteur inversé » (partie 2). |
| 2 | Contenu des fichiers non lu | 15, 18 | **frontière** | Pulse ne lit pas les fichiers ; note de décision, `dogfooding.md`. |
| 1 | Devenir des modifications après la fin de session | 14 | **nouveau** | Lié à « contenu des commits ». |
| 1 | Bloc de commandes chaînées : un seul code global | 04 | **nouveau** | Sous-commande fautive inconnue. |
| 1 | Nature d'un chemin (archive dans Downloads) | 04 | **nouveau** | Note. |
| 1 | Dépôt hors périmètre du watcher | 04 | périmètre, pas collecte | Vérifié : 0 événement de fichier dans la capture du 22 août. |
| 1 | Événements applicatifs d'une app à soi (DevNote) | 07 | **nouveau** | Le chantier jetons API DevNote sert à ça. |
| 1 | Lancement d'un processus hors shell | 07 | **nouveau** | Note. |
| 1 | Fragmentation d'un chantier en tranches de session | 15 | **TODO Core** P2 | Chaque tranche ressemble à « des fichiers modifiés ». |
| 1 | Déplacement `git mv` vu comme création + suppression | 16 | **TODO Core** P4 (kind `renamed`) | |
| 1 | Résultats de CI distants | 12 | **frontière** probable | Pas d'appel à GitHub. |
| 1 | Sessions d'agent antérieures au hook SessionEnd | 03 | limite historique du corpus | Ne pas compter. |
| 1 | Intention non écrite, dans la tête de l'utilisateur | 01 | pas un trou | Rejoint `pulse note` si l'utilisateur veut la déposer. |

Frontières nommées comme telles par l'utilisateur : le secret hors repo
(`~/.config/pulse/llm.env`, fiche 13) et le cadre du projet hors machine
(intranet, énoncés, contrainte « à trois » ; fiches 03, 04).

Lecture : trois trous dominent (pushs et merges, déclarations hors
machine, commandes de l'agent). Deux sont déjà en P3 dans `core/TODOS.md`
(push, PostToolUse) ; le troisième, `pulse note`, est nouveau et c'est le
seul qui capte une décision prise hors de la machine, la classe d'erreur
la plus grave observée (fiche 04). Les merges, cités 13 fois avec les
pushs, n'ont pas d'item Core aujourd'hui.

## 2. Observations transversales hors collecte

Défauts qui ne viennent pas d'une information manquante : l'entrée les
contenait, le résumé les a mal rendus. Numérotées pour la suite ; les
lettres D1 à D6 restent celles du journal de dogfooding.

| # | Observation | Fiches | Ce que ça montre |
| --- | --- | --- | --- |
| T1 | **Commande corrigée jamais résolue.** La règle de résolution exige la même commande exacte dans le même cwd ; une commande relancée avec un chemin corrigé n'est jamais « la même ». Les échecs restent en `open` alors qu'un add corrigé, un commit et un push suivent. | 03 (raté), 04 (la règle marche quand la commande est identique) | Défaut de `command_outcomes`, pas du modèle. Reviendra sur toute session où une faute de frappe est corrigée. |
| T2 | **Filtre de candidature.** 37 minutes, zéro commande de travail, quatre événements ; la session passe le seuil de 30 activités parce que les activations d'apps comptent. | 07 | Exiger au moins une commande ou un fichier de code avant de résumer. La bonne sortie ici est « rien à reprendre ». |
| T3 | **Deux fils, un seul résumé.** Deux projets ou deux chantiers dans la même session ; le résumé n'en garde qu'un. | 04 (DevNote effacé), 09 (spec v2 sur main effacée), 18 (cinq fichiers Core hors commit), 14 (clôture de l'étape 3 ratée) | Un résumé multi-fils qui efface un fil est faux, pas incomplet. |
| T4 | **Acteur inversé.** « L'agent a effectué… » pour un `ls` passé par le shell de l'utilisateur, ou pour 28 minutes de travail manuel cadrées par une annexe de 17 secondes. Symétriquement, un agent externe (Astral) n'est jamais nommé. | 04, 05, 11, 17 ; 15, 18 | Le modèle attribue l'acteur sans base observée. v6 retire l'annexe et supprime les cas 04/05/11 par construction, sans régler l'attribution. |
| T5 | **Commit riche appauvri.** Le message de commit contient le déclencheur, la limite, une décision de périmètre ; le résumé les jette. | 10 (condition de reproduction), 09 (auth reportée, Swift hors CI), 01 (tag exact) | Quand le commit est riche, le résumé doit le suivre. |
| T6 | **`recorded_statement` qui ne capte pas un point ouvert déclaré en commit.** « 14 fiches à compléter » est une sous-chaîne littérale du dernier message de commit ; le validateur l'aurait acceptée ; `open` est vide sous v5 et v6. | 16 (cas le plus net), 13 (« exposer les paramètres retirés »), 09 (auth reportée) ; contre-exemple 14 (D1 à juger : capté) | Voir partie 3. |
| T7 | **Détails inventés.** « après l'activation de l'environnement virtuel » absent de la vue ; intents « consulter les journaux » sans base ; « sans rapport final de vérification » ; « commande non trouvée » comme lecture d'un 127. | 01, 07, 17, 06 | Faible volume, mais chaque cas est une affirmation sans observation. |
| T8 | **Dernier diagnostic terminal pris pour dernière activité.** Base et journaux bougent après les échecs de `migrate` ; le résumé s'arrête aux échecs, `blockers` est probablement faux. | 06 | Le point d'arrêt doit être le dernier fait, pas le dernier échec. |
| T9 | **Checkout, déplacement, rebase pris pour du travail.** Rafale de fichiers au changement de branche, `git mv` en 20 créés + 20 supprimés, 8 commits réémis. `central_files` rempli par des fichiers déplacés. | 05, 10, 16, 17 | Trous de collecte (partie 1) qui deviennent des défauts de résumé. |
| T10 | **D1 : recopie de `previous_summary`.** 6/11 sous v5 au jour 5 ; dans le corpus, 15 est le cas le plus grave (tout le résumé est celui d'une autre session, `central_files` vides avec 27 fichiers). v6 corrige 15, 16, 17. D1 passe sur 12 et 14 sous v5. | 15, 16, 17 ; 12, 14 | Réglé par v6 par retrait de l'annexe, pas par meilleure réévaluation. |
| T11 | **Point d'arrêt mal choisi dans une session à commits.** v5 cite le premier commit (le snapshot WIP) ; v6 cite l'avant-dernier ; 21 commits, aucun des deux ne prend le dernier. | 17 | Le dernier commit de la vue est une ancre disponible et non prise. |
| T12 | **La règle de prudence est parfois bien appliquée.** « main, propre » sans conclure au merge (05), pas de « non commises » (08), D1 non reporté (12, 14 C4), question PR #28 en intent et non en fait (11). | 05, 08, 11, 12, 14 | À préserver : ce sont les comportements que l'utilisateur a jugés « exactement le niveau voulu ». |

Deux remarques de l'utilisateur qui dépassent les fiches. L'utilité d'un
résumé dépend du délai et du nombre de bascules de projet, pas seulement
de son contenu (fiche 13) : dès le lendemain il est utile, dans la
journée même seulement après une bascule ou une longue inactivité. Et
une session d'usage d'une app à soi (07) n'est pas un chantier : la
sortie juste est de le dire.

## 3. Verdict v5 contre v6, et la question de `open` vide

### 3.1 Fiche par fiche

Les fiches 01 à 14 n'ont qu'une sortie v5 (replay du 8 septembre) ;
aucun rejeu v6 n'a été fait sur ce corpus. Les fiches 15 à 18 ont le v5
émis en production le 9 au soir et un dry-run v6 (17 et 16 aussi réémis
en v6 par le lot launchd du 10 au matin, texte identique au dry-run).
Verdict d'après les jugements C et E de l'utilisateur : **juste** (rien
de faux, manques hors vue seulement), **partiel** (manque une
information présente dans la vue), **faux** (affirme quelque chose que
la vue contredit ou efface un fil).

| Fiche | v5 | v6 | Défaut principal |
| --- | --- | --- | --- |
| 01 | partiel | — | Tag exact absent ; « environnement virtuel » inventé (T7). |
| 02 | partiel | — | GraphView.tsx absent ; `open` réécrit avec `&&` ; 130 présenté comme échec. |
| 03 | partiel | — | Deux `git add` corrigés restent en `open` (T1). Le reste juste. |
| 04 | **faux** | — | DevNote effacé (T3), acteur inversé (T4), trois échecs dépassés en `open`. La pire des 14. |
| 05 | partiel | — | « L'agent a finalisé » (T4, D3 léger). « main, propre » bien géré (T12). |
| 06 | partiel | — | `blockers` probablement faux, dernier échec pris pour dernière activité (T8). |
| 07 | partiel | — | Intents inventés (T7) ; n'aurait pas dû être résumée (T2). |
| 08 | **juste** | — | Aucune correction. |
| 09 | partiel | — | Spec v2 sur main effacée (T3) ; deux décisions de périmètre jetées (T5, T6). |
| 10 | partiel | — | Déclencheur et limite jetés (T5). Rien de faux. |
| 11 | partiel | — | « L'agent a effectué » (T4). Question PR #28 bien placée (T12). |
| 12 | **juste** | — | D1 non reporté (T12). |
| 13 | partiel | — | Consigne d'action (« exposer les paramètres retirés ») absente (T6) ; plan en 4 PR hors vue. |
| 14 | partiel | — | Clôture de l'étape 3 ratée (T3) ; « non commises » (T7). D1 bien capté en `open`. |
| 15 | **faux** | partiel | v5 : tout le résumé est celui d'une autre session (T10). v6 : juste sur les fichiers, aveugle sur la décision créée et la frontière Core. |
| 16 | **faux** | partiel | v5 : décrit la nuit précédente (T10). v6 : juste, sauf `open` vide devant « 14 fiches à compléter » (T6) et `central_files` remplis de fichiers déplacés (T9). |
| 17 | **faux** | partiel | v5 : point d'arrêt sur le premier commit, « sans rapport final » inventé. v6 : contenu du lot pris pour le travail de la session, avant-dernier commit cité (T11). |
| 18 | partiel | partiel | Les deux ratent le fil Core hors commit (T3). v6 explicite mieux la règle D6. |

Bilan : sous v5, 2 justes, 8 partielles, 4 fausses sur 14 (fiches 01 à
14) ; sur les quatre sessions récentes, v5 est faux 3 fois sur 4 et v6
partiel 4 fois sur 4. **v6 supprime les résumés faux par recopie ; il ne
rend aucun résumé juste** parmi les quatre. Les défauts restants sous v6
sont T3, T5, T6, T9, T11 : ils ne dépendent pas des annexes.

### 3.2 `open` vide : défaut de prompt, ou validateur qui rejette ?

Vérifié le 2026-09-11 sur le code et les données, sans rien modifier.

- **Le validateur ne filtre pas, il refuse tout ou rien.** Dans
  `session_summary.py`, `_resumption_items` lève `InvalidModelOutput`
  au premier point non conforme ; `summarize_session` attrape
  l'exception et rend un échec de tentative. Un point rejeté ne donne
  jamais un `open` vide : il donne un résumé absent et un compteur
  d'échec.
- **Aucun rejet en production.** Le journal `~/.pulse_intelligence/logs/run.log`
  ne contient aucune occurrence de `InvalidModelOutput` ni de
  `reprise.open`. Les lots du 9 (11/11 créés) et du 10 (3/3) n'ont eu
  aucun échec.
- **Aucun rejet dans les replays archivés.** Sur les 14 replays v5 de
  `corpus/docs/audits/2026-09-08-reprise-fondee/after/`, le `open` brut
  du modèle (`raw_output`) a exactement le même nombre de points que le
  `open_items` validé : 0, 0, 0, 3, 0, 2, 0, 0, 1, 0, 2, 0, 0, 1. Le
  validateur a accepté tout ce que le modèle a proposé.
- **Un appui valide existait et n'a pas été pris.** Fiche 16 : « 14
  fiches à compléter » est une sous-chaîne littérale du message du
  dernier commit, observation `kind=commit` présente dans la timeline.
  Un `recorded_statement` la citant aurait passé le validateur.

Conclusion : **`open` vide est le choix du modèle sous le prompt, pas un
effet du validateur.** Deux causes candidates dans le prompt v6 lui-même,
non testées : la phrase « [] est préférable à un reste hypothétique » et
l'exemple de sortie qui montre `"open": []`. Quand le modèle propose des
points (fiches 03, 04, 06, 14), ce sont des `command_failure` ; sur les
sept cas où l'utilisateur voulait un `recorded_statement` (T6), un seul
est capté (14). Le modèle sait produire un échec de commande, il ne
sélectionne presque jamais une déclaration de commit.

Ce qui permettrait de trancher, à faire seulement si vous le décidez :
un rejeu à entrée constante sur les quatre sessions à déclaration
attendue (09, 13, 16, et 14 en contrôle), avec un prompt v6 dont
l'exemple montre un `recorded_statement` au lieu de `[]`. Si `open` se
remplit, c'est l'exemple ; sinon, c'est le modèle ou la consigne de
prudence. Aucune donnée nouvelle, aucun changement de collecte, un
prompt versionné en PR comme d'habitude.

### 3.3 Complément du 2026-09-11 au soir : les fiches 15 à 18 n'avaient pas d'appui citable

Constat fait en préparant le rejeu, sans rien modifier en production. Le
Core de production (launchd `com.pulse.daemon`) tourne sans redémarrage
depuis le 06 à 23:56 ; le schéma 3 est sur main depuis le 09 à 00:35
(2ed558b). Il sert donc encore `schema_version 2` : la vue héritée
`files / git / terminal`, sans `observations`. Intelligence accepte ce
schéma en lecture et bascule sur `legacy_aggregates`, sans `oN`.

Preuve : le hash d'entrée des cinq résumés v6 émis en production
(1eb35865, a1040f4f, f8aab73b le 10 ; 32ca64e5, d283f6dd le 11) est
identique, à l'octet, à l'entrée reconstruite depuis la vue schéma 2
servie aujourd'hui. Sans référence citable, ni `command_failure` ni
`recorded_statement` ne peuvent passer le validateur : **pour les fiches
15 à 18, `open` vide est forcé par l'entrée, pas choisi par le modèle.**
La conclusion de 3.2 reste valable pour les fiches 01 à 14, dont les
replays ont reçu l'export schéma 3 de `eval/observed`. Le rejeu utilise
pour 16 une vue schéma 3 figée depuis un Core jetable (code de main, copie
de `trace.db`). Verdict du rejeu : `docs/dogfooding.md`, jour 7.

## Décisions de l'utilisateur, 2026-09-11

1. **Rejeu sur `open` : oui**, trois variantes du prompt v6 sur les quatre
   sessions à entrée constante (09, 13, 16, et 14 en contrôle) : sans la
   phrase « [] est préférable à un reste hypothétique » ; sans l'exemple
   `"open": []` ; sans les deux. Qwen seulement, en batch, pas maintenant.
   Précondition vérifiée le 2026-09-11 : les observations `kind=commit` du
   schéma 3 portent le message de commit complet, corps compris (fiche 09,
   `o67`, 8 lignes ; fiche 13, `o21`, 22 lignes ; fiche 16, message d'une
   ligne contenant « 14 fiches à compléter »). Seule la vue `git.commits`
   héritée garde la première ligne (`_commit_view` dans
   `context_snapshot.py`), et ce n'est pas elle que le validateur lit.
2. **Registre D → `core/TODOS.md`, trois entrées** : l'item `pre-push`
   élargi aux merges (hook `post-merge` ou reflog), remonté de P3 à P2, avec
   les 13 fiches en référence ; `pulse note` en nouveau P2 (déclaration
   explicite horodatée → `recorded_statement`), 7 fiches ; PostToolUse reste
   P3 avec ses 5 fiches. Les 22 autres trous restent dans `D-backlog.md`.
3. **Frontières** : contenu des sessions d'agent, confirmée (rétention
   inchangée ; PostToolUse donne les commandes sans le contenu) ;
   navigateur, confirmée (pas d'URL) ; CI distante, pas une frontière,
   reste en bas du registre.
4. **Réponses** : elles restent dans ce dossier, étiquetées « vérité
   terrain reconstruite ». Rien dans `eval/expected` tant que le format
   `ANNOTATION-PROPOSEE.md` n'est pas validé.
5. **Rien d'autre n'est activé ni implémenté.** T1 (commande corrigée), T2
   (filtre de candidature) et les variantes de prompt du rejeu attendent
   un chantier propre, en PR.
