# Tests Pulse

Ce document décrit la batterie de tests actuelle de Pulse.

## Philosophie de test

Les tests Pulse servent aujourd’hui à trois choses distinctes :

- `Unit tests` : vérifier une logique locale en isolation
- `Integration tests` : vérifier que plusieurs modules continuent de fonctionner ensemble dans le vrai pipeline
- `Contract tests` : vérifier que certaines sorties publiques ou legacy-compatibles ne changent pas

Les contract tests ne sont pas des tests de confort. Ce sont des garanties structurelles.

Règle :

> Si un test vérifie une sortie exacte, toute modification devient par défaut un breaking change.

## Tests automatisés

Exécuter la suite Python non interactive complète :

```bash
cd /path/to/Pulse
./scripts/test_all.sh
```

C’est le point d’entrée canonique pour les tests du daemon :
- utilise le venv du projet plutôt que le Python système macOS
- échoue immédiatement si l’interpréteur est plus ancien que Python 3.11
- évite les faux négatifs causés par l’usage de `/usr/bin/python3`

Ce que cela couvre :
- command interpreter
- signal scorer
- decision engine
- state store
- builders `CurrentContext` et adaptateurs legacy
- builders `SessionSnapshot` et adaptateurs legacy
- adaptateurs `ProposalCandidate`
- `SessionFSM`
- matrice runtime (`/ping`, `/state`, `/event`, `/insights`)
- handlers MCP
- mémoire de session
- FactEngine (facts, reinforce, contradict, decay, archive)
- memory extractor (cooldown, journal, projects)
- module git diff
- routes API `/facts`
- runtime orchestrator
- matrice de disponibilité LLM

## Tests de verrouillage de contrat

Certaines sorties sont maintenant explicitement gelées par des golden tests ou des tests d’égalité exacte.

Ces tests existent pour empêcher les régressions structurelles pendant les refactors.
Ce ne sont pas des tests "nice to have".

Sorties actuellement verrouillées :
- `build_context_snapshot()` -> sortie Markdown exacte
- `/state` -> sortie JSON exacte
- `export_session_data()` -> dict legacy exact
- sortie de génération de proposal -> payload / structure / evidence exacts

Ces tests servent quand Pulse doit conserver le même comportement tout en changeant sa structure interne.
Si l’un de ces tests casse, l’hypothèse par défaut est que le changement est cassant tant que le contraire n’est pas démontré.

## Artéfacts cœur sous test

La fondation actuelle du runtime introduit plusieurs artéfacts structurels qui sont maintenant testés directement :

- `CurrentContext`
- `SessionSnapshot`
- `ProposalCandidate`
- `SessionFSM`

Ils ne sont pas testés pour justifier une dérive de comportement.
Ils sont testés pour verrouiller :
- la compatibilité
- les invariants
- la stabilité des sorties legacy
- la cohérence du lifecycle de session

Attendus typiques :
- un builder peut remplacer un assemblage inline sans changer la sortie
- un adaptateur legacy reproduit exactement le contrat précédent
- le lifecycle de session garde une seule source de vérité
- une conversion candidate -> transport ne modifie pas le payload externe final

## E2E interactif

Le smoke test MCP reste séparé car il nécessite un daemon vivant :

```bash
cd /path/to/Pulse
.venv/bin/python3 tests/test_e2e.py
```

Commande custom optionnelle :

```bash
.venv/bin/python3 tests/test_e2e.py "find . -type f -name \"*.swift\" | head"
```

## Checklist UI manuelle

### Dashboard

- Ouvrir et fermer l’encoche.
- Vérifier que le dashboard apparaît en premier.
- Vérifier que la carte de contexte courant affiche :
  - app active ou projet
  - fichier actif
  - tâche, focus, session
  - badge de friction
- Vérifier que la bulle d’entrée reste entièrement dans le panneau étendu.
- Envoyer un message et vérifier que l’UI bascule en mode chat.

### Services

- Ouvrir `Services` depuis l’icône health.
- Vérifier que la ligne daemon permet :
  - start
  - pause
  - resume
  - stop
  - restart
- Vérifier que la ligne observation peut être mise en pause / reprise indépendamment.
- Vérifier que la ligne `LLM` affiche :
  - disponibilité courante
  - bouton de refresh
  - menu de choix de modèle
- Changer les modèles command et summary puis redémarrer Pulse pour vérifier la persistance.

### Settings

- Ouvrir les settings depuis l’icône engrenage.
- Vérifier que `Réglages` apparaît dans la top bar.
- Vérifier que la vue ne contient plus que des éléments de guidance runtime et ne duplique plus les contrôles LLM.

### Chat

- Envoyer un message depuis le dashboard.
- Vérifier que le panneau passe en mode chat et affiche :
  - un état de chargement
  - la réponse finale
- Vérifier que le bouton close fait revenir au dashboard.
- Vérifier qu’aucun contrôle n’est rendu dans la zone physique de l’encoche.

### Context

- Appuyer sur `Cmd+Option+Shift+C`.
- Vérifier que l’encoche affiche le feedback de copie.
- Coller dans un champ texte et confirmer que le snapshot commence par `# Pulse Context Snapshot`.

### Observation

- Ouvrir `Observation` depuis l’icône œil.
- Vérifier que le panneau n’affiche que des lignes d’activité récente.
- Vérifier que chaque ligne affiche :
  - une icône
  - une valeur principale
  - une description secondaire
  - un timestamp relatif
- Modifier un vrai fichier `.swift` ou `.py`.
- Confirmer que `Project` et `Active file` se mettent à jour dans le contexte copié.
- Désactiver l’observation et vérifier que l’activité fichiers / apps cesse de se mettre à jour.

### Session Memory

- Travailler au moins 20 minutes avec Pulse actif.
- Déclencher une période idle ou verrouiller l’écran (ou faire un commit git).
- Vérifier que les fichiers mémoire existent :

```bash
ls ~/.pulse/memory
ls ~/.pulse/memory/sessions
```

- Vérifier :
  - `facts.md` (export profil utilisateur)
  - `projects.md`
  - un fichier daté sous `sessions/` (par ex. `2026-04-13.md`)
  - que `~/.pulse/facts.db` existe et contient des faits actifs

- Vérifier l’API facts :

```bash
curl http://127.0.0.1:8765/facts
curl http://127.0.0.1:8765/facts/profile
```

## Vérifications LaunchAgent

Vérifier que l’autostart du daemon est chargé :

```bash
launchctl list | grep cafe.pulse.daemon
ps aux | grep '[d]aemon.main'
```

Vérifier les logs si nécessaire :

```bash
tail -n 80 ~/.pulse/logs/daemon.error.log ~/.pulse/logs/daemon.stdout.log
```
