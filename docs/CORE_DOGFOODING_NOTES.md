

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

Une amélioration éventuelle devra d’abord passer par une décision produit explicite : Pulse doit-il couvrir aussi les activités personnelles / administratives, ou rester centré sur le travail projet ?