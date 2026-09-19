# Le lot part en réveil complet, capot ouvert, batterie au-dessus du plancher, à la première occasion du jour

**Date :** 2026-09-19
**Statut :** tranchée
**Précise :** [compteur de l'étape 4 : la veille du Mac](2026-09-15-compteur-etape-4-veille-du-mac.md)
et sa précision du 18 (« le lot du jour est le passage planifié »)
**Remplace :** la tâche calendaire de 06:30 (`StartCalendarInterval`) et le
`caffeinate -i` de la PR #100 comme seule parade à la veille

## Constat

Le passage planifié de 06:30 part quand le Mac dort capot fermé : launchd le
lance dans un DarkWake de deux secondes, le Mac se rendort, et le lot
n'avance que par tranches de 2 à 20 s à chaque DarkWake jusqu'au réveil
complet. Lots des 10, 11, 12, 13, 14, 15 et 19 septembre. Le 19
(`pmset -g log`) : DarkWake à 06:45:11, rendormi à 06:45:13, dix-sept
DarkWakes, réveil complet à 11:09:22, fin du lot à 11:18:43 : dix minutes de
calcul pour 4 h 33 d'horloge, et deux `generation_ms` de 3 h 06 et 1 h 19
qui ne mesurent que la veille. `caffeinate -i` (#100) n'y peut rien capot
fermé, et l'ancienne consigne du README (« le lot avance par DarkWake et se
termine à l'ouverture ») décrivait ce défaut comme un fonctionnement.

Le problème est le DarkWake capot fermé, pas l'alimentation : le poste
travaille sur batterie la plupart du temps, exiger le secteur reviendrait à
ne jamais lancer le lot.

## Décision

- **Un seul agent launchd**, `com.pulse.intelligence-run`, en `StartInterval`
  de 900 s (`PULSE_INTEL_RUN_INTERVAL`), à la place de la tâche calendaire.
  Il appelle `intelligence/scripts/pulse_intel_run.sh`, qui interroge
  `pulse-intel gate` avant tout passage.
- **La garde répond dans cet ordre :**
  1. le lot du jour est déjà fait : `last_complete_pass` (UTC) postérieur au
     début du cycle en cours, 06:30 en heure locale
     (`PULSE_INTEL_CYCLE_START`), la veille avant 06:30. Sortie muette,
     code 10, rien dans `run.log` ;
  2. le Mac n'est pas en réveil complet : `pmset -g systemstate` rend
     `Current System Capabilities are: CPU Graphics Audio Network` en réveil
     complet, et `Graphics` manque en DarkWake (c'est la définition du
     DarkWake dans powerd) : « lot reporté : pas en réveil complet
     (capacités lues : CPU Network) », code 11 — les capacités lues sont
     dans la ligne pour vérifier le signal au premier DarkWake réel ;
  3. le capot est fermé (`"AppleClamshellState" = Yes` dans
     `ioreg -r -k AppleClamshellState -d 4`) : « lot reporté : capot
     fermé », code 11 ;
  4. le Mac est sur batterie sous le plancher de 40 % (`pmset -g batt`) :
     « lot reporté : sur batterie à NN %, plancher 40 % », code 11 ;
  5. sinon le lot part, code 0, sous `caffeinate -i`.
  Une source illisible (poste sans batterie ou sans capot) ne reporte pas.
  Un report n'écrit **qu'une ligne par cycle** dans `run.log` : `gate.json`,
  à côté de `state.json`, retient l'heure de la dernière ligne. Dans tous
  les cas de report, `state.json` n'est pas touché : le repère ne bouge pas,
  l'appel suivant relit la même fenêtre.
- **Le niveau de batterie est journalisé** au début et à la fin du passage
  (« `run --once (launchd) — 85 % batterie` », « `fin du passage, code 0 —
  81 % batterie` ») pour ajuster le plancher sur des mesures.
- **Compteur de l'étape 4** : le lot du jour est le **premier passage
  complet du cycle** commencé au dernier 06:30, quelle que soit l'heure
  de l'appel qui l'a lancé. « Reporté » n'est pas « interrompu » : un jour
  sans appel qui passe la garde n'a pas de lot, et le rattrapage à sept
  jours ([décision du 18](2026-09-18-rattrapage-des-jours-non-resumes.md))
  absorbe ses sessions le lendemain. Un `generation_ms` mesuré Mac éveillé
  redevient significatif ; un lot parti malgré la garde reste à lire dans
  `pmset -g log`.

## Vérifications faites le 19

- `pmset -g batt` : première ligne `Now drawing from 'AC Power'` /
  `'Battery Power'`, niveau `NN%` sur la seconde ;
  `ioreg -r -k AppleClamshellState -d 4` : `"AppleClamshellState" = No`
  capot ouvert ; `pmset -g systemstate` : `CPU Graphics Audio Network` en
  réveil complet. Les trois lus sur ce poste ; la forme DarkWake (sans
  `Graphics`) n'a pas encore été lue en réel, d'où les capacités dans la
  ligne de report.
- `pulse-intel gate` sur l'état du poste à 12:30 : code 10 (lot du 19
  fait) ; sur un état vide, réveil complet, capot ouvert, batterie à 85 % :
  code 0.
- Wrapper joué contre un faux `pulse-intel` : codes 10 et 11 sortent en 0
  sans passage ; code 0 lance le passage, journalise le niveau de batterie
  avant et après, et rend le code du passage.

## Cas couvert : veille d'inactivité capot ouvert

Un Mac laissé capot ouvert s'endort par inactivité (`pmset -g` : `sleep 1`,
`displaysleep 20`). Ses DarkWakes ressemblent à ceux du 19, capot ouvert :
sans le test 2, la garde disait go (capot ouvert, batterie au-dessus du
plancher, lot pas fait), le lot partait dans une fenêtre de quelques
secondes, et `caffeinate -i` n'a pas été vu retenir un DarkWake (le 14 :
06:32 → 14:24 sans réveil complet). Le test 2 écarte ce cas par la
capacité `Graphics`. Un signal plus strict d'usage réel, `HIDIdleTime` dans
`ioreg -c IOHIDSystem` (nanosecondes depuis la dernière saisie), reste en
réserve : il refuserait un Mac allumé mais laissé seul, ce que la règle
d'aujourd'hui accepte.

## Limites

- Le lot du jour part à la première occasion, éventuellement pendant le
  travail : le repère avance à cette heure, et les sessions closes après
  lui attendent le lendemain, comme avec 06:30.
- L'appel toutes les quinze minutes lit `state.json` (0,5 Mo) et deux
  commandes système, sans verrou ni Core : moins d'une seconde. Un passage
  en cours tient le verrou ; l'appel suivant répond « lot du jour fait »
  ou, si le passage n'a pas encore posé le repère, sort en 5 (verrou tenu),
  déjà prévu.
