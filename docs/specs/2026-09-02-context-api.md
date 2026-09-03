# Spec — Context API (`GET /context`)

Pas 2 de la roadmap V3 (voir `docs/VISION.md`). Seul changement autorisé dans Core depuis le gel 0.2.0.

> Livré le 2026-09-02 dans Core 0.3.0 (branche `ship/context-api`). **`schema_version` 2 depuis Core 0.5.0** (2026-09-03) : l'`id` de session est un hash stable, plus un ordinal — voir la section « Identité stable » ci-dessous et la route `GET /context/sessions`. Ce document décrit **ce qui est livré** : les décisions d'implémentation prises pendant le chantier sont intégrées au contrat (§3) et récapitulées en §9, les limites connues en §10.

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

GET /context/sessions                  # sessions de travail closes du jour local
GET /context/sessions?date=2026-09-02  # d'une journée donnée ; at optionnel comme /context
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
    "id": "3f9c2a1b7e4d5c60",
    "label": "work-3",
    "source_event_ids": ["…", "…"],
    "reconstruction_version": 1,
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
      "id": "a81d0e7f2c93b415",
      "label": "work-2",
      "source_event_ids": ["…"],
      "reconstruction_version": 1,
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

  "last_session_summary": {
    "id": "a81d0e7f2c93b415",
    "label": "work-2",
    "session_ended_at": "…",
    "reprise": {"doing": "…", "stopped_at": "…", "open": "…"},
    "confidence": "high",
    "age_minutes": 930
  },

  "last_agent_session": {
    "agent": "claude-code",
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
| `schema_version` | Entier, `2` depuis Core 0.5.0 (`1` en 0.3.0 et 0.4.0). Toute modification incompatible incrémente. Ajout de champ optionnel = compatible. |
| `current_session.id`, `label`, `source_event_ids`, `reconstruction_version` | **Identité stable** (Core 0.5.0). `id` = sha256 tronqué à 16 hex des `event_id` des activités de la session, triés : déterministe, sans état, correct par construction (si la composition change, c'est une autre session). `label` = l'ordinal `work-N` de la journée, pour l'affichage seulement : il bouge dès qu'un événement tardif s'insère plus tôt dans la journée. `source_event_ids` = la liste triée qui a produit le hash. `reconstruction_version` = constante de `analysis/timeline.py`, incrémentée à chaque changement des règles de sessionnisation. Mêmes champs sur chaque entrée de `recent_sessions`. |
| `reference_at` | `at` si fourni, sinon `now` en UTC. Tout le calcul est relatif à cet instant. |
| `timezone` | Celle de `_trace_timezone()`, informative seulement — **tous les timestamps sont en UTC ISO 8601 avec offset**. |
| `workspace` | Résolu par le résolveur unique existant (`analysis/projects.py`, `persisted_workspace_identity`), jamais par `resolve_project_context` qui lit le disque. `resolution` ∈ `session` (workspace dominant de la session courante : le plus observé, égalité tranchée par le workspace attribué à la session puis par le chemin le plus petit), `last_observed` (pas de session courante, dernier workspace utile vu dans la fenêtre). Quand rien n'est résolu, `workspace` vaut `null` tout court : il n'y a pas de champ `resolution: "none"` orphelin. |
| `workspace.git` | Repris des détails **persistés** des événements (règle du 2026-08-30 : jamais l'état du disque au moment du rendu). Le périmètre suit la résolution : `resolution == "session"` → calculé sur les activités de la session courante (une fenêtre de 5 min sur une session de 3 h connaît toujours le commit de la première heure) ; `last_observed` → sur la fenêtre. `branch` vient du dernier événement porteur (contexte git du producteur terminal ou `git_commit`), `dirty` du dernier contexte git terminal et vaut `null` si aucune commande de la période n'en portait (un `git_commit` ne renseigne pas l'état de l'arbre), `last_commit` du dernier événement `git_commit` (hash court, première ligne du message, instant). `null` si aucun événement du périmètre ne porte d'info git pour ce workspace. |
| `current_session` | La session de travail (jamais une activité isolée) dont `last_activity_at` est la plus récente **et** postérieure à `reference_at − session_gap` (`DEFAULT_SESSION_GAP` de `session_tracker`, 30 min). `is_open` = `true` dans ce cas. Si aucune session ne satisfait ça, `current_session` vaut `null`. On ne met **pas** la dernière session fermée à la place : « rien en cours » est une information. Les sessions sont reconstruites jour local par jour local, comme la trace quotidienne, sur la journée entière jusqu'à `reference_at` : une session commencée avant la fenêtre garde ses vraies bornes. Identifiant : le hash stable (voir la ligne suivante) ; `label` porte l'ordinal `work-N`. |
| `current_session.apps` | Triées par activations décroissantes puis nom. `IGNORED_APP_NAMES_FOR_RENDERING` s'applique. Max 5. |
| `current_session.files` | Chemins relatifs au workspace quand possible (même logique que `_display_file_path`). Dédupliqués, ordre de première apparition. Max 20 par catégorie, `truncated: true` si coupé. |
| `current_session.terminal` | Réutilise `useful_command_lines`, `is_test_command`, `is_interrupted_exit` (les prompts collés sont exclus par `useful_command_lines`). Une commande interrompue n'est pas une erreur. Max 10 par liste, `truncated: true` si une liste est coupée. |
| `current_session.git` | `commits` ne compte que les événements `git_commit` du hook (preuve vérifiée, hash disponible) ; un `git commit` tapé sans hook ne produit pas d'entrée. `push_observed` vient des commandes `git push` observées au terminal. |
| `current_session.signals` | Types d'activité présents dans la session, ordre fixe = ordre de `SUPPORTED_ACTIVITY_TYPES` trié. Pas de doublon. |
| `recent_sessions` | Les sessions **fermées** dont `ended_at` ≥ `reference_at − window`, hors session courante, les plus récentes d'abord, max 3. Forme compacte uniquement. |
| `isolated_signals` | Les activités isolées (règle du 2026-08-30 : un signal fort seul ne crée pas de session) dans la fenêtre, max 10, plus récentes d'abord. `summary` : dernière ligne utile pour une commande, `Événement chemin-relatif` pour un fichier, le résumé stocké sinon. Un signal isolé dont le seul contenu est un prompt collé est écarté. |
| `last_session_summary` | Ajouté en Core 0.4.0 (pas 3, spec du 2026-09-03 §8), forme 0.5.0 : `id` (hash stable), `label`, `session_ended_at`, `reprise`, `confidence`, `age_minutes` — le dernier événement `session_summary` **sans limite de fenêtre**, borné par `reference_at`, ordonné par `occurred_at` (fin de la session résumée) puis par ligne (un résumé régénéré de la même session gagne). `null` si aucun. Ajout optionnel, `schema_version` reste 1. |
| `last_agent_session` | Le dernier événement `agent_session` **sans limite de fenêtre** (une reprise a besoin du dernier résumé même s'il date d'hier), mais borné par `reference_at` pour rester déterministe. `null` si aucun. `agent` = la valeur stockée de `source_tool` (`claude-code`, `codex`), telle quelle. `summary` = le résumé figé de l'événement, jamais le transcript. `age_minutes` compté depuis `ended_at`. |

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
    local_timezone: tzinfo | None = None,
) -> dict[str, Any]: ...
```

- Entrée : le store + un instant (avec fuseau, sinon `ValueError`) + une fenêtre. Sortie : un dict JSON-sérialisable.
- `local_timezone` (ajout additif) ne décide que du début des jours locaux, comme `build_daily_trace` ; défaut = fuseau de la machine. Les tests passent UTC pour être indépendants de la machine ; la route n'y touche pas.
- Réutilise `reconstruct_session_views`, le résolveur de workspace, `parse_status_output`, et les helpers de `analysis/terminal.py`. **Aucune duplication** de logique de classification : si un helper manque, il est ajouté dans `analysis/` et utilisé par les deux consommateurs.
- Ne connaît ni Flask, ni le rendu.

### Route : `daemon_v2/routes.py`

```python
@api.get("/context")
def get_context(): ...
```

Parse `window` et `at`, appelle `build_context_snapshot`, retourne `jsonify` avec `sort_keys`. Rien d'autre.

### Statut : `scripts/status.sh` et `/status`

`scripts/status.sh` affiche une ligne `Contexte : session en cours depuis 2 h 12 · Pulse` (ou `aucune session en cours`) lue sur `GET /context`. C'est la preuve d'usage minimale : le status consomme le contrat. `/status` expose en plus un bloc `context` compact (`session_open`, `duration_minutes`, `projects`, `workspace`) dérivé de `build_context_snapshot`.

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
- Session sans workspace résolu (cwd générique, fichiers hors projet) → `workspace: null`, session quand même retournée avec `projects: []`.
- Deux workspaces dans la session → `projects` en contient deux, `workspace` = le dominant.
- Signal fort isolé dans la fenêtre → dans `isolated_signals`, pas dans `current_session`.
- Commande interrompue (exit 130) → absente de `terminal.errors`.
- Prompt collé au shell → jamais dans la réponse.
- 25 fichiers modifiés → 20 retournés, `truncated: true`.
- Fenêtre de 5 min sur une session de 3 h avec un commit à la première heure → `workspace.git.last_commit` rempli (git suit la session).
- Pas de session courante, commit dans la fenêtre et un autre avant → `workspace.git.last_commit` = celui de la fenêtre (git suit la fenêtre).
- Apps triées par activations puis nom, bornées à 5.
- Des lignes datées après `at` ajoutées à la base ne changent pas la réponse.

**Route**
- `GET /context` → 200, `schema_version: 1`.
- `window=0`, `window=abc`, `window=99999` → 400.
- `at=2026-09-02T14:00:00Z` → `reference_at` renvoyé à l'identique en UTC.
- `at=hier`, `at` sans fuseau, `at` non calendaire → 400.

**Statut**
- `/status` expose `context` (session ouverte, durée, projets, workspace) ; base vide → `session_open: false`.

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

## 9. Décisions d'implémentation (2026-09-02)

Prises pendant le chantier, relues et acceptées, intégrées au contrat ci-dessus :

1. `workspace.git.dirty` est `bool | null` : `null` quand aucune commande terminal du périmètre n'a porté de contexte git.
2. Rien de résolu → `workspace: null`, sans champ `resolution` orphelin.
3. `workspace.git` suit la résolution du workspace (session courante entière si `session`, fenêtre si `last_observed`), pas la fenêtre seule.
4. `current_session.git.commits` ne compte que les événements `git_commit` du hook ; `push_observed` vient du terminal.
5. `last_agent_session.agent` = valeur stockée de `source_tool`, sans renommage.
6. ~~Identifiants de session `YYYY-MM-DD/work-N`.~~ Remplacé en Core 0.5.0 par l'identité stable (hash des `event_id`), l'ordinal ne survivant pas à un événement tardif.
7. `build_context_snapshot` accepte `local_timezone` (additif) pour des tests indépendants de la machine.
8. La session courante suit la règle du gap littéralement, sans tenir compte de la clôture `day_boundary` de la trace quotidienne (voir §10).

Plus deux choix de robustesse : un signal isolé réduit à un prompt collé est écarté, et `/status` expose un bloc `context`.

## 10. Route `GET /context/sessions` (Core 0.5.0)

`GET /context/sessions?date=YYYY-MM-DD` (défaut : la journée locale courante ; `at` optionnel, même parsing que `/context`) renvoie les sessions de travail **closes** de cette journée locale dans la forme exacte de `current_session` — même code, mêmes bornes 20/10/5, identité stable incluse — plus `is_open` (toujours `false` ici). Enveloppe : `schema_version`, `generated_at`, `reference_at`, `date`, `timezone`, `reconstruction_version`, `sessions` (ordre chronologique). `date` invalide → 400. C'est ce qu'un consommateur qui mémorise des sessions (la couche Intelligence) lit à la place de `/trace/<date>` : il ne reconstruit rien.

## 11. Limites connues

- **Minuit local.** La trace quotidienne ferme toute session à minuit (`day_boundary`). `/context` applique le gap de 30 min tel quel : entre 00:00 et 00:30, une session de la veille encore dans le gap est rapportée comme courante alors que le HTML l'affiche fermée. Cas rare, assumé ; à réconcilier si un consommateur en souffre.
- **Fuseau machine.** Les bornes de jour dépendent du fuseau de la machine qui sert la route (comme la trace quotidienne). Le JSON est déterministe pour une machine donnée.
