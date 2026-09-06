# Spec — Résumé de session (`intelligence/`) — v2

Pas 3 de la roadmap V3 (voir `docs/VISION.md`). Premier code de la couche Intelligence, premier événement de mémoire de niveau 2.

**v2 du 2026-09-03** — réécrit après relecture externe. Changements par rapport à la v1 : identité de session stable (hash des sources) à la place de l'ordinal `work-N` ; Intelligence lit `GET /context/sessions` et ne reconstruit rien ; rédaction de tout le texte libre produit par le modèle ; livraison en CLI batch avant tout service résident ; corpus d'évaluation gelé dès le premier prototype. Dépend de Core ≥ 0.5.0 (`ship/session-identity`) et de la PR `hardening`.

## 1. Objectif

Produire, pour chaque session de travail close, un **résumé figé** en deux parties :

- une **reprise** en langage naturel — ce que tu faisais, où tu t'es arrêté, ce qui restait ouvert — lisible en dix secondes le lendemain matin ;
- un **bloc structuré** — projet, intentions déduites, fichiers centraux, blocages — destiné à l'indexation future (hors périmètre ici).

Le résumé est stocké comme événement dérivé dans `trace.db`, via l'ingestion normale de Core : versionné, jamais régénéré en silence, jamais le brut.

Usage prioritaire : la reprise. Le bloc structuré est produit dans le même appel mais n'est consommé par rien dans ce chantier.

## 2. Non-objectifs

- Aucune proactivité, aucune notification, aucune interruption.
- Aucune mémoire sémantique, aucun embedding, aucune recherche.
- Un seul modèle, un seul prompt. Pas de routeur, pas de fallback distant.
- Pas de résumé de la session en cours.
- Pas d'interface : JSON et Markdown brut. L'affichage HTML viendra plus tard.
- Pas d'authentification des producteurs locaux : question à rouvrir quand la couche Agent agira sur ces données (noté dans la Vision, « Plus tard »).

## 3. Principes

1. **Core ne sait pas qu'Intelligence existe.** Intelligence lit Core par HTTP (`GET /context`, `GET /context/sessions`) et écrit par `POST /activities`. Aucun import de `daemon_v2` depuis `intelligence/`, vérifié par un test.
2. **Intelligence ne reconstruit rien.** Les sessions closes arrivent de Core déjà bornées, avec leur identité stable. Toute règle de sessionnisation ou de bornage vit dans Core et nulle part ailleurs.
3. **Le modèle est un détail d'implémentation.** Interface `Summarizer`, une implémentation `MLXSummarizer`, `model_id` en configuration. Changer de modèle ne modifie aucune ligne hors config.
4. **Un résumé est immuable et vérifiable.** Une session a au plus un résumé par `(prompt_version, model_id)`. Il porte le hash de ses événements sources et la version de reconstruction : on peut dire, dans six mois, de quoi exactement il est le résumé.
5. **Tout ce que le modèle écrit est non fiable.** Validé par schéma, rédigé par Core à l'ingestion, jamais affiché sans passer par ces deux barrières. Un chemin cité qui n'existe pas dans l'entrée invalide le résumé.
6. **Batch avant résident.** La première version est une commande. Le service, l'API et le job périodique n'arrivent que quand la reprise est jugée utile.
7. **Le texte est jugé par toi, pas par un test** — mais sur un corpus gelé, pour que deux prompts ou deux modèles soient comparables.

## 4. Contrat Core consommé (fourni par 0.5.0 et hardening)

Ce que ce chantier attend de Core, sans y toucher :

- `GET /context` `schema_version: 2` : `current_session.id` = sha256 tronqué (16 hex) des `event_id` triés, `label` = `work-N`, `source_event_ids`, `reconstruction_version` ; `last_session_summary` avec `id` et `label`.
- `GET /context/sessions?date=YYYY-MM-DD` : sessions de travail de la journée locale, forme exacte de `current_session`, champ `is_open`. C'est **la seule source** de sessions closes pour Intelligence.
- `is_open == false` est **monotone** (décision du 2026-09-03, `reconstruction_version` 2) : une session fermée par un verrouillage ou une mise en veille ne rouvre jamais, quelle que soit la quantité de données arrivée ensuite. Intelligence peut résumer une session close sans risque que Core la « rouvre » deux minutes plus tard. L'activité forte observée pendant un verrouillage (`activity_kind: background`) n'est jamais une session à résumer.
- `POST /activities` accepte `session_summary` avec `details.session_id` (16 hex) et `details.source_event_ids_hash` égal ; rejette sinon avec `field`.
- Core rédige (`redact_command`) **toutes** les chaînes libres de `details` d'un `session_summary` : `reprise.*`, `structured.intents[]`, `structured.blockers[]`, `structured.central_files[]`.
- `schema_version` d'événement inconnu → 400.

Si l'un de ces points manque, ce chantier s'arrête et Core reçoit d'abord la correction.

## 5. Structure d'`intelligence/`

```
intelligence/
  README.md
  pyproject.toml                    # mlx-lm (extra optionnel), requests, pytest ; rien de Core
  requirements.lock
  pulse_intelligence/
    __init__.py
    config.py                       # lecture config.toml + défauts + validation
    core_client.py                  # GET /context, GET /context/sessions, POST /activities
    summarizer.py                   # Summarizer (interface), FakeSummarizer, MLXSummarizer
    prompts/session_summary_v1.md
    session_input.py                # vue de session → entrée du modèle (+ contexte adjacent)
    session_summary.py              # summarize_session(), parsing, validation, événement
    selection.py                    # sessions candidates
    state.py                        # état local du job (~/.pulse_intelligence/state.json)
    cli.py                          # pulse-intel : list, summarize, run, show, eval
  tests/
  eval/
    corpus/                         # 10 entrées gelées + reprise attendue, voir §11
  scripts/
    install_launchd.sh              # étape 5 seulement
```

Venv séparée de Core, même Python. `mlx-lm` est un extra (`pip install -e '.[mlx]'`) : le paquet s'installe et se teste sans lui.

## 6. L'événement `session_summary`

Émis via `POST /activities`, format producteur existant. `producer.name = "pulse-intelligence"`, `producer.version` = version du paquet.

```json
{
  "type": "session_summary",
  "occurred_at": "<ended_at de la session résumée>",
  "summary": "<première ligne de la reprise>",
  "workspace": "<workspace_root de la session, s'il existe>",
  "details": {
    "session_id": "3f9a1c0be2d47a58",
    "session_label": "work-3",
    "session_date": "2026-09-02",
    "session_started_at": "…",
    "session_ended_at": "…",
    "source_event_ids_hash": "3f9a1c0be2d47a58",
    "source_event_count": 214,
    "reconstruction_version": 1,
    "prompt_version": "v1",
    "model_id": "<config>",
    "generated_at": "…",
    "generation_ms": 4210,
    "input_hash": "sha256 de l'entrée sérialisée",
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

- `occurred_at` = fin de la session ; `generated_at` garde la vérité de production.
- `event_id` déterministe côté producteur : uuid5 de `session_id + prompt_version + model_id`. Rejouer n'écrit rien ; Core répond `duplicate`.
- `session_id == source_event_ids_hash`, toujours. La redondance est volontaire : le champ dit explicitement ce qu'est l'identifiant.
- `reconstruction_version` : celle renvoyée par Core au moment de la génération. Si Core l'incrémente plus tard, les anciens résumés restent valides pour leur version, et les sessions changées auront de nouveaux ids donc de nouveaux résumés — rien à migrer.
- `reprise.*` : trois chaînes, une phrase chacune, en français, jamais vides. Si le modèle ne peut rien dire : `"—"` et `confidence = "low"`.
- `structured.intents` 0–3, `central_files` 0–5 chemins relatifs **présents dans l'entrée**, `blockers` 0–3.
- Rien de brut ne transite : l'entrée est la vue Core, déjà rédigée ; la sortie est rédigée à nouveau par Core, sur **tout** champ texte libre du schéma, `reprise.doing`, `reprise.stopped_at`, `reprise.open`, `structured.project`, et chaque élément de `structured.intents`, `structured.central_files`, `structured.blockers` (décision du 2026-09-06, défaut 9 de l'audit). `structured.confidence` est une énumération fermée. Un champ hors schéma dans `reprise` ou `structured` est refusé en 400, faute de politique de rédaction : le schéma est énuméré une fois dans `core/daemon_v2/ingest.py` et un test le vérifie.

## 7. Sélection et entrée du modèle

### Candidates

Lues par `GET /context/sessions?date=` pour aujourd'hui et hier (`lookback_days = 1`). Une session est candidate si :

- `is_open == false` ;
- `duration_minutes >= 10` ou `activity_count >= 30` ;
- aucun `session_summary` connu pour `(id, prompt_version, model_id)` — connu = présent dans l'état local, ou `GET /context/sessions` le signale (champ `summaries: [{prompt_version, model_id}]` si Core l'expose ; sinon l'état local fait foi et Core dédoublonne par `event_id`).

Une session dont l'`id` a disparu de `/context/sessions` entre deux ticks (composition changée par un événement tardif) est simplement oubliée : son résumé, s'il existait, reste dans `trace.db` comme résumé d'un ensemble d'événements qui a existé.

### Vidage de la file `pending` (2026-09-06, défaut 4 de l'audit, issue #62)

Chaque passage commence par rejouer les payloads `pending`, **avant** la sélection et indépendamment de la fenêtre `lookback_days` : un résumé gelé pendant une panne Core repart au premier passage après rétablissement, même plusieurs jours plus tard, sans commande datée. Le rejeu est octet pour octet, `entry["event"]` tel que figé : ni `generated_at`, ni `generation_ms`, ni `input_hash`, ni `producer` ne sont recalculés, et les versions enregistrées avec l'entrée servent à l'inscription dans `emitted`. Le budget d'échecs et le `409` de Core s'appliquent comme à toute émission ; un rejeu refusé compte `failed` dans le bilan (`replayed=` dans la ligne de `run`, codes de sortie inchangés). Un `pending` d'une session `given_up` n'est pas rejoué par le vidage : il reste sur disque jusqu'à une reprise explicite (`summarize <id> --retry`). Ce vidage est distinct du rattrapage des sessions jamais traitées, qui relève d'une politique de curseur séparée, non livrée.

### Récupération après perte de l'état local (2026-09-06, défaut 3 de l'audit)

L'identité d'un résumé est `event_id = f(session_id, prompt_version, model_id)`, mais son contenu porte `generated_at` et `generation_ms` : régénérer après une perte de `state.json` produit un contenu différent sous le même `event_id`, que Core refuse (`409`, préservé). Avant tout appel au modèle, quand l'état local ne connaît ni l'`event_id` ni un `pending` pour lui, Intelligence lit `GET /activities/<event_id>` : si Core l'a, l'entrée est enregistrée localement telle que Core l'a stockée (`origin: "core"`), statut `already_known`, zéro appel modèle, zéro POST ; sinon le chemin normal reprend. Core injoignable à cet instant remonte comme sur `/context` (code 2), jamais en `failed`.

Limite explicite : la récupération renvoie **le résumé accepté par Core**, même si la session a grandi depuis son émission (`grown_after_emit`) ; elle ne le régénère pas.

### Une seule forme d'entrée `emitted` (2026-09-06, défaut 9 de l'audit)

La copie de référence d'un résumé est l'événement **accepté par Core**, après normalisation. Après un `201` ou un `200 duplicate`, Intelligence relit `GET /activities/<event_id>` et enregistre cette forme, `origin: "core"`, jamais la sortie du modèle avant normalisation ; si la relecture échoue, l'entrée est enregistrée sans `event`, avec avertissement, et `show <id>` lit Core. Les entrées émises et récupérées ont donc la même forme. `show <id>` sans entrée locale interroge Core par l'identité (session, prompt, modèle), jamais le dernier résumé de `/context`, qui peut être une autre session ; un préfixe ne se résout que sur l'état local. Limite : les entrées antérieures, sans `origin`, gardent leur forme ancienne non rédigée et sont signalées dans la fiche (« copie locale antérieure à la rédaction Core ») ; pas de migration.

### Entrée du modèle

La vue de session renvoyée par Core, telle quelle, sérialisée `sort_keys`. Son sha256 est `input_hash`. Intelligence n'y retire ni n'y ajoute de faits.

Y sont **annexés**, sous des clés séparées, s'ils existent :

- `previous_summary` : la `reprise` du résumé précédent de la même journée (continuité) ;
- `agent_session` : le résumé du dernier `agent_session` dont l'intervalle chevauche la session (via `/context.last_agent_session` si l'intervalle correspond, sinon rien — pas de lecture de `/trace`).

### Prompt `session_summary_v1.md`

Structure imposée :

- Rôle : « tu écris la note de reprise d'un développeur pour lui-même ». Deuxième personne, français, présent.
- Interdits explicites : inventer un fichier, une commande ou une intention absents de l'entrée ; commenter la qualité du travail ; féliciter ; conseiller.
- Sortie : JSON seul, schéma `reprise` + `structured`, rien autour.
- `confidence` : `high` si commits + tests + fichiers cohérents, `medium` si fichiers sans commit, `low` si surtout des activations d'apps.
- Deux exemples courts (un `high`, un `low`) tirés du corpus §11.

### Parsing et validation

Tolère les clôtures ```` ```json ````. Rejette : schéma invalide, `reprise.*` vide, `confidence` hors énumération, tout `central_files[]` absent des chemins de l'entrée, toute chaîne > 300 caractères. Un rejet = pas d'émission, compteur d'échec dans l'état local, nouvelle tentative au tick suivant, trois maximum puis `given_up`. Jamais rien dans `trace.db` avant validation. **Budget par identité** (2026-09-06, défaut 5 de l'audit) : le compteur et l'abandon sont indexés par `event_id`, donc par (session, prompt, modèle) ; une clé de seize hexadécimaux dans `failures` / `failed` est un abandon ancien, portant sur la session entière, toujours respecté. Trois natures d'échec côté modèle : une **entrée refusée** de façon déterministe (`ProviderInputRefused` : plafond de tokens, HTTP 400) consomme le budget comme une sortie invalide ; une **panne transitoire** (`ProviderError` nue : délai de lecture, 429, 5xx, erreur de génération) donne `failed` sans consommer le budget ; un **modèle indisponible** (`ProviderUnavailable` : runtime absent, poids non chargés, connexion refusée) arrête le passage à la première candidate, `report.error`, code 2, comme un Core injoignable. Reprise explicite d'un abandon : `summarize <id> --retry` efface les deux formes de clé pour cette session puis repart, `pending` d'abord.

## 8. Exposition

### Étapes 1–3 : CLI seulement

```
pulse-intel list [--date]          # sessions closes, candidates ou non, avec raison
pulse-intel summarize <id>         # une session, affiche le résultat, --dry-run sans émission
pulse-intel run [--once]           # toutes les candidates
pulse-intel show [<id>|latest]     # le résumé, --md pour la reprise seule en trois lignes
pulse-intel eval                   # §11
```

`pulse-intel show latest --md` est le `curl` du matin, en attendant le service.

### Étape 5 : service résident (conditionné, voir §12)

Port 8767. `POST /summaries/<id>` (202, 409, `?force=1`), `GET /summaries/<id>`, `GET /summaries/latest.md`, `GET /status`, `POST /summaries/tick`. Même code que la CLI, launchd `com.pulse.intelligence`, `KeepAlive`, journaux dans `~/.pulse_intelligence/logs/`. Chargement du modèle une fois au démarrage ; échec = `/status` le dit, le job ne tourne pas, Core n'est pas concerné.

## 9. Configuration

`~/.pulse_intelligence/config.toml`, défauts dans `config.py` :

```toml
core_url = "http://127.0.0.1:8765"
model_id = ""              # obligatoire ; vide = refus de démarrer
prompt_version = "v1"
tick_minutes = 10
generation_timeout_s = 120
min_session_minutes = 10
min_session_activities = 30
lookback_days = 1
```

Le dossier `~/.pulse_intelligence/` est créé en `0700`, ses fichiers en `0600` — même politique que Core après hardening.

## 10. Tests — `intelligence/tests/`

`FakeSummarizer` rend une sortie fixée ou programmée ; un Flask de test rejoue des fixtures de `/context` et `/context/sessions` et enregistre les `POST /activities`. Aucun test ne charge MLX.

**Isolation** — un test grep les imports : rien de `daemon_v2`, rien de `core/`.

**Sélection** — ouverte → non ; 4 min / 12 activités → non ; résumé existant même version → non, version différente → oui ; deux journées de lookback, pas trois ; id disparu entre deux ticks → oubliée sans erreur.

**Entrée** — hash stable entre deux constructions ; annexes présentes ou absentes selon les fixtures ; la vue Core n'est jamais modifiée.

**Parsing** — sortie valide → événement avec `session_id == source_event_ids_hash`, `occurred_at = ended_at`, `event_id` uuid5 attendu ; clôtures markdown acceptées ; `reprise.doing` manquant → rejet ; chemin absent de l'entrée → rejet ; chaîne de 301 caractères → rejet ; trois rejets → `failed`.

**Émission** — premier `run` → un POST par candidate ; second `run` → zéro POST et zéro appel au modèle.

**CLI** — `list` marque les candidates avec raison ; `summarize --dry-run` n'émet rien ; `show latest --md` sort trois lignes.

## 11. Corpus d'évaluation — `intelligence/eval/`

Constitué à l'étape 3, avant le premier vrai résumé :

- dix vues de sessions réelles à toi, exportées par `pulse-intel list --export`, relues et gelées (fichiers JSON commités, chemins anonymisés si besoin) ;
- pour chacune, ta **reprise attendue** écrite à la main, trois phrases, dans `expected.md` ;
- `pulse-intel eval` fait tourner le modèle courant sur les dix et écrit un `report.md` : entrée, attendu, obtenu, côte à côte. Pas de score automatique — un regard.

Règle : tout changement de prompt ou de modèle passe par `eval` avant d'être activé, et le rapport est joint à la PR.

## 12. Ordre de livraison et critères

1. **Squelette** (`ship/intelligence-skeleton`, reprise de la branche existante si compatible, sinon repartir) : config, `core_client`, `Summarizer` + `FakeSummarizer`, sélection, entrée, parsing, émission, CLI `list`/`summarize --dry-run`/`run`. Tout le §10 sauf MLX. Vérifiable de bout en bout avec le faux Core.
2. **CLI complète** : `show`, `run --once` contre le vrai Core, état local, permissions.
3. **Modèle** (`ship/intelligence-mlx`) : `MLXSummarizer`, prompt v1, corpus §11 et `eval`. Premier vrai résumé à la main. Attend le benchmark.
4. **Dogfooding** : `pulse-intel run` chaque soir ou via un `StartInterval` launchd minimal (une commande, pas un service), `show latest --md` chaque matin. Cinq jours.
5. **Service résident** — **uniquement si** au terme des cinq jours, quatre reprises sur cinq sont jugées justes et utiles. Sinon on itère sur le prompt ou le modèle avec `eval`, et le service attend.

Critères d'acceptation du pas 3 : (a) le 5 est atteint ; (b) tous les tests passent, Core reste vert ; (c) `intelligence/` n'importe rien de Core ; (d) Core arrêté → Intelligence log et s'arrête proprement ; Intelligence absent → Core ne change en rien ; (e) `VISION.md` mis à jour, note de décision sur le modèle avec le rapport `eval` en lien.

## 13. Hors périmètre, explicitement

- Affichage définitif des résumés dans le HTML de Core — l'aperçu actuel via `build_current_state` est accepté en attendant.
- Résumé de journée, mémoire sémantique, recherche.
- Fine-tuning, LoRA, LLM-as-judge.
- Authentification des producteurs locaux.
- Notification, menu bar, interruption.