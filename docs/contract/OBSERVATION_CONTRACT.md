# Contrat d’observation Pulse

État courant au moment de R2a Core Reset. Ce document décrit le comportement runtime qui existe aujourd’hui. Ce n’est pas une architecture cible et il n’introduit aucun nouveau comportement.

## Périmètre

L’observation correspond au chemin entre un événement local et le flux d’événements du daemon :

```text
Swift / producteur local -> POST /event -> ingestion runtime -> EventBus -> routes de lecture
```

Le contrat est volontairement placé sous le scoring, les sessions, la mémoire, les facts, les LLM, les propositions et l’apprentissage. R2 prouve uniquement que Pulse reçoit, normalise, filtre et expose l’activité locale assez proprement pour que les couches suivantes puissent l’interpréter plus tard.

## Point d’entrée runtime

`POST /event` est enregistré dans `daemon/routes/runtime_ingestion.py`.

Comportement actuel :

- si le runtime est en pause, la route retourne `{"ok": true, "paused": true, "ignored": true}` et ne publie rien ;
- si l’écran est verrouillé, seuls `screen_locked` et `screen_unlocked` sont publiables ;
- les événements d’application mettent à jour `RuntimeState.latest_active_app` avant publication quand `app_name` est présent ;
- les événements terminal sont normalisés avant filtrage / publication ;
- les événements fichier peuvent recevoir une attribution d’acteur avant publication ;
- les événements de création / modification / renommage fichier peuvent être retardés par le coalescer fichier ; fermer le coalescer force l’émission des événements en attente dans les tests ;
- les événements non-fichier sont généralement publiés, sauf blocage par pause / lock ;
- les événements fichier sont filtrés par `EventMeaningPolicy`.

## Familles d’événements

| Famille | Types d’événements | Source probable | Payload minimal | Publiable | Pertinent runtime | Flag scoring policy |
|---|---|---|---|---|---|---|
| app | `app_activated`, `app_switch`, `window_title_poll` | Swift observer / app watcher | `app_name` ; optionnellement `bundle_id`, `system_category`, `window_title` | oui | oui | non selon `EventMeaningPolicy` ; peut influencer le contexte ailleurs |
| file | `file_created`, `file_modified`, `file_renamed`, `file_deleted`, `file_change` | Swift filesystem observer | `path` | meaningful / observe-only : oui ; technical noise : non | meaningful : oui ; observe-only : non ; technical noise : non | oui si non-noise |
| terminal | `terminal_command_started`, `terminal_command_finished` | terminal observer / intégration shell locale | `command` ou `raw` ; optionnellement `cwd`, `exit_code`, `duration_ms`, résumé output | oui | oui | non selon `EventMeaningPolicy` ; peut influencer l’interprétation plus tard |
| idle | `user_presence`, `user_idle`, `user_active` | idle heartbeat / présence OS | état ou champs en secondes selon le producteur | oui | oui | non selon `EventMeaningPolicy` ; signal de support de présence |
| lock | `screen_locked`, `screen_unlocked` | Swift observer / notification système | timestamp optionnel uniquement | oui, même pendant le verrouillage | non dans `EventMeaningPolicy` ; signal de cycle de vie ailleurs | non |
| clipboard | `clipboard_updated` | clipboard observer | métadonnées comme `content_kind`, `char_count` ; le `content` brut est retiré | oui | oui | non |
| MCP | `mcp_command_received`, `mcp_decision` | couche de routes MCP, pas le Swift observer | métadonnées commande / décision | oui, aussi hors `/event` | oui | non selon `EventMeaningPolicy` ; signal de contexte outil |
| internal system | `context_probe_executed`, `llm_loading`, `llm_ready`, `resume_card` | internes daemon / surfaces debug ou Lab | payload spécifique à la route | oui | publié par politique générique ; à traiter comme contextual / debug sauf prise en charge explicite | non |
| unknown | tout autre type d’événement | producteur local inconnu | métadonnées arbitraires | oui sauf pause / lock | oui par politique non-fichier générique actuelle, mais non fiable contractuellement | non |

## Couches de champs

Le payload runtime actuel reste un dictionnaire legacy, pas une envelope typée. R2 utilise ces noms de couches pour éviter que les futures interprétations ne deviennent trop affirmatives.

Quand un champ peut appartenir à plusieurs couches, l’interprétation la plus prudente et la moins confiante doit gagner. Par exemple, `terminal_project` est dérivé depuis `cwd` ; ce n’est pas une identité de projet observée ou confirmée.

### Champs observés

Les champs observés viennent directement du producteur :

- `type`
- `timestamp`
- `app_name`
- `bundle_id`
- `system_category`
- `window_title`
- `path`
- `extension`
- `command` / `raw`
- `cwd`
- `shell`
- `terminal_program`
- `exit_code`
- `duration_ms`
- `stdout_summary`, `test_output_summary`, `output_summary`
- champs de présence comme `presence_state`, `idle_seconds`, `seconds`, `source`

### Champs normalisés

Les champs normalisés sont des réécritures déterministes de données observées :

- `source: "terminal"`
- `kind: "started" | "finished"` pour les événements terminal
- `terminal_command`
- `terminal_command_base`
- `terminal_exit_code`
- `terminal_duration_ms`
- `terminal_success`
- `terminal_summary`
- `terminal_shell`
- `terminal_program`
- `terminal_cwd`

### Champs dérivés

Les champs dérivés sont des enrichissements locaux déterministes construits depuis des données observées / normalisées :

- `terminal_project` depuis `cwd`
- `terminal_workspace_root` depuis la recherche de workspace
- `git_context` depuis `cwd` quand disponible
- `terminal_action_category`
- `terminal_is_read_only`
- `terminal_affects`
- `test_result`
- `file_significance`
- `noise_policy`
- priorité de coalescing et clé de déduplication dans `EventMeaningPolicy`

### Champs inférés

Les champs inférés sont probabilistes ou heuristiques et ne doivent pas être traités comme une vérité observée :

- `_actor`
- `_actor_confidence`
- `_automation_score`

L’attribution d’acteur s’applique actuellement uniquement aux événements fichier dans `/event`.

## Influence et sensibilité

Une observation reste une preuve partielle. Une source isolée ne doit pas être lue comme une certitude sur le travail utilisateur.

Règles prudentes conservées depuis l'ancien modèle d'observation :

- présence utilisateur seule ne prouve pas du travail ;
- app active seule ne prouve pas un projet ni une tâche ;
- titre de fenêtre seul ne confirme pas un projet ;
- commande terminal read-only seule indique surtout de l'inspection ;
- event MCP read-only seul indique un contexte outil, pas du travail utilisateur direct ;
- event fichier `tool_assisted` peut contribuer au contexte, mais ne doit pas être compté comme édition utilisateur directe ;
- event fichier `system` ou chemin technique ne doit pas influencer le présent ;
- clipboard seul ne doit pas inférer un projet ni créer une activité ;
- `screen_unlocked` seul ne rouvre pas automatiquement une activité de travail.

Les données sensibles doivent rester minimisées :

- contenu brut du clipboard : retiré avant publication ;
- commandes terminal / MCP : à traiter comme sensibles et à redacter avant persistance durable quand elles sont stockées ;
- titres de fenêtre : utiles comme support, mais potentiellement sensibles et faibles comme preuve ;
- chemins fichiers : utiles, mais les chemins techniques, caches, secrets et artefacts système doivent être filtrés ou déclassés.

Règle générale : plus une donnée est sensible, plus sa durée de vie et son influence doivent être réduites.

## Fixtures golden actuelles

La première fixture golden R2 est `tests/fixtures/observation/core_events.json`.

Elle couvre :

- activation d’une app de développement ;
- fichier source meaningful ;
- fichier cache / noise ;
- commande terminal de test en échec ;
- verrouillage d’écran ;
- déverrouillage d’écran.

Les chemins utilisent volontairement `/Users/tester/workspace/acme/...` et ne doivent pas utiliser de chemins développeur locaux comme `/Users/yugz`.

## Test golden pipeline actuel

`tests/test_observation_ingestion_golden.py` vérifie le comportement actuel à travers l’enregistrement réel des routes :

- `app_activated` est accepté, publié et met à jour l’app active la plus récente ;
- les événements de fichier source meaningful atteignent l’`EventBus` avec attribution d’acteur ;
- `.cache/models_cache.json` est filtré par la policy d’observation actuelle ;
- `terminal_command_finished` est normalisé ;
- les événements lock / unlock restent publiables ;
- `/feed` reste lisible après les événements golden.

## Ambiguïtés explicites

- `observation_qualification.py` est passif. Il documente l’influence autorisée, mais il n’est pas encore la source de vérité runtime.
- `event_envelope.py` est passif et ne doit pas être branché globalement pendant R2a.
- `EventMeaningPolicy.scoring_relevant` n’est pas équivalent à “affectera `SignalScorer`” ; R3 possède cette validation.
- Les événements inconnus non-fichier sont publiables aujourd’hui. C’est le comportement actuel, pas une recommandation de s’appuyer sur les événements inconnus.
- Certains champs nommés comme project / task sont dérivés du contexte local, pas des faits observés.
- Le feed est une projection lisible, pas le journal canonique des événements.

## Garde-fous R2

Ne pas utiliser ce contrat pour ajouter de l’apprentissage, des facts, des écritures mémoire, une réparation LLM, des propositions ou de l’inférence long terme d’identité / projet. R2 s’arrête à l’observation propre.
