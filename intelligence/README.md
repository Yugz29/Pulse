# Pulse Intelligence — guide d'usage

Couche Intelligence de Pulse (pas 3 de la roadmap, voir `../docs/VISION.md`).
Elle lit les sessions closes exposées par Pulse Core, les fait résumer par un
modèle local, et réémet le résumé vers Core comme événement `session_summary`.
Core ne sait pas qu'elle existe.

Le journal et `/context/sessions` partagent la reconstruction Core v3. Core
expose les observations ordonnées v1 dans son API v3. Intelligence les transmet
sans UUID sources ni faits `window` (qu'aucun prompt ne décrit, addendum du
2026-09-13 à la [décision contexte de fenêtre](../docs/decisions/2026-09-12-contexte-de-fenetre.md))
et ajoute des relations de résultats de commandes, bornées
à la session : entrée v3, prompt v5. L'état actuel reste explicitement inconnu.
Voir la [décision courante](../docs/decisions/2026-09-08-reprise-fondee.md) et le
[bilan des évaluations](../docs/audits/README.md).
Aucun service ni réglage personnel n'est activé par ce chantier.

## En bref

```
Core (:8765)  ──GET /context, /context/sessions──▶  Intelligence ──modèle──▶ résumé
      ▲                                                                          │
      └────────────────── POST /activities (session_summary) ◀──────────────────┘
```

Trois modèles interchangeables derrière une même interface, choisis par une
ligne de config :

- `mlx` — le modèle **local** sur Apple Silicon (`mlx-lm`). Le provider de
  production. Lent (dizaines de secondes par session), tout reste sur la machine.
- `openai-compatible` — un endpoint **distant** compatible OpenAI, pour
  comparer ou dépanner. Configuré par variables d'environnement, jamais dans un
  fichier.
- `fake` — une sortie fixe, pour les tests. Pas un vrai résumé.

## 1. Configuration

Tout vit dans **`~/.pulse_intelligence/`** (créé au premier écrit, permissions
`0700`/`0600`). La config est `~/.pulse_intelligence/config.toml` ; sans elle,
les défauts de `config.py` s'appliquent.

### Modèle local (le vôtre, pour le dogfooding)

```toml
# ~/.pulse_intelligence/config.toml
core_url      = "http://127.0.0.1:8765"
llm_provider  = "mlx"
model_id      = "mlx-community/Qwen3.8-27B-4bit"
prompt_version = "v6"         # reprise fondée sans annexes ; v5 avec annexes, v1–v4 historiques
llm_max_tokens = 2048          # sous 2048, des sessions denses sont tronquées
```

Le modèle (~14 Go) se télécharge au premier appel puis reste en cache. Il tient
en mémoire sur une session réelle ; une entrée au-dessus de `llm_max_input_tokens`
(défaut 30 000) est refusée avant de faire planter Metal — bruyamment : ligne
`⚠ failed …` sur stderr dans la sortie de `run` (donc dans `run.log` sous launchd).
Le compte de tokens (`prompt_tokens`) de chaque session est dans le `meta.json` d'`eval`.

### Endpoint distant (comparaison / dépannage)

```toml
# ~/.pulse_intelligence/config.toml
core_url     = "http://127.0.0.1:8765"
llm_provider = "openai-compatible"
```

Le point d'accès, le jeton et le nom du modèle viennent de l'environnement —
**jamais du dépôt** :

```bash
export PULSE_LLM_BASE_URL="https://…"     # racine de l'API
export PULSE_LLM_API_KEY="…"              # jeton
export PULSE_LLM_MODEL="…"                # nom du modèle côté endpoint
```

### Toutes les clés

| clé | défaut | rôle |
| --- | --- | --- |
| `core_url` | `http://127.0.0.1:8765` | Pulse Core |
| `core_timeout_s` | `60` | timeout HTTP par requête vers Core. `/context/sessions` reconstruit la journée à chaque appel : une journée chargée dépasse 5 s en production. Un GET qui échoue (timeout, connexion) est rejoué une fois après 2 s ; un POST jamais |
| `llm_provider` | `""` | `mlx` \| `openai-compatible` \| `fake` ; vide = refus de démarrer |
| `model_id` | `""` | identifiant du modèle (entre dans l'identité du résumé) |
| `llm_max_tokens` | `2048` | plafond de génération |
| `llm_max_input_tokens` | `30000` | au-delà, le modèle local refuse (mémoire) ; compté avec le tokenizer du modèle chargé |
| `llm_temperature` | `0.0` | envoyée à tous les providers : MLX la passe à `make_sampler`, soit l'argmax à `0.0` ; l'endpoint distant la reçoit, et s'il la refuse le provider la retire une fois et l'inscrit dans `dropped_parameters`. Réduit l'aléa sans garantir la reproductibilité tant que prompt, modèle, poids et runtime ne sont pas figés ([décision](../docs/decisions/2026-09-14-temperature-explicite.md)) |
| `prompt_version` | `v6` | reprise bornée à la session, sans annexes ; `v5` reçoit les annexes ; v1–v4 refusent cette entrée. `v6-sans-phrase`, `v6-sans-exemple`, `v6-sans-phrase-ni-exemple` : variantes du rejeu `open` du 2026-09-11 (`docs/dogfooding.md`, jour 7), pas des défauts |
| `tick_minutes` | `10` | intervalle de `run` sans `--once` |
| `min_session_minutes` | `10` | une session n'est écartée que si elle est **à la fois** plus courte que ce seuil et moins active que `min_session_activities` : atteindre l'un des deux suffit pour être candidate. Une session qui porte au moins un commit observé n'est jamais écartée pour sa durée, quels que soient les deux compteurs |
| `min_session_activities` | `30` | l'autre seuil de la même règle. Le journal de Core (`GET /`) applique ces deux défauts sans lire ce fichier et sans l'exception du commit : les changer ici décale son classement des sessions sans résumé, et il note « sous les seuils » une session courte à commit qu'Intelligence résume pourtant |

La fenêtre de sélection n'est plus une clé : `run` relit chaque jour depuis
celui du dernier passage complet (repère `last_complete_pass` dans
`state.json`, posé au début d'un passage qui a lu toute sa fenêtre et traité
chaque candidate), plafonné à sept jours en arrière — huit jours listés avec
aujourd'hui. Sans repère (premier passage, état perdu), la fenêtre est
pleine. `list` et `summarize <id>` lisent la même fenêtre. Un ancien
`config.toml` qui porte encore `lookback_days` est refusé comme clé
inconnue : retirer la ligne. Après un changement de `prompt_version` ou de
`model_id`, toute session de la fenêtre redevient candidate : deux jours en
régime quotidien, huit au pire après une semaine de lots manqués
([décision](../docs/decisions/2026-09-18-rattrapage-des-jours-non-resumes.md)).

## 2. Les commandes du quotidien

La commande est `pulse-intel` (dans la venv : `.venv/bin/pulse-intel`). Core
doit tourner ; sinon message et code 2.

### `list` — qu'est-ce qui est prêt à résumer ?

Lecture seule, n'appelle aucun modèle. Montre les sessions closes de la fenêtre,
candidates (`*`) ou non, avec la raison.

```
$ pulse-intel list
* work-3   2808ac8a3741f38a  2026-09-05 20:27–20:41   13 min   21 act.  core   candidate
  work-8   1a2b…              2026-09-05 18:02–18:07    5 min    4 act.  Pulse  trop courte (5 min, 4 activités)
```

### `run --once` — résumer toutes les candidates

Un passage : pour chaque session candidate, appelle le modèle, valide la sortie,
émet le `session_summary` vers Core. **Le plus long** (dizaines de secondes par
session avec le modèle local). Idempotent : une session déjà résumée n'est plus
candidate, le modèle n'est jamais rappelé pour elle.

```
$ pulse-intel run --once
[2026-09-05 22:41:03] candidates=2 replayed=0 created=2 duplicate=0 failed=0 given_up=0
  created 2808ac8a3741f38a event_id=882d8a86-…
  created 8af930d9ef437d2a event_id=26974b80-…
```

- `created` : résumé produit et émis.
- `duplicate` : Core avait déjà cet événement (rejeu inoffensif).
- `failed` : sortie rejetée (JSON invalide, chemin inventé…) ou entrée refusée
  par le modèle (plafond de tokens, HTTP 400) — réessai au passage suivant,
  trois fois puis `given_up`. Le budget est compté **par identité de résumé**
  (session, prompt, modèle) : changer de prompt ou de modèle ouvre une vraie
  nouvelle tentative. Une panne transitoire du modèle (délai dépassé, 5xx,
  erreur de génération) donne aussi `failed`, mais ne consomme pas le budget :
  une session n'est jamais abandonnée pour une panne.
- modèle indisponible pour toutes (runtime absent, poids non chargés, endpoint
  injoignable) : le passage s'arrête à la première candidate, `passage
  interrompu : modèle indisponible …` sur stderr, code 2, aucune tentative
  consommée — comme un Core injoignable.
- `replayed` : payloads `pending` rejoués **avant** la sélection, tels que
  figés lors d'une panne Core, même si leur session est sortie de la fenêtre
  de rattrapage — sans modèle, sans commande datée. Un rejeu que Core refuse
  encore compte comme `failed` ; un `409` (Core détient déjà un résumé pour
  cette identité, par exemple après restauration d'une sauvegarde) reprend
  l'événement de Core en `already_known`, sans consommer le budget ; le
  `pending` d'une session `given_up` n'est pas rejoué, il reste sur disque et
  ne cache pas la session à un autre prompt ou modèle.

Code de sortie de `run --once`, le plus grave gagne :

| Passage | Code |
| --- | --- |
| aucune candidate, ou toutes `created` / `duplicate` / `already_known` | 0 |
| Core injoignable | 2 |
| au moins une candidate `failed` (réessayée au passage suivant) | 3 |
| au moins une candidate `given_up` (abandonnée, intervention nécessaire) | 4 |
| un autre `run` ou `summarize` tient déjà l'état (`state.json.lock`) : sortie immédiate, rien n'est lu ni écrit | 5 |
| Core sert un `schema_version` plus ancien que l'attendu (vue héritée sans `observations` : résumés émis sans `open` citable, avertissement sur stderr ; daemon Core à redémarrer) | 6 |

Reprendre une session abandonnée : `pulse-intel summarize <id> --retry` efface
son budget d'échecs (sous ses deux formes de clé, session et identité), rejoue
le payload figé s'il en reste un, sinon régénère. Sans `--retry`, `summarize`
sur une session `given_up` le reste.
Avec `--retry --dry-run`, la prévisualisation conserve le fichier d'état,
les compteurs d'échec et les payloads en attente ; aucun abandon n'est levé.

Sans `--once`, `run` refait un passage toutes les `tick_minutes` jusqu'à Ctrl-C.

### `show` — lire un résumé

```
$ pulse-intel show latest --md        # la reprise seule, trois lignes
Tu corriges la résolution de casse du watcher de fichiers.
Après le troisième commit, suite verte.
La déduplication des workspaces n'est pas encore couverte par un test.

$ pulse-intel show latest             # l'événement complet, en JSON

$ pulse-intel show a0aacd1f           # un préfixe d'identifiant suffit
session         a0aacd1f17723f56  work-2  2026-09-06 00:26–00:39
résumé          v2  mlx-community/Qwen3.8-27B-4bit  généré 2026-09-06 09:47
confidence      medium
doing           Tu implémentes le module intelligence avec un corpus gelé…
stopped_at      Après le commit 1e893f6 (MLXProvider), sans push observé.
open            Le push n'a pas été observé ; la configuration de llm_max_tokens…
  ↳ reçu        (aucune annexe previous_summary)
central_files   []

$ pulse-intel show a0aacd1f --all     # tous les résumés coexistants (v1, v2…)
$ pulse-intel show a0aacd1f --json    # l'événement émis, tel quel
```

La ligne `↳ reçu` met le `open` de l'annexe `previous_summary` — ce que le
modèle a reçu — juste sous le `open` qu'il a produit : c'est le jugement du
défaut D1 (`docs/dogfooding.md`) d'un coup d'œil. L'annexe est conservée dans
l'état local à l'émission ; un résumé antérieur à cet enregistrement affiche
« inconnue », jamais « aucune ». Un préfixe ambigu est refusé avec la liste
des sessions qu'il désigne.

### `open` : observations et interprétations

Un point ouvert est un constat utile à la reprise, positivement appuyé et
sans résolution correspondante observée dans la session. Il n'est pas une
recommandation ni une affirmation sur l'état actuel. Deux appuis :

- `command_failure` : référence au dernier échec d'une commande exacte dans
  son cwd, sans résolution observée. Le code concerne le processus global.
- `recorded_statement` : déclaration explicite dans un commit, avec citation
  exacte. Sa pertinence est interprétée ; la citation ne prouve pas sa vérité.
  La citation reste exigée du modèle et validée ; dans `reprise.open`, elle
  n'est **affichée** que si elle ajoute au texte (`quote_adds_to_text`,
  2026-09-17). Texte et citation sont comparés une fois rendus comparables :
  NFKC, casse repliée, toute ponctuation et tout symbole remplacés par une
  espace (apostrophes et guillemets compris), blancs réduits. La citation est
  omise si elle est alors vide, égale au texte, ou contenue dans le texte
  comme suite de mots entiers, dans l'ordre ; elle est gardée dans tous les
  autres cas, y compris quand c'est le texte qui est contenu dans la
  citation. Rendu seulement : ni le prompt, ni `open_items`, ni le contrat
  ne changent. `reprise.open` est composé à la génération et stocké dans
  l'événement : la règle ne vaut que pour les résumés à venir, les résumés
  déjà stockés gardent leur texte (sur 9 points stockés au 17, un seul,
  `b6262f70`, portait le doublon).

`resumption.command_outcomes` distingue `resolved_observed`,
`unresolved_observed` et `unknown`. `as_of` borne l'interprétation à la session.
Un résultat ultérieur 0 n'établit une résolution que pour le même processus
identifié, sans chevauchement avec l'échec. Fichiers, Git, distant et contenu
des commits ne se résolvent pas par corrélation.

Les anciens résumés sont du contexte `previous_model_interpretation`, daté,
non admissible comme preuve. Les demandes initiales d'agent restent des intentions
à accomplissement inconnu. `carried_over` et `requested` ne sont plus produits
par v5 ; une liste vide est normale. Les lectures et rejeux historiques restent
possibles sans aucune conversion des événements.

Le validateur contrôle le schéma, les types de références, la relation de
résultat et la présence littérale d'une citation (espaces et retours à la ligne normalisés). Il ne vérifie pas la cause,
le sens de la citation ou l'utilité d'un point. Aucune regex sémantique ne s'y
substitue. La qualité du modèle est mesurée séparément.

Core conserve le texte rendu et masqué dans `reprise.open`, les métadonnées
fermées dans `open_items` (`kind`, `evidence`, `scope: session_end`), ainsi que
`observation_version` et `observation_sources`. Les citations libres ne sont
pas recopiées hors du champ masqué.

Une configuration épinglant v1–v4 doit choisir v5 pour générer avec l'entrée
courante. Les prompts v1–v4 sont conservés tels qu'envoyés au modèle : le v3
annonce encore le rejet D6 (« la note serait rejetée »), supprimé avec les
filtres lexicaux D5/D6 ([décision observations ordonnées](../docs/decisions/2026-09-08-observations-ordonnees.md)) ;
une sortie v3 rejouée aujourd'hui n'est plus rejetée pour ce motif. Les
anciennes vues Core restent lisibles en `legacy_aggregates`, sans chronologie
inventée. Le défaut de code v5 ne constitue pas une validation
de qualité pour l'usage quotidien : consulter le verdict du rapport.

Si Core a accepté un résumé mais que sa relecture après émission a échoué,
`show` récupère la copie manquante par son identifiant enregistré, même après
un changement de prompt ou de modèle. Cela s'applique aussi aux préfixes et à
`--all`, sans réécrire l'état local. Si la copie demandée reste inaccessible,
la commande sort en erreur (code 2) au lieu d'afficher un ancien résumé.

### `eval` — comparer un modèle sur le corpus gelé

Passe le modèle courant sur les 14 sessions de `eval/observed/` (dix gelées et quatre
cas supplémentaires issus du dogfooding), écrit un
résultat par session sous `eval/out/<provider>-<modèle>/` plus un `meta.json`.
Ne touche pas Core, ne dépend pas de la trace. Sert à juger un modèle ou un
changement de prompt avant de l'activer.

```
$ pulse-intel eval --provider mlx
  ✓ work-6   3cabaefb759dae36   20901tok  192212ms  La plus grosse…
  ✗ work-3   2ce344566f7e85dc    1993tok   23053ms  central_files: … absent de l'entrée
  …
  8/10 valides -> eval/out/mlx-mlx-community-Qwen3.8-27B-4bit
```

### Version de reconstruction de Core

Chaque vue de session porte `reconstruction_version` (Core : 3 depuis le
2026-09-06). Le code d'Intelligence déclare celle sur laquelle il a été
validé (`KNOWN_RECONSTRUCTION_VERSION`). Si Core en sert une autre — daemon
resté sur un ancien code, ou constante à relire — chaque commande l'annonce
sur stderr au premier `/context/sessions` (donc dans `run.log`), et `eval`
l'annonce aussi pour son corpus, dont `meta.json` note les versions figées
(`corpus_reconstruction_versions`) et la version connue. Le corpus actuel a
été capturé sous la v2 : l'avertissement est attendu jusqu'à sa recapture.

### Le passage quotidien via launchd

`run --once` chaque matin, sans y penser :

```bash
cd intelligence
scripts/install_run_launchd.sh                      # chaque jour à 06:30
PULSE_INTEL_RUN_HOUR=7 PULSE_INTEL_RUN_MINUTE=0 scripts/install_run_launchd.sh
scripts/install_run_launchd.sh --uninstall
```

Installe `~/Library/LaunchAgents/com.pulse.intelligence-run.plist` (même
patron que les agents de Core), qui lance `scripts/pulse_intel_run.sh` — le
`pulse-intel` de la venv, sur la config du poste, sous `caffeinate -i` (pas
de veille d'inactivité pendant le passage). Tâche calendaire : si le Mac
dort à l'heure dite, launchd la rattrape au réveil ; capot fermé sur
batterie, le lot avance par DarkWake et se termine à l'ouverture ; une
requête vers Core coupée par la veille est rejouée une fois au réveil
(`core_timeout_s`). Journal : `~/.pulse_intelligence/logs/run.log`. Le
matin couvre la veille entière, et les jours manqués depuis le dernier
passage complet (sept au plus) : une session close après le passage est
prise le lendemain, un lot qui n'a pas tourné est rattrapé par le suivant.

## 3. Lire un résumé

Un `session_summary` a deux moitiés :

- **`reprise`** — trois phrases écrites pour vous, à la deuxième personne :
  `doing` (ce sur quoi vous travailliez), `stopped_at` (où vous vous êtes
  arrêté), `open` (constats utiles à reprendre, bornés aux observations de la session). C'est ce que `show … --md` affiche.
- **`structured`** — de quoi filtrer et relier : `project`, `intents`,
  `central_files` (uniquement des chemins **réellement vus** dans la session —
  un chemin inventé fait rejeter le résumé), `blockers`, et `confidence`
  (`high` si commits + tests + fichiers concordent, `medium` si des fichiers
  sans commit, `low` si surtout du bruit d'apps).

La confiance annoncée par le modèle ne suffit pas à juger la justesse :
une sortie précise peut inventer un état, même lorsque les observations sont exactes.

## Principes (spec §3)

- **Core ne sait pas qu'Intelligence existe.** Lecture par `GET /context` et
  `GET /context/sessions`, écriture par `POST /activities`. Aucun import de
  `daemon_v2` (un test le garantit). Venv séparée.
- **Intelligence ne reconstruit rien** : les sessions arrivent déjà bornées,
  avec leur identité stable (hash des `event_id`).
- **Tout ce que le modèle écrit est non fiable** : schéma validé, chemins cités
  présents dans l'entrée, chaînes bornées à 300 caractères, rédaction par Core à
  l'ingestion. Une sortie non conforme est rejetée, jamais réparée.

## Installation et tests

```bash
cd intelligence
uv venv --python 3.14
uv pip install -e '.[dev]'          # ajouter ',mlx' pour le modèle local
.venv/bin/python -m pytest -q       # suite par défaut (hors modèle)
.venv/bin/python -m pytest -m slow  # charge le vrai modèle MLX
```

Les tests `slow` partagent un chargement des poids et vérifient les prompts
archivés sur leur ancien contrat ainsi que v5 sur une session réelle du corpus : génération, absence de balises de
raisonnement et sortie conforme au contrat. Un troisième test vérifie le refus
de l'entrée de stress avec le vrai tokenizer ; un garde de test interdit de
lancer la génération si ce refus régresse. Ces tests ne mesurent pas à eux
seuls la justesse des résumés.
Un quatrième test relie la CLI au vrai modèle et à un Core temporaire : résumé
accepté, copie locale conforme, affichage et seconde exécution sans recharger
le modèle ni créer de doublon.
Pour évaluer aussi les sessions ambiguës, longues ou enrichies d'un résumé
précédent, passer le corpus complet puis lire les sorties :

```bash
TZ=Europe/Paris HF_HUB_OFFLINE=1 .venv/bin/python -m pulse_intelligence.cli \
  eval --provider mlx --out /private/tmp/pulse-eval-mlx
```

Ce mode hors ligne nécessite le modèle déjà présent en cache. La sortie hors
du dépôt évite que le watcher transforme les résultats de l'évaluation en
activités. Utiliser un nouveau dossier `--out` pour conserver chaque passage.

La suite par défaut inclut deux familles de parcours sans modèle MLX.
`test_cli_process_lock.py` lance la CLI dans des processus distincts contre le
faux Core et vérifie le verrou d'exécution, sa libération après `SIGKILL` et
la lecture (`list`) pendant qu'un producteur le tient.
`test_real_core_integration.py` lance un vrai Core sur une base temporaire et
vérifie la reprise d'un résumé déjà accepté après `SIGKILL`, la restauration
d'une sauvegarde en conflit et la relecture des résumés après une panne, avec
le masquage des secrets par Core. Les arrêts des processus enfants sont
synchronisés par un marqueur sur un pipe, à des étapes précises.

Pour lancer uniquement ces parcours (macOS/Linux, ports locaux nécessaires) :

```bash
.venv/bin/python -m pytest -q tests/test_cli_process_lock.py tests/test_real_core_integration.py
```
