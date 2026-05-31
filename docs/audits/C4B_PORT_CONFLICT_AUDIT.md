# C4b.4a — Port / Conflict Boot Audit

## Statut

Cet audit est documentaire.

Aucun comportement produit n'est modifié.

Aucune route, payload, configuration de port ou surface Swift n'est modifiée.

Le but est de documenter le comportement réel avant une éventuelle correction C4b.4.

## Pourquoi cet audit existe

C4b vise à réduire les effets de bord au boot.

C4b.3-real phase 1 a rendu `get_runtime()` et `get_app()` lazy : `import daemon.main` ne crée plus runtime, app, routes ou fichiers `.pulse`.

La question restante concerne l'exécution réelle du daemon : que se passe-t-il si le port HTTP principal est déjà occupé, ou si un daemon Pulse est déjà actif ?

## Sources inspectées

Sources lues :

- `daemon/main.py`
- `scripts/start_pulse_daemon.sh`
- `App/App/DaemonController.swift`
- `launchd/cafe.pulse.daemon.plist`
- `docs/decisions/C4B_MAIN_BOOT_SAFETY_PLAN.md`
- `docs/audits/C4B_BOOT_IMPORT_AUDIT.md`
- `docs/audits/CORE_DOGFOODING_NOTES.md`
- `docs/decisions/C4B_LAZY_RUNTIME_CREATION_DECISION.md`

## Comportement de `main()`

`main()` appelle actuellement `get_app()` avant de lancer les services et avant `app.run(...)`.

Effet :

- `get_app()` matérialise l'app Flask ;
- `get_app()` appelle `get_runtime()` ;
- `get_runtime()` crée le `RuntimeBundle`, les stores et les DB nécessaires ;
- `create_app(runtime)` enregistre les routes ;
- `start_runtime_services()` démarre `RuntimeOrchestrator` et l'idle heartbeat ;
- `start_mcp_server(host="127.0.0.1", port=8766)` démarre le serveur MCP SSE secondaire ;
- deux threads daemon sont lancés pour watchdog et deferred startup ;
- `app.run(host="127.0.0.1", port=8765, ...)` tente ensuite le bind HTTP principal.

Conclusion : en lancement direct `python -m daemon.main`, le runtime, l'app, les routes et certains workers sont déjà créés avant que Flask échoue si le port 8765 est occupé.

## Port 8765 déjà occupé

### Via le script

`scripts/start_pulse_daemon.sh` protège le démarrage avant d'exécuter Python :

1. `curl http://127.0.0.1:8765/ping`
2. si `/ping` répond, le script logge `Daemon already active on :8765.` et sort avec succès ;
3. si `/ping` ne répond pas, le script teste `lsof` sur 8765 ;
4. si 8765 est occupé par autre chose, le script refuse de démarrer et sort avec erreur ;
5. dans ces deux cas, `python -m daemon.main` n'est pas exécuté.

Conclusion : via le script, le cas daemon déjà actif et le cas port 8765 occupé par autre chose sont préflightés avant création runtime/app Python.

### Via lancement direct

Un lancement direct `python -m daemon.main` ne bénéficie pas de ce préflight shell.

Dans ce cas, `main()` crée runtime/app et démarre des services avant que Flask tente le bind sur 8765.

Dette confirmée : le lazy import réduit les effets de bord à l'import, mais pas encore les effets de bord en cas de conflit de port pendant l'exécution directe.

## Port 8766 déjà occupé

`scripts/start_pulse_daemon.sh` teste aussi 8766 avec `lsof`.

Si 8766 est occupé, le script logge un warning :

- Core daemon startup continue ;
- MCP SSE secondaire peut être indisponible.

Dans `daemon/main.py`, `start_mcp_server(...)` démarre un thread qui appelle `mcp_app.run(...)`.

Le comportement en cas d'échec de bind 8766 côté thread n'est pas traité comme bloquant pour le Core.

Conclusion : 8766 est actuellement best-effort pour le serveur MCP SSE secondaire.

## Swift / LaunchAgent

`App/App/DaemonController.swift` lance le daemon de deux façons :

- si le LaunchAgent est installé : `launchctl bootstrap` puis `launchctl kickstart` ;
- sinon : exécution directe du script `start_pulse_daemon.sh` via `/bin/zsh`.

`launchd/cafe.pulse.daemon.plist` pointe également vers `scripts/start_pulse_daemon.sh`.

Conclusion : les chemins Swift et LaunchAgent passent par le script de préflight, pas directement par `python -m daemon.main`.

## Effet du lazy boot C4b.3

C4b.3 réduit déjà les effets de bord avant exécution :

- `import daemon.main` ne crée plus runtime/app/routes/.pulse ;
- les fichiers `.pulse` ne sont créés qu'au premier accès runtime/app ;
- le lancement via script peut refuser 8765 avant d'exécuter Python.

Limite :

- une fois `main()` appelé, le bind 8765 reste tenté après création runtime/app et démarrage des services.

## Tests existants

Tests existants pertinents :

- `tests/test_main_runtime_state.py` vérifie que l'import ne lance pas `Flask.run` et ne démarre pas les workers ;
- les tests full-app vérifient que `get_app()` expose les routes attendues ;
- les tests ne couvrent pas encore un échec réel de bind 8765 ;
- les tests ne couvrent pas encore le comportement de `scripts/start_pulse_daemon.sh` en cas de ports occupés.

Aucun test nouveau n'est ajouté dans cet audit pour éviter de simuler de façon fragile des ports système, `lsof`, `curl` et `launchctl`.

## Risques confirmés

Risques confirmés :

- lancement direct `python -m daemon.main` peut créer runtime/app/stores et démarrer des services avant d'échouer sur 8765 ;
- un conflit 8766 est toléré et peut rendre le serveur MCP SSE secondaire indisponible ;
- le script crée `~/.pulse/logs` avant les checks de port, pour pouvoir logger les refus ;
- le comportement du script dépend de `curl` et `lsof` ;
- si `lsof` est absent, le script ne peut pas préflighter le port et continue vers le lancement Python.

## Prochaine correction possible

Correction C4b.4 candidate :

- ajouter un préflight de port 8765 dans `main()` avant `get_app()` et `start_runtime_services()` ;
- garder le script comme première ligne de défense ;
- conserver les ports existants ;
- ne pas changer les routes ni les payloads ;
- ajouter des tests unitaires en patchant le préflight plutôt qu'en occupant réellement un port ;
- documenter le dogfooding après redémarrage daemon.

## Décision provisoire

Le comportement actuel est acceptable temporairement parce que les chemins Swift et LaunchAgent passent par `start_pulse_daemon.sh`.

La dette reste ouverte pour les lancements directs.

Ne pas corriger brutalement dans cet audit.
