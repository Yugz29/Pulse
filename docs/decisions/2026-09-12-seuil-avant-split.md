# Seuil avant split : un fragment d'un autre workspace n'est une session que s'il dure

**Date :** 2026-09-12
**Statut :** tranchée, implémentée (`reconstruction_version` 3 → 4, Core 0.8.0.0)
**Chantier :** `fix/core-split-threshold`, empilé sur `ship/observer-window-context`

## Décision

Un événement fort d'un autre workspace ne ferme plus la session en cours
sur-le-champ. Il ouvre un **fragment en attente** ; la session en cours ne
se ferme (`end_reason: workspace_changed`, à l'instant du premier événement
du fragment, comme avant) que si le fragment atteint **les deux** seuils :

- **M = 2 minutes** entre son premier et son dernier événement fort, condition
  première : un fragment de 0 minute n'est jamais une session, quel que soit
  le nombre d'activités fortes (une rafale de fichiers écrits dans la même
  seconde par un outil n'est pas du travail) ;
- **N = 2 activités fortes** (`terminal_finished`, `file_changed`,
  `git_commit`).

En dessous, le fragment est **absorbé** par la session en cours dès que
celle-ci reprend, qu'un troisième workspace apparaît, qu'un verrouillage ou
une inactivité la ferme, ou que la journée se termine. Variante B : les
événements absorbés gardent leur propre workspace dans le rendu (séparateur
de projet à l'intérieur de la session) et dans les observations (chaque fait
porte son cwd ou son workspace) ; la liste `projects` de la session inclut
le workspace absorbé. Le workspace de la session, lui, ne change pas.

Les règles de relation entre workspaces (`_workspace_relation`, ex
`workspace_transition`) s'appliquent à l'identique au fragment en attente :
une commande à faible confiance ne quitte jamais un dépôt sûr, une promotion
parent/enfant reste possible.

## Pourquoi

Mesuré sur les 30 jours du 13 août au 12 septembre (copie de `trace.db`,
règle actuelle puis règle nouvelle, même code, seuils à zéro pour reproduire
l'ancienne à l'identique) :

| | Avant | Après |
| --- | --- | --- |
| Sessions reconstruites | 183 | 137 |
| Trop courtes (moins de 10 min et moins de 30 activités) | 88 | 47 |
| Candidates Intelligence (closes, ni trop courtes) | 94 | 89 |
| Durée médiane | 8 min | 14 min |
| Coupures `workspace_changed` | 60 | 14 |

26 fragments absorbés : 6 Cortex dans Pulse (instantanés de 1 à 4 fichiers
dans la même seconde, ou une commande isolée), 9 `Pulse` ↔ `Pulse/core`
(historiques, avant la restructuration en dépôt unique), 2 commits de
worktrees d'agent le 11 septembre, 5 fragments Holberton d'une commande, le
reste : `ws_resident` de test, `gstack`, `DevNote/DevNote`. Les candidates
baissent de cinq parce que des fragments candidats fusionnent en sessions
plus longues ; aucun travail ne disparaît de la trace.

Le 6 septembre 12:12–13:19 passe de cinq sessions à une (66 min) ; la
soirée du 11 septembre de six sessions Pulse à deux (17 et 39 min), les
deux commits de worktree à l'intérieur.

## Ce qui est écarté

- Variante A (l'événement absorbé perd son workspace au rendu) : rien ne
  justifie de cacher d'où vient une commande.
- Le seul seuil en activités : 4 fichiers écrits dans la même seconde
  auraient encore fait une session. D'où M en condition première.
- Un seuil plus haut (N = 5) : fusionnerait davantage (147 sessions
  simulées) au prix de bascules réelles avalées.

## Limites connues

- Le contre-exemple du rapport (3 septembre, 17:21, « DevNote 8 minutes »)
  était en réalité deux fichiers écrits dans la même seconde ; les 8 minutes
  étaient le délai jusqu'au retour de Pulse. Sous la règle il est absorbé. Une
  vraie bascule de 8 minutes avec deux activités reste une session, et un test
  le garantit.
- Une bascule réelle mais brève (une commande dans Cortex, retour à Pulse)
  est rattachée à la session Pulse, avec son workspace visible. Quatre cas
  sur 30 jours.
- La durée d'un fragment se mesure entre ses propres événements : un
  fragment de un événement suivi d'un long silence n'est jamais une session.
- L'identité (`id`) d'une session reste le hash de ses événements sources ;
  le regroupement change, donc les identités des jours regroupés changent.
  Les résumés existants portent `reconstruction_version: 3` et restent
  lisibles tels quels ; Intelligence ne les réémet pas (l'identité d'un
  résumé inclut la session, pas la version de reconstruction).

## Rejeu

- Tests : `core/tests_v2/test_session_reconstruction.py` (les trois exemples
  réels du rapport, plus les cas seuil), rendus et routes adaptés.
- Mesure : `scratchpad/before_after.py` sur `scratchpad/trace-copy.db`
  (session de travail du 12 septembre) ; seuils à zéro = règle 3.
