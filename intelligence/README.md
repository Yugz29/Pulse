# Pulse Intelligence

Couche Intelligence de Pulse (pas 3 de la roadmap, voir `../docs/VISION.md`).
Premier composant : le résumé de session, spec v2 dans
`../docs/specs/2026-09-03-session-summary.md`.

État : **CLI complète avec faux modèle** (étapes 1 et 2 du §12). Sélection
des sessions closes, entrée du modèle, parsing et validation de sa sortie,
événement `session_summary`, émission idempotente avec état local, CLI
`list`, `summarize`, `run`, `show`. Pas encore de modèle MLX ni de prompt
(étape 3), ni de service résident (étape 5).

## Principes (spec §3)

- **Core ne sait pas qu'Intelligence existe.** Lecture par `GET /context`
  et `GET /context/sessions`, écriture par `POST /activities`. Aucun import
  de `daemon_v2` (un test le garantit). Venv séparée de Core.
- **Intelligence ne reconstruit rien.** Les sessions closes arrivent de Core
  déjà bornées, avec leur identité stable (hash des `event_id` sources).
- **Le modèle est un détail d'implémentation** : interface `Summarizer`,
  `FakeSummarizer` pour l'instant.
- **Tout ce que le modèle écrit est non fiable** : schéma, chemins cités
  présents dans l'entrée, chaînes bornées à 300 caractères, puis rédaction
  par Core à l'ingestion.

## Structure

```
pulse_intelligence/
  config.py            # config.toml, défauts, validation
  core_client.py       # GET /context, GET /context/sessions, POST /activities
  summarizer.py        # interface Summarizer + FakeSummarizer
  selection.py         # sessions candidates, avec raison
  session_input.py     # vue de session → entrée du modèle (+ annexes)
  session_summary.py   # parsing, validation, événement, summarize_session()
  state.py             # état local (~/.pulse_intelligence/state.json, 0700/0600)
  cli.py               # pulse-intel list | summarize | run | show
scripts/fix_permissions.sh   # ~/.pulse_intelligence en 0700/0600, idempotent
tests/                 # faux Core Flask + faux modèle, aucun test ne charge MLX
```

## Installation et tests

```bash
cd intelligence
python3.14 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

## Usage (étapes 1 et 2)

```bash
pulse-intel list                                          # sessions closes d'aujourd'hui et d'hier
pulse-intel list --date 2026-09-02 --json
pulse-intel summarize <id> --dry-run --fake sortie.json   # tout sauf l'émission
pulse-intel run --once --fake sortie.json                 # toutes les candidates, un passage
pulse-intel show latest --md                              # la dernière reprise, trois lignes
pulse-intel show <id>                                     # l'événement émis (copie locale)
```

`--fake FICHIER` est obligatoire pour `summarize` et `run` tant qu'il n'y a
pas de vrai modèle. L'état local `~/.pulse_intelligence/state.json` retient
ce qui a été résumé et ce qui a échoué trois fois : ces sessions ne sont plus
candidates, le modèle n'est jamais recontacté pour elles. Il retient aussi,
gelé avant le POST, le payload d'un résumé que Core n'a pas encore confirmé :
le passage suivant le renvoie octet pour octet, sans rappeler le modèle.
`run` sans `--once` refait un passage toutes les `tick_minutes` jusqu'à
Ctrl-C.

Core arrêté : message et code de sortie 2. Un Core en `schema_version` ≠ 2
est refusé (Core ≥ 0.5.0 requis).

## Configuration

`~/.pulse_intelligence/config.toml` (défauts dans `config.py`) :

```toml
core_url = "http://127.0.0.1:8765"
model_id = ""            # obligatoire pour le vrai modèle ; vide = refus de démarrer
prompt_version = "v1"
tick_minutes = 10
generation_timeout_s = 120
min_session_minutes = 10
min_session_activities = 30
lookback_days = 1
```
