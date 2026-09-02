# Spec — Context API (`GET /context`)

Pas 2 de la roadmap V3 (voir `docs/VISION.md`). Seul changement autorisé dans Core depuis le gel 0.2.0.

## 1. Objectif

Exposer, en JSON et sans aucun modèle, une réponse à la question **« que se passe-t-il en ce moment ? »**, calculée à partir de `trace.db`. C'est le contrat stable entre Core et la couche Intelligence : Intelligence ne connaîtra jamais les tables SQLite, elle connaîtra ce JSON.

Cette route est le socle du pas 3 (résumé de session par modèle local). Sa sortie doit pouvoir être donnée telle quelle à un prompt.

## 2. Non-objectifs

- Aucune interprétation : pas de « il refactorise le parseur ». Des faits agrégés, c'est tout.
- Aucun rendu : pas de chaînes françaises formatées façon `build_session_summary`. Des champs typés.
- Pas de nouvelle source d'observation, pas de nouveau type d'événement, pas de modification du schéma de `trace.db`.
- Pas de remplacement de `/trace/today.json` : celui-là reste la vue exhaustive d'une journée. `/context` est une vue fenêtrée et compacte du présent.
- Pas d'authentification, pas de CORS : localhost uniquement, comme le reste.

## 3. Contrat

### Requête

```
GET /context
GET /context?window=120        # minutes, défaut 120, min 5, max 1440
GET /context?at=2026-09-02T14:00:00Z   # instant de référence, défaut now (tests)
```

`window` invalide → 400, même forme d'erreur que les routes existantes (`{"error": "..."}`).
`at` invalide → 400. Un `at` dans le futur est accepté (il ne change rien).

### Réponse — `200 application/json`

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-02T15:52:10+00:00",
  "reference_at":  "2026-09-02T15:52:10+00:00",
  "window_minutes": 120,
  "timezone": "Europe/Paris",

  "workspace": {
    "path": "/Users/yugz/Projets/Pulse",
    "project": "Pulse",
    "resolution": "session",
    "git": {
      "branch": "main",
      "dirty": false,
      "last_commit": {
        "hash": "6264d1a",
        "message": "chore: restructuration en repo unique, archivage de Lab, ajout de VISION.md",
        "occurred_at": "2026-09-02T15:40:02+00:00"
      }
    }
  },

  "current_session": {
    "id": "…",
    "started_at": "2026-09-02T13:40:00+00:00",
    "last_activity_at": "2026-09-02T15:51:48+00:00",
    "duration_minutes": 132,
    "is_open": true,
    "activity_count": 214,
    "projects": ["Pulse"],
    "apps": [
      {"name": "Terminal", "activations": 41},
      {"name": "Code",     "activations": 12}
    ],
    "files": {
      "created":  ["docs/VISION.md", "intelligence/README.md"],
      "modified": ["core/README.md", ".gitignore"],
      "deleted":  [],
      "truncated": false
    },
    "git": {
      "commits": [
        {"hash": "6264d1a", "message": "chore: restructuration en repo unique…"}
      ],
      "push_observed": true
    },
    "terminal": {
      "tests_passed": ["pytest -q"],
      "tests_failed": [],
      "errors": ["git push origin main --tags"],
      "truncated": false
    },
    "signals": ["git_commit", "terminal_finished", "file_changed", "app_activated"]
  },

  "recent_sessions": [
    {
      "id": "…",
      "started_at": "…",
      "ended_at": "…",
      "duration_minutes": 47,
      "projects": ["Pulse"],
      "headline": {
        "commits": 1,
        "files_changed": 6,
        "tests_failed": 0,
        "errors": 0
      }
    }
  ],

  "isolated_signals": [
    {"type": "git_commit", "occurred_at": "…", "summary": "…"}
  ],

  "last_agent_session": {
    "agent": "claude_code",
    "started_at": "…",
    "ended_at": "…",
    "workspace": "/Users/yugz/Projets/Pulse",
    "summary": "Restructuration de Pulse en repo unique…",
    "age_minutes": 7
  }
}
```

### Sémantique champ par champ

| Champ | Règle |
|---|---|
| `schema_version` | Entier, `1`. Toute modification incompatible incrémente. Ajout de champ optionnel = compatible. |
| `reference_at` | `at` si fourni, sinon `now` en UTC. Tout le calcul est relatif à cet instant. |
| `timezone` | Celle de `_trace_timezone()`, informative seulement — **tous les timestamps sont en UTC ISO 8601 avec offset**. |
| `workspace` | Résolu par le résolveur unique existant (`analysis/projects.py`). `resolution` ∈ `session` (workspace dominant de la session courante), `last_observed` (pas de session courante, dernier workspace vu dans la fenêtre), `none`. Quand `none`, `workspace` vaut `null`. |
| `workspace.git` | Repris des détails **persistés** des événements (règle du 2026-08-30 : jamais l'état du disque au moment du rendu). `null` si aucun événement de la fenêtre ne porte d'info git pour ce workspace. |
| `current_session` | La session dont `last_activity_at` est la plus récente **et** postérieure à `reference_at − session_gap` (le gap déjà utilisé par `session_tracker`). `is_open` = `true` dans ce cas. Si aucune session ne satisfait ça, `current_session` vaut `null`. On ne met **pas** la dernière session fermée à la place : « rien en cours » est une information. |
| `current_session.apps` | Triées par activations décroissantes puis nom. `IGNORED_APP_NAMES_FOR_RENDERING` s'applique. Max 5. |
| `current_session.files` | Chemins relatifs au workspace quand possible (même logique que `_display_file_path`). Dédupliqués, ordre de première apparition. Max 20 par catégorie, `truncated: true` si coupé. |
| `current_session.terminal` | Réutilise `useful_command_lines`, `terminal_labels`, `is_interrupted_exit`, `is_pasted_prompt_command`. Une commande interrompue n'est pas une erreur. Max 10 par liste. |
| `current_session.signals` | Types d'activité présents dans la session, ordre fixe = ordre de `SUPPORTED_ACTIVITY_TYPES` trié. Pas de doublon. |
| `recent_sessions` | Les sessions **fermées** dont `ended_at` ≥ `reference_at − window`, hors session courante, les plus récentes d'abord, max 3. Forme compacte uniquement. |
| `isolated_signals` | Les activités isolées (règle du 2026-08-30 : un signal fort seul ne crée pas de session) dans la fenêtre, max 10, plus récentes d'abord. |
| `last_agent_session` | Le dernier événement `agent_session` **sans limite de fenêtre** (une reprise a besoin du dernier résumé même s'il date d'hier). `null` si aucun. `summary` = le résumé figé de l'événement, jamais le transcript. |

### Ce que la réponse ne contient jamais

- Contenu de commandes non « utiles » au sens de `useful_command_lines`.
- Texte de prompts collés (règle du 2026-08-30).
- Transcripts d'agents.
- Chemins absolus hors du workspace quand un chemin relatif existe.
- Toute chaîne produite par un renderer (`render_*`).

## 4. Déterminisme

Même base + même `at` + même `window` → **même JSON, octet pour octet**. Concrètement :

- Toutes les listes ont un ordre défini (spécifié ci-dessus), jamais l'ordre d'itération d'un `set` ou d'un `dict` non trié.
- Sérialisation avec `sort_keys=True`.
- Aucune lecture du disque, de git, de l'horloge (hors `generated_at`, qui est le seul champ non déterministe et qui est exclu de la comparaison dans les tests) ni du réseau.
- `generated_at` est le seul champ autorisé à différer entre deux appels identiques.

## 5. Implémentation

### Module pur : `daemon_v2/context_snapshot.py`

```python
def build_context_snapshot(
    store: TraceStore,
    *,
    reference_at: datetime,
    window_minutes: int = 120,
) -> dict[str, Any]: ...
```

- Entrée : le store + un instant + une fenêtre. Sortie : un dict JSON-sérialisable.
- Réutilise `reconstruct_session_views`, le résolveur de workspace, `parse_status_output`, et les helpers de `analysis/terminal.py`. **Aucune duplication** de logique de classification : si un helper manque, il est ajouté dans `analysis/` et utilisé par les deux consommateurs.
- Ne connaît ni Flask, ni le rendu.

### Route : `daemon_v2/routes.py`

```python
@api.get("/context")
def get_context(): ...
```

Parse `window` et `at`, appelle `build_context_snapshot`, retourne `jsonify` avec `sort_keys`. Rien d'autre.

### Statut : `scripts/status.sh` et `/status`

Ajoute une ligne `Contexte : session en cours depuis 2 h 12 · Pulse` (ou `aucune session en cours`) alimentée par `/context`. C'est la preuve d'usage minimale : le status consomme le contrat.

### Ce qui ne change pas

- `daily_trace.py` et les renderers HTML/Markdown : intacts dans ce chantier. La migration du HTML vers `/context` est un chantier ultérieur, pas celui-ci. On ajoute un consommateur, on n'en refactorise pas.
- `trace_store.py`, `session_tracker.py`, `models.py` : aucune modification. Si une lecture manque dans `TraceStore`, elle est ajoutée en lecture seule et testée séparément.

## 6. Tests — `tests_v2/test_context_snapshot.py`

Style existant : fixtures SQLite en mémoire, pas de mocks de Flask.

**Déterminisme**
- Deux appels identiques → dicts égaux hors `generated_at`.
- Le JSON sérialisé est stable (comparaison de chaînes).

**Cas nominaux**
- Session ouverte avec fichiers, commits, tests, apps → tous les blocs remplis et bornés.
- `window` couvre une session fermée + la courante → `recent_sessions` contient la fermée seulement.

**Cas limites** (chacun est un test)
- Base vide → `current_session`, `workspace`, `last_agent_session` à `null`, listes vides, 200.
- Dernière activité plus vieille que le gap → `current_session: null`, `workspace.resolution: last_observed` si une activité est dans la fenêtre.
- Activités présentes mais toutes hors fenêtre, sauf un `agent_session` ancien → `last_agent_session` rempli, le reste `null`/vide.
- Session sans workspace résolu (que des `app_activated`) → `workspace: null`, `resolution: none`, session quand même retournée.
- Deux workspaces dans la session → `projects` en contient deux, `workspace` = le dominant.
- Signal fort isolé dans la fenêtre → dans `isolated_signals`, pas dans `current_session`.
- Commande interrompue (exit 130) → absente de `terminal.errors`.
- Prompt collé au shell → jamais dans la réponse.
- 25 fichiers modifiés → 20 retournés, `truncated: true`.

**Route**
- `GET /context` → 200, `schema_version: 1`.
- `window=0`, `window=abc`, `window=99999` → 400.
- `at=2026-09-02T14:00:00Z` → `reference_at` renvoyé à l'identique en UTC.
- `at=hier` → 400.

## 7. Critères d'acceptation

1. `curl -s :8765/context | jq .current_session.projects` renvoie le bon projet pendant une vraie session de travail.
2. Tous les tests ci-dessus passent, suite complète toujours verte (≥ 432 + les nouveaux).
3. Aucune ligne de `daily_trace.py`, `trace_store.py`, `session_tracker.py`, `models.py` modifiée (vérifié au diff).
4. `VISION.md` : ligne « Le Context API manque encore » mise à jour ; `CHANGELOG.md` : entrée 0.3.0 ; `VERSION` : 0.3.0.
5. Un commit par étape logique, PR via le flux `ship/*` existant, message de PR en français.

## 8. Hors périmètre, explicitement

- Migration du renderer HTML vers `/context`.
- Toute forme de résumé textuel généré.
- WebSocket / streaming / push : `/context` est pull, point.
- Historique multi-jours : `window` max 24 h. Au-delà, c'est `/trace/<date>`.
