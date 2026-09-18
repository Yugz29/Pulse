# Changelog

Toutes les modifications notables de Pulse Core sont consignées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/) ;
versionnage 4 chiffres `MAJOR.MINOR.PATCH.MICRO`.

## [0.8.10.2] - 2026-09-18

Format commun d'une session d'agent vivante : Claude Code passe adaptateur
unique. Aucun contrat ne change ; le bloc « Session en cours » rendu sur la
page réelle (`trace.db` et session vivante gelées) est identique à l'octet
avant/après.

### Interne
- `daemon_v2/agent_actions.py` (nouveau) : le format commun d'une session
  d'agent vivante — qui (agent, session, dossier), état (peut valoir
  `inconnu`), actions (commandes avec description/commande masquée/issue/
  heure, fichiers modifiés, tests).
- `daemon_v2/agent_transcript.py` reste le seul module à connaître Claude
  Code (JSONL, noms d'outils, sous-agents, forme d'un `Exit code`) ; il
  fournit désormais aussi l'identité affichée (`AGENT_KIND`, `AGENT_LABEL`).
- `daemon_v2/agent_live.py` et le rendu (`renderers/live.py`,
  `renderers/html.py`) ne manipulent plus que le format commun ; le libellé
  « Claude Code » vient de l'adaptateur via `agents_label`, plus jamais en
  dur dans le rendu.

## [0.8.10.1] - 2026-09-18

Retour en réel sur l'étape 1 bis : les commandes d'agent étaient illisibles
et les heredocs exposaient du contenu de fichier (le corps d'un script
passé par `<<'EOF'` s'affichait entier, faux secrets d'un test compris).

### Corrigé
- `daemon_v2/agent_transcript.py` : la page montre la description, puis
  **la première ligne** de la commande, **coupée avant tout `<<`** et
  tronquée à 100 caractères (`command_head`, appliqué après
  `redact_command`). Le corps d'un heredoc n'est conservé ni dans la vue ni
  dans le cache. Test : un heredoc qui écrit `API_KEY=…` n'apparaît ni dans
  la vue ni dans le HTML ; sa première ligne, si.

## [0.8.10.0] - 2026-09-18

Étape 1 bis du mode continu : le bloc « Session en cours » montre, pour
chaque session Claude Code vivante, ce que son transcript dit de l'agent.
Aucun contrat consommé ne change : `/context`, `/context/sessions`, export
du journal, identité de session, `reconstruction_version`, version des
observations, schéma de `trace.db`. Rien n'entre en base.

### Ajouté
- `daemon_v2/agent_transcript.py` : lecture tolérante et incrémentale du
  transcript JSONL d'une session Claude Code (offset repris d'un rendu à
  l'autre, fichier rétréci ou remplacé relu du début, dernière ligne sans
  retour à la ligne laissée pour le rendu suivant, ligne illisible comptée
  et ignorée, entrées de sous-agent `isSidechain` ignorées). Ce qu'il rend :
  les 10 dernières commandes (description de l'agent, commande, issue
  `ok` / `échec` / `interrompue`, heure), le dernier test (un segment de la
  commande reconnu par la règle de la projection), les échecs bruts, les
  fichiers écrits par `Edit`/`Write`/`MultiEdit`/`NotebookEdit`. Commande et
  description passent par `redact_command` ; la description, texte libre,
  reçoit en plus un masque `utilisateur:secret@`. **Jamais** `stdout`,
  `stderr`, le prompt, ni le motif d'un `Exit code`.
- `daemon_v2/agent_live.py` : les sessions vivantes d'après le dossier
  d'état des hooks (`~/.pulse_v2/run/agents/`, `PULSE_AGENT_STATE_DIR`) :
  pid du processus `claude` encore là, ou fichier sans pid de moins de
  12 h. Dossier absent : liste vide, le bloc dit seulement qu'aucune
  session vivante n'est connue.
- Bloc « Session en cours », sous-section « Claude Code en cours » : une
  entrée par session (projet, état, depuis quand, identifiant court, cwd),
  puis commandes, dernier test, échecs, fichiers. Vue vivante seulement,
  jamais en archive. `render_daily_trace_html` gagne `agent_state_dir`
  (tests).
- `scripts/pulse_agent_state.py` (v0 des hooks) : le fichier d'état porte
  `transcript_path`, gardé d'un événement à l'autre.
- `tests_v2/test_agent_live.py` sur un transcript figé
  (`tests_v2/fixtures/claude_transcript_live.jsonl`) : deux tests dont un
  en échec, `Read` ignoré, `Edit` et `Write`, mot de passe dans l'URL et
  dans la description, interruption, sous-agent, ligne illisible, ligne
  tronquée puis complétée, fichier remplacé, bornes, page avec et sans
  dossier d'état, archive. Mesuré sur la session du 18 (4,1 Mo, 258
  commandes) : 86 ms la première lecture, 0,2 ms les suivantes.

## [0.8.9.1] - 2026-09-18

Le prédicat de bruit de l'historique sans `pathlib` : `/context/sessions`
d'une journée chargée rend la même réponse, deux fois et demie plus vite.
Aucun contrat ne change ; les réponses sont identiques à l'octet.

### Corrigé
- `daemon_v2/file_policy.py` : `is_file_noise` et `attributed_workspace`
  construisaient des `Path` et appelaient `relative_to` / `is_relative_to`
  / `parents` pour chaque `file_changed` de la journée — 13 364 fois pour
  le 2026-09-17, soit 2,2 s de `pathlib` sur 2,8 s de projection, et
  4,9 à 9 s servis par le daemon, au-delà du timeout de 5 s qu'avait alors
  le client d'Intelligence (lot du 18 interrompu). Le chemin rapide sur
  chaînes ne s'engage que sur un chemin absolu déjà normalisé (ni `//`, ni
  `.`, ni `..`, ni barre finale : `_plain_absolute`) ; tout autre chemin
  passe par les fonctions `Path` de référence, inchangées, que le watcher
  utilise toujours. `tests_v2/test_file_policy_history.py` compare les deux
  voies à l'ancienne implémentation sur un corpus de chemins propres et
  non normalisés, workspace racine, forme résolue et racines de virtualenv,
  et vérifie que la garde n'accepte que ce que `Path` rendrait tel quel.
  Mesuré sur une copie de `trace.db` (référence 2026-09-18T07:18:05Z) :
  `/context/sessions` du 17 en 0,90 s → 0,37 s hors daemon, réponses des
  15, 16 et 17 et `/context` identiques à l'octet hors `generated_at`
  (935 215 octets).

## [0.8.9.0] - 2026-09-17

Core dit quelle version et quel code il exécute, et `make status` juge chaque
service en trois états : à jour, STALE, INCONNU. Aucun contrat consommé ne
change : `/context`, `/context/sessions`, export du journal, identité de
session, `reconstruction_version`, version des observations, schéma de
`trace.db`. `/status` gagne deux champs.

### Ajouté
- `daemon_v2/version.py` : `CORE_VERSION` est le contenu de `core/VERSION`
  lu une fois, à l'import, donc au démarrage du processus. C'est la version
  du code exécuté : un service launchd ne recharge pas son code, et relire le
  fichier à chaque requête dirait la version du checkout. Fichier absent,
  vide ou illisible : `unknown`, jamais une erreur, la collecte n'en dépend
  pas.
- `daemon_v2/code_fingerprint.py` : empreinte du code, calculée au même
  moment. Chaque `.py` de `daemon_v2` est réduit à son arbre syntaxique,
  docstrings retirées ; `VERSION` et `requirements.txt` en font partie. Un
  commentaire, une docstring ajoutée, ôtée ou réécrite, une remise en forme
  ne la changent pas ; toute instruction modifiée la change, bump ou pas.
  Pure lecture, sans Git ni sous-processus ; environ 0,1 s au démarrage
  (11 000 lignes), une fois par processus. Un fichier qui ne se parse pas
  compte par ses octets.
- `GET /status` porte `version` et `code_fingerprint` ; la page `/` les
  affiche dans `État système`. `/context` ne les porte pas.
- Worker et file-watcher ne servent rien : ils annoncent pid, version et
  empreinte au démarrage dans `<dossier de la base>/run/<service>.json`
  (0600, écriture atomique, jamais bloquante). L'annonce d'un autre pid ne
  vaut rien. Un Core jetable (`PULSE_V2_DB_PATH`) annonce à côté de sa base,
  pas dans celle de la production.
- Observateur Swift : `install_observers_launchd.sh` note à côté du binaire
  installé (`PulseApplicationObserver.json`) l'empreinte de ses sources
  (`Package.swift`, `Sources/`, octets bruts) et le SHA-256 du binaire.
- `make status` affiche `Version servie`, l'empreinte servie, et celles du
  checkout.
- Dans `make status`, l'état ouvre la ligne du service, entre crochets et en
  colonne fixe, avant le `running` de launchd : `running` dit que le
  processus vit, pas qu'il exécute le bon code. `INCONNU` et `STALE` sont en
  capitales, `à jour` non ; une ligne de bilan compte les trois états et
  rappelle, s'il en reste, qu'INCONNU n'est pas à jour. Couleur (vert, rouge,
  jaune) sur un terminal seulement, jamais sous `NO_COLOR` ni dans un fichier.

### Modifié
- Le contrôle STALE ne compare plus l'heure de démarrage à la date du dernier
  commit sous `core/`. L'empreinte décide, la version se lit à côté :
  - **à jour** : même empreinte que le checkout ;
  - **STALE** : empreinte différente, avec les deux versions si elles
    diffèrent, ou « changement sans bump » si elles sont égales ;
  - **INCONNU** : rien d'annoncé (service antérieur à cette version, annonce
    illisible ou d'un autre pid) ou checkout illisible. Jamais compté à jour,
    jamais compté périmé.
- Observateur : à jour si le binaire installé est celui noté à l'installation
  et que ses sources sont celles du checkout ; STALE sinon, avec le bon
  remède (réinstaller : une relance ne recharge pas un binaire copié, et
  l'ancien STALE se levait pourtant par un `kickstart`) ; INCONNU sans note
  ou si le binaire a été remplacé à la main.
- L'ancien calcul (`ps -o etime`, `git log -1 --format=%ct`) est supprimé.

### Pistes évaluées
- Version servie plus date du dernier commit « de code exécuté » : écartée.
  Un chemin ne distingue pas un docstring d'une instruction (#106 touchait
  `daemon_v2`), la date d'un commit en rebase est celle de son arrivée, et
  la comparaison dépend de l'horloge, de `ps` et de la branche du checkout.
- SHA du commit du checkout au démarrage : écarté. Tout commit, même de
  documentation, change le SHA ; un arbre modifié sans commit ne le change
  pas ; un worktree a un `.git` en fichier.
- Empreinte des seuls modules chargés : écartée. Les imports tardifs
  (`renderers`) rendent l'ensemble instable d'un instant à l'autre.

### Ce que l'empreinte rate encore
- Les dépendances installées dans le venv quand `requirements.txt` ne bouge
  pas, l'environnement du plist, les fichiers de configuration relus au
  démarrage (`watched_workspaces`).
- Une docstring lue à l'exécution (`__doc__`) : aucune aujourd'hui dans
  `daemon_v2`.
- Elle marque trop large, du côté sûr : le paquet entier compte pour chaque
  service, et un renommage sans effet compte comme un changement. Une montée
  de version de Python change `ast.dump`, donc toutes les empreintes.
- Observateur : les sources sont comparées, pas le binaire. Comparer le
  binaire au checkout demande de le reconstruire (`swift build -c release`),
  sans garantie de reproductibilité à l'octet. Un processus démarré avant une
  réinstallation faite à la main n'est pas vu (le script relance).

### Déploiement
- Relancer daemon, worker et file-watcher (daemon et worker : `launchctl
  bootout`, attente de la sortie, `bootstrap` ; file-watcher : `kickstart
  -k`). D'ici là, `make status` les dit INCONNU.
- L'observateur reste INCONNU tant que rien n'est noté. Deux voies, au choix
  de l'utilisateur : réinstaller (reconstruit le binaire, donc redemande
  l'Accessibilité), ou noter sans reconstruire, depuis `core/` :
  `.venv/bin/python -m daemon_v2.service_staleness --record-observer
  ~/.pulse_v2/bin/PulseApplicationObserver`. La seconde affirme que le
  binaire installé vient des sources actuelles ; au 2026-09-17 les indices
  concordent, sans faire preuve : il est identique à l'octet au produit de
  `macos_observer/.build/release`, construit le 12 à 14:36, et le dernier
  commit des sources a été écrit le 12 à 14:36 (une date d'écriture survit à
  un amend).
- Fait le 2026-09-17 à 22:16, à la mise en production : l'empreinte de
  l'observateur a été **notée sans reconstruction** (`--record-observer`),
  sources `7c4d9f0f75fc`. Le binaire n'a été ni reconstruit ni réinstallé,
  l'Accessibilité n'a pas été redemandée. Cette note affirme, sans le
  prouver, que le binaire installé (construit le 2026-09-12 à 14:37,
  identique à l'octet au produit de `macos_observer/.build/release`) vient
  des sources actuelles. Dernier commit des sources (`Sources/`,
  `Package.swift`) : `5b59ca3`, arrivé sur main le 2026-09-12 à 14:58, écrit
  à 13:54 ; le plus tard écrit est `a17e25e`, le 2026-09-12 à 14:36. Un « à
  jour » de l'observateur vaut donc « sources inchangées depuis cette
  note », jusqu'à la prochaine réinstallation, qui notera une empreinte
  issue d'un vrai build.
- Aucune coordination avec Intelligence.

## [0.8.8.0] - 2026-09-17

La page du journal ne déroule plus le bruit de fichiers. Suite du « non
traité ici » de la 0.8.6.0. Page HTML seulement, comme 0.8.1.0 et 0.8.4.0 :
aucun contrat consommé ne change (`/context`, `/context/sessions`, export du
journal, identité de session, `reconstruction_version`, version des
observations, schéma de `trace.db`).

### Corrigé
- `GET /day/2026-09-17` : 2,3 s et 1,78 Mo ; `GET /` : 3,8 s et 1,90 Mo.
  Répartition de `/day` : requête SQL 0,12 s, construction de la vue 0,05 s,
  rendu HTML 2,15 s. Le journal lit les événements bruts
  (`activities_between` puis `reconstruct_session_views`), jamais la
  projection : le filtre `pyvenv.cfg` de la 0.8.6.0, posé à la collecte et
  dans `work_observations`, ne s'y appliquait pas. Les 13 059 `file_changed`
  de `DevNote-env` y passaient donc tous, chacun résolu par `pathlib`
  plusieurs fois par rendu (79 451 résolutions de projet), et sortaient en
  listes de plusieurs milliers de lignes. Le volume de `file_changed` est la
  seule cause : le 16 (659 événements, 107 fichiers) se rend en 25 ms pour
  43 Ko.
- `daily_trace.without_file_noise` : les pages HTML (`/` et `/day/…`)
  déroulent une vue de la journée sans les `file_changed` que la projection
  compte en `file_noise`. Même prédicat, désormais partagé
  (`file_policy.is_file_noise`, `attributed_workspace`), sans lecture du
  disque. Deux différences voulues avec la projection : les virtualenvs sont
  ceux que la journée révèle, toutes sessions confondues, et un préfixe de
  chaîne tranche les rafales avant `pathlib`.
- La page dit ce qu'elle masque : `Fichiers masqués` dans le résumé du jour
  (compte, virtualenv nommé, renvoi à l'export JSON) et une ligne par session
  concernée. L'en-tête et `Événements` gardent le compte de la base ;
  `Fichiers modifiés`, `Maintenant`, `Faits de reprise` et le
  `Workspace principal` d'`État système` suivent la vue. `Session en cours`
  lit toujours la trace entière : ses références oN restent celles de
  `/context`.
- Après correctif : `/day/2026-09-17` 0,20 s et 104 Ko (SQL 0,11 s, vue
  0,04 s, rendu 0,07 s) ; `/` 0,48 s et 229 Ko ; `/day/2026-09-16` 27 ms et
  42 947 octets, identique à l'octet.

### Ce que cela fait perdre
- Sur la page, le détail des fichiers masqués : il reste dans `/trace/…`.
  Neuf journées passées changent d'affichage, toutes par du bruit que la
  collecte n'enregistre plus : `node_modules`, `dist`, `.build` (juillet),
  `.gitnexus` (29 août – 3 septembre, 1 306 lignes le 2), le virtualenv du
  5 septembre (6 132). Une session faite seulement de bruit reste affichée,
  avec son compte masqué.
- Une rafale de vrais fichiers (259 dans la même minute le 9 septembre)
  reste déroulée en entier : ni plafond ni regroupement ajouté.

### Sans effet sur l'existant
- Sur une copie de la base de production, entre `main` et cette version :
  `/context/sessions` identique sur les 103 jours, `/context` (fenêtres 30,
  120, 720), `/trace/<jour>` JSON et Markdown sur 102 jours et `/trace/days`
  identiques, hors `generated_at`. Seules 9 pages `/day/…` diffèrent.
  `/status` et `/days` lisent toujours la trace entière, avec leur coût
  (0,9 s et 2,5 s le 17) : non traité ici.

### Déploiement
- Relancer les quatre services Core, pas le daemon seul. Daemon et worker :
  `launchctl bootout`, attendre la sortie effective du service, puis
  `launchctl bootstrap` ; file-watcher et observateur : `launchctl kickstart
  -k`, sans reconstruire l'observateur (signature ad hoc, Accessibilité).
  Seul le daemon porte le changement, mais le contrôle STALE de `make status`
  compare l'heure de démarrage de chaque service au dernier commit sous
  `core/` (`daemon_v2`, `scripts`, `macos_observer`, `requirements*`), pas au
  service concerné : un service non relancé reste marqué STALE. Mention
  corrigée le 2026-09-17, elle disait « relancer le daemon Core ».
  Intelligence n'est pas concernée.

## [0.8.7.0] - 2026-09-17

Worktrees Git liés : rattachés au dépôt principal, observés d'office. Depuis
le 17, toute branche autre que main se travaille dans un worktree
(`AGENTS.md`) ; Core n'en voyait que les commits, sous un projet à part
nommé d'après le dossier. Aucun contrat consommé ne change de forme :
`/context`, `/context/sessions`, export du journal, identité de session,
`reconstruction_version`, version des observations, schéma de `trace.db`.

### Ajouté
- **Attribution.** Quand `.git` est un fichier, sa ligne `gitdir:` mène au
  dossier commun du dépôt principal (`daemon_v2/git_worktree.py`, sans
  lancer Git ; un sous-module, sans `commondir`, n'est pas rattaché). Le nom
  de projet écrit à la collecte suit le dépôt principal : `git.repository` et
  `workspace.project_name` des commandes, `repository` du hook de commit
  (`git rev-parse --git-common-dir`). `git_root` et `workspace_root` restent
  le worktree : une bascule entre le dépôt et son worktree reste un
  changement de workspace.
- **Observation.** Le file-watcher observe d'office les worktrees liés des
  workspaces déclarés, lus par `git worktree list` au démarrage puis toutes
  les 60 secondes. Le contenu d'un worktree à sa découverte est la ligne de
  base : aucun événement. Un worktree placé sous un workspace déclaré n'est
  pas ajouté. Les `file_changed` d'un worktree persistent la forme résolue du
  workspace (racine du worktree, nom du dépôt principal), que l'ingestion
  acceptait déjà ; ceux d'un workspace déclaré gardent leur chemin.
- Un worktree disparu (dossier ou fichier `.git` absent, ou plus listé par
  Git) est retiré avant le flush : `git worktree remove` n'émet pas une
  suppression par fichier suivi.
- Le résolveur d'affichage du journal nomme un worktree d'après son dépôt
  principal tant que le worktree existe. `/context` ne lit jamais ce
  résolveur, seulement le nom persisté dans l'événement.

### Corrigé
- Le fichier `.git` d'un worktree ou d'un sous-module n'est plus un fichier
  de travail : il entrait dans le snapshot du watcher (aucun événement de ce
  genre dans la base).

### Sans effet sur l'existant
- Les noms de projet sont persistés à la collecte. `/context/sessions` est
  identique, champ pour champ, entre 0.8.6.0 et cette version sur les 103
  jours et 222 sessions closes de la base de production ; aucune référence
  oN n'est renumérotée. Les 16 `git_commit` du 17 émis depuis des worktrees
  gardent leur `repository` d'alors (`Pulse-live`, `Pulse-refs`…), et les 3
  sessions qui les portent gardent ce projet. Aucun des 68 résumés stockés
  n'a de worktree pour workspace ou pour projet.

### Déploiement
- Relancer les services Core : le file-watcher porte l'observation, le hook
  de commit est lu depuis le checkout à chaque commit. Aucune coordination
  avec Intelligence.

## [0.8.6.0] - 2026-09-17

Un virtualenv se reconnaît à son `pyvenv.cfg`, pas à son nom. Correctif de
bruit, comme l'exclusion de `.gitnexus/` en 0.3.1.0 : la forme de
`/context`, `/context/sessions`, de l'export du journal et le schéma de
`trace.db` ne changent pas ; l'identité des sessions et
`reconstruction_version` non plus (les événements stockés restent dans leurs
sessions, seule la projection en observations les écarte).

### Corrigé
- Le 2026-09-17, un environnement nommé `DevNote-env` a produit 19 191
  `file_changed` (suppression puis réinstallation), dont 13 059 dans une
  session de neuf minutes : 6 618 faits `file`, une entrée de résumé de
  951 008 tokens pour un plafond de 30 000, donc une session refusée par le
  lot. Seul `.venv` était ignoré, par son nom.
- **Collecte** (`file_watcher`) : un dossier qui porte `pyvenv.cfg` n'est ni
  parcouru ni observé, quel que soit son nom ; `.venv` reste ignoré par son
  nom, même sans `pyvenv.cfg`. Un `pyvenv.cfg` à la racine d'un workspace
  n'aveugle pas le workspace. La suppression d'un virtualenv n'émet rien :
  ses fichiers n'ont jamais été dans le snapshot.
- **Projection** (`work_observations`) : les fichiers d'un virtualenv que la
  session révèle elle-même, par un `pyvenv.cfg` créé, modifié ou supprimé
  parmi ses événements, sont comptés en `file_noise` et ne deviennent pas des
  faits. La projection ne lit jamais le disque : la même base rend la même
  projection, que le dossier existe encore ou non, et un `input_hash` se
  recalcule à l'identique. Mesure sur la session du 17 à 15:48 (`6af523d8`,
  13 114 activités inchangées) : 6 637 faits → 21, 951 008 tokens → 1 804.
- Limite assumée : une session ancienne qui touche un virtualenv sans
  événement `pyvenv.cfg` (un `pip install` dans un environnement existant)
  garde ses fichiers ; la collecte n'en enregistre plus. Les seuls
  `pyvenv.cfg` de la base sont ceux du 17 : aucun résumé stocké ne voit ses
  références renumérotées.
- Non traité ici : la chronologie HTML de la page déroule toujours ces
  événements (page de 1,8 Mo le 17) ; le document d'une fenêtre
  (`is_noise_path`) reste filtré par nom seulement.

### Déploiement
- Relancer les services Core : launchd ne recharge pas le code, et c'est le
  file-watcher qui porte la moitié du correctif. Aucune coordination avec
  Intelligence.

## [0.8.5.0] - 2026-09-17

Bloc `Session en cours` dans le journal HTML : étape 1 de
`docs/decisions/2026-09-17-resumes-en-continu.md`, l'état du travail pendant
la session, sans modèle. Lecture seule, calculé à chaque rendu, rien n'est
stocké ; aucun contrat consommé ne change : `/context`, `/context/sessions`,
export du journal, identité de session, `reconstruction_version`, version des
observations et schéma de `trace.db` restent identiques.

### Ajouté
- Sous `Maintenant`, quand une session de travail est ouverte, le bloc
  `Session en cours` (ancre `#session-en-cours`) range ses faits, numérotés
  comme dans `/context` (`project_work_observations`) : commits, fichiers les
  plus touchés (un par chemin, leurs faits réunis, huit au plus, le reste
  compté), dernier test et nombre de tests en échec, commandes en échec (huit
  au plus, du plus récent au plus ancien), sessions d'agent terminées depuis
  le début de la session. Chaque ligne est un fait ancré (`#fait-live-oN`),
  affiché comme les faits cités de 0.8.4.0 ; un lien mène à la chronologie
  complète de la session.
- Les échecs sont bruts : code et heure observés, jamais « résolu » ni
  « dépassé ». L'état net des commandes reste côté Intelligence
  (`resumption.py`) ; Core ne le recalcule pas. 130 est une interruption, pas
  un échec, comme dans `/context`.
- Le bloc est absent sans session ouverte, et dans `/day/<date>` et l'export
  Markdown. Aucun script : la page se recharge à la main.
- Modules `daemon_v2/live_session.py` et `daemon_v2/renderers/live.py` ;
  `renderers/summaries.render_fact` partagé entre faits cités et faits en
  direct.

### Déploiement
- Relancer les services Core : launchd ne recharge pas le code. Aucune
  coordination avec Intelligence.

## [0.8.4.0] - 2026-09-17

Références `oN` cliquables dans les zones `Reprise` et `Résumés` du journal
HTML (jour 13 du dogfooding : un résumé ne se jugeait pas sans rejouer son
entrée). Lecture seule, aucun contrat consommé ne change : `/context`,
`/context/sessions`, export du journal, identité de session,
`reconstruction_version`, version des observations et schéma de `trace.db`
restent identiques.

### Ajouté
- Une référence `oN` de `doing`, `stopped_at`, `open` ou des preuves d'un
  point ouvert renvoie au fait cité, affiché sous la fiche dans un bloc
  toujours ouvert (ancres sans JavaScript) : commit (hash, branche, première
  ligne du message, phrase que le résumé en cite surlignée, message complet
  replié et sans ses trailers Git), commande (texte, code, cwd), fichier
  (chemin, changements comptés), verrouillage ou veille. Le fait est l'événement
  stocké, retrouvé par la table `observation_sources` du résumé lui-même :
  rien n'est reprojeté, la référence garde le sens qu'elle avait quand le
  modèle l'a lue.
- Règle de liaison stricte : une référence n'est liée que hors citation et
  présente dans la table du résumé. Dans une citation (`« … »`, `“ … ”`,
  `" … "`), le texte reste inchangé : un message de commit peut contenir
  « o7 » pour tout autre chose (cas `a4109319`). Hors citation et non
  résolue, elle porte « non vérifiable ».
- Garde-fous au rendu : l'événement existe, son type est celui d'un fait
  numéroté (et celui qu'exige la nature du point ouvert : `terminal_finished`
  pour `command_failure`, `git_commit` pour `recorded_statement`), sa date
  tombe dans les bornes que le résumé déclare. Un échec donne « non
  vérifiable » avec sa raison, jamais un fait approximatif. Les résumés sans
  table de sources (v1 à v5, une partie des v6) restent lisibles : leurs
  références, s'ils en citent, sont « non vérifiable ».
- Module `daemon_v2/summary_references.py` ; la vue d'un résumé du board
  porte `references`.

### Déploiement
- Relancer les quatre services Core, pas le daemon seul : launchd ne recharge
  pas le code, et le contrôle STALE de `make status` compare chaque service
  au dernier commit sous `core/`, pas au service concerné (procédure à
  l'entrée 0.8.8.0). Mention corrigée le 2026-09-17, elle disait « relancer
  le daemon Core ». Aucune coordination avec Intelligence.

## [0.8.3.0] - 2026-09-16

Journal seulement : la règle de candidature du bloc « sessions sans résumé »
s'aligne sur l'exception qu'Intelligence applique depuis #98. Aucun contrat
consommé ne change : `/context`, `/context/sessions`, export du journal,
identité de session, `reconstruction_version` et schéma de `trace.db` restent
identiques.

### Corrigé
- Une session close qui porte au moins un événement `git_commit` n'est plus
  classée « sous les seuils » quels que soient sa durée et son nombre
  d'activités : elle est « éligible » (`pending` aujourd'hui, `missing` un
  jour passé), comme Intelligence la traite. Cas `dd06e6c8` (3 min,
  20 activités) et `8069a1f4` (0 min, 5 activités) du 2026-09-15, qui
  restaient invisibles en alerte alors que le lot devait les résumer.

### Déploiement
- Relancer les quatre services Core, pas le daemon seul : launchd ne recharge
  pas le code, et le contrôle STALE de `make status` compare chaque service
  au dernier commit sous `core/`, pas au service concerné (procédure à
  l'entrée 0.8.8.0). Mention corrigée le 2026-09-17, elle disait « relancer
  le daemon Core ». Aucune coordination avec Intelligence.

## [0.8.2.0] - 2026-09-14

Zone `Reprise` : la reprise d'abord, les seules anomalies en alerte. Addendum
du 2026-09-14 à `docs/decisions/2026-09-13-resumes-dans-le-journal.md`.
Lecture seule, aucun contrat consommé ne change.

### Corrigé
- Le bloc rouge des sessions sans résumé passait avant « En cours » et
  listait des sessions qu'Intelligence ne résume jamais. Il vient désormais
  sous la carte et ne liste que les sessions éligibles d'hier qu'aucun résumé
  ne couvre : au moins 10 minutes ou 30 activités, seuils du §7 de la spec du
  2026-09-03.
- Les sessions éligibles d'aujourd'hui, qui attendent le lot du matin, et les
  sessions sous les deux seuils sont comptées dans une ligne grise en bas de
  zone, seuils affichés.

### Déploiement
- Relancer les quatre services Core, pas le daemon seul : launchd ne recharge
  pas le code, et le contrôle STALE de `make status` compare chaque service
  au dernier commit sous `core/`, pas au service concerné (procédure à
  l'entrée 0.8.8.0). Mention corrigée le 2026-09-17, elle disait « relancer
  le daemon Core ». Aucune coordination avec Intelligence.

## [0.8.1.0] - 2026-09-13

Les résumés de session dans le journal HTML, note de décision
`docs/decisions/2026-09-13-resumes-dans-le-journal.md`. Lecture seule, aucun
contrat consommé ne change : `/context`, `/context/sessions`, export du
journal, identité de session, `reconstruction_version` et schéma de
`trace.db` restent identiques.

### Ajouté
- Zone `Reprise` en tête de `GET /` : le résumé exposé par `/context` comme
  `last_session_summary`, lu par la même requête, avec `doing`, `stopped_at`
  et `open` en clair, nature des points ouverts, fichiers centraux, session,
  bornes, `prompt_version`, `model_id` et date de génération. Bandeau au-delà
  de 24 h depuis la fin de la session résumée.
- Liste des sessions de travail closes aujourd'hui et hier qu'aucun résumé
  ne couvre par identifiant ni par chevauchement de bornes, qu'elles
  précèdent ou suivent le résumé affiché.
- Zone `Résumés` : tous les `session_summary` stockés, par jour puis par
  session, repliés, chaque version coexistante visible avec sa
  `prompt_version`, la plus récemment générée en premier.
- `TraceStore.activities_of_type` : tous les événements d'un type avant un
  instant, dans l'ordre de `latest_activity_of_type`.

### Modifié
- La section déterministe `Reprise` du journal HTML devient `Faits de
  reprise`, ancre `#faits-de-reprise` ; `#reprise` désigne la nouvelle zone.
  L'export Markdown garde `## Reprise`.
- Les zones ne sont rendues ni dans `/day/<date>` ni dans l'export Markdown.

## [0.8.0.0] - 2026-09-12

Seuil avant split, note de décision
`docs/decisions/2026-09-12-seuil-avant-split.md`. Contrat consommé :
`reconstruction_version` passe de 3 à 4 (le regroupement des sessions
change ; le schéma de `/context` et l'export du journal ne changent pas).

### Modifié
- Un événement fort d'un autre workspace n'ouvre plus une session sur-le-champ :
  il ouvre un fragment en attente, qui ne devient une session (et ne ferme la
  précédente, à l'instant de son premier événement) que s'il dure au moins
  2 minutes entre ses événements forts **et** en compte au moins 2. Sinon il
  est absorbé par la session en cours, en gardant son workspace dans le rendu
  (séparateur de projet), dans les observations et dans `projects`.
- Les règles de relation entre workspaces (`_workspace_relation`) s'appliquent
  à l'identique au fragment en attente.
- Mesure sur 30 jours : 183 → 137 sessions, 88 → 47 trop courtes, médiane
  8 → 14 min, 60 → 14 coupures `workspace_changed`, 26 fragments absorbés.
- Consommateur : Intelligence passe `KNOWN_RECONSTRUCTION_VERSION` à 4
  (`pulse_intelligence/__init__.py`), sinon chaque lot annonce « Core sert la
  reconstruction v4, validé sur v3 ». Le corpus figé `eval/observed` reste en
  reconstruction 2, inchangé.

## [0.7.0.0] - 2026-09-12

Contexte de fenêtre : l'observateur Swift capte ce que l'utilisateur regarde,
note de décision `docs/decisions/2026-09-12-contexte-de-fenetre.md`. Nouveau
type d'événement consommé par les observations : `observation_version` passe
à 2, `GET /context` reste au schéma 3 (ajout d'un genre de fait, aucune clé
existante ne change).

### Ajouté
- Type d'événement `window_focused` (producteur
  `pulse-macos-application-observer` version 2) : à chaque activation
  d'application et à chaque changement de fenêtre ou de titre au premier
  plan, lu via Accessibility. Détails : `app`, `bundle_id`, `title`
  (`AXTitle`), `document` (`AXDocument`, chemin local) et `url` (Safari,
  Chrome et navigateurs Chromium : `AXURL` de la zone web, sans AppleScript
  ni autorisation d'automatisation). Un seul mécanisme pour toutes les
  applications ; le cas navigateur ajoute la lecture de l'URL. Événementiel
  (`AXObserver` sur le processus actif), sans interrogation périodique.
- Rédaction à l'ingestion, quel que soit le producteur : jamais de contenu
  de fenêtre ni de capture ; `title` passe par `redact_command`, une ligne,
  300 caractères ; `url` réduite à origine + chemin (ni identifiants, ni
  paramètres, ni fragment, `reduce_window_url`) ; `document` passe par le
  filtre de bruit des `file_changed` (`file_policy.is_noise_path`).
- Liste d'applications dont la fenêtre n'est jamais observée,
  `~/.pulse_v2/ignored_applications` (créée par l'installeur) : Messages,
  Mail, FaceTime, Trousseaux d'accès, Mots de passe, gestionnaires de mots de
  passe courants, Réglages Système. Aucun `window_focused` pour elles ;
  `app_activated` (le nom seul) est inchangé.
- Fait `window` dans les observations (`app`, `title`, `document`, `url`),
  provenance `sources` comme les autres faits ; ligne « fenêtre » par
  fenêtre dans le journal HTML et Markdown, sans lien cliquable.
- Titres à répétition : le dédoublonnage compare le titre sans ses glyphes
  de progression (spinner de Claude Code dans Terminal : 2 032 événements
  pour sept titres en une heure), et un filet de 30 s par application
  retient le dernier état au lieu de l'émettre à chaque seconde. Le titre
  stocké reste le titre affiché.
- Domaines ignorés `~/.pulse_v2/ignored_domains` (créée par l'installeur :
  messageries web Gmail, Outlook, Proton), appliqués à l'ingestion : un
  `window_focused` sur ces domaines est refusé en 204, l'`app_activated`
  du navigateur reste.

### Modifié
- `window_focused` est un contexte faible comme `app_activated`
  (`WEAK_CONTEXT_TYPES`) : ne démarre ni ne prolonge une session, ne prouve
  aucun workspace, ne compte pas dans « Apps actives ».
- L'observateur journalise une fois si l'autorisation Accessibilité manque ;
  `app_activated` et les événements système continuent sans elle.

### Déploiement
- Déployer Core avant l'observateur : un daemon antérieur refuse
  `window_focused` en 400 et le worker le met en dead-letter. Accorder
  l'Accessibilité à `~/.pulse_v2/bin/PulseApplicationObserver` (Réglages
  Système › Confidentialité et sécurité › Accessibilité) ; sans elle, aucun
  contexte de fenêtre, aucune autre régression.

## [0.6.0.0] - 2026-09-09

Observations de travail ordonnées, notes de décision
`docs/decisions/2026-09-08-observations-ordonnees.md` et
`docs/decisions/2026-09-08-reprise-fondee.md`. Le gel fonctionnel est levé pour
cette frontière précise : le contrat `GET /context` change de version.

### Modifié
- `GET /context` et `GET /context/sessions` passent en `schema_version: 3`.
  Les clés de session `files`, `terminal`, `git`, `apps` et `signals` sont
  remplacées par `observations` : commandes complètes avec cwd et code de
  sortie global, transitions de fichiers avec intervalles, commits complets,
  activations d'applications, dernières références observées, couverture de
  collecte et provenance `sources` (event_id exacts). Plus de coupe à 20
  fichiers, 10 lignes de terminal ou 5 applications. `workspace` est exposé
  sur chaque session.
- Les en-têtes des sessions récentes comptent les exécutions en échec (dont
  commandes de test simples, interruptions 130 exclues) et les fichiers de la
  projection, bruit d'outillage écarté.
- Le dernier `agent_session` retenu est le plus récent compatible avec le
  workspace résolu, ou d'attribution inconnue ; un agent d'un autre projet ne
  masque plus un agent compatible. `last_agent_session` et
  `last_session_summary` exposent leur `event_id` ; le résumé expose en plus
  `origin` et `workspace`.
- L'ingestion d'un `session_summary` valide `observation_version` et
  `observation_sources` quand ils sont présents : références fermées, ids de
  source exacts, aucun texte non masqué.

### Ajouté
- `daemon_v2/work_observations.py` : projection pure et versionnée
  (`observation_version: 1`) d'une session reconstruite, sans I/O ni lecture
  de Git.
- `daemon_v2/file_policy.py` : politique de bruit fichiers partagée entre le
  collecteur et la projection.

### Déploiement
- Mise à jour coordonnée avec Intelligence : une Intelligence antérieure
  refuse `schema_version: 3` ; l'Intelligence `model-v3` lit les deux
  versions. Déployer Core puis Intelligence, ou les deux ensemble. Les bases,
  résumés stockés et payloads pending existants restent lisibles tels quels.

## [0.5.6.0] - 2026-09-05

Lot hardening ouvert au retour de migration, note de décision
`docs/decisions/2026-09-05-reouverture-core-hardening.md`. Le gel de Core porte
sur son périmètre fonctionnel, pas sur ses correctifs : aucun ajout de source,
de type d'événement ni de changement du contrat `GET /context`.

### Corrigé
- Le pont vers l'outbox attend la fin de son processus sans faire tourner la
  run loop du thread appelant. `waitUntilExit` la pompait, ce qui redélivrait
  les notifications AppKit pendant l'enqueue : `ApplicationObserver.observe`
  était ré-entré alors que son `recorder` tenait encore un accès exclusif, et
  le processus était abattu (« Fatal access conflict detected », 4 fois le
  2026-09-05). `SystemObserver` passe par le même pont.
- Les workspaces déclarés dans `watched_workspaces` sont ramenés à la casse du
  disque. APFS est insensible à la casse et `resolve()` ne la corrige pas :
  une graphie différente laissait le watcher démarrer, journaliser
  « Watching files in … » et n'émettre plus rien, `should_ignore` filtrant
  chaque chemin remonté par FSEvents. La déduplication porte désormais sur la
  forme canonique.
- Un chemin sous une racine Pulse écrit dans une autre casse est reconnu comme
  privé et resserré en `0700`/`0600`. Le repli compare l'identité de l'objet
  (`st_dev`/`st_ino`), pas la casse : `private_roots()` ne bouge pas, donc
  l'ensemble des dossiers dont Pulse modifie le mode ne s'élargit jamais.
- `status.sh` ne confond plus un daemon absent avec un daemon lent : le délai
  passe à 10 s et une expiration a son propre message. `/status` répondant en
  ~2,1 s, `make status` sortait en erreur pendant que les cinq services
  tournaient.

### Documentation
- Versions de Core réalignées dans `CLAUDE.md`, `AGENTS.md`, `README.md` et
  `docs/VISION.md` ; la formule « gelé » précise désormais que le gel porte sur
  le périmètre fonctionnel.

Suite portée à 550 tests Core et 15 tests Swift. Suite Intelligence inchangée :
62 tests.

## [0.5.5.0] - 2026-09-03

Durcissement secondaire issu de l'audit externe (PR #38 et #39), sans ajout
fonctionnel.

### Corrigé
- L'observateur d'applications ne déduplique une activation qu'après son
  enqueue confirmé ; un échec temporaire ne masque plus l'activation suivante.
- `OutboxBridge` draine `stdout` et `stderr` pendant l'exécution du processus,
  sans deadlock quand un enfant remplit les deux pipes.
- Le hook terminal signale un échec d'enqueue après contention SQLite sans
  afficher le contenu de la commande.
- Le filtre des `curl` internes vers `/activities` s'arrête à la fin réelle de
  la commande shell et ne masque plus les commandes suivantes.
- Les adresses IPv6 sont entourées de crochets dans les URLs des producteurs.

### Documentation
- Politique d'écoute locale, versions, `schema_version`, chemins du repo unique
  et seuil de vigilance du coût de reconstruction réalignés avec l'état livré.

Suite portée à 540 tests Core et 14 tests Swift. Suite Intelligence inchangée :
62 tests.

## [0.5.4.0] - 2026-09-03

Bloqueur P0 de l'audit externe du pas 3 (PR #37). Note de décision
`docs/decisions/2026-09-03-fermeture-monotone.md`. `reconstruction_version`
passe à 2 : un consommateur qui a mémorisé des sessions sait que leur
composition peut avoir changé.

### Corrigé
- Fermeture de session monotone : un `screen_locked` ou un `system_sleep`
  ouvrait une interruption « en attente » sans rien fermer, et la même
  session sortait fermée ou rouverte par fusion selon les données
  disponibles au calcul ; une activité forte sans déverrouillage vu passait
  pour une reprise. Désormais le verrouillage ou la veille ferme la session
  ouverte sur-le-champ, sur son dernier travail observé, avec ce motif, et
  rien ne la rouvre — `is_open: false` ne se défait jamais. La reprise du
  bon type prouve seulement le retour de l'utilisateur ; l'activité forte
  suivante démarre une nouvelle session. Seuil de fusion
  `PULSE_SESSION_INTERRUPTION_MINUTES` retiré ; `interruptions` et
  `active_duration_seconds` conservés dans le JSON, toujours vides.

### Ajouté
- Vue `activity_kind: background` : l'activité forte observée entre un
  verrouillage et sa reprise (un agent qui tourne seul) est regroupée par
  fenêtre de verrouillage, avec son propre hash, `lock_type`, `locked_at`,
  `resumed_at`, hors identité et bornes de session de travail, hors
  `/context`. Rendue à part dans la trace journalière (HTML et Markdown)
  sous « Activité en arrière-plan (écran verrouillé) », distincte des
  sessions d'agent.

### Limite connue
- Reconstruction journalière : un verrouillage de la veille sans
  déverrouillage vu le jour même n'est pas connu du jour suivant.

Suite portée à 532 tests.

## [0.5.3.0] - 2026-09-03

Deux corrections issues de l'audit externe du pas 3 (PR #35), livrées avec
la correction jumelle côté Intelligence (PR #36 : payload de résumé gelé
dans l'état local avant le POST vers Core, rejoué octet pour octet tant que
Core n'a pas confirmé). Note de décision
`docs/decisions/2026-09-03-agent-session-hors-identite.md`.

### Corrigé
- `agent_session` hors identité des sessions : émis après coup (hook
  `SessionEnd`, passage horaire launchd) avec un `occurred_at` au milieu
  d'une session déjà reconstruite, il en changeait l'`id` (hash des sources)
  et les bornes, donc un résumé attaché désignait un ensemble d'événements
  disparu. Il n'est plus un signal fort et ne compose plus ni
  `source_event_ids` ni `started_at`/`ended_at` ; il reste exposé par
  `/context.last_agent_session`. Effet de bord accepté : il ne fait plus
  pont entre deux grappes à moins de 30 min de lui.
- Watcher fichiers : `resolve_dirty_paths` avançait le snapshot avant
  l'enqueue dans l'outbox, un refus (verrou, disque) perdait le changement
  pour de bon. Détection pure (`detect_changes`), snapshot avancé sur succès
  seulement, chemins refusés re-signalés au passage suivant jusqu'à succès.

### Ajouté
- Trace journalière : section « Sessions d'agent » (HTML et Markdown), hors
  Session et hors « Activité non attribuée », avec les bornes stockées et le
  résumé figé de chaque `agent_session`. Affichage seulement, rien n'est
  recalculé.

Suite portée à 521 tests.

## [0.5.2.0] - 2026-09-03

### Corrigé
- Course au passage en WAL d'une outbox neuve : deux premiers connecteurs
  simultanés se disputaient le verrou exclusif du `PRAGMA journal_mode=WAL`,
  qui ne passe pas par le busy handler (« database is locked », 13 fois sur
  40 en local ; `make reset` puis `dev.sh` relançant ses producteurs d'un
  coup reproduit le cas). `ProducerOutbox._connect` pose `busy_timeout`
  avant le pragma et réessaie jusqu'à 20 fois à 50 ms. Test à quatre
  créateurs sur dix bases neuves, bouclé 20 fois en local sans échec.

Suite portée à 511 tests.

## [0.5.1.0] - 2026-09-03

Hardening après relecture externe : cinq corrections indépendantes et la CI,
aucune feature, aucun changement de comportement visible. Note de décision
`docs/decisions/2026-09-03-hardening.md`.

### Sécurité
- Permissions locales : `umask 077` dans chaque point d'entrée Python,
  `~/.pulse_v2/` et `~/.pulse_core/` (l'outbox durable) créés en `0700`,
  bases SQLite en `0600`, chmod correctif sous ces racines seulement.
  `scripts/fix_permissions.sh` migre l'existant, idempotent, appelé par les
  installateurs launchd, liste ce qu'il change.
- `session_summary` : `structured.intents`, `blockers` et `central_files`
  passent par `redact_command` élément par élément, comme la reprise.
- `schema_version` : seules les versions de `SUPPORTED_SCHEMA_VERSIONS`
  (`{1}`) sont acceptées ; une version inconnue est refusée (400,
  `field: schema_version`) au lieu d'être lue comme une version 1. Le chemin
  legacy sans version ne change pas.

### Corrigé
- Course entre le hook SessionEnd et le passage horaire : l'archivage des
  transcripts et l'émission des `agent_session` prennent chacun un verrou
  `flock` (60 s puis abandon propre, exit 2) et écrivent par temporaire
  unique puis `os.replace` — plus de `FileNotFoundError` au renommage.
  Le hook et le wrapper shell ne changent pas.

### Interne
- `core/requirements.txt` et `requirements-dev.txt` épinglés sur la venv ;
  le README installe par `pip install -r`.
- CI GitHub `.github/workflows/core.yml` : pytest sur `macos-latest`,
  Python 3.14 ; le build Swift de `macos_observer/` n'y est pas encore.

Suite portée à 509 tests.

## [0.5.0.0] - 2026-09-03

Identité stable des sessions de travail. Bloqueur trouvé en relecture du
pas 3 : l'ordinal `work-N` est recalculé à chaque reconstruction, un
événement tardif (rejeu d'outbox, `agent_session` émis après coup) décale la
numérotation, et un résumé attaché à `work-1` désignait une autre session
le lendemain. On ne bâtit pas la mémoire sur une clé instable.

### Modifié
- L'`id` d'une session de travail est le sha256 tronqué à 16 hex des
  `event_id` de ses activités, triés : déterministe, sans état, correct par
  construction. `work-N` reste comme `label`. Chaque session porte
  `source_event_ids` (triés) et `reconstruction_version` (constante de
  `analysis/timeline.py`, 1, à incrémenter à chaque changement des règles
  de sessionnisation).
- Context API `schema_version` 2 (incompatible : l'ancien `id` change de
  sens) : `current_session` et `recent_sessions` exposent `id`, `label`,
  `source_event_ids`, `reconstruction_version` ; `last_session_summary`
  expose `id` et `label`.
- `session_summary` : `details.session_id` doit être le hash de 16 hex
  (400 avec `field` sinon), `details.source_event_ids_hash` requis et égal à
  `session_id`, `details.session_label` optionnel.
- Rendu HTML/Markdown inchangé : aucun renderer ne lisait l'`id`.

### Ajouté
- Route `GET /context/sessions?date=YYYY-MM-DD` (défaut aujourd'hui, `at`
  optionnel) : les sessions de travail closes de la journée locale dans la
  forme exacte de `current_session` (même code, mêmes bornes 20/10/5), plus
  `is_open`. Un consommateur qui mémorise des sessions lit cette route et
  ne reconstruit rien.

Suite portée à 492 tests, dont celui qui démontre le bug : deux événements
à 14 h font une session ; un événement inséré à 10 h déplace les labels,
l'identité de la session de 14 h ne bouge pas.

## [0.4.0.0] - 2026-09-03

Pas 3 de la roadmap V3, côté Core : le type d'événement `session_summary`.
Seul changement de Core pour ce pas (spec `docs/specs/2026-09-03-session-summary.md`, §4).

### Ajouté
- Type `session_summary` accepté par `POST /activities` : résumé de session
  dérivé, produit par la couche Intelligence. Validation minimale du contrat
  (`session_id`, `prompt_version`, `model_id`, `reprise.doing/stopped_at/open`,
  `structured.project` et `structured.confidence`), le reste passé tel quel,
  reprise rédigée en profondeur comme `first_prompt`. Le `summary` de
  l'activité est la première ligne de la reprise.
- `GET /context` expose `last_session_summary` (dernier résumé sans limite de
  fenêtre, même règle que `last_agent_session`) ; `schema_version` reste 1,
  ajout optionnel.
- Aucun rendu : le type est stocké et exposé par `/context`, pas affiché dans
  le HTML. `analysis/timeline.py` l'exclut explicitement des activités non
  attribuées (sans cela, chaque résumé aurait ajouté une ligne vide et
  incrémenté le compteur du journal).

### Interne
- `analysis/timeline.py` : `display_file_path`, `app_activation_counts` et
  `is_strong_work_activity` deviennent publics (importés par `daily_trace`,
  `context_snapshot` et les renderers) ; les anciens noms restent comme alias
  dépréciés.

## [0.3.1.0] - 2026-09-03

### Corrigé
- Le watcher fichiers exclut `.gitnexus/` : l'index GitNexus (base et CSV
  régénérés à chaque analyse) produisait des rafales de `file_changed` qui
  remplissaient `/context` jusqu'à la troncature des listes de fichiers.

## [0.3.0.0] - 2026-09-02

Pas 2 de la roadmap V3 : le Context API. Seul changement prévu dans Core
depuis le gel ; Core est de nouveau gelé après cette version.

### Ajouté
- Route `GET /context` : réponse JSON déterministe, sans modèle, à « que se
  passe-t-il en ce moment ? » — workspace (résolveur unique, git persisté
  uniquement), session courante bornée (apps, fichiers, commits, tests,
  erreurs, signaux), sessions récentes, signaux isolés, dernier
  `agent_session` sans limite de fenêtre. Paramètres `window` (5–1440 min,
  défaut 120) et `at` (instant de référence, défaut maintenant). Même base +
  même `at` + même `window` → même JSON, `generated_at` excepté. Contrat
  `schema_version: 1`, spec dans `docs/specs/2026-09-02-context-api.md`.
- Module pur `daemon_v2/context_snapshot.py` : ne connaît ni Flask ni le
  rendu, réutilise la reconstruction des sessions et les helpers d'analyse.
- Lecture `TraceStore.latest_activity_of_type`, bornée par un instant.
- `/status` expose un bloc `context` compact et `scripts/status.sh` affiche
  une ligne « Contexte : session en cours depuis … · projet » lue sur
  `/context` : premier consommateur du contrat.

Suite portée à 462 tests. `daily_trace.py`, `trace_store.py` (hors lecture
ajoutée), `session_tracker.py`, `models.py` et les renderers sont inchangés.

## [0.2.0.0] - 2026-08-31

Le journal s'étend aux sessions d'agents IA et devient un service autonome.
Politique de rétention tranchée : conservation infinie du brut de `trace.db`,
les transcripts d'agents n'y entrent jamais en brut (dérivés + archives zstd).

### Ajouté
- Événements `agent_session` : une entrée par session Claude Code / Codex
  terminée — résumé déterministe versionné, bornes, compteurs de messages,
  premier prompt (rédigé), pointeur vers le transcript. Backfill initial :
  152 sessions uniques sur 74 jours (173 transcripts traités, doublons de
  reprise absorbés), réparties dans les journées passées.
- Archivage compressé des transcripts d'agents (`scripts/archive_transcripts.py`,
  zstd de la stdlib) : copie pérenne avant la purge des outils sources
  (839 Mo → 220 Mo), idempotent, garde anti-troncature.
- Fonctionnement en continu : LaunchAgents `KeepAlive` pour le daemon et le
  worker, passage horaire des producteurs (archive puis émission), bascule
  `make mode-dev` / `make mode-service` avec retour au mode service garanti
  à la sortie du hot reload.
- Visibilité services : `make logs`, `make status` enrichi (état launchd,
  compteurs outbox), livraisons du worker horodatées dans le journal.
- Section « Activités isolées » : un `cd` nu ou un commit isolé apparaît en
  une ligne au lieu d'ouvrir une fausse session de 0 minute.
- Commande `replay-dead-letter` : re-enfile les événements en échec définitif
  dans la file de livraison (par événement, par statut HTTP, ou tous).
- Colonne `occurred_at_utc` canonique indexée et cache par jour de `/days` :
  les pages d'historique ne reparcourent plus toute la base.

### Modifié
- Qualification des projets du jour identique en vue live et archive : la
  preuve git vient des détails persistés, plus jamais de l'état du disque au
  rendu — un dépôt déplacé ne réécrit plus les journées passées.
- Résolveur de workspace unique et parseur `git status` unique, partagés par
  tout le pipeline (décision 5A).
- Le watcher de fichiers passe par l'outbox durable : un daemon arrêté ne
  perd plus d'événements.
- Prompts collés par erreur au shell : stockés en placeholder
  (`[prompt collé : N lignes, M caractères]`), jamais en clair.

### Corrigé
- Fuite d'un descripteur de fichier par opération SQLite : le worker en
  service launchd saturait ses 256 descripteurs en ~10 minutes (panne
  silencieuse) — fermeture déterministe partout, tests de régression.
- Un Ctrl-C (exit 130) n'est plus compté comme erreur : ni badge, ni
  « Erreur terminal récente » dans la reprise.
- Les transcripts de sous-agents (sidechains) n'émettent plus de fausse
  session d'agent (les émissions antérieures au filtre restent en base,
  figées — conforme à la politique de rétention).
- Deux transcripts partageant un même identifiant de session (reprise/fork)
  n'écrasent plus l'émission : la première gagne, le doublon est tracé.

### Supprimé
- `app_watcher.py` (déprécié, doublon de l'observateur Swift) et le
  paramètre `project_mode` des rendus (plus de divergence à piloter).

Suite portée à 407 tests.

## [0.1.0.0] - 2026-08-30

Premier jalon versionné de Pulse V2 : durcissement de la rédaction des secrets,
robustesse de l'outbox, et déterminisme des tests.

### Sécurité
- Rédaction des secrets élargie dans `redact_command` : jetons connus
  (`sk-`, `ghp_`, `AKIA`, `xox…`, `glpat-`), identifiants dans les URLs,
  en-têtes `Authorization`/`X-Api-Key`, `curl -u user:pass`, `mysql -p`,
  `sshpass -p`, `aws configure set`, variables d'environnement et options
  `--password`/`--token`/`--passphrase`.
- Captures conscientes des guillemets (un secret entre guillemets avec espaces
  est masqué en entier) et repli des continuations de ligne `\`+retour-ligne
  avant rédaction, pour empêcher les contournements.
- Motifs ancrés au contexte pour éviter la corruption de commandes légitimes :
  `Authorization:` pour bearer/basic, commandes à credentials pour `-u`,
  famille mysql pour `-p` (sensible à la casse : `-P3306` reste le port).
- Rédaction des messages de commit git, à l'ingestion et côté producteur.
- Nouvel outil `scripts/audit_secrets.py` (lecture seule, suit
  `PULSE_V2_DB_PATH`/`PULSE_CORE_OUTBOX_PATH`, code de sortie 2 distinct pour
  les erreurs d'infrastructure) et prédicat `command_has_secret`.

### Robustesse
- Sémantique de livraison de l'outbox clarifiée : les erreurs de connexion
  (daemon indisponible) sont réessayées indéfiniment ; seuls les échecs HTTP
  répétés partent en dead-letter (après ~1 h, `MAX_DELIVERY_ATTEMPTS=20`) ;
  une réponse 204 supprime l'événement sans dead-letter.
- `run_forever` résiste aux erreurs de stockage (plus de crash-loop du worker).
- `move_to_dead_letter` en `INSERT OR REPLACE` (rejeu sûr), `response_body`
  borné à 4096 caractères.
- `producer_instance_id` : lecture sans verrou sur le chemin chaud.
- Mode WAL + `busy_timeout` sur les deux bases SQLite (écritures concurrentes
  sans blocage). Voir la note de sauvegarde `-wal`/`-shm` du README.

### Tests
- Filtres d'inspection restreints aux ports Pulse (configuré, 8765, 5000
  historique) et au chemin `/activities` exact : les commandes de dev locales
  (`curl localhost:3000/…`) ne sont plus supprimées de la trace.
- Tests temporels ancrés sur un horodatage fixe via l'injection `now=` dans
  `build_daily_trace` ; nouveaux tests de frontière de jour aux changements
  d'heure (DST). Fin des échecs intermittents entre 00h et 03h.
- Suite portée à 340 tests.

### Interne
- `select_database_path` déplacée dans `runtime_config` (sans Flask) pour que
  les outils CLI n'importent plus Flask.
