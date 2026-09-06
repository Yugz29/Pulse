# Pulse Intelligence — guide d'usage

Couche Intelligence de Pulse (pas 3 de la roadmap, voir `../docs/VISION.md`).
Elle lit les sessions closes exposées par Pulse Core, les fait résumer par un
modèle local, et réémet le résumé vers Core comme événement `session_summary`.
Core ne sait pas qu'elle existe.

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
| `llm_provider` | `""` | `mlx` \| `openai-compatible` \| `fake` ; vide = refus de démarrer |
| `model_id` | `""` | identifiant du modèle (entre dans l'identité du résumé) |
| `llm_max_tokens` | `2048` | plafond de génération |
| `llm_max_input_tokens` | `30000` | au-delà, le modèle local refuse (mémoire) |
| `llm_temperature` | `null` | absente = non envoyée (le modèle local reste alors en argmax) ; `0.0` réduit l'aléa de l'échantillonnage, sans garantir la reproductibilité tant que prompt, modèle, poids et runtime ne sont pas figés |
| `prompt_version` | `v2` | version du prompt (`prompts/session_summary_<v>.md`) ; `v1` reste disponible, `v3` produit des points `open` référencés (voir plus bas) |
| `tick_minutes` | `10` | intervalle de `run` sans `--once` |
| `min_session_minutes` | `10` | une session plus courte n'est pas candidate |
| `min_session_activities` | `30` | une session moins active n'est pas candidate |
| `lookback_days` | `1` | fenêtre : aujourd'hui + N jours en arrière |

## 2. Les commandes du quotidien

La commande est `pulse-intel` (dans la venv : `.venv/bin/pulse-intel`). Core
doit tourner ; sinon message et code 2.

### `list` — qu'est-ce qui est prêt à résumer ?

Lecture seule, n'appelle aucun modèle. Montre les sessions closes de la fenêtre,
candidates (`*`) ou non, avec la raison.

```
$ pulse-intel list
* work-3   2808ac8a3741f38a  2026-09-05 20:27–20:41   13 min   21 act.  core   candidate
  work-8   1a2b…              2026-09-05 18:02–18:07    5 min    4 act.  Pulse  trop courte (5 min < 10)
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
  `lookback_days` — sans modèle, sans commande datée. Un rejeu que Core refuse
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

### `open` v3 : des points étayés

Avec `prompt_version = "v3"`, `open` n'est plus une phrase libre mais une
liste de points, chacun d'une nature déclarée et étayé par des références de
l'entrée :

```json
{"text": "Aucun push observé pour les commits a1b2c3 et d4e5f6",
 "kind": "observed", "evidence": ["commit:a1b2c3", "commit:d4e5f6"]}
{"text": "La configuration de llm_max_tokens reste à valider",
 "kind": "carried_over", "evidence": [], "carried_from": "previous_summary:1",
 "reason_kept": "aucun événement sur config.toml depuis le résumé précédent"}
{"text": "L'agent devait vérifier l'état de la PR #28",
 "kind": "requested", "evidence": ["agent_request:0"]}
```

Le validateur rejette la note entière si : `kind` est inconnu ; un point
`observed` n'a pas de preuve, cite une référence absente de l'entrée ou
s'appuie sur une annexe ; un point `carried_over` ne désigne pas un point
réel de `previous_summary` ou n'a pas de `reason_kept` ; un point
`requested` cite autre chose que `agent_request:<i>` ; un texte reprend un
point de `previous_summary` sans `kind: carried_over` (D1) ; un point
`observed` affirme qu'un push n'a pas été effectué (D5 — Core n'observe pas
les pushs). Les références s'écrivent `<type>:<clé>` avec la clé telle que
Core la sert : `path:`, `commit:`, `event:`, `app:`, `test_passed:`,
`test_failed:`, `error:`, `signal:`, `agent_request:0`,
`previous_summary:<i>` (le i-ième point du `open` reçu, listé dans
`previous_summary.open_items` de l'entrée). Aucune référence n'existe pour
une absence.

Core ne change pas : il reçoit `reprise.open` rendu en texte (une phrase par
point, la raison d'une reprise entre parenthèses, une phrase fixe pour une
liste vide) et recopie `details.open_items` — nature, preuves,
`carried_from`, jamais de texte libre hors des champs qu'il rédige. Les
résumés v1/v2 déjà en base gardent leur `open` en chaîne ; `show` les affiche
comme avant et, pour un résumé v3, liste sous `open` chaque point avec sa
nature et ses preuves.

Les attentes annotées des quatre sessions D1/D3/D5 sont dans
`eval/expected/` ; après un passage `eval` en v3, l'écart par session est
imprimé (retrouvé, manquant, interdit, en plus), et
`PULSE_EVAL_RUN=<dossier> pytest -m slow tests/test_expectations.py` le rejoue
comme test.

Si Core a accepté un résumé mais que sa relecture après émission a échoué,
`show` récupère la copie manquante par son identifiant enregistré, même après
un changement de prompt ou de modèle. Cela s'applique aussi aux préfixes et à
`--all`, sans réécrire l'état local. Si la copie demandée reste inaccessible,
la commande sort en erreur (code 2) au lieu d'afficher un ancien résumé.

### `eval` — comparer un modèle sur le corpus gelé

Passe le modèle courant sur les 14 sessions de `eval/` (dix gelées et quatre
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
`pulse-intel` de la venv, sur la config du poste. Tâche calendaire : si le Mac
dort à l'heure dite, launchd la rattrape au réveil. Journal :
`~/.pulse_intelligence/logs/run.log`. Le matin couvre la veille entière (la
fenêtre de `run` est « aujourd'hui + hier ») : une session close après le
passage est prise le lendemain.

## 3. Lire un résumé

Un `session_summary` a deux moitiés :

- **`reprise`** — trois phrases écrites pour vous, à la deuxième personne :
  `doing` (ce sur quoi vous travailliez), `stopped_at` (où vous vous êtes
  arrêté), `open` (ce qui reste ouvert). C'est ce que `show … --md` affiche.
- **`structured`** — de quoi filtrer et relier : `project`, `intents`,
  `central_files` (uniquement des chemins **réellement vus** dans la session —
  un chemin inventé fait rejeter le résumé), `blockers`, et `confidence`
  (`high` si commits + tests + fichiers concordent, `medium` si des fichiers
  sans commit, `low` si surtout du bruit d'apps).

Un `confidence: low` ou une `reprise` vague veut souvent dire que la session
elle-même était diffuse — pas que le résumé a raté.

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

Les tests `slow` partagent un chargement des poids et vérifient les prompts v1
et v2 sur une session réelle du corpus : génération, absence de balises de
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
