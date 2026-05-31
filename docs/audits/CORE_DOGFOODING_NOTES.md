
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
    "active_file": "/Users/yugz/Projets/Pulse/Pulse/docs/audits/CORE_DOGFOODING_NOTES.md",
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


### Suite C2

C2.2 a ensuite été réalisée : clarification des textes UI Lab, notamment DayDream et Mémoire, pour éviter de vendre des comportements Lab comme automatiques ou requis par le Core.

---

## 2026-05-28 — C2.2 clarification des textes Lab UI

### Contexte

Après C2.1, l’UI distingue mieux la santé Core de la disponibilité LLM.

Le point suivant identifié par C1 concernait les textes du Dashboard : plusieurs surfaces étaient déjà marquées `Lab`, mais certaines micro-copies présentaient encore mémoire avancée, DayDream, profile / facts ou injection LLM comme des comportements normaux ou stables du Core.

Objectif C2.2 : clarifier les textes sans masquer les onglets Lab, sans changer les données, et sans modifier le daemon.

### Problème ciblé

Textes problématiques repérés :

- `Profil injecté au LLM` ;
- `Aucun profil consolidé` ;
- `Faits consolidés` ;
- `Mémoire figée` ;
- texte indiquant une mémoire consolidée et injectée dans chaque échange LLM ;
- DayDream présenté comme automatique ;
- `context_injection` présenté comme application automatique.

Ces textes pouvaient laisser croire que :

- la mémoire avancée est une capacité Core ;
- le profil / facts sont stables et actifs en Core ;
- DayDream se déclenche naturellement en Core ;
- l’injection LLM fait partie du chemin Core ;
- des flux automatiques sont acceptés hors validation contrôlée.

### Patch appliqué

Patch limité à la micro-copy Swift / UI :

- aucun changement de données ;
- aucun changement de route ;
- aucun changement de gate Core / Lab ;
- aucun changement daemon ;
- aucun changement scoring, `SessionFSM`, `RuntimeState` ou `EventBus`.

Fichiers modifiés :

- `App/App/DashboardRootView.swift` ;
- `App/App/DaemonBridgeModels.swift` ;
- `AppTests/PulseViewModelInteractionsTests.swift`.

### Textes changés

- `Profil injecté au LLM` -> `Profil Lab pour contexte LLM` ;
- `Aucun profil consolidé` -> `Aucun profil Lab consolidé` ;
- `Faits consolidés` -> `Faits Lab consolidés` ;
- `Mémoire figée` -> `Snapshot mémoire Lab / debug` ;
- `Consolidée depuis les faits... injectée dans chaque échange LLM.` -> `Vue Lab issue des faits et journaux. Non requise par le Core et non injectée dans le chemin Core.` ;
- texte DayDream automatique -> `DayDream est une expérimentation Lab, non requise par le Core...` ;
- détails DayDream `running`, `generated`, `pending` préfixés par `Mode Lab` ;
- `context_injection` : `application automatique` -> `Lab automatique` ;
- détail `context_injection` : précision `hors Core contrôlé`.

### Comportement avant / après

Avant :

- les onglets étaient déjà marqués `Lab`, mais certains textes internes vendaient encore le Lab comme comportement stable ou automatique ;
- l’utilisateur pouvait croire que mémoire avancée, DayDream ou injection LLM étaient requis par le Core ;
- certaines formulations brouillaient la séparation entre Core contrôlé et expérimentation Lab.

Après :

- les surfaces Lab restent visibles pour le dogfooding ;
- les textes indiquent plus clairement que ces capacités sont Lab / debug ;
- DayDream, mémoire avancée et injection LLM ne sont plus présentés comme requis par le Core ;
- `context_injection` est explicitement marqué comme hors Core contrôlé.

### Tests

Test Swift modifié :

- `testProposalRecordClarifiesBlockingVsAutomaticFlows` attend maintenant les formulations `Lab automatique` et `hors Core contrôlé`.

Tests lancés :

```bash
xcodebuild test -project App/Pulse.xcodeproj -scheme App -destination 'platform=macOS' -only-testing:AppTests/PulseViewModelInteractionsTests
```

Résultat observé : `64 tests passed`.

Tests non lancés :

- suite Swift complète ;
- suite Python, non concernée par ce patch Swift UI / model copy.

### Verdict provisoire

C2.2 est cohérent avec C1 : le patch ne rend pas Pulse plus intelligent, il rend l’UI plus honnête.

Les surfaces Lab restent disponibles pour dogfooding, mais elles sont moins susceptibles d’être confondues avec le Core stable.

À surveiller :

- lisibilité des nouveaux textes plus longs ;
- cohérence des labels Lab dans toutes les vues ;
- absence de nouvelle micro-copy qui présenterait facts, mémoire avancée, DayDream ou LLM comme requis par le Core.

---

## 2026-05-28 — C2.3 tests de garde routes / state / UI

### Contexte

Après C2.1 et C2.2, les corrections étaient principalement des clarifications UI et de santé Core côté Swift.

Objectif C2.3 : verrouiller ces frontières par des tests de garde, sans ajouter de feature et sans modifier le comportement runtime.

Ce patch vise à éviter les régressions silencieuses autour de :

- l’inventaire des routes Core / debug / Lab ;
- la propreté de `/state.present` ;
- la compatibilité assumée de `/state.signals` ;
- les labels Lab côté Swift.

### Patch appliqué

Patch test-only appliqué.

Fichiers modifiés :

- `tests/test_main_runtime_state.py` ;
- `tests/routes/test_runtime_state_payloads.py` ;
- `AppTests/PulseViewModelInteractionsTests.swift`.

### Tests ajoutés / modifiés

Tests ajoutés :

- `test_runtime_api_route_inventory_documents_core_debug_and_lab_surfaces` ;
- `test_state_present_contract_rejects_raw_debug_lab_and_terminal_fields`.

Test Swift modifié :

- `testDashboardSectionLabelsUseProductNavigation` verrouille maintenant aussi `Mémoire (Lab)` et `DayDream (Lab)`.

### Comportement verrouillé

Routes Core stables documentées par test :

- `/ping` ;
- `/health/core` ;
- `/state` ;
- `/event` ;
- `/feed`.

Routes debug visibles documentées :

- `/debug/state` ;
- `/insights` ;
- `/events/debug` ;
- `/work-context` ;
- `/debug/work-episodes`.

Routes Lab / legacy visibles documentées :

- `/daydreams` ;
- `/facts` ;
- `/memory` ;
- `/context-probes/requests` ;
- `/work-intent/candidates` ;
- `/llm/lightweight/*`.

Contrat `/state.present` :

- ne doit pas exposer commandes terminal ;
- ne doit pas exposer cwd terminal ;
- ne doit pas exposer window title brut ;
- ne doit pas exposer git context ;
- ne doit pas exposer stdout / stderr / raw output ;
- ne doit pas exposer facts / profile ;
- ne doit pas exposer DayDream ;
- ne doit pas exposer vector / embeddings ;
- ne doit pas exposer LLM summary.

Point important : `/state.signals` reste volontairement plus large pour compatibilité Swift / debug.

### Tests lancés

Tests Python ciblés :

```bash
.venv/bin/python3 -m pytest tests/test_runtime_routes.py tests/routes/test_runtime_state_payloads.py tests/test_main_runtime_state.py -q
```

Résultat observé : `165 passed`.

Tests Swift ciblés :

```bash
xcodebuild test -project App/Pulse.xcodeproj -scheme App -destination 'platform=macOS' -only-testing:AppTests/PulseViewModelInteractionsTests
```

Résultat observé : `64 tests passed`.

Tests non lancés :

- suite Python complète `./scripts/test_all.sh` ;
- suite Swift complète.

### Verdict provisoire

C2.3 est cohérent avec C1 et C2 : il ne rend pas Pulse plus intelligent, il verrouille les frontières existantes.

Le patch documente explicitement que certaines surfaces Lab / debug restent visibles, mais qu’elles doivent rester nommées et testées comme telles.

À surveiller :

- toute nouvelle route ajoutée à `register_runtime_routes()` sans classification Core / debug / Lab ;
- tout ajout de champ brut dans `/state.present` ;
- toute régression UI qui retirerait les labels `(Lab)` des surfaces expérimentales ;
- toute tentation de nettoyer `/state.signals` brutalement sans migration Swift.

### État C2 après C2.3

C2.1, C2.2 et C2.3 sont terminés.

Le Core est dans un état adapté au dogfooding post-hardening : santé Core séparée du LLM, surfaces Lab moins trompeuses, et tests de garde autour des frontières API / UI.

---

## 2026-05-28 — C2.4 observation terrain post-hardening

### Contexte

Après C2.1, C2.2 et C2.3, une session terrain d’environ 20 à 30 minutes a été observée.

Objectif : vérifier que le Core reste sain en usage réel après les corrections de hardening, sans relancer de nouvelle feature.

Activités observées pendant la session :

- édition et nettoyage de documentation Core ;
- utilisation de scripts Python locaux pour modifier la documentation ;
- commandes Git ;
- résolution d’un `index.lock` Git ;
- vérification de l’état Pulse via les endpoints Core.

### Vérification `/health/core`

Résultat observé :

```json
{
  "status": "ok",
  "pulse_mode": "core",
  "experimental_enabled": false,
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
  "failed": {}
}
```

Lecture terrain : le Core reste sain après une session réelle de documentation / Git. Les services Lab restent non requis.

### Vérification `/state`

État live observé après la session :

```text
pulse_mode = core
experimental_enabled = false
session_status = active
session_duration_min = 26
session_fsm.state = active
session_fsm.session_started_at = 2026-05-28T21:31:34
user_presence_state = active
activity_level = executing
probable_task = general
task_confidence = 0.4
active_project = Pulse
```

Lecture terrain : la session active est cohérente avec une période d’environ 26 minutes.

Le contexte reste prudent : `probable_task=general` avec une confiance faible / modérée. C’est acceptable, car au moment de la vérification, les signaux récents étaient surtout des commandes terminal et les signaux app / fichier étaient absents.

### Observation app / fichier actif

Point à surveiller : au moment du `curl`, certains champs live étaient absents :

```text
active_app = null
active_file = null
recent_apps = []
```

Mais le projet restait correctement ancré par le terminal :

```text
terminal_cwd = /Users/yugz/Projets/Pulse/Pulse
terminal_project = Pulse
active_project = Pulse
```

Lecture terrain : Pulse ne force pas une interprétation quand les signaux app / fichier ne sont pas disponibles. Le fallback terminal permet tout de même de garder le projet actif.

Décision provisoire au moment de C2.4 : ne pas corriger immédiatement. Surveiller si `active_app` / `active_file` restent régulièrement `null` pendant des sessions normales où VS Code est clairement actif.

Note C2.5 : ce point a été réévalué après relance de l’app macOS via Xcode. Les champs `active_app`, `active_file` et `recent_apps` sont revenus correctement. L’hypothèse la plus probable est que le daemon Python tournait sans producteur Swift / SystemObserver complet pendant l’observation précédente. Ce n’est pas un bug Core confirmé.

### Vérification `/feed`

Le feed a correctement raconté les commandes récentes de la session :

- activation de l’environnement virtuel ;
- script Python de remplacement documentaire ;
- `git add` ;
- `git commit` / `git push` ;
- `ps aux | grep git` ;
- suppression de `.git/index.lock`.

Lecture terrain : `/feed` fonctionne correctement après commande terminée. Les cas précédents où `/feed` répondait `[]` étaient liés au timing : l’endpoint était interrogé pendant que la commande courante était encore au stade `terminal_command_started`.

### Vérification `recent_sessions`

Les raisons de fermeture récentes sont maintenant plus informatives :

```text
stale_repair
idle_timeout
stale_repair
session_end
```

Points validés :

- `stale_repair` apparaît après redémarrage / réparation d’une session ouverte ;
- `idle_timeout` apparaît pour une coupure liée à l’inactivité ;
- les anciennes sessions gardent `session_end` comme fallback.

Lecture terrain : le patch `close_reason` apporte une vraie valeur d’observabilité dans `/state.recent_sessions`.

### Points positifs

- Core sain après une session terrain de 20 à 30 minutes.
- Mode Core confirmé.
- Services Lab non requis.
- Session active cohérente.
- `/feed` utile sur une vraie activité terminal / Git.
- `boundary_reason` devient exploitable avec `stale_repair` et `idle_timeout`.
- Le scorer reste prudent quand les preuves app / fichier sont faibles.

### Points à surveiller

- `active_app` / `active_file` peuvent être `null` même pendant une session de travail, selon la fraîcheur ou la disponibilité des signaux Swift / app.
- Les commandes de diagnostic `curl` continuent de polluer le contexte live immédiatement après vérification.
- `/feed` ne doit pas être interprété comme un journal complet ; il reste une sélection notable.
- `StateStore` reste legacy et ne doit pas être utilisé comme vérité produit si ses valeurs divergent de `present` / `session_fsm`.

### Verdict provisoire

C2.4 confirme que le Core tient en dogfooding post-hardening.

Aucun patch immédiat n’est nécessaire.

Le prochain mouvement ne doit pas être une nouvelle feature. Deux options raisonnables :

- poursuivre le dogfooding terrain et documenter seulement les irritants reproduits ;
- préparer C3 sous forme de contrats mémoire / apprentissage contrôlé, sans implémentation.

---

## 2026-05-28 — C2.5 petit patch test `/feed` et observation avec app Swift lancée

### Contexte

Après C2.4, une petite session de code / test a été réalisée sans redémarrer le daemon ni l’app, afin de produire une activité de développement réelle observable par Pulse.

Objectifs :

- ne pas ajouter de feature ;
- renforcer seulement un contrat existant si nécessaire ;
- observer comment Pulse lit une activité dev normale ;
- vérifier l’hypothèse `active_app = null` observée en C2.4.

### Patch test appliqué

Patch test-only appliqué côté Python.

Fichier modifié :

- `tests/test_runtime_routes.py`.

Test ajouté :

- `test_feed_contract_is_not_a_complete_raw_event_journal`.

Contrat verrouillé :

```text
/feed = sélection d’événements notables
/feed ≠ journal brut complet
```

Le test vérifie que `/feed` ignore les événements bruts non promus, notamment :

- `app_activated` ;
- `file_modified` ;
- `user_presence` ;
- `screen_locked` ;
- `screen_unlocked`.

Et qu’il ne retourne que l’événement terminal notable.

### Tests lancés

Tests Python ciblés :

```bash
.venv/bin/python3 -m pytest tests/test_main_runtime_state.py tests/routes/test_runtime_state_payloads.py tests/test_runtime_routes.py -q
```

Résultat observé : `166 passed`.

Tests non lancés :

- suite Python complète ;
- suite Swift, non concernée par ce patch test-only.

### Observation terrain après commit / push

Après commit et push du patch test, les endpoints Core ont été vérifiés sans redémarrage du daemon.

`/health/core` est resté sain :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

La session active est restée cohérente :

```text
session_status = active
session_duration_min = 37
active_project = Pulse
activity_level = executing
probable_task = general
task_confidence = 0.4
```

Le feed a correctement raconté les commandes notables de la session :

- activation de l’environnement virtuel ;
- script Python de documentation ;
- `git add` ;
- `git commit` / `git push` ;
- diagnostic Git autour de `.git/index.lock` ;
- commandes `curl` de vérification.

Lecture terrain : le comportement réel de `/feed` est aligné avec le nouveau test C2.5. Le feed reste une timeline lisible d’événements notables, pas un journal exhaustif.

### Réévaluation `active_app = null`

Pendant C2.4, `active_app`, `active_file` et `recent_apps` étaient parfois `null` / vides alors que le projet restait détecté via le terminal.

Une cause probable a été identifiée : l’app macOS Pulse n’était pas lancée via Xcode pendant cette observation. Le daemon Python tournait, mais il ne recevait pas forcément les événements Swift / SystemObserver complets.

Après lancement de l’app via Xcode, les signaux sont revenus correctement :

```text
active_app = Code
active_file = CORE_DOGFOODING_NOTES.md
active_project = Pulse
active_app_bundle_id = com.microsoft.VSCode
recent_apps = Xcode, Codex, ChatGPT, Code
```

Lecture terrain : l’anomalie `active_app = null` n’est pas un bug Core confirmé. Elle correspond probablement à une condition de test incomplète : daemon actif sans app Swift lancée.

### Verdict provisoire

C2.5 confirme plusieurs points :

- le Core reste sain pendant un petit patch test réel ;
- `/feed` fonctionne comme sélection notable ;
- le contrat `/feed` est maintenant verrouillé par test ;
- `active_app` / `active_file` reviennent quand l’app Swift est lancée correctement ;
- les observations C2.4 doivent être lues avec cette nuance.

Aucun patch runtime immédiat n’est nécessaire.

### Points à surveiller

- si `active_app` / `active_file` redeviennent `null` alors que l’app Swift est bien lancée, ouvrir une investigation ciblée Swift / SystemObserver ;
- si `/feed` devient trop bavard, conserver le contrat C2.5 comme garde-fou ;
- documenter clairement dans les futures sessions si le daemon tourne seul ou si l’app macOS est aussi lancée.

---

## 2026-05-29 — C4-mini memory candidates skeleton terrain check

### Contexte

Après l’ajout et le push du squelette C4-mini `memory_candidates`, Pulse a été redémarré pour vérifier que le nouveau code fonctionne en conditions réelles Core.

Objectif : confirmer que la surface `memory_candidates` reste dédiée, locale, review-only et inerte après redémarrage, sans polluer le Core live.

### Vérification `/health/core`

Résultat observé :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

Lecture terrain : le Core reste sain après l’ajout du squelette `memory_candidates`. Les services Lab restent non requis.

### Vérification `/state`

État live observé pendant les commandes de diagnostic :

```text
active_app = Terminal
active_project = Pulse
activity_level = executing
probable_task = general
task_confidence = 0.48
session_status = active
```

Lecture terrain : le contexte est cohérent avec l’activité réelle du moment, à savoir des commandes `curl` de diagnostic lancées depuis le repo Pulse.

Le scorer reste prudent : `probable_task=general` avec une confiance modérée. C’est attendu, car les commandes de diagnostic influencent temporairement le contexte live.

### Vérification `/memory/candidates`

Résultat observé :

```json
{
  "candidates": [],
  "canonical_memory": false,
  "count": 0,
  "surface": "memory_candidates"
}
```

Points validés :

- la route dédiée `/memory/candidates` répond correctement ;
- aucune candidate n’est créée spontanément ;
- `count=0` confirme l’absence de génération automatique ;
- `canonical_memory=false` confirme que la surface ne représente pas une mémoire stable ;
- `surface=memory_candidates` confirme que la réponse est isolée de la mémoire Core / Lab existante.

### Vérification complémentaire après activité documentaire réelle

Après un peu d’activité autour de la documentation, de Codex, ChatGPT, VS Code et Terminal, les endpoints Core ont été revérifiés.

`/health/core` reste sain :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

`/state` reflète correctement le contexte réel :

```text
active_app = Terminal
active_file = docs/audits/CORE_DOGFOODING_NOTES.md
active_project = Pulse
probable_task = writing
activity_level = executing
task_confidence = 0.76
session_status = active
```

Lecture terrain : après activité documentaire réelle, Pulse qualifie mieux le contexte comme `writing`. Les commandes `curl` restent visibles dans le contexte live, ce qui est attendu pendant le diagnostic.

`/memory/candidates` reste vide :

```json
{
  "candidates": [],
  "canonical_memory": false,
  "count": 0,
  "surface": "memory_candidates"
}
```

Conclusion : même après activité réelle, le squelette `memory_candidates` ne génère rien automatiquement et ne crée aucune mémoire canonique.

### Vérification complémentaire `/debug/state`

Après les vérifications Core, `/debug/state` confirme que le contexte runtime reste cohérent :

```text
pulse_mode = core
experimental_enabled = false
legacy_in_state = false
active_app = Terminal
active_file = docs/audits/CORE_DOGFOODING_NOTES.md
active_project = Pulse
probable_task = writing
activity_level = executing
task_confidence = 0.76
session_fsm.state = active
```

`recent_sessions` expose des fermetures avec `stale_repair` et `screen_lock`, cohérentes avec les redémarrages daemon et les cycles lock / unlock observés pendant le dogfooding.

Lecture terrain : le squelette `memory_candidates` ne modifie pas la compréhension runtime. Pulse continue à lire correctement une session de documentation / diagnostic, tout en gardant `/memory/candidates` vide.

Conclusion : la surface `memory_candidates` reste inerte même après consultation de `/debug/state` et activité documentaire réelle.

### Verdict provisoire

Le squelette C4-mini est inerte en Core après redémarrage.

Comportement conforme au contrat :

- pas de génération automatique ;
- pas de candidate créée depuis `/state` ou les commandes de diagnostic ;
- pas de pollution visible du Core live ;
- pas de mémoire canonique créée ;
- surface `memory_candidates` disponible mais vide.

Aucun patch code immédiat n’est nécessaire.

### Points à surveiller

- vérifier que `/memory/candidates` reste vide tant qu’aucune création explicite n’existe ;
- vérifier que les futures actions `accept`, `edit`, `reject`, `archive` et `delete` restent review-only ;
- ne pas ajouter de création manuelle, génération offline ou scan de sessions sans décision séparée ;
- documenter toute future modification de la mécanique `memory_candidates` dans `docs/decisions/` et/ou les contrats concernés avant implémentation.

---

## 2026-05-29 — C4-mini.1 manual candidate creation pre-restart check

### Contexte

Avant redémarrage du daemon après l’implémentation de `POST /memory/candidates/manual`, les endpoints Core ont été vérifiés pour capturer l’état réel de la session en cours.

Objectif : confirmer que le Core existant reste sain et que le squelette `memory_candidates` reste inerte avant activation du nouveau code.

### Vérification `/health/core`

Résultat observé :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

Lecture terrain : le daemon actif reste sain en mode Core avant redémarrage.

### Vérification `/state`

État live observé pendant les commandes de diagnostic :

```text
active_app = Terminal
active_file = tests/memory/test_candidates.py
active_project = Pulse
probable_task = coding
activity_level = executing
task_confidence = 0.92
session_status = active
session_duration_min = 26
```

Lecture terrain : Pulse comprend correctement la session comme une activité de code / tests sur le projet Pulse. Le fichier actif `tests/memory/test_candidates.py`, le contexte Terminal et l’activité récente Codex / ChatGPT / VS Code expliquent `probable_task=coding` avec une confiance élevée.

Les commandes `curl` de diagnostic restent visibles dans le contexte live, ce qui est attendu pendant le dogfooding.

### Vérification `/feed`

Le feed expose les commandes terminal notables récentes, notamment :

- correction documentaire locale via script Python ;
- vérifications `/health/core`, `/state` et `/memory/candidates` ;
- commande `clear` ;
- vérification complète `/health/core`, `/state`, `/feed`, `/memory/candidates` et `/debug/state`.

Lecture terrain : `/feed` reste conforme à son contrat. Il raconte les commandes notables de la session sans devenir un journal brut complet.

### Vérification `/memory/candidates`

Résultat observé :

```json
{
  "candidates": [],
  "canonical_memory": false,
  "count": 0,
  "surface": "memory_candidates"
}
```

Points validés :

- aucune candidate n’est créée automatiquement pendant l’activité de code / tests ;
- aucune mémoire canonique n’est créée ;
- la surface reste dédiée à `memory_candidates` ;
- `count=0` confirme l’inertie avant redémarrage du daemon.

### Vérification `/debug/state`

`/debug/state` confirme le contexte runtime :

```text
pulse_mode = core
experimental_enabled = false
legacy_in_state = false
active_app = Terminal
active_file = tests/memory/test_candidates.py
active_project = Pulse
probable_task = coding
activity_level = executing
task_confidence = 0.92
session_fsm.state = active
```

`recent_sessions` expose encore des fermetures avec `stale_repair` et `screen_lock`, cohérentes avec les redémarrages daemon et les cycles lock / unlock déjà observés pendant le dogfooding.

### Verdict provisoire

Pré-redémarrage conforme :

- Core sain ;
- session active cohérente ;
- scoring pertinent pour une activité de code / tests ;
- feed exploitable ;
- `/memory/candidates` reste vide ;
- aucune candidate spontanée ;
- aucune mémoire canonique créée.

Ce test valide l’état du daemon actif avant activation du nouveau code `POST /memory/candidates/manual`.

Après redémarrage, vérifier explicitement :

- `/health/core` ;
- `/memory/candidates` avant création ;
- `POST /memory/candidates/manual` ;
- `GET /memory/candidates` après création ;
- `/state`, pour confirmer l’absence de pollution Core ;
- puis documenter le résultat terrain post-redémarrage.

---

## 2026-05-29 — C4-mini.1 manual candidate creation post-restart check

### Contexte

Après redémarrage du daemon avec `POST /memory/candidates/manual`, le cycle manuel de création et de review a été testé en conditions réelles Core.

Objectif : vérifier qu’une candidate peut être créée explicitement, relue, rejetée, et rester isolée de la mémoire canonique et du LLM.

### Vérification initiale

`/health/core` reste sain :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

Avant création, `/memory/candidates` est vide :

```json
{
  "candidates": [],
  "canonical_memory": false,
  "count": 0,
  "surface": "memory_candidates"
}
```

Lecture terrain : le Core reste sain après redémarrage, et la surface `memory_candidates` ne contient aucune candidate avant action explicite.

### Création manuelle

Commande testée : `POST /memory/candidates/manual`.

Payload utilisé :

```json
{
  "memory_type": "project_pattern",
  "claim": "Pulse est un projet de travail récurrent.",
  "evidence": [
    {
      "source_type": "human_manual",
      "summary": "Créé explicitement par l’utilisateur pour tester le cycle de review."
    }
  ],
  "sensitivity": {
    "level": "low",
    "reason": "non-sensitive project pattern"
  }
}
```

Résultat observé :

```text
ok = true
surface = memory_candidates
status = pending
canonical_memory_created = false
llm_injected = false
human_review.required = true
confidence = 0.0
```

Candidate créée :

```text
id = 019e749a-f966-7ffe-965c-60da278bc4dd
memory_type = project_pattern
claim = Pulse est un projet de travail récurrent.
status = pending
evidence.source_type = human_manual
sensitivity.level = low
```

Lecture terrain : la route crée bien une candidate `pending`, sourcée, non sensible, sans mémoire canonique et sans injection LLM.

### Lecture après création

`GET /memory/candidates` expose la candidate avec `count=1`.

`GET /memory/candidates/<id>` permet de lire la candidate individuellement.

Points validés :

- la candidate est persistée ;
- elle reste dans la surface dédiée `memory_candidates` ;
- elle reste `pending` avant review ;
- `canonical_memory=false` confirme l’absence de mémoire stable ;
- `/state` ne présente pas `memory_candidates` comme état Core live.

### Rejet humain

Commande testée : `POST /memory/candidates/<id>/reject`.

Raison fournie :

```text
Candidate créée uniquement pour tester le cycle de review.
```

Résultat observé :

```text
ok = true
surface = memory_candidates
status = rejected
canonical_memory_created = false
llm_injected = false
human_review.decision = rejected
human_review.reviewer = human
```

La trace de review est conservée :

```text
human_review.trace[0].decision = rejected
human_review.trace[0].reason = Candidate créée uniquement pour tester le cycle de review.
```

### Relecture après rejet

`GET /memory/candidates/<id>` confirme :

```text
status = rejected
human_review.decision = rejected
canonical_memory = false
surface = memory_candidates
```

Lecture terrain : le rejet humain est persisté, la candidate reste auditable dans la surface dédiée, et aucune mémoire canonique n’est créée.

### Suppression de la candidate de test

Commande testée : `DELETE /memory/candidates/<id>`.

Résultat observé :

```json
{
  "deleted": true,
  "ok": true,
  "surface": "memory_candidates"
}
```

Après suppression, `GET /memory/candidates` retourne :

```json
{
  "candidates": [],
  "canonical_memory": false,
  "count": 0,
  "surface": "memory_candidates"
}
```

Lecture terrain : la candidate de test rejetée est supprimée correctement. La surface `memory_candidates` revient à vide, sans mémoire canonique créée.

### Vérification `/state` après suppression

Après suppression, `/state` reste cohérent avec l’activité live :

```text
active_app = Terminal
active_file = docs/audits/CORE_DOGFOODING_NOTES.md
active_project = Pulse
probable_task = writing
activity_level = executing
task_confidence = 0.76
session_status = active
```

Lecture terrain : la suppression d’une candidate ne pollue pas le Core live. `memory_candidates` reste séparé de `/state`.

### Vérification complémentaire `edit` / `archive`

Une deuxième candidate manuelle a été créée pour tester les actions de review restantes.

Candidate créée :

```text
id = 019e74a5-1d7c-7e71-ae6d-abf63e8d491a
status = pending
claim = Pulse est un projet de travail récurrent.
evidence.source_type = human_manual
```

`POST /memory/candidates/<id>/edit` a modifié la claim :

```text
claim = Pulse est un projet personnel récurrent de diagnostic local.
status = edited
human_review.decision = edited
human_review.edited_claim = Pulse est un projet personnel récurrent de diagnostic local.
canonical_memory_created = false
llm_injected = false
```

`POST /memory/candidates/<id>/archive` a archivé la candidate :

```text
status = archived
human_review.decision = archived
trace[0].decision = edited
trace[1].decision = archived
canonical_memory_created = false
llm_injected = false
```

La relecture individuelle confirme :

```text
status = archived
canonical_memory = false
surface = memory_candidates
```

La candidate a ensuite été supprimée :

```json
{
  "deleted": true,
  "ok": true,
  "surface": "memory_candidates"
}
```

Après suppression, `GET /memory/candidates` retourne :

```json
{
  "candidates": [],
  "canonical_memory": false,
  "count": 0,
  "surface": "memory_candidates"
}
```

Lecture terrain : `edit`, `archive`, la relecture, puis `delete` fonctionnent correctement. Les actions de review restent tracées, sans création de mémoire canonique ni injection LLM.

### Verdict provisoire

C4-mini.1 fonctionne en dogfooding terrain :

- création manuelle explicite OK ;
- candidate `pending` créée uniquement sur action explicite ;
- preuve `human_manual` conservée ;
- sensibilité `low` conservée ;
- lecture liste et lecture individuelle OK ;
- rejet humain OK ;
- édition humaine OK ;
- archivage humain OK ;
- trace multi-action conservée ;
- suppression de la candidate de test OK ;
- liste revenue vide après suppression ;
- aucune mémoire canonique créée ;
- aucune injection LLM ;
- aucune génération automatique observée ;
- `/state` reste séparé de la surface `memory_candidates`.

Aucun patch code immédiat n’est nécessaire.

### Points à surveiller

- tester plus tard `accept` avec wording strict avant toute UI ;
- vérifier que les candidates rejetées ne sont pas reproposées par un futur générateur ;
- ne pas ajouter de générateur offline sans décision séparée ;
- ne pas présenter `accepted` ou `rejected` comme mémoire produit stable ;
- documenter toute prochaine évolution `memory_candidates` avant implémentation.
---

## 2026-05-31 — C4b.3 lazy runtime/app post-restart check

### Contexte

Après l’implémentation de C4b.3-real phase 1, le daemon a été redémarré pour vérifier le comportement terrain du lazy `get_runtime()` / `get_app()`.

Objectif : confirmer que le boot lazy ne crée pas de régression visible côté Core.

### Vérification `/health/core`

Résultat observé :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

Lecture terrain : le Core reste sain après redémarrage avec lazy runtime/app.

### Vérification `/state`

État observé :

```text
active_app = Code
active_file = C4B_BOOT_IMPORT_AUDIT.md
active_project = Pulse
activity_level = executing
probable_task = general
task_confidence = 0.48
session_status = active
```

Lecture terrain : Pulse capte correctement une session de documentation / diagnostic dans VS Code et Terminal. Le scoring reste prudent, ce qui est acceptable pour une activité mixte.

### Vérification `/feed`

Résultat observé : le feed expose une commande terminal notable récente, `clear`.

Lecture terrain : `/feed` reste disponible et conserve son rôle de sélection notable, sans devenir un journal brut complet.

### Vérification `/memory/candidates`

Résultat observé :

```json
{
  "candidates": [],
  "canonical_memory": false,
  "count": 0,
  "surface": "memory_candidates"
}
```

Lecture terrain : aucune candidate mémoire n’est créée spontanément après redémarrage. La surface `memory_candidates` reste vide et séparée de la mémoire canonique.

### Verdict provisoire

C4b.3-real phase 1 est conforme en dogfooding post-redémarrage :

- `/health/core` OK ;
- `/state` OK ;
- `/feed` OK ;
- `/memory/candidates` OK ;
- aucune candidate spontanée ;
- aucune mémoire canonique créée ;
- aucune régression Core visible.

Point observé : `recent_sessions` expose un `stale_repair` après redémarrage, cohérent avec le comportement déjà observé pendant le dogfooding.

### Suite

C4b.3 peut être considéré validé côté terrain pour cette première phase lazy.

Avant toute suppression des globals legacy ou des façades de compatibilité, une décision séparée devra confirmer :

- les consommateurs restants ;
- le risque Swift / tests ;
- la stratégie de migration ;
- les tests et le dogfooding requis.


---

## 2026-05-31 — C4b.4b HTTP port preflight post-restart check

### Contexte

Après l’ajout du préflight local du port HTTP principal `127.0.0.1:8765` dans `main()`, le daemon a été redémarré pour vérifier le comportement terrain.

Objectif : confirmer que le préflight 8765 ne crée pas de régression visible côté Core.

### Vérification `/health/core`

Résultat observé :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

Lecture terrain : le Core reste sain après redémarrage avec le préflight 8765 actif.

### Vérification `/state`

État observé :

```text
active_app = Code
active_file = C4B_PORT_CONFLICT_AUDIT.md
active_project = Pulse
activity_level = executing
probable_task = general
task_confidence = 0.48
session_status = active
```

Lecture terrain : Pulse capte correctement une session de documentation / diagnostic dans VS Code et Terminal. Le scoring reste prudent, ce qui est acceptable pour cette activité mixte.

### Vérification `/feed`

Résultat observé : le feed expose une commande terminal notable récente, `clear`.

Lecture terrain : `/feed` reste disponible et conserve son rôle de sélection notable, sans devenir un journal brut complet.

### Vérification `/memory/candidates`

Résultat observé :

```json
{
  "candidates": [],
  "canonical_memory": false,
  "count": 0,
  "surface": "memory_candidates"
}
```

Lecture terrain : aucune candidate mémoire n’est créée spontanément après redémarrage. La surface `memory_candidates` reste vide et séparée de la mémoire canonique.

### Verdict provisoire

C4b.4b est conforme en dogfooding post-redémarrage :

- `/health/core` OK ;
- `/state` OK ;
- `/feed` OK ;
- `/memory/candidates` OK ;
- aucune candidate spontanée ;
- aucune mémoire canonique créée ;
- aucune régression Core visible.

Point observé : `recent_sessions` expose encore `stale_repair` après redémarrage, cohérent avec les observations précédentes.

### Suite

C4b.4b peut être considéré validé côté terrain pour le chemin de démarrage normal.

Avant de traiter le port `8766` ou les conflits MCP plus finement, une décision séparée devra confirmer :

- le comportement attendu si `8766` est occupé ;
- le rôle exact du script `scripts/start_pulse_daemon.sh` comme première ligne de défense ;
- le comportement souhaité du lancement direct `python -m daemon.main` ;
- les tests et le dogfooding requis.


---

## 2026-05-31 — Today summary value-loop check

### Contexte

Après C4a, C4b et l'audit C4c.1, la priorité produit est temporairement réorientée vers la boucle de valeur minimale “Aujourd'hui”.

Objectif terrain : vérifier si les surfaces existantes permettent déjà de répondre à la question :

> Qu'est-ce que j'ai fait aujourd'hui ?

Surfaces vérifiées :

- `GET /today_summary`
- `GET /feed`

Commandes utilisées :

```bash
curl http://127.0.0.1:8765/today_summary | python -m json.tool
curl http://127.0.0.1:8765/feed | python -m json.tool
```

### Observation `/today_summary`

Résultat utile observé :

```text
date = 2026-05-31
project = Pulse
worked_min = 103
active_min = 103
window_count = 4
project_count = 1
commit_count = 24
first_activity_at = 2026-05-31T12:04:28
last_activity_at = 2026-05-31T14:24:26
current_window.project = Pulse
current_window.probable_task = writing
current_window.activity_level = executing
```

Blocs de travail observés :

```text
12:04 -> 12:44 | Pulse | writing | editing | 39 min | 95 events
13:05 -> 13:30 | Pulse | writing | editing | 25 min | 69 events
13:40 -> 13:54 | Pulse | writing | editing | 14 min | 17 events
13:58 -> 14:24 | Pulse | writing | executing | 25 min | 81 events
```

Lecture terrain : `/today_summary` donne déjà une structure exploitable de la journée. Pulse identifie correctement que le travail du jour concerne `Pulse`, avec des blocs temporels cohérents et une activité majoritairement `writing`.

### Observation `/feed`

Résultat utile observé : `/feed` retourne seulement une commande notable récente, `clear`.

Lecture terrain : `/feed` est disponible, mais trop pauvre dans cette session pour aider réellement à reprendre le fil. Il confirme que la surface fonctionne, pas encore qu'elle apporte une valeur suffisante pour “Aujourd'hui”.

### Lecture produit

`/today_summary` répond partiellement à :

> Pulse a-t-il compris que j'ai travaillé sur Pulse aujourd'hui ?

Réponse terrain : oui, partiellement. Le projet, la durée, les blocs et la fenêtre courante sont exploitables.

`/today_summary` ne répond pas encore assez à :

> Qu'est-ce que j'ai réellement fait ?

La surface reste trop agrégée pour expliquer le contenu du travail sans ouvrir d'autres vues ou relire les journaux.

### Manques observés

- fichiers principaux par bloc ;
- commandes utiles par bloc ou journée ;
- commits ou messages de commit ;
- sujet lisible du bloc ;
- lien explicite entre les blocs.

### Verdict provisoire

`/today_summary` est la bonne surface de départ pour la boucle de valeur minimale “Aujourd'hui”.

Ne pas créer immédiatement une nouvelle route `/today`.

Un enrichissement déterministe futur peut être utile si le besoin est confirmé par d'autres sessions terrain, par exemple :

- `top_files` dans `/today_summary` ;
- commandes notables utiles par journée ou par bloc ;
- commits ou messages de commit filtrés.

### Interdits maintenus

- pas de Lab ;
- pas de DayDream ;
- pas de `FactEngine` ;
- pas de `VectorStore` ;
- pas de LLM summaries ;
- pas de génération de memory candidates ;
- pas de nouvelle mémoire ;
- pas de nouvelle route produit tant que `/today_summary` n'a pas été évalué davantage.


---

## 2026-05-31 — Today summary top files patch prepared

### Contexte

Après la première observation terrain de la boucle “Aujourd'hui”, le manque le plus concret pour reprendre le fil est l'absence de fichiers principaux par bloc.

Choix produit : utiliser d'abord un enrichissement déterministe minimal de `/today_summary`, sans créer de nouvelle route.

### Décision de patch

`top_files` est le premier enrichissement retenu parce que `build_work_blocks(all_events)` le calcule déjà localement à partir des événements fichier.

Le patch prévu reste strictement borné :

- exposer `top_files` dans `work_blocks[]` de `/today_summary` ;
- décoder ce champ côté Swift ;
- afficher quelques fichiers dans la carte “Aujourd'hui” ;
- ne pas ajouter `notable_commands` maintenant ;
- ne pas ajouter de messages de commit maintenant.

### Interdits maintenus

- pas de nouvelle route `/today` ;
- pas de Lab ;
- pas de DayDream ;
- pas de `FactEngine` ;
- pas de `VectorStore` ;
- pas de LLM summaries ;
- pas de memory candidates ;
- pas de nouvelle mémoire.

### Dogfooding requis

Après patch et redémarrage, vérifier :

- `/today_summary` contient `work_blocks[].top_files` ;
- la carte Swift “Aujourd'hui” affiche les derniers blocs avec fichiers ;
- la reprise du fil est plus rapide qu'avant ;
- aucune route debug n'est nécessaire pour comprendre la journée ;
- aucune candidate mémoire spontanée n'est créée.


---

## 2026-05-31 — Today summary top_files post-patch check

### Contexte

Après le patch minimal “Aujourd'hui”, `/today_summary.work_blocks[]` expose maintenant `top_files`.

Objectif terrain : vérifier si les fichiers principaux rendent les blocs du jour plus utiles pour reprendre le fil.

Commandes utilisées :

```bash
curl http://127.0.0.1:8765/health/core | python -m json.tool
curl http://127.0.0.1:8765/today_summary | python -m json.tool
curl http://127.0.0.1:8765/feed | python -m json.tool
```

### Vérification `/health/core`

Résultat observé :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

Lecture terrain : le Core reste sain après le patch `top_files`.

### Vérification `/today_summary`

Les blocs exposent maintenant des fichiers principaux.

Exemples significatifs :

```text
13:58 -> 14:24 | Pulse | writing | executing
top_files = main.py, test_main_runtime_state.py, C4B_BOOT_IMPORT_AUDIT.md, CORE_DOGFOODING_NOTES.md, C4B_PORT_CONFLICT_AUDIT.md
```

```text
18:56 -> 19:16 | Pulse | writing | executing
top_files = TODAY_VALUE_LOOP_PLAN.md, README.md, CORE_DOGFOODING_NOTES.md, ReleaseNotes.md
```

```text
19:19 -> 19:24 | Pulse | writing | executing
top_files = session.py, test_session.py, DaemonBridgeModels.swift, DashboardRootView.swift, PulseViewModelInteractionsTests.swift, CORE_DOGFOODING_NOTES.md
```

### Lecture produit

`top_files` améliore nettement la capacité à reprendre le fil.

Avant le patch, les blocs indiquaient surtout quand Pulse avait observé du travail. Après le patch, ils donnent des indices concrets sur le contenu : backend, tests, Swift UI, modèles et documentation.

Le dernier bloc reflète correctement le travail réel sur :

- `session.py` ;
- `test_session.py` ;
- `DaemonBridgeModels.swift` ;
- `DashboardRootView.swift` ;
- `PulseViewModelInteractionsTests.swift` ;
- `CORE_DOGFOODING_NOTES.md`.

Lecture terrain : la surface `/today_summary` devient utile sans route produit supplémentaire.

### Vérification `/feed`

Résultat observé : `/feed` retourne seulement `clear`.

Lecture terrain : `/feed` reste disponible, mais ne complète pas assez `/today_summary` dans cette session.

### Verdict provisoire

Le patch `top_files` est validé côté terrain.

Il apporte une valeur réelle sans nouvelle route, sans Lab, sans LLM et sans mémoire supplémentaire.

Ne pas ajouter `notable_commands` immédiatement.

### Suite

- vérifier la carte Swift “Aujourd'hui” visuellement ;
- confirmer que les 3 derniers blocs restent lisibles ;
- continuer le dogfooding sur au moins une ou deux sessions ;
- commit si l'UI est correcte.


---

## 2026-05-31 — Today card visual check after compact blocks

### Contexte

Après le patch UI de la carte “Aujourd'hui”, la section “Derniers blocs” a été vérifiée visuellement dans l'app macOS.

### Observation

La carte affiche maintenant les derniers blocs avec des heures courtes `HH:mm → HH:mm`, sans date complète. La durée reste visible sur la ligne principale.

La tâche et le projet sont affichés ensemble, tandis que l'activité est clarifiée comme `Signal récent`. Cette distinction rend la lecture moins ambiguë.

Les fichiers principaux sont affichés sur une ligne dédiée. Le suffixe `+N` évite de surcharger la carte quand un bloc contient plus de deux fichiers.

### Lecture produit

Le résultat est lisible et aide davantage à reprendre le fil. Les blocs restent compacts tout en donnant des indices concrets sur le travail récent.

Ne pas ajouter `notable_commands` pour l'instant.

### Suite

Continuer le dogfooding sur 1 ou 2 sessions réelles avant d'élargir la surface “Aujourd'hui”.


---

## 2026-05-31 — Today value-loop field session 2

### Contexte

Mini-session terrain après le patch `top_files` dans `/today_summary` et le micro-ajustement UI de la carte “Aujourd'hui”.

Activité réelle observée :

- exploration légère de la documentation Pulse ;
- consultation du `README.md` ;
- lancement de `pytest` ;
- vérification des surfaces Core.

Surfaces vérifiées :

- `/health/core`
- `/today_summary`
- `/feed`
- `/state`

### Vérification `/health/core`

Résultat observé :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

Lecture terrain : le Core reste sain.

### Vérification `/today_summary`

Résultat observé :

```text
worked_min = 146
active_min = 146
window_count = 8
project_count = 1
commit_count = 29
project = Pulse
top_tasks = writing, tests
```

Bloc récent :

```text
20:38 -> 20:39
project = Pulse
probable_task = tests
activity_level = executing
duration_min = 1
event_count = 9
top_files = []
```

Lecture terrain : Pulse identifie correctement un bloc court de tests après `pytest`. `top_files=[]` est compréhensible pour une commande terminal courte sans fichier actif significatif.

### Vérification `/feed`

Résultat observé :

```text
pytest
clear
```

Lecture terrain : `/feed` complète utilement `/today_summary` en exposant `pytest`.

### Vérification `/state`

Résultat observé :

```text
active_app = Code
active_file = README.md
active_project = Pulse
probable_task = writing
activity_level = executing
session_status = active
```

Lecture terrain : le live state reflète la consultation / écriture autour du `README.md`. `probable_task=writing` côté live et `tests` dans le bloc récent ne sont pas contradictoires : ce sont deux temporalités différentes.

### Lecture produit

La séparation actuelle reste pertinente :

- `/today_summary` donne structure + fichiers principaux quand ils existent ;
- `/feed` donne les commandes terminal notables ;
- `/state` décrit la situation live.

Cette session n'est pas encore une preuve suffisante pour ajouter `notable_commands` dans `/today_summary`.

### Verdict provisoire

Session terrain #2 légère exploitable.

Le couple `/today_summary` + `/feed` reste cohérent.

Ne pas ajouter `notable_commands` dans `/today_summary` maintenant.

### Suite recommandée

Continuer le dogfooding sur une session plus longue, idéalement avec code + tests, sans interroger Pulse trop souvent pendant le travail.


---

## 2026-05-31 — Today value-loop field session 3

### Contexte

Session courte de revue documentaire autour de `TODAY_VALUE_LOOP_PLAN.md`, après validation du patch `top_files`.

### Observations

`/health/core` est OK.

`/today_summary` reste cohérent.

Dernier bloc observé :

```text
22:52 -> 22:57
project = Pulse
probable_task = writing
activity_level = executing
top_files = TODAY_VALUE_LOOP_PLAN.md
```

`/state` reflète bien `TODAY_VALUE_LOOP_PLAN.md` comme fichier actif.

`/feed` ne remonte que `clear`, mais ce n'est pas bloquant pour une session documentaire courte.

### Lecture produit

Pour une session documentaire courte, `top_files` suffit à reprendre le fil. Le bloc indique clairement que l'activité récente concernait le plan Today.

### Décision provisoire

Ne pas ajouter `notable_commands` maintenant.

### Limite

Cette session est courte. Il faut encore une session plus longue code + tests pour valider la boucle “Aujourd'hui” sur une activité plus représentative.

---

## 2026-05-31 — Dashboard Product / Debug-Lab split visual check

### Contexte

Après la décision `UI_PRODUCT_DEBUG_LAB_SPLIT`, un patch UI-only a séparé la navigation du dashboard Swift en deux surfaces locales :

- `Produit` ;
- `Debug / Lab`.

Objectif : vérifier que le dashboard ne présente plus toutes les surfaces comme équivalentes et que la boucle produit “Aujourd’hui” devient l’entrée principale.

### Patch observé

Changement appliqué côté Swift uniquement :

- ajout d’une surface `Produit` ;
- ajout d’une surface `Debug / Lab` ;
- ajout d’un sélecteur en haut de la sidebar ;
- filtrage des sections visibles selon la surface ;
- sélection automatique d’une section valide lors du changement de surface.

Aucun changement daemon, route, modèle API, `/today_summary`, `/feed`, `/state`, backend Lab ou encoche n’a été fait dans ce patch.

### Surface Produit

La surface `Produit` expose uniquement :

- `Aujourd’hui` ;
- `Notifications`.

Lecture terrain : la vue produit est maintenant centrée sur la reprise du fil et les informations utiles au quotidien, sans mélanger directement les surfaces internes ou expérimentales.

### Surface Debug / Lab

La surface `Debug / Lab` conserve les surfaces internes :

- `Séquences debug` ;
- `Observation` ;
- `Événements` ;
- `MCP` ;
- `Système` ;
- `Mémoire (Lab)` ;
- `DayDream (Lab)` ;
- `Contexte (Lab)`.

Lecture terrain : les outils de diagnostic et les surfaces expérimentales restent accessibles, mais ils ne sont plus au même niveau que l’expérience produit principale.

### Vérifications attendues

Le dogfooding visuel doit confirmer :

- le sélecteur `Produit` / `Debug / Lab` est visible en haut de sidebar ;
- `Produit` n’affiche que `Aujourd’hui` et `Notifications` ;
- `Debug / Lab` garde toutes les anciennes surfaces internes ;
- le passage vers `Produit` sélectionne `Aujourd’hui` si nécessaire ;
- le passage vers `Debug / Lab` sélectionne `Séquences debug` si nécessaire ;
- aucune surface Debug/Lab n’a été supprimée.

### Verdict provisoire

Le split `Produit` / `Debug-Lab` est cohérent avec la direction produit actuelle.

Il améliore la lisibilité du dashboard sans modifier le backend et sans cacher les outils de dogfooding.

La prochaine étape ne doit pas être une nouvelle donnée backend. Elle doit rester UI-only : vérifier le confort visuel, puis décider séparément si l’encoche doit être alignée avec la nouvelle hiérarchie produit.

### Points à surveiller

- `DashboardViewModel.refresh()` charge encore des données Produit, Debug et Lab ensemble ; c’est accepté pour ce patch UI-only.
- L’optimisation réseau ou le lazy loading par surface est hors scope.
- Le skin visuel global du dashboard reste basique et pourra être retravaillé plus tard.
- L’encoche n’a pas encore été mise à jour pour refléter la séparation Produit / Debug-Lab.

---

## 2026-05-31 — Product dashboard visual redesign check

### Contexte

Après la décision `UI_PRODUCT_DEBUG_LAB_SPLIT`, le dashboard Swift a été séparé en deux surfaces :

- `Produit` ;
- `Debug / Lab`.

Une première passe visuelle avait surtout changé le skin sombre. Le résultat restait trop proche d’un dashboard admin/debug : grille rigide, cartes éclatées, vide important et hiérarchie produit encore faible.

Un second patch UI-only a donc refondu la composition de la surface `Produit`, sans modifier le daemon, les routes, les modèles API, `/today_summary`, `/feed`, `DashboardViewModel`, l’encoche ou Debug / Lab.

### Patch observé

La surface `Aujourd’hui` a été réorganisée autour de trois zones principales :

- un hero `Aujourd’hui` en haut ;
- une carte centrale `Derniers blocs` ;
- une colonne secondaire avec `État Pulse` et `Projets du jour`.

Le hero regroupe maintenant :

- la tâche principale du jour ;
- le projet ;
- l’activité récente ;
- l’état actif ;
- le bloc en cours ;
- le temps travaillé ;
- les commits ;
- les blocs ;
- les projets.

Lecture terrain : le hero devient la source principale de lecture produit. Il donne immédiatement l’état de la journée sans obliger à lire plusieurs cartes indépendantes.

### Derniers blocs

La carte `Derniers blocs` devient la zone centrale de reprise du fil.

Elle affiche les blocs récents avec :

- heure courte ;
- durée ;
- tâche ;
- projet ;
- fichiers principaux ;
- suffixe `+N` quand plusieurs fichiers sont masqués.

Exemples visibles après patch :

```text
23:14 | 31 min | Rédaction | Pulse
UI_PRODUCT_DEBUG_LAB_SPLIT.md · README.md · DashboardRootView.swift · +2

22:52 | 8 min | Rédaction | Pulse
TODAY_VALUE_LOOP_PLAN.md · CORE_DOGFOODING_NOTES.md

20:38 | 6 min | tests | Pulse
CORE_DOGFOODING_NOTES.md
```

Lecture terrain : cette zone répond mieux à la question produit `Qu’est-ce que j’ai fait aujourd’hui ?`. Elle raconte les sujets de travail récents sans passer par les vues debug.

### Clarification `Aujourd’hui` / `Maintenant`

Une confusion visuelle restait après la première refonte de composition :

- le hero `Aujourd’hui` affichait déjà la tâche, le projet, l’activité récente et le bloc en cours ;
- une carte `Maintenant` dans la colonne droite affichait aussi une interprétation live forte.

Cela donnait deux lectures concurrentes du présent.

Un ajustement UI-only a remplacé `Maintenant` par une carte plus passive : `État Pulse`.

`État Pulse` affiche maintenant :

- l’état actif ;
- un signal live léger ;
- la dernière mise à jour ;
- la confiance / ambiguïté ;
- le dernier signal.

Lecture terrain : la hiérarchie est plus claire. Le hero `Aujourd’hui` porte la vérité produit principale, tandis que `État Pulse` reste un statut secondaire.

### Surface Produit après refonte

La surface `Produit` est maintenant plus cohérente :

- `Aujourd’hui` devient une page de reprise du fil ;
- `Derniers blocs` apporte la valeur principale ;
- `État Pulse` ne concurrence plus le hero ;
- `Projets du jour` reste un contexte secondaire ;
- Debug / Lab reste séparé dans sa propre surface.

Lecture terrain : le dashboard commence à ressembler à une vraie surface produit, et plus seulement à un cockpit de diagnostic assombri.

### Ce qui n’a pas été changé

Aucun changement n’a été fait sur :

- daemon ;
- routes ;
- modèles API ;
- `/today_summary` ;
- `/feed` ;
- `/state` ;
- `DashboardViewModel` ;
- encoche ;
- Debug / Lab ;
- memory candidates ;
- Lab backend ;
- LLM ;
- DayDream ;
- FactEngine ;
- VectorStore.

### Verdict provisoire

La refonte visuelle Produit est validée côté dogfooding initial.

Elle améliore fortement la lisibilité et renforce la direction produit actuelle : Pulse doit aider à reprendre le fil avant d’ajouter de nouvelles capacités intelligentes.

Le prochain travail UI ne doit pas ajouter de données backend. Les prochaines pistes doivent rester visuelles ou structurelles :

- vérifier le confort sur fenêtre réduite ;
- surveiller les fichiers longs dans `Derniers blocs` ;
- rendre les formulations comme `Confiance : Ambigu` plus naturelles plus tard ;
- aligner l’encoche avec la nouvelle hiérarchie produit dans une décision séparée.

### Points à surveiller

- La page garde encore du vide vertical sur grande fenêtre.
- La sidebar reste assez orientée outil développeur.
- `État Pulse` contient encore des formulations techniques comme `Confiance` et `Signal live`.
- L’encoche n’est pas encore alignée avec cette nouvelle composition produit.
- Debug / Lab n’a pas encore reçu de traitement visuel spécifique, ce qui est accepté pour cette phase.

---

## 2026-05-31 — Today value-loop field session 3 intense

### Contexte

Session terrain représentative après séparation `Produit` / `Debug / Lab` et refonte visuelle de la surface Produit du dashboard Swift.

Activité réelle observée :

- travail UI autour du dashboard Produit ;
- documentation de la décision `UI_PRODUCT_DEBUG_LAB_SPLIT` ;
- modifications de composition dans `DashboardRootView.swift` ;
- tests Swift ciblés ;
- mise à jour des notes de dogfooding.

Surfaces vérifiées :

- `/health/core`
- `/today_summary`
- `/feed`
- `/state`
- `/memory/candidates`
- `history | tail -30`

### Vérification `/health/core`

Résultat observé :

```text
status = ok
pulse_mode = core
experimental_enabled = false
lab_services = not_required
```

Lecture terrain : le Core est sain. Les services Lab restent non requis.

### Vérification `/today_summary`

Résultat observé :

```text
worked_min = 203
active_min = 203
window_count = 10
project_count = 1
commit_count = 37
top_tasks = writing, tests
```

Bloc principal :

```text
23:14 -> 23:58
project = Pulse
probable_task = writing
activity_level = executing
duration_min = 44
event_count = 100
top_files =
  - UI_PRODUCT_DEBUG_LAB_SPLIT.md
  - README.md
  - DashboardRootView.swift
  - PulseViewModelInteractionsTests.swift
  - CORE_DOGFOODING_NOTES.md
```

Lecture terrain : le bloc permet de reconstruire clairement le travail réel sans relire toute la conversation. Il capture à la fois la décision UI, le dashboard Swift, les tests et les notes terrain.

### Vérification `/feed`

Résultat observé :

```text
clear
```

Lecture terrain : `/feed` est pauvre sur cette session, mais ce n'est pas bloquant pour une session UI/docs. Les commandes ne sont pas la valeur principale ici.

### Vérification `/state`

Résultat observé :

```text
active_app = Code
active_file = CORE_DOGFOODING_NOTES.md
active_project = Pulse
probable_task = writing
activity_level = executing
session_duration_min = 66
```

Lecture terrain : l'état live est cohérent avec l'instant courant, mais il sert surtout à comprendre ce qui se passe maintenant. Pour reprendre le fil de la session, `/today_summary` reste plus utile.

### Vérification `/memory/candidates`

Résultat observé :

```text
count = 0
canonical_memory = false
surface = memory_candidates
```

Lecture terrain : aucune candidate spontanée n'a été créée. La surface reste non canonique et ne perturbe pas la boucle Core.

### Lecture produit

Cette session valide mieux la boucle “Aujourd'hui” sur une activité UI/docs significative :

- la journée est structurée ;
- les derniers blocs sont exploitables ;
- `top_files` donne le vrai contenu de la session ;
- `/feed` peut rester complémentaire sans être intégré à `/today_summary` ;
- la vue Produit doit continuer à privilégier les derniers blocs plutôt qu'une unique tâche probable.

La combinaison des totals, du bloc principal et des fichiers principaux suffit à comprendre le travail réel : séparation Produit / Debug-Lab, refonte du dashboard Produit, tests Swift et dogfooding.

### Verdict

Session terrain #3 intense validée.

`/today_summary` + `top_files` suffisent à reprendre le fil sur une session UI/docs significative.

Ne pas ajouter `notable_commands`.

### Prochaine étape

Alignement visuel de l'encoche dans une décision séparée.
