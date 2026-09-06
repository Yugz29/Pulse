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
(défaut 30 000) est refusée avant de faire planter Metal.

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
| `llm_temperature` | `null` | absente = non envoyée ; `0.0` = reproductible |
| `prompt_version` | `v2` | version du prompt (`prompts/session_summary_<v>.md`) ; `v1` reste disponible |
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
[2026-09-05 22:41:03] candidates=2 created=2 duplicate=0 failed=0 given_up=0
  created 2808ac8a3741f38a event_id=882d8a86-…
  created 8af930d9ef437d2a event_id=26974b80-…
```

- `created` : résumé produit et émis.
- `duplicate` : Core avait déjà cet événement (rejeu inoffensif).
- `failed` : sortie rejetée (JSON invalide, chemin inventé…) — réessai au
  passage suivant, trois fois puis `given_up`.

Sans `--once`, `run` refait un passage toutes les `tick_minutes` jusqu'à Ctrl-C.

### `show` — lire un résumé

```
$ pulse-intel show latest --md        # la reprise seule, trois lignes
Tu corriges la résolution de casse du watcher de fichiers.
Après le troisième commit, suite verte.
La déduplication des workspaces n'est pas encore couverte par un test.

$ pulse-intel show latest             # l'événement complet, en JSON
$ pulse-intel show <session_id>       # un résumé précis
```

### `eval` — comparer un modèle sur le corpus gelé

Passe le modèle courant sur les dix sessions figées de `eval/`, écrit un
résultat par session sous `eval/out/<provider>-<modèle>/` plus un `meta.json`.
Ne touche pas Core, ne dépend pas de la trace. Sert à juger un modèle ou un
changement de prompt avant de l'activer.

```
$ pulse-intel eval --provider mlx
  ✓ work-6   3cabaefb759dae36  ~ 6369tok  187366ms  La plus grosse…
  ✗ work-3   2ce344566f7e85dc  ~  427tok   22684ms  central_files: … absent de l'entrée
  …
  8/10 valides -> eval/out/mlx-mlx-community-Qwen3.8-27B-4bit
```

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
