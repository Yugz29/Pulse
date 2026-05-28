

# Notes de dogfooding Core

Ce document rassemble les observations terrain faites après la validation du Core Reset R1-R6.

Il ne remplace pas les contrats Core ni la roadmap. Il sert à conserver les faits observés en usage réel avant toute correction ou nouvelle feature.

Autorités de référence :

- `docs/CORE_RESET_VALIDATION_SUMMARY.md`
- `docs/ROADMAP_CORE_RESET.md`
- contrats Core : observation, interprétation, sessions, mémoire minimale, propositions contrôlées

## Règles de lecture

- Une observation terrain n’est pas automatiquement un bug confirmé.
- Une anomalie doit être reproduite avant correction.
- Ne pas démarrer R7 depuis ce document.
- Ne pas réactiver DayDream, facts/profile, vector store, LLM summaries, context probes, work intent ou propositions intelligentes depuis ces notes.
- Le but immédiat est de vérifier que le Core reste cohérent en usage réel.

---

## 2026-05-27 — Première session terrain Core

### Contexte

Première relance réelle de l’app macOS après le Core Reset.

Mode attendu : `PULSE_MODE=core`.

Objectif : vérifier que l’app, le daemon, les endpoints Core et le dashboard restent utilisables après le refactor R1-R6.

### Lancement app / daemon

L’app macOS démarre correctement après le Core Reset.

Le daemon redémarré depuis l’interface Pulse fonctionne et répond sur l’API locale.

Un lancement manuel préalable a échoué :

```bash
PULSE_MODE=core .venv/bin/python3 -m daemon.main
```

Sortie observée :

```text
Address already in use
Port 8766 is in use by another program.
Port 8765 is in use by another program.
```

Interprétation actuelle : une instance du daemon était probablement déjà active ou gérée par l’app.

Précision utilisateur : la mini-session observée ensuite correspond surtout au stop / redémarrage du daemon depuis l’interface Pulse, pas seulement au lancement manuel échoué.

Note de contexte dev : pendant le développement de Pulse, les redémarrages daemon seront fréquents pour appliquer du nouveau code. Des sessions très courtes autour d’un stop / restart volontaire doivent donc être considérées comme un comportement attendu en développement, sauf si elles polluent fortement l’historique ou faussent les métriques utilisateur.

À surveiller : friction UX/dev autour du daemon déjà lancé et du redémarrage depuis l’interface. Le comportement n’est pas traité comme une régression Core à ce stade.

### Vérification `/health/core`

Commande :

```bash
curl http://127.0.0.1:8765/health/core | python -m json.tool
```

Résultat observé :

```json
{
  "checks": {
    "event_bus": "ok",
    "feed_source": "ok",
    "lab_services": "not_required",
    "ping": "ok",
    "runtime": "ok",
    "runtime_state": "ok",
    "scoring": "available",
    "session_fsm": "ok"
  },
  "experimental_enabled": false,
  "failed": {},
  "pulse_mode": "core",
  "status": "ok"
}
```

Points validés manuellement :

- mode Core actif ;
- services Lab non requis ;
- runtime OK ;
- `RuntimeState` OK ;
- `EventBus` OK ;
- feed source OK ;
- scoring disponible ;
- `SessionFSM` OK.

Conclusion : le socle Core répond correctement en usage réel initial.

### Vérification `/state`

Commande :

```bash
curl http://127.0.0.1:8765/state | python -m json.tool | head -80
```

Extraits significatifs :

```json
{
  "active_app": "Code",
  "active_file": "CORE_RESET_VALIDATION_SUMMARY.md",
  "active_project": "Pulse",
  "experimental_enabled": false,
  "current_context": {
    "active_app": "Code",
    "active_project": "Pulse",
    "active_file": "CORE_RESET_VALIDATION_SUMMARY.md",
    "activity_level": "executing",
    "focus_level": "normal",
    "probable_task": "general",
    "task_confidence": 0.48,
    "terminal_action_category": "execution",
    "terminal_cwd": "/Users/yugz/Projets/Pulse/Pulse",
    "terminal_project": "Pulse"
  },
  "present": {
    "active_project": "Pulse",
    "active_file": "CORE_RESET_VALIDATION_SUMMARY.md",
    "activity_level": "executing",
    "focus_level": "normal",
    "probable_task": "general",
    "session_status": "active"
  }
}
```

Points positifs :

- app active correctement détectée : `Code` ;
- projet actif correctement détecté : `Pulse` ;
- fichier actif correctement détecté : `CORE_RESET_VALIDATION_SUMMARY.md` ;
- terminal rattaché au projet via `terminal_cwd` ;
- activité terminal reconnue comme `execution` ;
- mode expérimental désactivé ;
- session runtime active.

Point important : le scorer reste prudent.

```text
probable_task = general
task_confidence = 0.48
focus_level = normal
```

C’est cohérent avec le Core Reset : Pulse observe un contexte de travail réel, mais ne sur-affirme pas une tâche spécialisée.

Limite observée : les commandes de diagnostic `curl` sont elles-mêmes observées par Pulse. Elles peuvent temporairement influencer :

- `activity_level` ;
- `terminal_action_category` ;
- `/feed` ;
- le contexte courant.

Ce comportement est normal, mais doit être pris en compte pendant le dogfooding.

### Vérification `/feed`

Commande :

```bash
curl http://127.0.0.1:8765/feed | python -m json.tool
```

Résultat observé :

```json
[
  {
    "command": "curl http://127.0.0.1:8765/health/core | python -m json.tool",
    "kind": "terminal",
    "label": "✓ Télécharge des données depuis 127.0.0.1:8765",
    "success": true,
    "timestamp": "2026-05-27T10:48:47"
  },
  {
    "command": "curl http://127.0.0.1:8765/state | python -m json.tool | head -80",
    "kind": "terminal",
    "label": "✓ Télécharge des données depuis 127.0.0.1:8765",
    "success": true,
    "timestamp": "2026-05-27T10:49:42"
  }
]
```

Points positifs :

- `/feed` fonctionne ;
- les événements terminal sont lisibles ;
- les commandes réussies sont marquées `success: true` ;
- le résumé terminal est compréhensible.

Limite : pendant le diagnostic, le feed devient surtout un feed des commandes `curl` envoyées à Pulse.

À vérifier plus tard : comportement du feed après 30 à 60 minutes de travail normal sans interroger Pulse en boucle.

### Vérification `/debug/state`

Commande :

```bash
curl http://127.0.0.1:8765/debug/state | python -m json.tool | head -120
```

Résultats notables :

```json
{
  "pulse_mode": "core",
  "experimental_enabled": false,
  "legacy_in_state": false
}
```

Le `current_context` est cohérent avec `/state` :

```json
{
  "active_app": "Code",
  "active_file": "CORE_RESET_VALIDATION_SUMMARY.md",
  "active_project": "Pulse",
  "activity_level": "executing",
  "probable_task": "general",
  "task_confidence": 0.48,
  "terminal_project": "Pulse"
}
```

`recent_sessions` contient bien des sessions historiques.

Observation notable : une session très courte apparaît autour du lancement manuel échoué :

```json
{
  "active_project": null,
  "activity_level": "idle",
  "boundary_reason": "session_end",
  "duration_sec": 0,
  "started_at": "2026-05-27T10:35:17.206045",
  "ended_at": "2026-05-27T10:35:17.244862"
}
```

Interprétation corrigée : cette session très courte correspond probablement au stop / redémarrage du daemon depuis l’interface Pulse. Elle ne prouve pas encore qu’un lancement manuel échoué crée systématiquement une session vide.

Décision provisoire : ne pas traiter les sessions très courtes de redémarrage comme des bugs tant qu’elles sont liées à un cycle dev volontaire. Elles deviennent un sujet produit seulement si elles apparaissent dans une session utilisateur normale, si elles dominent `recent_sessions`, ou si elles perturbent les durées / résumés affichés.

À reproduire avant correction :

- distinguer un redémarrage volontaire depuis l’interface d’un échec de lancement manuel par port déjà utilisé ;
- vérifier si le redémarrage depuis l’interface crée systématiquement une session courte attendue ;
- vérifier si un échec de bind sur les ports `8765` / `8766` crée réellement une session vide ;
- vérifier si ces sessions courtes polluent `recent_sessions` ou sont simplement une trace normale de cycle daemon.

Ne pas corriger sans reproduction ciblée.

### Observation dashboard : temporalités mélangées

La capture dashboard montrait plusieurs couches d’information qui semblaient partiellement divergentes :

- projet du jour : `Pulse` ;
- tâche ou activité liée à `version_control` / `Exécution` dans certaines zones ;
- contexte actuel plus faible, avec `Général`, `Lecture` ou confiance modérée dans d’autres zones.

Au même moment, l’API `/state` indiquait plutôt :

```text
active_project = Pulse
probable_task = general
activity_level = executing
task_confidence = 0.48
```

Interprétation actuelle : le dashboard semble afficher plusieurs temporalités ou surfaces sans toujours les distinguer clairement :

- activité du jour ;
- session actuelle ;
- bloc de travail ou historique récent ;
- contexte live ;
- signaux terminal récents ;
- peut-être données liées à Git / version control.

Ce n’est pas forcément faux, mais cela peut donner une impression de contradiction si la source temporelle n’est pas visible.

**Observation utilisateur : après redémarrage du daemon, Pulse est capable de récupérer une partie du flux déjà en cours avant interruption. Tant qu’aucune nouvelle activité solide n’a encore eu lieu, il est cohérent que le contexte reste faible ou prudent. Ce comportement est acceptable si l’interface le présente comme un contexte en reprise / faible preuve, et non comme une contradiction.**

À surveiller : clarifier dans le dashboard la provenance temporelle de chaque donnée.

Découpage utile à vérifier plus tard :

- contexte live ;
- résumé de session ;
- activité du jour ;
- historique / mémoire minimale ;
- signaux terminal récents ;
- surfaces Lab / debug.

Ne pas corriger maintenant avant observation terrain supplémentaire.

## Verdict de la première session

Premier signal terrain positif.

Validé manuellement :

- l’app macOS démarre ;
- le daemon Core répond ;
- `/health/core` est OK ;
- `PULSE_MODE=core` est effectif ;
- `experimental_enabled=false` ;
- `/state` est cohérent ;
- `/feed` est lisible ;
- `/debug/state` est exploitable ;
- l’interprétation reste prudente.

Points à surveiller :

- conflit de daemon déjà lancé ;
- sessions très courtes liées aux redémarrages daemon en développement ;
- pollution de `/feed` par les commandes de diagnostic ;
- dashboard qui mélange possiblement plusieurs temporalités.

## À reproduire avant correction

- Différencier session courte attendue après redémarrage daemon volontaire, session courte liée à l’interface, et session vide éventuelle après conflit de ports `8765` / `8766`.
- Dashboard qui semble mélanger activité du jour, session, contexte actuel et historique.
- Feed pollué par les commandes de diagnostic.

## Prochain test terrain

Faire 30 à 60 minutes de travail normal sans interroger Pulse constamment.

À observer ensuite :

- `/health/core` ;
- `/state` ;
- `/feed` ;
- `/debug/state` ;
- dashboard ;
- sessions récentes ;
- logs daemon.

Objectif : vérifier si Pulse reste cohérent hors scénario de diagnostic.

Pendant les prochaines sessions de développement de Pulse, noter séparément :

- redémarrage daemon volontaire ;
- redémarrage daemon inattendu ;
- conflit de ports ;
- session courte attendue ;
- session courte qui pollue réellement les métriques.


---

## 2026-05-27 — Session hors-code : candidatures

### Contexte

Activité réelle : candidature à plusieurs offres d’emploi.

Ce n’était pas une session de code ni une session centrée sur le projet Pulse.

Cette session sert à vérifier un point important du Core Reset : Pulse doit rester prudent quand l’activité n’entre pas clairement dans son modèle de session de travail technique.

### Vérification `/health/core`

Commande :

```bash
curl http://127.0.0.1:8765/health/core | python -m json.tool
```

Résultat :

```json
{
  "status": "ok",
  "pulse_mode": "core",
  "experimental_enabled": false,
  "checks": {
    "runtime": "ok",
    "runtime_state": "ok",
    "event_bus": "ok",
    "feed_source": "ok",
    "scoring": "available",
    "session_fsm": "ok",
    "lab_services": "not_required"
  },
  "failed": {}
}
```

Conclusion : le daemon reste sain après une activité hors-code.

### Vérification `/state`

Commande :

```bash
curl http://127.0.0.1:8765/state | python -m json.tool | head -120
```

Extraits significatifs :

```json
{
  "active_app": "Code",
  "active_file": "CORE_DOGFOODING_NOTES.md",
  "active_project": "Pulse",
  "experimental_enabled": false,
  "current_context": {
    "active_app": "Code",
    "active_project": "Pulse",
    "active_file": "CORE_DOGFOODING_NOTES.md",
    "activity_level": "executing",
    "probable_task": "general",
    "task_confidence": 0.48,
    "terminal_action_category": "execution",
    "terminal_cwd": "/Users/yugz/Projets/Pulse/Pulse",
    "terminal_project": "Pulse"
  },
  "present": {
    "active_project": "Pulse",
    "active_file": "CORE_DOGFOODING_NOTES.md",
    "activity_level": "executing",
    "probable_task": "general",
    "session_duration_min": 104,
    "session_status": "active"
  }
}
```

Applications récentes observées :

```json
[
  "Plans",
  "Safari",
  "Google Chrome",
  "ChatGPT",
  "Code"
]
```

### Lecture terrain

Le résultat `/state` reflète surtout le contexte live au moment de la commande : retour dans VS Code, fichier de notes dogfooding ouvert, commande `curl` lancée depuis le repo Pulse.

Il ne résume pas directement toute l’activité précédente de candidature.

Les applications récentes racontent mieux le flux réel hors-code : navigation web, possible consultation de lieux / trajets, ChatGPT, puis retour dans Code.

### Limite connue

Cette limite est attendue pour l’instant.

Pulse Core est encore centré sur les sessions de travail et les signaux techniques observables. Une activité personnelle, administrative ou hors projet peut donc être traitée comme :

- contexte faible ;
- activité générale ;
- navigation / lecture / rédaction si les signaux sont suffisants ;
- bruit ou activité hors projet si elle ne se rattache pas clairement à un espace de travail.

Ce comportement est préférable à une sur-interprétation.

Le bon comportement actuel n’est pas que Pulse comprenne parfaitement une candidature. Le bon comportement est qu’il n’invente pas un projet technique, une tâche de code ou une mémoire forte à partir de signaux faibles.

### Points positifs

- Le Core reste sain après une activité hors-code.
- `pulse_mode=core` et `experimental_enabled=false` restent corrects.
- Pulse ne force pas une tâche spécialisée : `probable_task=general`.
- La confiance reste prudente : `task_confidence=0.48`.
- Le contexte live est correctement compris après retour dans VS Code.
- Les apps récentes conservent une trace utile de l’activité précédente.


### Vérification `/feed`

Commande :

```bash
curl http://127.0.0.1:8765/feed | python -m json.tool
```

Résultat observé :

```json
[
  {
    "command": "curl http://127.0.0.1:8765/health/core | python -m json.tool",
    "kind": "terminal",
    "label": "✓ Télécharge des données depuis 127.0.0.1:8765",
    "success": true,
    "timestamp": "2026-05-27T12:31:59"
  },
  {
    "command": "curl http://127.0.0.1:8765/state | python -m json.tool | head -120",
    "kind": "terminal",
    "label": "✓ Télécharge des données depuis 127.0.0.1:8765",
    "success": true,
    "timestamp": "2026-05-27T12:33:25"
  },
  {
    "command": "clear",
    "kind": "terminal",
    "label": "✓ Commande terminal",
    "success": true,
    "timestamp": "2026-05-27T12:35:36"
  }
]
```

Lecture terrain :

- `/feed` reste fonctionnel et lisible ;
- les commandes terminal sont correctement normalisées ;
- les commandes réussies sont bien marquées `success: true` ;
- le feed ne raconte pas l’activité de candidature elle-même ;
- il reflète surtout les commandes de diagnostic lancées après coup.


### Vérification `/debug/state`

Commande :

```bash
curl http://127.0.0.1:8765/debug/state | python -m json.tool | head -180
```

Extraits significatifs :

```json
{
  "pulse_mode": "core",
  "experimental_enabled": false,
  "legacy_in_state": false,
  "current_context": {
    "active_app": "Code",
    "active_file": "/Users/yugz/Projets/Pulse/Pulse/docs/CORE_DOGFOODING_NOTES.md",
    "active_project": "Pulse",
    "activity_level": "executing",
    "probable_task": "writing",
    "task_confidence": 0.52,
    "terminal_project": "Pulse"
  },
  "session_fsm": {
    "state": "active",
    "session_started_at": "2026-05-27T10:48:47",
    "last_meaningful_activity_at": "2026-05-27T12:39:46",
    "last_screen_locked_at": null
  }
}
```

Applications récentes :

```json
[
  "Plans",
  "Safari",
  "Google Chrome",
  "ChatGPT",
  "Code"
]
```

Lecture terrain :

- `/debug/state` confirme que Pulse reste en Core ;
- le contexte live est revenu sur le projet Pulse après retour dans VS Code ;
- la rédaction de `CORE_DOGFOODING_NOTES.md` est maintenant qualifiée comme `writing` ;
- la confiance reste modérée (`0.52`) ;
- `recent_apps` garde une trace de la séquence hors-code précédente ;
- `SessionFSM` reste `active`, avec une activité significative récente.

Conclusion : le comportement est cohérent. Pulse ne résume pas toute la période de candidature, mais il suit correctement le contexte live après retour sur la documentation et reste prudent dans son interprétation.

### Captures dashboard après retour sur la documentation

Captures observées après retour dans Pulse / VS Code et rédaction des notes de dogfooding.

État visible dans l’onglet `Aujourd’hui` :

- daemon actif ;
- travail du jour autour de `01h00` ;
- `10` commits ;
- `4` blocs ;
- `1` projet ;
- projet du jour : `Pulse` ;
- contexte actuel : `Rédaction` ;
- projet : `Pulse` ;
- tâche : `Rédaction` ;
- activité : `Exécution` ;
- focus : `Normal` ;
- confiance : `76 %` ;
- explication : projet corroboré par les signaux disponibles, avec mention que des apps support détectées ne sont pas utilisées comme preuve principale.

État visible dans l’onglet `Travail` :

- une séquence en cours `12:36 → 12:40`, durée `3 min`, étiquetée `Pulse`, `Docs`, `Rédaction` ;
- statut `En cours` ;
- message : `Pulse observe encore cette séquence de travail.` ;
- confiance `0.60` ;
- séquences précédentes autour de livraison / Git et rédaction.

Lecture terrain :

- après retour sur la documentation, le dashboard converge vers une interprétation plus solide que juste après le redémarrage ;
- la tâche `Rédaction` est cohérente avec la modification de `CORE_DOGFOODING_NOTES.md` ;
- l’onglet `Travail` isole correctement une séquence courte `Pulse / Docs / Rédaction` en cours ;
- l’activité `Exécution` reste probablement influencée par les commandes terminal `curl` lancées pour diagnostiquer Pulse ;
- la confiance élevée côté dashboard (`76 %`) peut coexister avec une confiance plus modérée dans certains payloads debug (`0.52`) car les surfaces ne semblent pas représenter exactement la même temporalité ou le même agrégat ;
- l’onglet `Travail` distingue mieux les séquences historiques et la séquence en cours.

Observation UX : le dashboard affiche plusieurs niveaux de vérité en même temps : résumé du jour, bloc courant, contexte live, séquence de travail et historique. Ces informations peuvent toutes être correctes, mais l’interface ne nomme pas encore assez clairement la source temporelle de chaque donnée.

Point précis observé : `Tâche = Rédaction` et `Activité = Exécution` peuvent paraître contradictoires visuellement. C’est probablement cohérent côté signaux, car la tâche principale est la rédaction de documentation tandis qu’un signal terminal récent indique une exécution de commande. Côté UX, il serait plus clair de distinguer `tâche principale` et `signal récent` plutôt que de présenter `Exécution` comme activité globale non contextualisée.

Conclusion : le dashboard devient plus cohérent après activité solide dans le projet Pulse. Le problème principal n’est pas forcément le scorer, mais la lisibilité des agrégats affichés : contexte live, activité du jour, séquence de travail, historique et signaux récents doivent rester visuellement distingués.

### Points à surveiller

- `/state` est une photo du contexte live, pas un résumé de toute la période précédente.
- Les commandes de diagnostic après coup peuvent masquer l’activité réelle précédente.
- Les activités hors projet risquent d’être invisibles ou faiblement qualifiées, ce qui est acceptable tant que Pulse ne sur-affirme pas.
- Le dashboard devra éviter de présenter une activité hors-code comme une session technique claire.

### Décision provisoire

Ne pas corriger maintenant.

Pour le Core actuel, ce comportement est acceptable : Pulse reste prudent et ne prétend pas comprendre une activité hors projet.


---

## 2026-05-27 — Patch UI : clarification des temporalités dashboard

### Contexte

Après les premières captures terrain, le dashboard donnait parfois une impression de contradiction entre plusieurs informations pourtant probablement cohérentes côté backend :

- `Tâche = Rédaction` ;
- `Activité = Exécution` ;
- confiance dashboard élevée ;
- confiance de séquence différente ;
- confiance debug/current context différente.

Lecture : le problème principal n’était pas le scoring, mais la lisibilité des sources et temporalités affichées.

### Patch appliqué

Patch Swift/UI appliqué pour clarifier les libellés, sans modifier les données backend :

- `Travail` -> `Séquences debug` ;
- `Mémoire` -> `Mémoire (Lab)` ;
- `DayDream` -> `DayDream (Lab)` ;
- `Contexte` -> `Contexte (Lab)` ;
- `Contexte actuel` -> `Lecture courante` ;
- `Bloc de travail courant` -> `Bloc du jour en cours` ;
- `Épisodes de travail` -> `Séquences reconstruites (debug)` ;
- `Tâche` -> `Tâche principale` ;
- `Activité` -> `Activité récente` ;
- `Confiance` -> `Confiance tâche` ;
- `Confiance` des séquences -> `Confiance séquence`.

Micro-copy ajoutée :

- le contexte live décrit l’instant courant ;
- les séquences et le résumé du jour agrègent une période plus large ;
- les séquences debug sont une reconstruction depuis événements / journal, pas une source Core canonique.

### Observation après patch

Captures après patch :

- la navigation distingue mieux Core, debug et Lab ;
- les surfaces expérimentales sont plus honnêtes : `Mémoire (Lab)`, `DayDream (Lab)`, `Contexte (Lab)` ;
- `Séquences debug` rend plus clair que l’onglet `Travail` repose sur une reconstruction ;
- `Lecture courante` et `Hypothèse live` rendent mieux la nature instantanée du contexte ;
- `Tâche principale` et `Activité récente` réduisent l’impression de contradiction entre `Développement` / `Lecture` ou `Rédaction` / `Exécution`.

### Verdict provisoire

Patch UI réussi pour le dogfooding.

Il ne rend pas le dashboard parfait, mais il réduit fortement le risque de vendre une reconstruction debug ou une surface Lab comme vérité Core stable.


---

## 2026-05-27 — Hardening daemon dev : stop / restart / ports occupés

### Contexte

Pendant le développement de Pulse, les redémarrages daemon sont fréquents pour appliquer du nouveau code.

Les premières sessions de dogfooding ont montré deux risques autour du cycle daemon :

- l’interface pouvait croire que le daemon était arrêté alors qu’il répondait encore ;
- le script dev pouvait lancer `daemon.main` alors que le port `8765` était déjà occupé mais que `/ping` ne répondait pas comme un daemon Pulse valide.

Ces cas pouvaient provoquer des faux redémarrages, des conflits de ports ou des sessions très courtes parasites.

### Patch Swift appliqué

Patch appliqué côté `DaemonController` :

- `waitForStop()` confirme maintenant réellement l’arrêt du daemon ;
- si `/ping` cesse de répondre avant timeout, l’état passe à `.stopped` ;
- si `/ping` répond encore après timeout, l’état repasse à `.running` ;
- `lastError` indique : `Daemon still responds on :8765 after stop timeout` ;
- `restartDaemon()` ne relance plus le script dev si l’arrêt n’est pas confirmé.

Tests ajoutés :

- stop confirmé -> `.stopped` ;
- stop timeout avec `/ping` vivant -> reste `.running` ;
- restart timeout -> ne relance pas après arrêt non confirmé.

Validation ciblée :

```bash
xcodebuild test -project App/Pulse.xcodeproj -scheme App -only-testing:AppTests/DaemonControllerTests
```

Résultat observé : `3 tests OK`.

### Patch script appliqué

Patch appliqué dans `scripts/start_pulse_daemon.sh` :

- le script teste maintenant `/ping` avant de vérifier `.venv` ;
- si `/ping` répond, il loggue `Daemon already active on :8765.` et sort `0` ;
- si `/ping` échoue mais que `8765` a déjà un listener, il refuse de lancer `daemon.main` et sort `1` ;
- si `8766` est occupé, il loggue un warning non bloquant et continue le lancement Core ;
- l’absence éventuelle de `lsof` est traitée par warning, sans bloquer.

Comportement corrigé :

- avant : `8765` occupé + `/ping` invalide -> lancement de `python -m daemon.main` ;
- après : `8765` occupé + `/ping` invalide -> refus explicite, pas de lancement Python.

### Validation manuelle

Commande lancée avec un daemon déjà actif :

```bash
scripts/start_pulse_daemon.sh
echo $?
```

Résultat observé :

```text
[Pulse] Daemon already active on :8765.
0
```

Vérification ports :

```bash
lsof -i :8765
lsof -i :8766
```

Résultat : un seul process Python écoute sur les deux ports.

Conclusion : le script détecte correctement un daemon déjà actif et ne relance pas `daemon.main`.

### Observation `/state` après hardening

Après les patchs, Pulse détecte correctement une session de développement sur le script daemon :

```text
active_app = Code
active_file = scripts/start_pulse_daemon.sh
active_project = Pulse
probable_task = coding
activity_level = executing
task_confidence = 0.71
session_status = active
```

Lecture terrain : le contexte est cohérent avec le travail réel effectué : audit, patch script, tests Swift, tests Python, validation ports et commandes de diagnostic.

### Observation `/feed` après hardening

Le feed devient pertinent sur une vraie session de développement projet. Il expose notamment :

- `/health/core` ;
- tests `xcodebuild` ciblés ;
- `./scripts/test_all.sh` ;
- `scripts/start_pulse_daemon.sh` ;
- `lsof -i :8765` / `lsof -i :8766` ;
- commandes `curl` de diagnostic.

Lecture terrain : contrairement aux sessions hors-code, `/feed` raconte correctement une session technique Pulse.

### Point à surveiller

`recent_sessions` peut encore contenir des sessions très courtes ou incohérentes issues de tests, redémarrages ou artefacts de développement.

Hypothèse actuelle : ces entrées sont liées aux cycles dev / tests Codex / restart daemon, pas à un problème utilisateur normal.

Décision provisoire : ne pas corriger tant que ce n’est pas reproduit hors cycle dev.

### Verdict provisoire

Le cycle daemon dev est plus robuste :

- Swift évite le faux état `stopped` ;
- le script évite le faux démarrage quand `8765` est déjà occupé ;
- le risque de sessions courtes parasites est réduit à la source ;
- le Core reste sain après les patchs.

À vérifier dans les prochaines sessions :

- redémarrage volontaire depuis l’interface ;
- conflit de ports réel ;
- lisibilité de l’erreur côté app ;
- absence de second daemon lancé ;
- impact restant des sessions courtes de dev dans le dashboard.
---

## 2026-05-28 — Test terrain : pause, verrouillage, déverrouillage, reprise

### Contexte

Session terrain après application des réglages Xcode recommandés, lancement de tests, pause avec verrouillage / déverrouillage du Mac, puis reprise et relance de tests.

Objectif : vérifier le comportement Core autour d’un cycle naturel de travail : activité -> pause / lock -> unlock -> reprise.

### Vérification `/health/core`

Résultat observé :

```json
{
  "status": "ok",
  "pulse_mode": "core",
  "experimental_enabled": false,
  "checks": {
    "runtime": "ok",
    "runtime_state": "ok",
    "event_bus": "ok",
    "feed_source": "ok",
    "scoring": "available",
    "session_fsm": "ok",
    "lab_services": "not_required"
  },
  "failed": {}
}
```

Conclusion : le Core reste sain après pause, verrouillage et déverrouillage.

### Vérification `/state`

Après reprise, le contexte live indique :

```text
active_app = Code
active_file = CORE_DOGFOODING_NOTES.md
active_project = Pulse
probable_task = writing
activity_level = executing
task_confidence = 0.43
session_status = active
locked = false
user_presence_state = active
```

Lecture terrain : après retour dans VS Code et lancement des commandes de diagnostic, Pulse comprend correctement que le contexte live est revenu sur Pulse / documentation / terminal.

La confiance modérée est cohérente : le contexte est réel, mais les commandes `curl` de diagnostic influencent l’activité récente.

### Vérification `/debug/state`

État runtime observé après reprise :

```text
pulse_mode = core
experimental_enabled = false
legacy_in_state = false
session_fsm.state = active
session_fsm.session_started_at = 2026-05-28T12:24:32
session_fsm.last_meaningful_activity_at = 2026-05-28T12:25:24
runtime.lock_marker_active = false
runtime.last_screen_locked_at = null
```

Une session précédente a été fermée :

```text
started_at = 2026-05-28T12:05:11
ended_at = 2026-05-28T12:20:33
duration_sec = 922
active_project = Pulse
probable_task = coding
activity_level = executing
```

Lecture terrain : Pulse semble avoir séparé la session de travail avant pause de la session active après reprise. Ce comportement est acceptable si la pause / lock représente une vraie rupture de travail.

Limite : le `boundary_reason` exposé dans `recent_sessions` reste générique (`session_end`). Il ne permet pas encore de savoir clairement si la coupure vient du lock, de l’idle, d’un timeout ou d’un restart.

### Vérification `/feed`

`/feed` expose surtout les événements terminal récents :

```text
pytest -m
pytest
pytest
clear
```

Lecture terrain : pour une session de dev, le feed reste utile pour les commandes terminal, mais il ne raconte pas clairement le cycle lock / unlock.

Conclusion : `/feed` est encore très terminal-centric. Il ne doit pas être utilisé seul pour comprendre les transitions de session.

### Observation dashboard / Événements

Dans l’onglet `Événements`, le déverrouillage est visible :

```text
screen_unlocked
session déverrouillée
```

Le verrouillage est aussi visible dans la capture :

```text
screen_locked
session verrouillée
```

Observation : les événements lock / unlock existent bien dans la surface Événements, mais ils ne ressortent pas dans `/feed` et ne sont pas expliqués clairement dans `recent_sessions`.

Autre observation : l’onglet `Événements` contient beaucoup d’événements `user_presence`, ce qui ajoute du bruit visuel autour des événements réellement importants comme `screen_locked` et `screen_unlocked`.

### Points positifs

- Le daemon reste sain après lock / unlock.
- `SessionFSM` revient en `active` après reprise.
- Le contexte live redevient cohérent après retour dans VS Code.
- Les événements `screen_locked` et `screen_unlocked` sont bien visibles dans l’onglet Événements.
- Une session de travail précédente est bien présente dans `recent_sessions`.

### Points à surveiller

- `/feed` ne montre pas clairement le lock / unlock.
- `recent_sessions.boundary_reason` reste trop générique (`session_end`).
- `runtime.last_screen_locked_at` vaut `null` après reprise, ce qui est normal si l’état lock est terminé, mais moins utile pour comprendre l’historique immédiat.
- L’onglet `Événements` est bruité par de nombreux `user_presence`.
- Il faudra décider si `user_presence` doit être filtré, groupé ou rendu moins visible dans la vue par défaut.

### Verdict provisoire


Le cycle lock / unlock semble fonctionner côté Core, mais son observabilité est incomplète.

La priorité n’est pas de modifier `SessionFSM`. Le sujet terrain est plutôt l’explicabilité : rendre les transitions lock / unlock plus lisibles dans les surfaces de diagnostic, sans transformer chaque `user_presence` en événement visible de même importance.

---

## 2026-05-28 — Patch UI : réduction du bruit `user_presence` dans Événements

### Contexte

Le test terrain pause / verrouillage / déverrouillage a confirmé que les événements `screen_locked` et `screen_unlocked` existent bien et sont visibles dans l’onglet `Événements`.

Le problème observé n’était pas une perte d’événement côté backend, mais une lisibilité insuffisante : beaucoup d’événements `user_presence` rendaient la vue `Tous` trop bruitée.

### Patch appliqué

Patch Swift/UI appliqué sans modification backend :

- `user_presence` est masqué par défaut dans l’onglet `Événements` quand le filtre est `Tous` ;
- le filtre explicite `user_presence` reste disponible via les chips existants ;
- une micro-copy indique que `user_presence` est masqué par défaut pour réduire le bruit ;
- les labels sont rendus plus lisibles :
  - `screen_locked` -> `Verrouillage écran` ;
  - `screen_unlocked` -> `Déverrouillage écran` ;
  - `user_presence` -> `Présence`.

### Comportement avant / après

Avant :

- `user_presence` pouvait dominer la vue `Tous` ;
- les événements lock / unlock existaient, mais se retrouvaient noyés dans le bruit de présence ;
- les labels bruts `screen_locked` / `screen_unlocked` restaient trop techniques.

Après :

- la vue `Tous` reste plus lisible ;
- les événements de cycle écran ressortent mieux ;
- `user_presence` reste inspectable explicitement en debug ;
- aucun événement n’est supprimé côté backend.

### Tests

Test Swift ciblé ajouté / lancé :

```bash
xcodebuild test -project App/Pulse.xcodeproj -scheme App -destination 'platform=macOS' -only-testing:AppTests/PulseViewModelInteractionsTests/testInsightEventLabelsUseReadableLifecycleNames
```

Résultat observé : `TEST SUCCEEDED`.

### Verdict provisoire

Patch réussi pour le dogfooding.

La correction reste au bon niveau : elle améliore l’observabilité et la lisibilité de l’onglet `Événements` sans toucher au runtime, à l’EventBus, à `SessionFSM`, à `SessionMemory`, au scoring ou aux heartbeats `user_presence`.

À vérifier dans les prochaines sessions :

- `Verrouillage écran` / `Déverrouillage écran` ressortent-ils clairement dans `Tous` ?
- le filtre `Présence` reste-t-il suffisant pour inspecter le bruit de présence quand nécessaire ?
- la micro-copy est-elle utile sans surcharger l’interface ?
---

## 2026-05-28 — Patch Core : persistance de `close_reason` session

### Contexte

Le test terrain lock / unlock a montré que `SessionFSM` et les événements `screen_locked` / `screen_unlocked` fonctionnent, mais que `/state.recent_sessions` exposait systématiquement :

```text
boundary_reason = session_end
```

Cette valeur était trop générique et pouvait masquer la vraie raison de fermeture d’une session : lock long, idle timeout, shutdown ou réparation stale.

Audit ciblé : le problème ne venait pas de `SessionFSM`. Le runtime transmettait déjà parfois une vraie raison via `close_reason`, mais `SessionMemory` ne la persistait pas et reconstruisait ensuite `boundary_reason` en dur.

### Patch appliqué

Patch Core minimal appliqué côté `SessionMemory` :

- ajout de la colonne SQLite `close_reason TEXT` sur la table `sessions` ;
- `SessionMemory.close(close_reason=...)` persiste maintenant la raison de fermeture ;
- `_repair_stale_open_rows()` marque les fermetures réparées avec `close_reason="stale_repair"` ;
- `get_recent_sessions()` expose maintenant :

```text
boundary_reason = close_reason or session_end
```

### Comportement avant / après

Avant :

- `/state.recent_sessions[].boundary_reason` valait toujours `session_end` ;
- l’UI ne pouvait pas distinguer une fermeture normale, un lock long, un idle timeout ou une réparation stale ;
- la projection était artificielle et moins honnête que le runtime.

Après :

- une session fermée par lock peut exposer `boundary_reason="screen_lock"` ;
- une session fermée par idle peut exposer `boundary_reason="idle_timeout"` ;
- une session réparée peut exposer `boundary_reason="stale_repair"` ;
- les anciennes lignes sans `close_reason` conservent le fallback `session_end`.

### Migration / compatibilité SQLite

Le patch reste compatible avec les anciennes bases locales :

- la colonne `close_reason` est ajoutée automatiquement via le mécanisme d’extension de schéma existant ;
- les anciennes sessions sans valeur persistée continuent d’être projetées avec `boundary_reason="session_end"` ;
- aucune migration lourde ni refonte de `SessionFSM` n’est nécessaire.

### Tests

Tests ciblés lancés :

```bash
.venv/bin/python3 -m pytest tests/memory/test_session.py tests/test_runtime_orchestrator.py tests/routes/test_runtime_state_payloads.py -q
```

Résultat observé : `164 passed`.

Cas couverts :

- fermeture normale -> `session_end` ;
- `new_session(..., close_reason="screen_lock")` -> `boundary_reason="screen_lock"` ;
- `close(..., close_reason="idle_timeout")` -> `boundary_reason="idle_timeout"` ;
- DB legacy sans colonne -> colonne ajoutée automatiquement ;
- stale repair -> `close_reason="stale_repair"` ;
- projection `/state.recent_sessions` conserve `boundary_reason`.

### Verdict provisoire

Patch Core réussi.

La chaîne de vérité est plus propre :

```text
RuntimeOrchestrator -> SessionMemory.close(close_reason) -> SQLite -> get_recent_sessions() -> /state.recent_sessions[].boundary_reason
```

Ce patch améliore l’observabilité du cycle de session sans toucher à `SessionFSM`, au scoring, à l’EventBus, aux routes Lab ou à la mémoire intelligente.

À vérifier dans les prochaines sessions :

- les nouvelles sessions fermées après lock long exposent bien `screen_lock` ;
- les coupures idle exposent bien `idle_timeout` ;
- les anciennes sessions restent lisibles avec `session_end` ;
- le dashboard utilise cette information sans surinterpréter les sessions historiques.
---

## 2026-05-28 — C1 terminé / C2.1 santé Core côté Swift

### Contexte

Après plusieurs audits ciblés et groupés, la phase `C1 — Core Internal Audit` a été synthétisée.

Verdict C1 : Pulse Core est suffisamment stabilisé pour le dogfooding local, mais il n’est pas prêt pour R7, apprentissage utilisateur ou mémoire intelligente.

Le Core actuel doit rester centré sur :

- observation passive ;
- interprétation prudente ;
- sessions fiables ;
- mémoire minimale ;
- propositions contrôlées avec validation humaine ;
- surfaces Core / debug / Lab plus lisibles.

### Synthèse C1

Points solides confirmés :

- `/event`, `EventBus`, filtrage bruit et attribution acteur fonctionnent comme fondation d’observation ;
- `SignalScorer` reste déterministe, testé, sans LLM ni apprentissage ;
- `RuntimeState` reste une source live, pas un moteur d’intelligence ;
- `SessionFSM` et `SessionMemory` couvrent sessions, lock / unlock, restart repair et `close_reason` ;
- les gates R1-R6 neutralisent DayDream, facts, sync mémoire avancée et LLM auto en Core ;
- MCP reste le seul flux Core de proposition contrôlée, avec validation humaine.

Dettes principales identifiées :

- `RuntimeOrchestrator` concentre encore trop de responsabilités Core + Lab ;
- `main.py` conserve des effets de bord au chargement et un ordre de boot fragile ;
- `/state` reste trop large pour une API produit propre ;
- le Dashboard Swift reste un cockpit interne Core / debug / Lab ;
- les routes Lab restent enregistrées, même si les gates tiennent globalement.

Décision : ne pas lancer R7. La phase suivante est `C2 — Hardening minimal`.

### C2.1 — Santé Core côté Swift

Problème ciblé : côté Swift, l’état global pouvait encore être perçu comme dégradé lorsque le LLM était indisponible, même si le Core répondait correctement.

Or en `PULSE_MODE=core`, le LLM n’est pas requis.

Le bon contrat est :

```text
Core OK + LLM indisponible ≠ Pulse dégradé
```

### Patch appliqué

Patch Swift appliqué :

- ajout d’un modèle Swift minimal pour `/health/core` ;
- ajout d’un appel API `/health/core` ;
- `PulseViewModel` peut maintenant considérer le Core comme sain si `/health/core.status == "ok"` ;
- l’indisponibilité LLM reste visible via les champs LLM existants, mais ne dégrade plus l’état Core global ;
- fallback conservé : si `/health/core` échoue ou n’est pas disponible, l’ancien comportement continue de fonctionner.

Fichiers modifiés :

- `App/App/DaemonBridge+CoreAPI.swift` ;
- `App/App/DaemonBridgeModels.swift` ;
- `App/App/PulseViewModel.swift` ;
- `App/App/PulseViewModel+Runtime.swift` ;
- `AppTests/PulseViewModelInteractionsTests.swift`.

### Comportement avant / après

Avant :

- `/ping` OK + LLM indisponible pouvait produire un statut global `llmUnavailable` ;
- cela donnait l’impression que Pulse Core dépendait du LLM.

Après :

- `/health/core.status == "ok"` maintient le statut global Core sain ;
- le LLM devient une capacité Lab / génération séparée ;
- l’UI distingue mieux daemon / Core / LLM.

### Tests

Tests Swift ajoutés :

- `testCoreHealthOkKeepsGlobalStatusHealthyWhenLLMUnavailable` ;
- `testDaemonBridgeDecodesCoreHealth`.

Test ajusté :

- le test de polling daemon reconnecté accepte maintenant l’appel `/health/core`.

Tests lancés :

```bash
xcodebuild test -project App/Pulse.xcodeproj -scheme App -destination 'platform=macOS' -only-testing:AppTests/PulseViewModelInteractionsTests
```

Résultat observé : `64 tests passed`.

### Verdict provisoire

C2.1 est cohérent avec l’audit C1.

Le patch ne rend pas Pulse plus intelligent. Il rend l’UI plus honnête sur l’état réel du Core.

À surveiller :

- impact du nouvel appel `/health/core` pendant le polling ;
- cohérence visuelle entre santé Core, statut LLM et surfaces Lab ;
- absence de régression quand le daemon est down ou quand `/health/core` est temporairement indisponible.

### Prochaine étape C2

C2.2 : clarifier les textes UI Lab, notamment DayDream et Mémoire, pour éviter de vendre des comportements Lab comme automatiques ou requis par le Core.