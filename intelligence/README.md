# Pulse Intelligence

Couche Intelligence de Pulse (pas 3 de la roadmap, voir `../docs/VISION.md`).
Premier composant : le résumé de session, spec v2 dans
`../docs/specs/2026-09-03-session-summary.md`.

État : **squelette** (étape 1 du §12). Sélection des sessions closes,
entrée du modèle, parsing et validation de sa sortie, construction de
l'événement `session_summary`, CLI `list` et `summarize --dry-run` avec un
faux modèle. Pas encore de modèle MLX, de prompt, de job résident ni d'API :
étapes 2 à 5.

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
  cli.py               # pulse-intel list | summarize
tests/                 # faux Core Flask + faux modèle, aucun test ne charge MLX
```

## Installation et tests

```bash
cd intelligence
python3.14 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

## Usage (étape 1)

```bash
pulse-intel list                                          # sessions closes d'aujourd'hui et d'hier
pulse-intel list --date 2026-09-02 --json
pulse-intel summarize <id> --dry-run --fake sortie.json   # tout sauf l'émission
```

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
