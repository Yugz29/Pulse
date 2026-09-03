# Spec — Résumé de session (`intelligence/`)

Pas 3 de la roadmap V3 (voir `docs/VISION.md`). Premier code de la couche Intelligence, premier événement de mémoire de niveau 2.

## 1. Objectif

Produire, pour chaque session de travail close, un **résumé figé** en deux parties :

- une **reprise** en langage naturel — ce que tu faisais, où tu t'es arrêté, ce qui restait ouvert — lisible en dix secondes le lendemain matin ;
- un **bloc structuré** — projet, intentions déduites, fichiers centraux, blocages — destiné à l'indexation future (mémoire sémantique, hors périmètre ici).

Le résumé est stocké comme événement dérivé dans `trace.db`, via l'ingestion normale de Core, exactement comme `agent_session` : versionné, jamais régénéré en silence, jamais le brut.

Usage prioritaire : la reprise. Le bloc structuré est produit dans le même appel mais n'est consommé par rien dans ce chantier.

## 2. Non-objectifs

- Aucune proactivité : rien ne notifie, rien n'interrompt. Le résumé se lit quand on le demande.
- Aucune mémoire sémantique, aucun embedding, aucune recherche.
- Un seul modèle, un seul prompt. Pas de routeur, pas de fallback vers un modèle distant.
- Pas de résumé de la session en cours : on résume ce qui est clos, avec ses vraies bornes.
- Pas d'interface : la reprise est exposée en JSON et en Markdown brut, l'affichage HTML viendra plus tard.

## 3. Principes

1. **Core ne sait pas qu'Intelligence existe.** Intelligence lit Core par `GET /context` et écrit par `POST /activities`. Aucun import Python de `daemon_v2` depuis `intelligence/`. Si `intelligence/` est absent ou arrêté, Core ne remarque rien.
2. **Le modèle est un détail d'implémentation.** Une interface `Summarizer` avec une seule implémentation (`MLXSummarizer`), dont le nom du modèle est une valeur de configuration. Changer de modèle ne modifie aucune ligne hors config et incrémente `prompt_version` si le prompt change.
3. **Un résumé est immuable.** Une session close a au plus un résumé par `(prompt_version, model_id)`. Regénérer = un nouvel événement avec une nouvelle version, l'ancien reste. Le plus récent fait foi.
4. **Deux déclencheurs, une fonction.** Le job périodique et la route HTTP appellent la même `summarize_session(session_id)`.
5. **Le texte est jugé par toi, pas par un test.** Les tests couvrent le pipeline (sélection, prompt, parsing, émission, idempotence). La justesse de la reprise se vérifie en dogfooding.

## 4. Le seul changement dans Core

Core est gelé. Ce chantier y touche à un seul endroit, justifié par le contrat de données : Core doit **accepter et stocker** un nouveau type d'événement, sinon Intelligence n'a nulle part où écrire.

- `models.py` : `"session_summary"` ajouté à `SUPPORTED_ACTIVITY_TYPES`.
- `ingest.py` : validation minimale des `details` (voir §6). Le `summary` de l'`Activity` est la première ligne de la reprise.
- `context_snapshot.py` : `last_session_summary` ajouté à la réponse de `GET /context` (voir §8), `schema_version` reste 1 (ajout optionnel).
- `analysis/timeline.py` : `session_summary` exclu explicitement de la collecte des activités non attribuées. Trou trouvé à l'implémentation : la reconstruction ne connaît pas ce type (ni signal fort, ni activation d'app, ni type système), donc sans cette ligne chaque résumé aurait ajouté une ligne vide dans la section « non attribuées » du HTML et du Markdown et incrémenté son compteur. Ce n'est pas un rendu, c'est la garantie du « aucun rendu ». Au passage, les trois helpers de ce module importés par plusieurs consommateurs (`display_file_path`, `app_activation_counts`, `is_strong_work_activity`) deviennent publics, anciens noms conservés en alias dépréciés.
- **Aucun rendu** : `daily_trace.py` et les renderers ne changent pas (`daily_trace.py` ne fait que suivre les noms publics des helpers). Le type est stocké, exposé par `/context`, pas affiché dans le HTML. L'affichage est un chantier ultérieur.

PR séparée sur Core (`ship/session-summary-type`), mergée **avant** le premier commit d'`intelligence/`. Version Core 0.4.0.

## 5. Structure d'`intelligence/`

```
intelligence/
  README.md
  pyproject.toml                 # dépendances : mlx-lm, requests, pytest ; rien de Core
  pulse_intelligence/
    __init__.py
    config.py                    # PULSE_CORE_URL, MODEL_ID, PROMPT_VERSION, tick, timeouts
    core_client.py               # GET /context, GET /trace/<date>, POST /activities
    summarizer.py                # interface Summarizer + MLXSummarizer
    prompts/
      session_summary_v1.md      # le prompt, versionné comme du code
    session_summary.py           # summarize_session(), parsing, construction de l'événement
    job.py                       # summarize-closed-sessions : boucle périodique
    api.py                       # POST /summaries/<session_id>, GET /summaries/<session_id>
    main.py                      # point d'entrée : job + api dans un process, port 8767
  tests/
  scripts/
    install_launchd.sh           # com.pulse.intelligence, KeepAlive, même style que Core
    status.sh
```

Venv séparée de Core. Python identique.

## 6. L'événement `session_summary`

Émis via `POST /activities` avec le format producteur existant (`schema_version`, `producer`, `occurred_at`, `details`). `producer.name = "pulse-intelligence"`, `producer.version` = version du paquet.

```json
{
  "type": "session_summary",
  "occurred_at": "<ended_at de la session résumée>",
  "summary": "<première ligne de la reprise>",
  "workspace": "<workspace_root de la session, s'il existe>",
  "details": {
    "session_id": "3f9c2a1b7e4d5c60",
    "source_event_ids_hash": "3f9c2a1b7e4d5c60",
    "session_label": "work-3",
    "session_started_at": "…",
    "session_ended_at": "…",
    "prompt_version": "v1",
    "model_id": "<valeur de config, ex. mlx-community/…>",
    "generated_at": "…",
    "generation_ms": 4210,
    "input_context_hash": "sha256 du JSON d'entrée",
    "reprise": {
      "doing": "…",
      "stopped_at": "…",
      "open": "…"
    },
    "structured": {
      "project": "Pulse",
      "intents": ["…"],
      "central_files": ["…"],
      "blockers": ["…"],
      "confidence": "high | medium | low"
    }
  }
}
```

Règles :

- `occurred_at` = fin de la session, pas l'instant de génération. Le résumé se range à sa place dans la journée. `generated_at` garde la vérité de production.
- `event_id` déterministe côté producteur : uuid5 de `(session_id, prompt_version, model_id)`. Rejouer le job n'écrit rien de nouveau ; Core répond `duplicate`.
- `input_context_hash` permet de savoir si le contexte a changé depuis (une session close ne devrait pas bouger ; si le hash diffère, c'est un bug ou un nouveau pas de Core à signaler).
- `reprise.*` : trois chaînes, une phrase chacune, en français, jamais vides. Si le modèle ne peut rien dire, `stopped_at` et `open` valent `"—"` et `confidence = "low"`.
- `structured.intents` : 0 à 3 entrées. `central_files` : 0 à 5, chemins relatifs. `blockers` : 0 à 3.
- Aucun contenu de commande, aucun prompt collé, aucun transcript ne transite : l'entrée du modèle est `GET /context`, qui applique déjà ces règles.

`session_id` est l'**identité stable** de la session (Core 0.5.0) : le sha256 tronqué à 16 hex des `event_id` de ses activités, triés, tel que `GET /context/sessions` l'expose — jamais l'ordinal `work-N`, qui bouge dès qu'un événement tardif s'insère dans la journée. `source_event_ids_hash` est requis et égal à `session_id` (il rend explicite que la clé est un hash de composition). `session_label` (optionnel) porte l'ordinal pour l'affichage.

Validation Core (`ingest.py`) : `session_id` chaîne de 16 hex (400 avec `field` sinon), `source_event_ids_hash` égal à `session_id`, `session_label` chaîne non vide si présent, `prompt_version`, `model_id` chaînes non vides ; `reprise` dict avec les trois clés chaînes ; `structured` dict avec `project` chaîne ou null et `confidence` dans l'énumération. Le reste est passé tel quel.

## 7. Sélection, entrée du modèle, prompt

### Quelle session résumer

Une session est **candidate** si :
- `activity_kind == "work"` ;
- elle est close : `ended_at` + `DEFAULT_SESSION_GAP` < maintenant (Intelligence lit le gap via `/status` ou le duplique en config — dupliqué, avec un test qui compare à la valeur exposée) ;
- `duration_minutes >= 10` ou `activity_count >= 30` (une session de deux minutes n'a pas de reprise) ;
- aucun `session_summary` avec `(prompt_version, model_id)` courants n'existe pour son `session_id`.

Les sessions sont lues par `GET /trace/<date>` pour la journée courante et la veille. Pas plus loin : un résumé produit trois jours après n'a plus d'usage de reprise.

### Entrée du modèle

Pas `GET /context` directement — il décrit le présent. Intelligence construit une **vue de session** de même forme que `current_session` du Context API, depuis `/trace/<date>`, en réutilisant les mêmes règles de bornage (20 fichiers, 10 lignes terminal, 5 apps). Le JSON sérialisé (`sort_keys`) est l'entrée unique ; son sha256 est `input_context_hash`.

Y sont ajoutés, s'ils existent :
- la reprise du **résumé précédent** de la même journée (pour la continuité : « tu avais repris le parseur, puis… ») ;
- le résumé du dernier `agent_session` dont l'intervalle chevauche la session.

### Prompt `session_summary_v1.md`

Structure imposée, contenu à écrire dans l'implémentation :

- Rôle : « tu écris la note de reprise d'un développeur pour lui-même ». Deuxième personne, français, présent.
- Interdits explicites : inventer un fichier, une commande ou une intention absents de l'entrée ; commenter la qualité du travail ; féliciter ; conseiller.
- Format de sortie : JSON seul, schéma de `reprise` + `structured`, aucun texte autour.
- `confidence` : `high` si commits + tests + fichiers cohérents, `medium` si fichiers sans commit, `low` si surtout des activations d'apps.
- Deux exemples courts dans le prompt (un `high`, un `low`), construits à la main depuis des sessions réelles anonymisées de toi.

Le parsing tolère les clôtures ```` ```json ```` mais rejette toute sortie qui ne valide pas le schéma : on n'écrit pas un résumé bancal, on log et on réessaie au tick suivant, trois fois maximum, puis on marque la session en `failed` dans l'état local du job (fichier JSON dans `~/.pulse_intelligence/`), jamais dans `trace.db`.

## 8. Exposition

### Dans Core — `GET /context`

Champ ajouté : `last_session_summary`, le `session_summary` le plus récent (par `occurred_at`, puis `generated_at`) **sans limite de fenêtre**, même règle que `last_agent_session`. Forme : `session_id`, `session_ended_at`, `reprise` (les trois chaînes), `confidence`, `age_minutes`. `null` si aucun.

### Dans Intelligence — port 8767

- `POST /summaries/<session_id>` → force la génération, même hors fenêtre de deux jours. 202 avec `{"status": "queued"}` ; le job traite au tick suivant. 409 si un résumé existe déjà pour `(prompt_version, model_id)` sauf `?force=1`, qui produit un nouvel événement avec `prompt_version` suffixé `-manual-<n>`. À utiliser rarement.
- `GET /summaries/<session_id>` → le dernier résumé, JSON, ou 404.
- `GET /summaries/latest.md` → la dernière reprise en Markdown brut, trois lignes. C'est le `curl` du matin.
- `GET /status` → modèle chargé, `prompt_version`, sessions en attente, dernier succès, derniers échecs.

## 9. Le job `summarize-closed-sessions`

- Un process résident (`main.py`) : API Flask + boucle de job dans un thread, tick toutes les 10 minutes, déclenchable à la main (`POST /summaries/tick`).
- Charge le modèle **une fois** au démarrage. Si le chargement échoue, `/status` le dit et le job ne tourne pas ; Core, lui, n'est pas concerné.
- À chaque tick : candidates → pour chacune, construction de l'entrée, appel modèle, parsing, `POST /activities`. Une session à la fois, séquentiellement. Timeout par génération : 120 s.
- launchd `com.pulse.intelligence`, `KeepAlive`, journal dans `~/.pulse_intelligence/logs/`. Installé et retiré par ses propres scripts, jamais par ceux de Core.
- Le job ne tourne pas pendant `system_sleep`/`screen_locked` ? **Non** : au contraire, la fin de session arrive souvent quand tu quittes l'écran. Le job tourne quand la machine est éveillée, c'est launchd qui gère.

## 10. Configuration

`~/.pulse_intelligence/config.toml`, avec des valeurs par défaut dans `config.py` :

```toml
core_url = "http://127.0.0.1:8765"
model_id = ""            # obligatoire ; vide = le service refuse de démarrer
prompt_version = "v1"
tick_minutes = 10
generation_timeout_s = 120
min_session_minutes = 10
min_session_activities = 30
lookback_days = 1
```

`model_id` vide est une erreur explicite au démarrage, pas un défaut silencieux : le choix du modèle est une décision, il doit être écrit quelque part.

## 11. Tests — `intelligence/tests/`

Le modèle est remplacé par un `FakeSummarizer` qui rend une sortie fixée ; Core est remplacé par un serveur Flask de test qui rejoue des fixtures JSON de `/trace/<date>` et enregistre les `POST /activities`. Aucun test ne charge MLX.

**Sélection**
- Session ouverte → pas candidate. Session de 4 minutes / 12 activités → pas candidate. Session avec résumé existant même version → pas candidate ; version différente → candidate.
- Deux journées de lookback, pas trois.

**Entrée**
- La vue de session est bornée comme le Context API (20/10/5). Le hash est stable entre deux constructions.
- Le résumé précédent de la journée est injecté ; absent sinon.

**Prompt et parsing**
- Sortie valide → événement construit avec les bons champs, `occurred_at = ended_at`, `event_id` = uuid5 attendu.
- Sortie avec clôtures markdown → acceptée. Sortie sans `reprise.doing` → rejetée, aucun POST, compteur d'échec incrémenté. Trois échecs → `failed`, plus de tentative.
- Sortie contenant un chemin absent de l'entrée → **rejetée** (garde-fou anti-hallucination sur `central_files` : chaque chemin doit apparaître dans l'entrée).

**Émission et idempotence**
- Premier tick → un POST par candidate. Second tick identique → zéro POST (Core simulé répond `duplicate`, et le job n'appelle même pas le modèle si l'état local connaît déjà le `event_id`).

**API**
- `POST /summaries/<id>` → 202 ; puis 409 ; `?force=1` → 202 et `prompt_version` suffixée.
- `GET /summaries/latest.md` → trois lignes, dernière session.

**Core (dans `core/tests_v2`)**
- `session_summary` accepté par `/activities`, refusé si `reprise` incomplète (400 avec `field`).
- `/context.last_session_summary` rempli sans fenêtre, `null` si absent.

## 12. Critères d'acceptation

1. Tu arrives le matin, `curl -s :8767/summaries/latest.md`, et la reprise de la veille est **juste** — tu la reconnais. C'est le critère qui compte ; il se vérifie sur cinq jours de suite avant de considérer le pas 3 terminé.
2. Tous les tests ci-dessus passent ; Core reste vert.
3. `intelligence/` n'importe rien de `core/` (vérifié par un test qui grep les imports).
4. Core arrêté → Intelligence log une erreur de connexion à chaque tick et ne plante pas. Intelligence arrêté → Core ne change en rien.
5. `docs/VISION.md` : couche Intelligence passée de « à construire » à « premier composant livré : résumé de session » ; `docs/decisions/` : note datée avec le modèle retenu et pourquoi.

## 13. Hors périmètre, explicitement

- Affichage définitif des résumés dans le HTML de Core — l'aperçu actuel via `build_current_state` (le résumé peut apparaître comme « Dernière activité utile » dans « Maintenant » et « Reprise », seulement quand rien de plus récent n'existe) est accepté en attendant.
- Résumé de journée (agrégat des résumés de sessions) — chantier suivant naturel, pas celui-ci.
- Toute forme de recherche, embedding ou mémoire sémantique.
- Fine-tuning, LoRA, évaluation automatique de la qualité des reprises.
- Notification, menu bar, interruption.

## 14. Ordre de livraison

1. PR Core `ship/session-summary-type` : type + validation + `last_session_summary` dans `/context`. Petite, mergée d'abord.
2. `intelligence/` squelette : config, `core_client`, `Summarizer` + `FakeSummarizer`, tests de sélection et d'émission. **Sans MLX.** Vérifiable de bout en bout avec le faux modèle.
3. `MLXSummarizer` + prompt v1 + parsing. Premier vrai résumé sur ta machine, à la main via `POST /summaries/<id>`.
4. Job + launchd + `/summaries/latest.md`. Cinq jours de dogfooding.
5. Note de décision sur le modèle, mise à jour de la Vision.

Les étapes 1 et 2 peuvent commencer avant le choix du modèle. L'étape 3 attend le benchmark.
