# Commandes d'un agent : les voir pendant la session

**Date :** 2026-09-17
**Statut :** en cadrage (aucun code ; les points « À trancher » attendent
l'utilisateur)
**Voir :** `core/TODOS.md`, « Hook PostToolUse Claude Code (second étage) »
(P1 depuis le 17), [émission SessionEnd immédiate](2026-08-31-emission-session-end-immediate.md),
[rétention de `trace.db`](2026-08-30-retention-trace-db.md),
[résumés en continu](2026-09-17-resumes-en-continu.md) (bloc `Session en
cours`, Core 0.8.5.0)

## Problème

Les commandes lancées par un agent ne sont jamais observées. Les faits de
commande viennent d'un seul producteur, `pulse-zsh`
(`core/scripts/pulse_terminal_watcher.zsh`, `preexec`/`precmd` d'un shell
interactif) ; l'outil Bash de Claude Code n'y passe pas. Le 17, journée menée
presque entièrement par un agent : 13 `terminal_finished`, tous humains,
aucun après 15:47. Le bloc `Session en cours` et le résumé de nuit ne voient
d'une telle journée que ses commits et, dans les dossiers surveillés, ses
fichiers ; ni ses tests, ni ses échecs.

## 1. Ce que les hooks de Claude Code donnent

Source : référence des hooks, <https://code.claude.com/docs/en/hooks>
(markdown brut lu le 2026-09-17 : <https://code.claude.com/docs/en/hooks.md>).

- **Deux événements, pas un.** `PostToolUse` « runs immediately after a tool
  completes successfully ». Un appel qui échoue passe par
  **`PostToolUseFailure`** : « runs when a tool that started executing
  fails ». Une commande Bash qui sort en code non nul est un échec : la doc
  donne l'exemple d'un `npm test` raté livré à `PostToolUseFailure`. Un hook
  posé sur `PostToolUse` seul ne verrait donc **aucun échec**.
- **Champs communs** (section « Common input fields ») : `session_id`,
  `transcript_path`, `cwd` (« current working directory when the hook is
  invoked »), `permission_mode`, `hook_event_name`, plus `agent_id` et
  `agent_type` dans un sous-agent.
- **`PostToolUse`** : `tool_name`, `tool_input`, `tool_response`,
  `tool_use_id`, `duration_ms` (optionnel). Pour Bash, `tool_input` porte
  `command`, `description`, et au besoin `timeout`, `run_in_background`. Le
  schéma de `tool_response` « depends on the tool » ; celui de Bash n'est pas
  documenté sur cette page. Aucun code de sortie n'est annoncé : le succès
  vaut code 0.
- **`PostToolUseFailure`** : mêmes `tool_name` et `tool_input`, plus `error`,
  `is_interrupt` (optionnel) et `duration_ms`. Pour Bash, « a command that
  ran and exited produces a first line `Exit code N`, then any output » ; la
  doc demande de se caler sur `tool_name`, `is_interrupt` et cette première
  ligne, le reste n'étant pas un format stable. Une charge peut ne porter
  aucune ligne de code de sortie quand le shell n'a pas pu démarrer.
  « Cancelling a running tool does not fire this hook. »
- **Pas d'horodatage** dans la charge : l'instant de fin est celui du hook,
  le début s'en déduit par `duration_ms` quand il est présent.
- **Mode asynchrone.** `"async": true` sur un hook `command` : le hook tourne
  en arrière-plan, « Claude continues working immediately », il ne peut rien
  bloquer, et « Claude Code doesn't enforce `timeout` on it ». En mode `-p`,
  un hook asynchrone encore actif à la fin est tué. Délai par défaut d'un
  hook synchrone : 600 s pour `command` (30 s sur quelques événements, qui ne
  sont pas ceux-ci).
- **Si le hook échoue.** Code 0 : succès, la sortie va au journal de debug.
  Code 2 : « blocking error » ; sur `PostToolUse` l'outil a déjà tourné,
  le texte est seulement montré à Claude. Tout autre code : erreur non
  bloquante, l'action continue, le transcript affiche « `<hook name>` hook
  error ». Un script introuvable tombe dans ce même cas (code 127).
- **Où il se configure** : `~/.claude/settings.json` (tous les projets),
  `.claude/settings.json` (un projet, versionnable), le fichier de réglages
  locaux du projet, ignoré par Git, réglages gérés par l'organisation,
  plugins. Un `matcher` `Bash` limite le hook à cet
  outil.

## 2. Ce que les transcripts contiennent

Lu dans `~/.claude/projects/-Users-Yugz-Projets-Pulse/` (25 transcripts), en
lecture seule ; formes relevées sur le transcript de la session du 17, sans
recopier de commande.

- **La commande** : entrée `assistant`, élément `tool_use` de nom `Bash`,
  `input.command` (texte entier) et `input.description`. L'entrée porte
  `timestamp` (ISO, à la milliseconde, UTC), `cwd`, `sessionId`,
  `gitBranch`, `isSidechain`, `version`.
- **Le résultat** : entrée `user`, élément `tool_result` relié par
  `tool_use_id`, avec `is_error` et son propre `timestamp` (la fin).
  En succès, `toolUseResult` est un objet `{stdout, stderr, interrupted,
  isImage, noOutputExpected}` : **pas de code de sortie**, il vaut 0 par
  construction. En échec, `is_error` est vrai et le contenu commence par
  `Exit code N` (6 cas sur 7 le 17) ; le septième est une erreur de
  l'outillage, sans commande exécutée : il faut filtrer sur cette première
  ligne, comme pour le hook.
- **`cwd`** est celui de la session, pas celui de la commande : le 17, 87
  commandes sur 190 commencent par `cd …`, et toutes portent le `cwd` du
  checkout principal alors qu'elles tournent dans un worktree. Le hook a la
  même limite.
- **Volume.** 190 commandes Bash dans la session du 17 : médiane 441
  caractères, maximum 14 190, 71 sur plusieurs lignes (heredocs), 23 au-delà
  de 2 000 caractères, **212 000 caractères au total**.
- **Ce qu'`agent_sessions.py` en lit aujourd'hui** : bornes, nombre de
  messages, premier `cwd`, branche, version de l'outil, première demande.
  Aucune commande. Un seul événement `agent_session` par session, calculé
  une fois et jamais recalculé ; le brut des transcripts n'entre jamais dans
  `trace.db` (décision du 2026-08-30). Fréquence : toutes les heures
  (`com.pulse.agent-producers`, `StartInterval` 3600) pour les transcripts
  silencieux depuis 60 min, et tout de suite à la fin d'une session par le
  hook `SessionEnd`, posé dans `~/.claude/settings.json`, donc global.
- Le format des transcripts n'est pas documenté comme une interface ; la doc
  des hooks prévient en plus qu'il « is written asynchronously and may lag ».

## 3. Hook ou transcripts

| | Hook `PostToolUse` + `PostToolUseFailure` | Lecture des transcripts |
| --- | --- | --- |
| **Délai d'observation** | Immédiat, à chaque commande | Au mieux à la fin de la session ; sinon une heure après 60 min de silence. Une session d'une journée n'apparaît qu'après coup |
| **Effet sur les sessions déjà reconstruites** | Aucun : les faits arrivent dans l'ordre | Des faits anciens arrivent en retard : la composition d'une session close change, donc son identité (hash des `event_id`), après que le résumé de nuit a été produit |
| **Installation** | Un réglage Claude Code. Global (`~/.claude/settings.json`, comme `SessionEnd` aujourd'hui) ou par projet (le fichier de réglages locaux du projet, ignoré par Git, à recopier dans chaque worktree) | Rien à installer : le producteur parcourt déjà tout `~/.claude/projects` |
| **Projets Cogity** | Global : le hook se déclenche aussi dans un dépôt Cogity ; rien ne quitte la machine, mais ses commandes entreraient dans `trace.db`, conservée sans limite. À filtrer dans le script sur la liste déclarée (`~/.pulse_v2/watched_workspaces`) et ses worktrees. Aujourd'hui `trace.db` porte 1 `terminal_finished` et 0 `agent_session` qui mentionnent Cogity | Même question, déjà ouverte : le producteur lit tous les projets sans filtre |
| **Core arrêté** | Rien n'est perdu : le script écrit dans l'outbox durable (`producer_outbox`), pas en HTTP, comme le hook zsh et l'observateur | Rien n'est perdu : même outbox |
| **Si le producteur casse** | Avec `async`, la session de l'agent n'attend jamais. Un code non nul affiche « hook error » dans la session : le script doit toujours sortir en 0 et écrire ses erreurs dans un journal, comme `pulse_session_end_hook.sh` | Invisible pour l'agent |
| **Rédaction** | Celle de l'ingestion, avant SQLite : `build_terminal_payload` applique `filter_terminal_command` puis `redact_command` avant l'outbox. Motifs connus seulement ; un heredoc peut porter un contenu de fichier | Identique si le même chemin est emprunté |
| **Stabilité** | Interface documentée, versionnée par l'éditeur | Format interne, non documenté |
| **Coût** | Un processus Python par commande (190 le 17), hors du chemin de l'agent grâce à `async` | Un passage par heure |

**Contrat.** Deux voies :

- **`terminal_finished` sous un autre producteur** (`pulse-claude-code`) :
  aucun schéma ne change. Le type existe, l'ingestion et l'export l'acceptent,
  la projection en fait un fait `command`, `is_test_command` et le compte des
  échecs suivent, et aucun consommateur ne lit le nom du producteur. Mais le
  **sens** change : `/context` et l'entrée du résumé de nuit reçoivent des
  commandes que l'utilisateur n'a pas tapées, sans pouvoir les distinguer.
- **Un fait distinct, ou un champ `actor` sur le fait `command`** : additif,
  mais c'est la version des observations qui bouge (2 → 3), avec note datée,
  mise à jour d'Intelligence et du prompt, qui doit apprendre qu'une commande
  peut venir d'un agent.

**Le volume tranche une partie du choix.** 212 000 caractères de commandes
pour une session, c'est de l'ordre de 60 000 tokens : deux fois le plafond
d'entrée du résumé de nuit (`llm_max_input_tokens` 30 000, refus avant le
prefill). Verser les commandes d'agent telles quelles ferait refuser les
sessions les plus riches, et `trace.db` ne s'élague pas. Le texte doit être
borné **à la source** : corps des heredocs retiré (on garde la ligne
d'ouverture et un compte de lignes), puis plafond sur le reste.

## 4. Recommandation

**Le hook, pas les transcripts** : le délai et l'identité des sessions
closes départagent. Les transcripts restent la source de l'événement
`agent_session`, inchangé.

**Plus petite étape qui fait apparaître les tests et les échecs de Claude
Code dans `Session en cours` :**

1. Un script `core/scripts/pulse_post_tool_use_hook.sh`, sur le modèle de
   `pulse_session_end_hook.sh` : lit la charge sur stdin, ne garde que
   `tool_name` `Bash`, sort toujours en 0, journalise dans
   `~/.pulse_v2/logs/`.
2. Branché sur **`PostToolUse` et `PostToolUseFailure`**, `matcher` `Bash`,
   `"async": true`.
3. Code de sortie : 0 sur `PostToolUse` ; le `N` de la première ligne
   `Exit code N` sur `PostToolUseFailure` ; rien d'émis quand cette ligne
   manque (l'outil n'a pas tourné) ; 130 quand `is_interrupt` est vrai.
   Aucune sortie de commande n'est lue ni stockée, comme pour zsh.
4. Émission par le chemin existant (`producer_outbox`, même filtrage, même
   rédaction, même outbox), en `terminal_finished`, producteur
   `pulse-claude-code`, avec `session_id` de l'agent dans les détails ;
   `started_at` déduit de `duration_ms`.
5. Commande bornée à la source : corps des heredocs retiré, plafond de
   2 000 caractères, drapeau `command_truncated`.
6. Filtre : n'émettre que si le `cwd` est sous un workspace déclaré ou l'un
   de ses worktrees.

Avec cela, les commandes de l'agent deviennent des faits `command` sans
toucher au rendu. **Corrigé par la mesure du 17 (plus bas) :** cela ne suffit
pas à faire apparaître ses tests. La projection ne marque `test_command` que
sur une commande simple (`work_observations._simple_command`), et les 22
commandes de test de l'agent des 16 et 17 sont toutes composées
(`cd … && … | tail`) : aucune ne serait reconnue. Le tube final masque en
plus le code de sortie du test, qui est celui de `tail`. Tests : charges d'exemple des deux événements, échec sans
ligne de code, interruption, heredoc, plafond, `cwd` hors liste, outbox
indisponible (sortie 0 quand même).

**Limites connues de cette étape** : le `cwd` est celui de la session, pas
celui d'un `cd … &&` en tête de commande (46 % des commandes du 17) ; une
commande composée porte un seul code, qui ne localise pas la sous-commande
en échec (règle déjà écrite pour zsh) ; les commandes d'un sous-agent
arrivent avec `agent_id` et sont à garder ou à écarter ; une commande lancée
en arrière-plan par l'agent n'a pas été examinée.

**Étape suivante, séparée** : distinguer l'agent de l'utilisateur dans les
faits (`actor`), donc version des observations 3, note datée, prompt et
Intelligence mis à jour.

## Décisions du 2026-09-17 (utilisateur)

- **Distinction par le producteur seul** (`pulse-claude-code`) : ni champ
  `actor`, ni changement de version des observations.
- **Hook global**, filtré dans le script sur les workspaces déclarés et leurs
  worktrees, avant toute émission.
- **Texte borné** : heredocs retirés et plafond de 2 000 caractères, sous
  réserve de la mesure. **Réserve non levée** : voir « Mesure ».
- **Sous-agents gardés** ; commandes interrompues non émises en V1.
- **Codex hors périmètre.**
- **`cwd`** : si la commande commence par `cd <chemin> &&`, le `cwd` émis est
  ce chemin, résolu depuis le `cwd` de la session.
- **Compteur de l'étape 4** : activation seulement après la mesure, puis lots
  marqués « avec commandes d'agent » dans `docs/dogfooding.md`.

## Mesure du 2026-09-17 : l'entrée du résumé de nuit avec les commandes d'agent

**Méthode**, en lecture seule sur la production. `trace.db` est copiée par
sauvegarde SQLite depuis une connexion immuable. Les commandes Bash des
transcripts des 16 et 17 (430, dont 14 en échec, aucune de sous-agent ;
interrompues écartées ; `cwd` selon la règle du `cd` ; workspaces déclarés et
worktrees de Pulse seulement) sont rejouées sur la copie par le vrai chemin
d'ingestion (`build_terminal_payload` : filtrage, rédaction). Core reconstruit
les sessions des deux jours, Intelligence construit l'entrée v7, comptée comme
`MLXProvider` la compte, tokenizer du modèle de production sans les poids.
Plafond : 30 000 tokens (`llm_max_input_tokens`). Les copies sont détruites ;
scripts et chiffres sous `corpus/docs/audits/2026-09-17-commandes-agent/`.
Approximations : un worktree retiré depuis est résolu sur le dépôt principal
(borne haute) ; l'instantané Git des commandes est celui du jour de la mesure.

| Scénario | Sessions | Médiane | Au-dessus du plafond |
| --- | --- | --- | --- |
| Référence, sans commandes d'agent | 14 | 2 802 | 1 (bruit de virtualenv) |
| Commandes entières | 12 | 25 317 | 6, dont 4 par les commandes |
| Heredocs retirés, plafond 2 000 | 12 | 14 462 | 3, dont **1 par les commandes** |
| Plafond 1 000 | 12 | 14 331 | 3, dont 1 par les commandes |
| Plafond 500 | 12 | 13 442 | 2, aucune par les commandes |
| Plafond 300 | 12 | 12 508 | 2, aucune par les commandes |
| Tests et échecs seulement (36 commandes sur 432), plafond 2 000 | 15 | 2 966 | 1 (bruit de virtualenv) |

- **La borne décidée ne tient pas.** Le 16, la session de 107 min (92
  commandes) monte à 31 252 tokens, contre 12 159 sans les commandes ; le lot
  l'aurait refusée. Celle de 93 min est à 26 979.
- **Le texte n'est pas le levier.** De 2 000 à 300 caractères, cette session
  passe de 31 252 à 27 993 : à 500, elle est sous le plafond de 1,6 %, sans
  marge. Ce qui pèse est le **nombre** de faits : chaque commande coûte
  environ 200 tokens avec son `cwd`, ses codes, son instantané Git et sa part
  de `resumption`, et l'agent en lance une par minute.
- **Le bruit de virtualenv est un problème à part**, déjà présent sans le
  hook : la session du 17 à 15:48 (13 114 activités sous `DevNote-env`) fait
  951 008 tokens et sera refusée par le lot du 18. C'est le TODO P2
  « virtualenv reconnu par son `pyvenv.cfg` ». Les commandes d'agent
  déplacent les frontières de session et étalent ce bruit sur deux sessions.
- **Tests invisibles.** Sur 22 commandes de test de l'agent, 0 serait marquée
  `test_command` par la projection (toutes composées) et les 22 finissent
  par un tube vers `tail`, `head` ou `grep` : 14 échecs seulement sur 430
  commandes, parce que le code rendu est celui du dernier maillon.

**Proposition, à la place de la borne seule** (non appliquée, à trancher) :

1. **N'émettre que ce qui porte un signal** : les commandes en échec et
   celles dont un segment est une commande de test (`is_test_command` appliqué
   à chaque segment séparé par `&&`, `||`, `;` ou `|`), heredocs retirés,
   plafond de 2 000 caractères. Mesuré : 36 commandes sur 432, la plus grosse
   session à 13 004 tokens, aucune au-dessus du plafond hors bruit de
   virtualenv. C'est aussi exactement l'objectif : les tests et les échecs.
2. À défaut, plafond de 500 caractères sur toutes les commandes : passe sur
   ces deux jours, sans marge, et ne protège pas d'une session plus longue.
3. Quel que soit le choix, **les tests de l'agent ne s'afficheront comme
   tests** que si la projection reconnaît un test dans un segment d'une
   commande composée. C'est un changement de `work_observations`
   (`test_command`), donc de ce que `/context` sert : note datée et version
   des observations, ou bien un marquage posé par le hook dans les détails de
   l'événement, que seul le bloc `Session en cours` lirait. Le code de sortie
   masqué par un tube ne se rattrape pas côté Pulse.

## À trancher par l'utilisateur

Les points 1 à 6 ci-dessous sont tranchés par les décisions du 17, sauf la
borne du texte (point 4), que la mesure ne confirme pas, et la
reconnaissance des tests composés, que la mesure ajoute.

1. **Sens de `terminal_finished`.** Accepter, pour la première étape, que les
   commandes d'agent entrent comme des commandes ordinaires (distinguées
   seulement par le producteur de l'événement), ou attendre `actor` et la
   version 3 des observations avant toute émission.
2. **Compteur de l'étape 4.** L'entrée du résumé de nuit change de nature en
   cours de comptage (9 sur 15 au jour 13) : poursuivre, marquer les lots
   d'après, ou attendre la fin du comptage pour activer le hook.
3. **Installation et périmètre.** Global avec filtre sur la liste déclarée
   (recommandé, cohérent avec « aucune surveillance sans action de
   l'utilisateur »), ou par projet. Et le sort des projets Cogity, pour ce
   hook comme pour le producteur `agent_session`, qui lit déjà tout.
4. **Borne du texte.** Heredocs retirés et plafond de 2 000 caractères
   (recommandé), autre plafond, ou texte entier avec une troncature à la
   projection seulement (mais `trace.db` garde tout, indéfiniment).
5. **Sous-agents et interruptions** : garder les commandes des sous-agents ;
   émettre ou non une commande interrompue.
6. **Autres agents.** Codex n'a pas d'équivalent examiné ici : le laisser
   hors périmètre de cette étape.
